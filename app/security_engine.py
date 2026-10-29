import hashlib
import uuid
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple

from app.models import db_session
from app.sms_service import sms_service

MAX_ATTEMPTS = 3
DEFAULT_PER_TX_LIMIT_NGN = 10000

class SecurityError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

def hash_pin(pin: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """
    Hashes a PIN using hashlib.scrypt with a 16-byte salt.
    Returns: (hex_hash, hex_salt)
    """
    if salt is None:
        salt_bytes = secrets.token_bytes(16)
        salt_hex = salt_bytes.hex()
    else:
        salt_bytes = bytes.fromhex(salt)
        salt_hex = salt

    # scrypt parameters: n=16384, r=8, p=1
    key = hashlib.scrypt(pin.encode("utf-8"), salt=salt_bytes, n=16384, r=8, p=1, maxmem=32 * 1024 * 1024)
    return key.hex(), salt_hex

def verify_pin(pin: str, stored_hash: str, salt_hex: str) -> bool:
    expected_hash, _ = hash_pin(pin, salt=salt_hex)
    return secrets.compare_digest(expected_hash, stored_hash)

class SecurityEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def create_intent(
        self,
        merchant_id: str,
        amount_ngn: int,
        action: str = "ussd_request_payment",
        ttl_seconds: int = 120
    ) -> Dict[str, Any]:
        """Creates an intent with a unique single-use nonce and short expiry."""
        intent_id = str(uuid.uuid4())
        nonce = secrets.token_hex(16)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        with db_session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO intents (id, merchant_id, nonce, action, amount_ngn, expiry, status, attempts)
                VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', 0)
                """,
                (intent_id, merchant_id, nonce, action, amount_ngn, expiry.isoformat())
            )
            conn.execute(
                """
                INSERT INTO audit_log (entity_type, entity_id, action, details)
                VALUES (?, ?, ?, ?)
                """,
                ("intent", intent_id, "INTENT_CREATED", f"Action: {action}, Amount: {amount_ngn} NGN, Expiry: {expiry}")
            )

        return {
            "id": intent_id,
            "nonce": nonce,
            "merchant_id": merchant_id,
            "amount_ngn": amount_ngn,
            "expiry": expiry.isoformat(),
            "status": "ACTIVE"
        }

    def consume_intent(
        self,
        nonce: str,
        merchant_id: str,
        pin: str,
        per_tx_limit_ngn: int = DEFAULT_PER_TX_LIMIT_NGN
    ) -> Dict[str, Any]:
        """
        Consumes an intent enforcing decline-by-default (INV-4):
        - Nonce unknown / belongs to another merchant -> BLOCKED ('unknown')
        - Attempts >= 3 -> BLOCKED ('locked')
        - Expired -> EXPIRED ('expired')
        - Bad PIN -> attempts++, BLOCKED ('bad_pin')
        - Amount > per_tx_limit -> BLOCKED ('over_tx_limit')
        - Daily settled total + amount > daily_limit_ngn -> BLOCKED ('over_daily_limit')
        - If already USED / REPLAY -> BLOCKED ('replay_blocked')
        - Success -> status marked 'USED'
        """
        now = datetime.now(timezone.utc)

        with db_session(self.db_path) as conn:
            cursor = conn.cursor()

            # 1. Look up intent
            cursor.execute("SELECT * FROM intents WHERE nonce = ?", (nonce,))
            row = cursor.fetchone()
            if not row or row["merchant_id"] != merchant_id:
                self._record_block(conn, "unknown_intent", nonce, "unknown")
                raise SecurityError("unknown", "Intent not found or merchant mismatch")

            intent = dict(row)
            intent_id = intent["id"]
            amount_ngn = intent["amount_ngn"]

            # Fetch merchant for PIN and phone
            cursor.execute("SELECT * FROM merchants WHERE id = ?", (merchant_id,))
            merchant_row = cursor.fetchone()
            if not merchant_row:
                self._record_block(conn, intent_id, nonce, "merchant_not_found")
                raise SecurityError("merchant_not_found", "Merchant not found")
            merchant = dict(merchant_row)

            # Check replay
            if intent["status"] == "USED":
                self._record_block(conn, intent_id, nonce, "replay_blocked", merchant["phone"])
                cursor.execute("UPDATE intents SET status = 'REPLAY_BLOCKED' WHERE id = ?", (intent_id,))
                raise SecurityError("replay_blocked", "Intent already used - replay blocked")

            if intent["status"] != "ACTIVE":
                self._record_block(conn, intent_id, nonce, f"status_{intent['status']}", merchant["phone"])
                raise SecurityError(intent["status"].lower(), f"Intent is {intent['status']}")

            # Check locked attempts
            if intent["attempts"] >= MAX_ATTEMPTS:
                self._record_block(conn, intent_id, nonce, "locked", merchant["phone"])
                raise SecurityError("locked", "PIN entry locked after too many attempts")

            # Check expiry
            expiry_dt = datetime.fromisoformat(intent["expiry"])
            if now > expiry_dt:
                cursor.execute("UPDATE intents SET status = 'EXPIRED' WHERE id = ?", (intent_id,))
                self._record_block(conn, intent_id, nonce, "expired", merchant["phone"])
                raise SecurityError("expired", "Intent expired")

            # Check PIN
            if not verify_pin(pin, merchant["pin_hash"], merchant["pin_salt"]):
                new_attempts = intent["attempts"] + 1
                cursor.execute("UPDATE intents SET attempts = ? WHERE id = ?", (new_attempts, intent_id))
                self._record_block(conn, intent_id, nonce, "bad_pin", merchant["phone"])
                conn.commit()  # commit incremented attempts and audit record before raising!
                raise SecurityError("bad_pin", f"Invalid PIN ({new_attempts}/{MAX_ATTEMPTS} attempts)")

            # Check per-tx limit
            if amount_ngn > per_tx_limit_ngn:
                self._record_block(conn, intent_id, nonce, "over_tx_limit", merchant["phone"])
                raise SecurityError("over_tx_limit", f"Amount ₦{amount_ngn} exceeds per-tx limit of ₦{per_tx_limit_ngn}")

            # Check daily limit: calculate today's settled volume
            # Look up invoices settled today
            today_start = now.strftime("%Y-%m-%d 00:00:00")
            cursor.execute(
                """
                SELECT SUM(amount_ngn) as total_today 
                FROM invoices 
                WHERE merchant_id = ? AND status = 'SETTLED'
                """,
                (merchant_id,)
            )
            sum_row = cursor.fetchone()
            total_today = sum_row["total_today"] or 0
            daily_limit = merchant.get("daily_limit_ngn", 50000)

            if total_today + amount_ngn > daily_limit:
                self._record_block(conn, intent_id, nonce, "over_daily_limit", merchant["phone"])
                raise SecurityError("over_daily_limit", f"Exceeds daily limit (Current: ₦{total_today}, Limit: ₦{daily_limit})")

            # All checks pass -> mark USED
            cursor.execute("UPDATE intents SET status = 'USED' WHERE id = ?", (intent_id,))
            cursor.execute(
                """
                INSERT INTO audit_log (entity_type, entity_id, action, details)
                VALUES (?, ?, ?, ?)
                """,
                ("intent", intent_id, "INTENT_CONSUMED", f"Successfully authorized ₦{amount_ngn}")
            )

            intent["status"] = "USED"
            return intent

    def _record_block(self, conn, intent_id: str, nonce: str, reason: str, phone: Optional[str] = None):
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO audit_log (entity_type, entity_id, action, details)
            VALUES (?, ?, ?, ?)
            """,
            ("security", intent_id, "BLOCKED", f"Reason: {reason}, Nonce: {nonce}")
        )
        if phone:
            sms_service.send_blocked(phone, reason, nonce)

security_engine = SecurityEngine()
