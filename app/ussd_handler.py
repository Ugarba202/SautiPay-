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
    "CON SautiPay (English)\n"
    "1. Balance & History\n"
    "2. Request Payment (Invoice)\n"
    "3. Send to Phone Number\n"
    "4. Swap to On-Chain BTC\n"
    "5. Settlement Mode (lock_ngn/keep_sats)\n"
    "6. Yare / Language (Hausa)\n"
    "0. Exit"
)

MENU_HA = (
    "CON SautiPay (Hausa)\n"
    "1. Duba Balance da Tarihi\n"
    "2. Nemi Biya (Invoice)\n"
    "3. Tura Kudi zuwa Lambar Waya\n"
    "4. Musanya zuwa On-Chain BTC\n"
    "5. Yanayin Ajiya (lock_ngn/keep_sats)\n"
    "6. Switch to English\n"
    "0. Fita"
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
        """
        Handles Africa's Talking USSD turn.
        Supports:
        - Auto-registration on first dial (Language -> PIN setup)
        - Full wallet operations (Balance, Request, Send to Phone, Swap, Mode, Language)
        """
        session = ussd_sessions.get(session_id)
        if session is None:
            session = {"step": "INIT", "phone": phone, "data": {}}
            ussd_sessions[session_id] = session

        merchant = self._get_merchant(phone)
        inputs = [i.strip() for i in text.split("*")] if text.strip() else []
        current_input = inputs[-1] if inputs else ""

        # --- FLOW 1: AUTO-REGISTRATION FOR NEW USERS ---
        if not merchant:
            if not text or session["step"] == "INIT":
                session["step"] = "REG_CHOOSE_LANG"
                return (
                    "CON Welcome to SautiPay / Maraba da SautiPay\n"
                    "Select Language / Zabi Yare:\n"
                    "1. English\n"
                    "2. Hausa"
                )

            if session["step"] == "REG_CHOOSE_LANG":
                if current_input == "1":
                    session["data"]["lang"] = "en"
                elif current_input == "2":
                    session["data"]["lang"] = "ha"
                else:
                    return "END Invalid selection / Zabi ba daidai ba."

                session["step"] = "REG_SET_PIN"
                return (
                    "CON Enter a 4-digit secret PIN / Shiga lambobin sirri 4:"
                    if session["data"]["lang"] == "en"
                    else "CON Shiga lambobin sirri 4 na asusunka:"
                )

            if session["step"] == "REG_SET_PIN":
                pin = current_input
                if not (len(pin) == 4 and pin.isdigit()):
                    return "END PIN must be 4 digits / Dole PIN ya zama lambobi 4."

                pin_hash, pin_salt = hash_pin(pin)
                merchant_id = str(uuid.uuid4())
                with db_session(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO merchants (id, phone, pin_hash, pin_salt, settlement_mode, daily_limit_ngn)
                        VALUES (?, ?, ?, ?, 'lock_ngn', 50000)
                        """,
                        (merchant_id, phone, pin_hash, pin_salt)
                    )

                lang = session["data"].get("lang", "en")
                ussd_sessions.pop(session_id, None)
                if lang == "ha":
                    return "END SAUTIPAY: An bude asusunka! Sake kira domin fara aiki. / Dial again to start."
                return "END SAUTIPAY: Wallet created! Your phone number is your account. Dial again to use."

        # --- FLOW 2: REGISTERED USER WALLET OPERATIONS ---
        merchant_id = merchant["id"]
        # In this prototype, mode also hints language preference, default English
        lang = session["data"].get("lang", "en")

        if not text or session["step"] in ("INIT", "MAIN"):
            session["step"] = "MAIN"
            if not text:
                return MENU_HA if lang == "ha" else MENU_EN

            choice = current_input
            if choice == "1": # Balance
                session["step"] = "BAL_PIN"
                return "CON Shiga PIN:" if lang == "ha" else "CON Enter your PIN:"
            elif choice == "2": # Request Payment
                session["step"] = "REQ_AMT"
                return "CON Shiga adadin Naira (e.g. 2000):" if lang == "ha" else "CON Enter amount in Naira (e.g. 2000):"
            elif choice == "3": # Send to Phone
                session["step"] = "SEND_PHONE"
                return "CON Shiga lambar mai karba (e.g. 08012345678):" if lang == "ha" else "CON Enter recipient phone number:"
            elif choice == "4": # Swap to On-Chain
                session["step"] = "SWAP_AMT"
                return "CON Shiga adadin sats da za a cire (min 1000):" if lang == "ha" else "CON Enter sats to swap to on-chain (min 1000):"
            elif choice == "5": # Mode toggle
                session["step"] = "MODE_CHOICE"
                return "CON 1. Adana sats (keep_sats)\n2. Kulle Naira (lock_ngn)"
            elif choice == "6": # Switch language
                session["data"]["lang"] = "ha" if lang == "en" else "en"
                return MENU_HA if session["data"]["lang"] == "ha" else MENU_EN
            elif choice == "0":
                return "END Mun gode. / Thank you for using SautiPay."
            else:
                return "END Invalid choice / Zabi ba daidai ba."

        # 1. BALANCE CHECK
        elif session["step"] == "BAL_PIN":
            pin = current_input
            intent = self.sec_engine.create_intent(merchant_id, 0, action="ussd_balance")
            try:
                self.sec_engine.consume_intent(intent["nonce"], merchant_id, pin)
            except SecurityError as e:
                return f"END SAUTIPAY: BLOCKED — {e.code}"

            ledger = Ledger(self.db_path)
            receipts = ledger.get_merchant_receipts(merchant_id)
            total_ngn = sum(r["amount_ngn"] for r in receipts)
            rate, _, _ = self.oracle.get_rate()
            total_sats = int(total_ngn * rate) if rate > 0 else 0

            return (
                f"END SAUTIPAY: Kudi a asusu: {total_sats} sats (~₦{total_ngn}). Tarihi: {len(receipts)} receipts."
                if lang == "ha"
                else f"END SAUTIPAY: Balance: {total_sats} sats (~₦{total_ngn}). History: {len(receipts)} receipts."
            )

        # 2. REQUEST PAYMENT (INVOICE)
        elif session["step"] == "REQ_AMT":
            if not current_input.isdigit() or int(current_input) <= 0:
                return "END Invalid amount / Adadi ba daidai ba."
            session["data"]["req_amount"] = int(current_input)
            intent = self.sec_engine.create_intent(merchant_id, session["data"]["req_amount"], action="ussd_invoice")
            session["data"]["nonce"] = intent["nonce"]
            session["step"] = "REQ_PIN"
            return "CON Shiga PIN ɗinka:" if lang == "ha" else "CON Enter your PIN:"

        elif session["step"] == "REQ_PIN":
            pin = current_input
            amount_ngn = session["data"]["req_amount"]
            nonce = session["data"]["nonce"]
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

            return f"END SAUTIPAY: Invoice ₦{amount_ngn} ready. Ref {payment_hash[:6]}. Awaiting payment…"

        # 3. SEND TO PHONE NUMBER
        elif session["step"] == "SEND_PHONE":
            dest_phone = current_input
            dest_merchant = self._get_merchant(dest_phone)
            if not dest_merchant:
                return f"END SAUTIPAY: Recipient {dest_phone} has no wallet."

            session["data"]["dest_phone"] = dest_phone
            session["data"]["dest_id"] = dest_merchant["id"]
            session["step"] = "SEND_AMT"
            return "CON Shiga adadin Naira da za a tura:" if lang == "ha" else "CON Enter amount in Naira to send:"

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
            # Credit recipient on ledger
            ledger = Ledger(self.db_path)
            with db_session(self.db_path) as conn:
                # Mock invoice for internal transfer
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

        # 4. SWAP TO ON-CHAIN
        elif session["step"] == "SWAP_AMT":
            if not current_input.isdigit() or int(current_input) < 1000:
                return "END Min swap is 1,000 sats / Karancin musanya sats 1000 ne."
            session["data"]["swap_sats"] = int(current_input)
            session["step"] = "SWAP_ADDR"
            return "CON Shiga Bitcoin Address (on-chain):" if lang == "ha" else "CON Enter Bitcoin On-Chain Address:"

        elif session["step"] == "SWAP_ADDR":
            onchain_addr = current_input
            sats = session["data"]["swap_sats"]
            swap = self.swaps.create_swap(merchant_id, "ln_to_btc", sats, onchain_addr)
            # Execute swap settlement
            self.swaps.execute_and_claim_swap(swap["swap_id"])
            return f"END SAUTIPAY: Swap complete! {swap['net_sats']} sats sent to on-chain BTC address. Fee: {swap['fee_sats']} sats."

        # 5. MODE CHOICE
        elif session["step"] == "MODE_CHOICE":
            new_mode = "keep_sats" if current_input == "1" else ("lock_ngn" if current_input == "2" else None)
            if not new_mode:
                return "END Invalid choice / Zabi ba daidai ba."
            with db_session(self.db_path) as conn:
                conn.execute("UPDATE merchants SET settlement_mode = ? WHERE id = ?", (new_mode, merchant_id))
            return f"END SAUTIPAY: Mode changed to {new_mode}."

        return "END Mun gode. / Thank you."

    def _get_merchant(self, phone: str) -> Optional[Dict[str, Any]]:
        with db_session(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM merchants WHERE phone = ?", (phone,))
            row = cursor.fetchone()
            return dict(row) if row else None

ussd_handler = USSDHandler()
