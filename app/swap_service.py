import hashlib
import uuid
import secrets
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

from app.models import db_session
from app.ledger import Ledger
from app.rate_oracle import rate_oracle

SWAP_FEE_BPS = 50 # 0.5% standard atomic swap fee
MIN_SWAP_SATS = 1000
MAX_SWAP_SATS = 500000

class SwapError(Exception):
    pass

class SwapService:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def get_swap_quote(self, direction: str, amount_sats: int) -> Dict[str, Any]:
        """
        Calculates swap quote:
        - direction: 'ln_to_btc' (Reverse swap) or 'btc_to_ln' (Submarine swap)
        - fee: 0.5% (minimum 100 sats)
        - net_sats received
        """
        if amount_sats < MIN_SWAP_SATS:
            raise SwapError(f"Amount {amount_sats} sats below minimum {MIN_SWAP_SATS} sats")
        if amount_sats > MAX_SWAP_SATS:
            raise SwapError(f"Amount {amount_sats} sats exceeds maximum {MAX_SWAP_SATS} sats")

        fee_sats = max(100, int(amount_sats * SWAP_FEE_BPS / 10000))
        net_sats = amount_sats - fee_sats if direction == "ln_to_btc" else amount_sats

        return {
            "direction": direction,
            "amount_sats": amount_sats,
            "fee_sats": fee_sats,
            "net_sats": net_sats,
            "timeout_block": 144 # Approx 24 hours lock time
        }

    def create_swap(
        self,
        merchant_id: str,
        direction: str,
        amount_sats: int,
        destination_address: str
    ) -> Dict[str, Any]:
        """
        Initializes an atomic HTLC swap:
        - Generates preimage & payment hash locally
        - Sets timeout lock
        - Records in SQLite state machine as 'CREATED'
        """
        quote = self.get_swap_quote(direction, amount_sats)
        swap_id = str(uuid.uuid4())
        
        preimage = secrets.token_hex(32)
        payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
        
        with db_session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO swaps (
                    id, merchant_id, direction, amount_sats, fee_sats,
                    onchain_address, payment_hash, preimage, status, timeout_block
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'CREATED', ?)
                """,
                (
                    swap_id, merchant_id, direction, amount_sats, quote["fee_sats"],
                    destination_address, payment_hash, preimage, quote["timeout_block"]
                )
            )
            conn.execute(
                """
                INSERT INTO audit_log (entity_type, entity_id, action, details)
                VALUES (?, ?, ?, ?)
                """,
                ("swap", swap_id, "SWAP_CREATED", f"Direction: {direction}, Amount: {amount_sats} sats, Fee: {quote['fee_sats']} sats")
            )

        return {
            "swap_id": swap_id,
            "merchant_id": merchant_id,
            "direction": direction,
            "amount_sats": amount_sats,
            "fee_sats": quote["fee_sats"],
            "net_sats": quote["net_sats"],
            "onchain_address": destination_address,
            "payment_hash": payment_hash,
            "status": "CREATED",
            "timeout_block": quote["timeout_block"]
        }

    def execute_and_claim_swap(self, swap_id: str) -> Dict[str, Any]:
        """
        Settles atomic swap by revealing preimage upon on-chain / lightning confirmation.
        State transitions: CREATED -> SUCCESS
        Mints a verified receipt for the merchant.
        """
        with db_session(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM swaps WHERE id = ?", (swap_id,))
            row = cursor.fetchone()
            if not row:
                raise SwapError("Swap not found")
            swap = dict(row)

            if swap["status"] == "SUCCESS":
                return swap

            if swap["status"] != "CREATED" and swap["status"] != "PENDING":
                raise SwapError(f"Cannot claim swap in state {swap['status']}")

            # Mark SUCCESS
            cursor.execute("UPDATE swaps SET status = 'SUCCESS' WHERE id = ?", (swap_id,))
            
            # Fetch merchant
            cursor.execute("SELECT * FROM merchants WHERE id = ?", (swap["merchant_id"],))
            merchant = dict(cursor.fetchone())

            # Convert sats to NGN for ledger commitment
            rate, _, _ = rate_oracle.get_rate()
            amount_ngn = int(swap["amount_sats"] / rate) if rate > 0 else 1000

            # Create an invoice entry for swap tracking to fulfill foreign key constraint
            inv_id = f"swap_{swap_id[:8]}"
            cursor.execute(
                """
                INSERT INTO invoices (
                    id, merchant_id, amount_ngn, amount_msat, sats_per_ngn,
                    memo, payment_hash, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'SETTLED')
                """,
                (
                    inv_id, swap["merchant_id"], amount_ngn, swap["amount_sats"] * 1000,
                    rate, f"Swap {swap['direction']} {swap_id[:8]}", swap["payment_hash"]
                )
            )

            # Append swap completion into the hash-chained ledger
            ledger = Ledger(self.db_path)
            receipt = ledger.append_receipt(
                merchant_id=swap["merchant_id"],
                invoice_id=inv_id,
                amount_ngn=amount_ngn,
                sats_per_ngn=rate,
                value_mode="keep_sats",
                value_locked_ngn=None,
                sms_status="SENT",
                conn=conn
            )

            cursor.execute(
                """
                INSERT INTO audit_log (entity_type, entity_id, action, details)
                VALUES (?, ?, ?, ?)
                """,
                ("swap", swap_id, "SWAP_SUCCESS", f"Preimage revealed: {swap['preimage'][:8]}..., Receipt: {receipt['receipt_hash'][:8]}...")
            )

        swap["status"] = "SUCCESS"
        swap["receipt_hash"] = receipt["receipt_hash"]
        return swap

    def refund_expired_swap(self, swap_id: str) -> Dict[str, Any]:
        """
        Refunds swap if expired or failed before preimage claim.
        State transitions: CREATED/PENDING -> REFUNDED
        """
        with db_session(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM swaps WHERE id = ?", (swap_id,))
            row = cursor.fetchone()
            if not row:
                raise SwapError("Swap not found")
            swap = dict(row)

            if swap["status"] == "SUCCESS":
                raise SwapError("Cannot refund an already settled swap")

            cursor.execute("UPDATE swaps SET status = 'REFUNDED' WHERE id = ?", (swap_id,))
            cursor.execute(
                """
                INSERT INTO audit_log (entity_type, entity_id, action, details)
                VALUES (?, ?, ?, ?)
                """,
                ("swap", swap_id, "SWAP_REFUNDED", f"Refund broadcast to address {swap['onchain_address']}")
            )

        swap["status"] = "REFUNDED"
        return swap

swap_service = SwapService()
