import hashlib
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import sqlite3

from app.models import db_session
from app.ledger import Ledger
from app.lightning_service import LightningService, lightning_service
from app.sms_service import sms_service

class SettlementError(Exception):
    pass

def settle(
    invoice_id: str,
    preimage: str,
    lnd_client: Optional[LightningService] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    THE CORE OF SAUTIPAY: Verify + Settle (Idempotent).
    
    Invariants enforced:
    - INV-1 Settlement proof: succeeds iff SHA256(preimage).hex() == invoice.payment_hash
      AND lnd node confirms invoice state == 'SETTLED'.
    - INV-2 Idempotency: duplicate call with settled invoice returns existing payment without DB changes.
    - INV-6 SMS gate: sms_service.send_settled is called ONLY from this verified path.
    """
    node = lnd_client or lightning_service
    ledger = Ledger(db_path)

    with db_session(db_path) as conn:
        cursor = conn.cursor()

        # 1. Load invoice
        cursor.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
        inv_row = cursor.fetchone()
        if not inv_row:
            raise SettlementError("INVOICE_NOT_FOUND")
        invoice = dict(inv_row)

        # Idempotency check: if already settled, return existing payment
        if invoice["status"] == "SETTLED":
            cursor.execute("SELECT * FROM payments WHERE invoice_id = ?", (invoice_id,))
            payment_row = cursor.fetchone()
            if payment_row:
                return dict(payment_row)

        # 2. Local proof: assert SHA256(preimage).hex() == invoice.payment_hash
        preimage_bytes = bytes.fromhex(preimage)
        computed_hash = hashlib.sha256(preimage_bytes).hexdigest()
        if computed_hash.lower() != invoice["payment_hash"].lower():
            raise SettlementError("PREIMAGE_MISMATCH")

        # 3. Node proof: lnd lookup_invoice(payment_hash) -> state == 'SETTLED'
        node_state, node_preimage = node.lookup_invoice(invoice["payment_hash"])
        if node_state != "SETTLED":
            raise SettlementError(f"NODE_UNCONFIRMED: state is {node_state}")

        # 4. Atomic DB updates: payment record, invoice status, receipt in ledger, audit log
        payment_id = str(uuid.uuid4())
        settled_at = datetime.now(timezone.utc).isoformat()
        
        cursor.execute(
            """
            INSERT INTO payments (id, invoice_id, preimage, settled_at, settle_source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (payment_id, invoice_id, preimage, settled_at, "lnd_lookup")
        )

        cursor.execute(
            "UPDATE invoices SET status = 'SETTLED' WHERE id = ?",
            (invoice_id,)
        )

        # Fetch merchant details for settlement mode and phone
        cursor.execute("SELECT * FROM merchants WHERE id = ?", (invoice["merchant_id"],))
        merchant = dict(cursor.fetchone())

        value_mode = merchant["settlement_mode"]
        value_locked_ngn = invoice["amount_ngn"] if value_mode == "lock_ngn" else None

        receipt = ledger.append_receipt(
            merchant_id=invoice["merchant_id"],
            invoice_id=invoice_id,
            amount_ngn=invoice["amount_ngn"],
            sats_per_ngn=invoice["sats_per_ngn"],
            value_mode=value_mode,
            value_locked_ngn=value_locked_ngn,
            sms_status="SENT",
            conn=conn
        )

        cursor.execute(
            """
            INSERT INTO audit_log (entity_type, entity_id, action, details)
            VALUES (?, ?, ?, ?)
            """,
            (
                "invoice",
                invoice_id,
                "SETTLE_VERIFIED",
                f"Settled payment {payment_id} for {invoice['amount_ngn']} NGN with preimage {preimage[:8]}..."
            )
        )

    # 5. THEN AND ONLY THEN: send settlement SMS to merchant
    # Time string in HH:MM format
    now_hm = datetime.now().strftime("%H:%M")
    sms_service.send_settled(
        phone=merchant["phone"],
        amount_ngn=invoice["amount_ngn"],
        receipt_hash=receipt["receipt_hash"],
        value_mode=value_mode,
        settled_time_str=now_hm
    )

    return {
        "id": payment_id,
        "invoice_id": invoice_id,
        "preimage": preimage,
        "settled_at": settled_at,
        "settle_source": "lnd_lookup",
        "receipt_hash": receipt["receipt_hash"]
    }

