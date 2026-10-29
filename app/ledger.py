import sqlite3
from typing import List, Dict, Any, Optional
from app.models import db_session
from app.receipt_chain import GENESIS_HASH, compute_receipt_hash, verify_receipt

class LedgerError(Exception):
    pass

class Ledger:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def get_last_receipt(self, merchant_id: str, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM receipts 
            WHERE merchant_id = ? 
            ORDER BY seq DESC LIMIT 1
            """,
            (merchant_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def append_receipt(
        self,
        merchant_id: str,
        invoice_id: str,
        amount_ngn: int,
        sats_per_ngn: float,
        value_mode: str,
        value_locked_ngn: Optional[int],
        sms_status: str = "SENT",
        conn: Optional[sqlite3.Connection] = None
    ) -> Dict[str, Any]:
        """
        Appends a hash-chained receipt for a merchant atomically.
        Enforces gapless sequence and canonical SHA256 chain hash.
        """
        def _do_append(c: sqlite3.Connection):
            last = self.get_last_receipt(merchant_id, c)
            if last is None:
                seq = 1
                prev_receipt_hash = GENESIS_HASH
            else:
                seq = last["seq"] + 1
                prev_receipt_hash = last["receipt_hash"]

            receipt_hash = compute_receipt_hash(
                merchant_id=merchant_id,
                seq=seq,
                invoice_id=invoice_id,
                amount_ngn=amount_ngn,
                sats_per_ngn=sats_per_ngn,
                value_mode=value_mode,
                value_locked_ngn=value_locked_ngn,
                prev_receipt_hash=prev_receipt_hash
            )

            cursor = c.cursor()
            cursor.execute(
                """
                INSERT INTO receipts (
                    seq, merchant_id, invoice_id, amount_ngn, sats_per_ngn,
                    value_mode, value_locked_ngn, prev_receipt_hash, receipt_hash, sms_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seq, merchant_id, invoice_id, amount_ngn, sats_per_ngn,
                    value_mode, value_locked_ngn, prev_receipt_hash, receipt_hash, sms_status
                )
            )
            return {
                "id": cursor.lastrowid,
                "seq": seq,
                "merchant_id": merchant_id,
                "invoice_id": invoice_id,
                "amount_ngn": amount_ngn,
                "sats_per_ngn": sats_per_ngn,
                "value_mode": value_mode,
                "value_locked_ngn": value_locked_ngn,
                "prev_receipt_hash": prev_receipt_hash,
                "receipt_hash": receipt_hash,
                "sms_status": sms_status
            }

        if conn is not None:
            return _do_append(conn)
        else:
            with db_session(self.db_path) as c:
                return _do_append(c)

    def get_merchant_receipts(self, merchant_id: str, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
        def _fetch(c: sqlite3.Connection):
            cursor = c.cursor()
            cursor.execute(
                "SELECT * FROM receipts WHERE merchant_id = ? ORDER BY seq ASC",
                (merchant_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

        if conn is not None:
            return _fetch(conn)
        else:
            with db_session(self.db_path) as c:
                return _fetch(c)

    def verify_chain(self, merchant_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
        """
        Verifies the complete receipt chain for a merchant:
        1. Gapless sequence starting at 1.
        2. Genesis points to 64 zeros.
        3. Each block points to the previous block's hash.
        4. Each receipt hash matches its canonical content.
        """
        receipts = self.get_merchant_receipts(merchant_id, conn)
        if not receipts:
            return True

        expected_prev_hash = GENESIS_HASH
        for idx, r in enumerate(receipts):
            expected_seq = idx + 1
            if r["seq"] != expected_seq:
                return False

            if r["prev_receipt_hash"] != expected_prev_hash:
                return False

            if not verify_receipt(r):
                return False

            expected_prev_hash = r["receipt_hash"]

        return True

