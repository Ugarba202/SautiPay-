import sqlite3
from typing import Dict, Any, Tuple
from app.models import db_session
from app.ledger import Ledger
from app.security_engine import security_engine, SecurityError

class DemoSimulator:
    """Scripted attack and tamper simulations for the demo room."""

    @staticmethod
    def tamper_latest_receipt(merchant_id: str, new_amount_ngn: int = 99999) -> Tuple[bool, str]:
        """
        Tamper Demo: Alters a stored receipt's amount directly in SQLite
        without recomputing the hash or updating downstream links.
        Returns: (is_tampered, message)
        """
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM receipts WHERE merchant_id = ? ORDER BY seq DESC LIMIT 1",
                (merchant_id,)
            )
            row = cursor.fetchone()
            if not row:
                return False, "No receipts exist to tamper with."
            receipt = dict(row)
            original_amt = receipt["amount_ngn"]
            cursor.execute(
                "UPDATE receipts SET amount_ngn = ? WHERE id = ?",
                (new_amount_ngn, receipt["id"])
            )

        ledger = Ledger()
        verified = ledger.verify_chain(merchant_id)
        msg = f"Tampered Receipt #{receipt['seq']}: Amount changed from ₦{original_amt} to ₦{new_amount_ngn}. Chain validity is now {verified}."
        return True, msg

    @staticmethod
    def simulate_replay_attack(merchant_id: str, consumed_nonce: str, pin: str = "1234") -> Tuple[bool, str]:
        """
        Attack Demo: Attempts to reuse a previously consumed intent nonce.
        Must be blocked fail-closed.
        """
        try:
            security_engine.consume_intent(consumed_nonce, merchant_id, pin)
            return False, "CRITICAL VULNERABILITY: Replay succeeded!"
        except SecurityError as e:
            return True, f"Replay successfully blocked: {e.code} ({e})"

    @staticmethod
    def simulate_over_limit_attack(merchant_id: str, excessive_amount: int = 15000, pin: str = "1234") -> Tuple[bool, str]:
        """
        Attack Demo: Attempts to execute an intent exceeding per-tx cap.
        Must be blocked fail-closed.
        """
        intent = security_engine.create_intent(merchant_id, excessive_amount)
        try:
            security_engine.consume_intent(intent["nonce"], merchant_id, pin)
            return False, "CRITICAL VULNERABILITY: Over-limit transaction succeeded!"
        except SecurityError as e:
            return True, f"Over-limit transaction successfully blocked: {e.code} ({e})"

