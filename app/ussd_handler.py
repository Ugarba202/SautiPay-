import uuid
import re
from typing import Dict, Any, Optional, Tuple
from app.models import db_session
from app.security_engine import security_engine, SecurityError, SecurityEngine, hash_pin
from app.rate_oracle import rate_oracle, RateOracle
from app.lightning_service import lightning_service, LightningService
from app.ledger import Ledger
from app.swap_service import swap_service, SwapService

# Session state dictionary for USSD sessions (keyed by sessionId)
ussd_sessions: Dict[str, Dict[str, Any]] = {}

MENU_EN = (
    "CON SautiPay\n"
    "1. Nemi Biya (Request Payment)\n"
    "2. Balance\n"
    "3. Zaɓi Moda (Choose Mode)\n"
    "4. Tura Kudi (Send to Phone)\n"
    "5. Swap to On-Chain BTC\n"
    "0. Fita (Exit)"
)

class USSDHandler:
    def __init__(
        self,
        db_path: Optional[str] = None,
        sec_engine: Optional[SecurityEngine] = None,
        oracle: Optional[RateOracle] = None,
        lnd: Optional[LightningService] = None,
        swaps: Optional[SwapService] = None
    ):
        self.db_path = db_path
        self.sec_engine = sec_engine or security_engine
        self.oracle = oracle or rate_oracle
        self.lnd = lnd or lightning_service
        self.swaps = swaps or swap_service

    def handle(self, session_id: str, phone: str, text: str) -> str:
        session = ussd_sessions.get(session_id)
        if session is None:
            session = {"step": "MAIN", "phone": phone, "data": {}}
            ussd_sessions[session_id] = session

        merchant = self._get_merchant(phone)
        if not merchant:
            return "END SAUTIPAY: Ba a yi rijistar lambar nan ba. / Phone number not registered."

        merchant_id = merchant["id"]
        inputs = [i.strip() for i in text.split("*")] if text.strip() else []
        current_input = inputs[-1] if inputs else ""

        if not text or session["step"] == "MAIN":
            if not text:
                return MENU_EN

            choice = current_input
            if choice == "1":
                session["step"] = "AWAITING_AMOUNT"
                return "CON Shiga adadin Naira (e.g. 2000):"
            elif choice == "2":
                session["step"] = "AWAITING_PIN_BALANCE"
                return "CON Shiga PIN ɗinka:"
            elif choice == "3":
                session["step"] = "AWAITING_MODE"
                return "CON 1. Adana sats (keep_sats)\n2. Kulle Naira (lock_ngn)"
            elif choice == "4":
                session["step"] = "SEND_PHONE"
                return "CON Shiga lambar mai karba (e.g. 08012345678):"
            elif choice == "5":
                session["step"] = "SWAP_AMT"
                return "CON Shiga adadin sats da za a cire (min 1000):"
            elif choice == "0":
                return "END Mun gode. / Thank you."
            else:
                return "END Zaɓi ba daidai ba. / Invalid choice."

        # 1. REQUEST PAYMENT
        elif session["step"] == "AWAITING_AMOUNT":
            if not current_input.isdigit() or int(current_input) <= 0:
                return "END SAUTIPAY: Adadi ba daidai ba. / Invalid amount."
            amount_ngn = int(current_input)
            if amount_ngn > 10000:
                return "END SAUTIPAY: PAYMENT BLOCKED — over_tx_limit (Max ₦10,000)."

            intent = self.sec_engine.create_intent(merchant_id, amount_ngn, action="ussd_request_payment")
            session["data"]["intent_nonce"] = intent["nonce"]
            session["data"]["amount_ngn"] = amount_ngn
            session["step"] = "AWAITING_PIN_PAYMENT"
            return "CON Shiga PIN ɗinka:"

        elif session["step"] == "AWAITING_PIN_PAYMENT":
            pin = current_input
            nonce = session["data"].get("intent_nonce")
            amount_ngn = session["data"].get("amount_ngn")
            try:
                self.sec_engine.consume_intent(nonce, merchant_id, pin)
            except SecurityError as e:
                return f"END SAUTIPAY: PAYMENT BLOCKED — {e.code}"

            amount_msat, sats_per_ngn = self.oracle.stamp_invoice(amount_ngn)
            payment_hash, payment_request = self.lnd.create_invoice(
                amount_msat=amount_msat,
                memo=f"SautiPay ₦{amount_ngn} for {phone}"
            )
            inv_id = str(uuid.uuid4())
            with db_session(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO invoices (id, merchant_id, amount_ngn, amount_msat, sats_per_ngn, memo, payment_hash, payment_request, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
                    """,
                    (inv_id, merchant_id, amount_ngn, amount_msat, sats_per_ngn, f"Invoice ₦{amount_ngn}", payment_hash, payment_request)
                )
            return f"END SAUTIPAY: Invoice ₦{amount_ngn} ready. Ref {payment_hash[:6]}. Customer yana biya…"

        # 2. BALANCE CHECK
        elif session["step"] == "AWAITING_PIN_BALANCE":
            pin = current_input
            intent = self.sec_engine.create_intent(merchant_id, 0, action="ussd_balance")
            try:
                self.sec_engine.consume_intent(intent["nonce"], merchant_id, pin)
            except SecurityError as e:
                return f"END SAUTIPAY: ACCESS BLOCKED — {e.code}"

            ledger = Ledger(self.db_path)
            receipts = ledger.get_merchant_receipts(merchant_id)
            total_ngn = sum(r["amount_ngn"] for r in receipts)
            rate, _, _ = self.oracle.get_rate()
            total_sats = int(total_ngn * rate) if rate > 0 else 0
            return f"END SAUTIPAY: Balance: {total_sats} sats (~₦{total_ngn}). Tarihi: {len(receipts)} receipts."

        # 3. MODE CHOICE
        elif session["step"] == "AWAITING_MODE":
            new_mode = "keep_sats" if current_input == "1" else ("lock_ngn" if current_input == "2" else None)
            if not new_mode:
                return "END Zaɓi ba daidai ba. / Invalid choice."
            with db_session(self.db_path) as conn:
                conn.execute("UPDATE merchants SET settlement_mode = ? WHERE id = ?", (new_mode, merchant_id))
            return f"END SAUTIPAY: An sauya mode zuwa {new_mode}."

        # 4. SEND TO PHONE
        elif session["step"] == "SEND_PHONE":
            dest_phone = current_input
            dest_merchant = self._get_merchant(dest_phone)
            if not dest_merchant:
                return f"END SAUTIPAY: Recipient {dest_phone} has no wallet."
            session["data"]["dest_phone"] = dest_phone
            session["data"]["dest_id"] = dest_merchant["id"]
            session["step"] = "SEND_AMT"
            return "CON Shiga adadin Naira da za a tura:"

        elif session["step"] == "SEND_AMT":
            if not current_input.isdigit() or int(current_input) <= 0:
                return "END Invalid amount / Adadi ba daidai ba."
            session["data"]["send_amount"] = int(current_input)
            intent = self.sec_engine.create_intent(merchant_id, session["data"]["send_amount"], action="ussd_p2p_send")
            session["data"]["nonce"] = intent["nonce"]
            session["step"] = "SEND_PIN"
            return f"CON Send ₦{current_input} to {session['data']['dest_phone']}?\nEnter PIN:"

        elif session["step"] == "SEND_PIN":
            pin = current_input
            amount_ngn = session["data"]["send_amount"]
            dest_id = session["data"]["dest_id"]
            nonce = session["data"]["nonce"]
            try:
                self.sec_engine.consume_intent(nonce, merchant_id, pin)
            except SecurityError as e:
                return f"END SAUTIPAY: SEND BLOCKED — {e.code}"

            rate, _, _ = self.oracle.get_rate()
            ledger = Ledger(self.db_path)
            with db_session(self.db_path) as conn:
                tx_inv_id = f"p2p_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO invoices (id, merchant_id, amount_ngn, amount_msat, sats_per_ngn, memo, payment_hash, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'SETTLED')
                    """,
                    (tx_inv_id, dest_id, amount_ngn, int(amount_ngn * rate * 1000), rate, f"P2P from {phone}", uuid.uuid4().hex)
                )
                r = ledger.append_receipt(dest_id, tx_inv_id, amount_ngn, rate, "lock_ngn", amount_ngn, "SENT", conn)

            return f"END SAUTIPAY: Sent ₦{amount_ngn} to {session['data']['dest_phone']} successfully! Ref: {r['receipt_hash'][:6]}."

        # 5. SWAP TO ON-CHAIN
        elif session["step"] == "SWAP_AMT":
            if not current_input.isdigit() or int(current_input) < 1000:
                return "END Min swap is 1,000 sats / Karancin musanya sats 1000 ne."
            session["data"]["swap_sats"] = int(current_input)
            session["step"] = "SWAP_ADDR"
            return "CON Shiga Bitcoin Address (on-chain):"

        elif session["step"] == "SWAP_ADDR":
            onchain_addr = current_input
            sats = session["data"]["swap_sats"]
            swap = self.swaps.create_swap(merchant_id, "ln_to_btc", sats, onchain_addr)
            self.swaps.execute_and_claim_swap(swap["swap_id"])
            return f"END SAUTIPAY: Swap complete! {swap['net_sats']} sats sent to on-chain BTC address. Fee: {swap['fee_sats']} sats."

        return "END Mun gode. / Thank you."

    def _get_merchant(self, phone: str) -> Optional[Dict[str, Any]]:
        with db_session(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM merchants WHERE phone = ?", (phone,))
            row = cursor.fetchone()
            return dict(row) if row else None

ussd_handler = USSDHandler()
