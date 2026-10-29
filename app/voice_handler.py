import json
from typing import Dict, Any, Optional
from app.models import db_session
from app.ledger import Ledger
from app.rate_oracle import rate_oracle
from app.security_engine import SecurityEngine, SecurityError

class VoiceHandler:
    """
    Africa's Talking & Twilio Voice/IVR Handler:
    - Provides spoken bilingual prompts (English and Hausa)
    - Collects DTMF keypad digits for PIN authentication
    - Handles Inbound calls to check balance and recent receipts
    - Handles Outbound Call-Back to confirm sensitive spends (DialSats security pattern)
    """
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.security_engine = SecurityEngine(db_path)

    def handle_inbound_call(self, caller_phone: str, dtmf_digits: Optional[str] = None) -> str:
        """
        Generates Voice XML response for inbound caller.
        """
        # Look up caller account
        with db_session(self.db_path) as conn:
            m = conn.execute("SELECT * FROM merchants WHERE phone = ?", (caller_phone,)).fetchone()
            if not m:
                # Spoken rejection for unregistered number
                return (
                    '<Response>\n'
                    '    <Say voice="woman" language="en-US">Welcome to SautiPay. Your phone number is not registered. Please dial star 384 hash to create a wallet. Goodbye.</Say>\n'
                    '    <Hangup/>\n'
                    '</Response>'
                )
            merchant = dict(m)

        merchant_id = merchant["id"]

        # Step 1: No DTMF yet -> Ask user to choose action or enter PIN
        if not dtmf_digits:
            return (
                '<Response>\n'
                '    <GetDigits timeout="10" numDigits="1" finishOnKey="#">\n'
                '        <Say voice="woman" language="en-US">Barka da zuwa SautiPay. Welcome to SautiPay. Press 1 for English, press 2 for Hausa.</Say>\n'
                '    </GetDigits>\n'
                '</Response>'
            )

        # Step 2: Language selected -> Request 4-digit PIN for security
        if dtmf_digits in ("1", "2"):
            lang = "en" if dtmf_digits == "1" else "ha"
            prompt = (
                "Please enter your 4 digit secret PIN followed by hash."
                if lang == "en"
                else "Shiga lambobin sirri hudu na asusunka sannan ka danna hash."
            )
            return (
                f'<Response>\n'
                f'    <GetDigits timeout="10" numDigits="4" finishOnKey="#">\n'
                f'        <Say voice="woman">{prompt}</Say>\n'
                f'    </GetDigits>\n'
                f'</Response>'
            )

        # Step 3: PIN entered (4 digits) -> Verify and speak balance
        if len(dtmf_digits) == 4:
            intent = self.security_engine.create_intent(merchant_id, 0, action="voice_balance")
            try:
                self.security_engine.consume_intent(intent["nonce"], merchant_id, dtmf_digits)
            except SecurityError as e:
                return (
                    '<Response>\n'
                    '    <Say voice="woman">Incorrect PIN. Your account access has been blocked. Goodbye.</Say>\n'
                    '    <Hangup/>\n'
                    '</Response>'
                )

            # Compute balance from ledger
            ledger = Ledger(self.db_path)
            receipts = ledger.get_merchant_receipts(merchant_id)
            total_ngn = sum(r["amount_ngn"] for r in receipts)
            rate, _, _ = rate_oracle.get_rate()
            total_sats = int(total_ngn * rate) if rate > 0 else 0

            return (
                f'<Response>\n'
                f'    <Say voice="woman">Your SautiPay balance is {total_sats} sats, approximately {total_ngn} Naira. You have {len(receipts)} verified receipts. Thank you for using SautiPay.</Say>\n'
                f'    <Hangup/>\n'
                f'</Response>'
            )

        return (
            '<Response>\n'
            '    <Say voice="woman">Invalid entry. Goodbye.</Say>\n'
            '    <Hangup/>\n'
            '</Response>'
        )

    def generate_callback_prompt(self, amount_ngn: int, recipient_phone: str, lang: str = "en") -> str:
        """
        DialSats pattern: The spoken message played when SautiPay rings the user
        back to authorize an outbound payment.
        """
        if lang == "ha":
            return (
                f'<Response>\n'
                f'    <GetDigits timeout="12" numDigits="4" finishOnKey="#">\n'
                f'        <Say voice="woman">Kira daga SautiPay. Za ka tura Naira dubu {amount_ngn} zuwa {recipient_phone}. Shiga lambobin PIN dinka don tabbatarwa.</Say>\n'
                f'    </GetDigits>\n'
                f'</Response>'
            )
        return (
            f'<Response>\n'
            f'    <GetDigits timeout="12" numDigits="4" finishOnKey="#">\n'
            f'        <Say voice="woman">SautiPay confirmation call. You are sending {amount_ngn} Naira to {recipient_phone}. Enter your 4 digit PIN followed by hash to authorize.</Say>\n'
            f'    </GetDigits>\n'
            f'</Response>'
        )

voice_handler = VoiceHandler()
