import re
from typing import Dict, Any, Optional
from app.models import db_session
from app.ledger import Ledger
from app.rate_oracle import rate_oracle
from app.security_engine import security_engine

class SMSHandler:
    """
    Strict, table-driven regex parser turning inbound SMS into SautiPay actions:
    - Watch-only balance & history: 'balance', 'kudi', 'tarihi' (No PIN needed)
    - Send with call-back: 'send 500 to 080...' (Triggers call-back for PIN)
    - Help / Menu: 'help', 'menu', 'madad'
    """
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def handle_inbound_sms(self, phone: str, message: str) -> str:
        text = message.strip().lower()

        # Check if merchant exists
        with db_session(self.db_path) as conn:
            m = conn.execute("SELECT * FROM merchants WHERE phone = ?", (phone,)).fetchone()
            if not m:
                return "SAUTIPAY: Lambar nan ba ta da asusu. / Phone number not registered. Dial *384# to open a wallet."
            merchant = dict(m)

        merchant_id = merchant["id"]

        # 1. WATCH-ONLY BALANCE (DialSats Gem: Zero key risk, answered live)
        if text in ("balance", "kudi", "bal"):
            ledger = Ledger(self.db_path)
            receipts = ledger.get_merchant_receipts(merchant_id)
            total_ngn = sum(r["amount_ngn"] for r in receipts)
            rate, _, _ = rate_oracle.get_rate()
            total_sats = int(total_ngn * rate) if rate > 0 else 0
            return f"SAUTIPAY: Kudi a asusu / Balance: {total_sats} sats (~₦{total_ngn}). Total receipts: {len(receipts)}."

        # 2. WATCH-ONLY RECENT HISTORY
        if text in ("history", "tarihi", "receipts"):
            ledger = Ledger(self.db_path)
            receipts = ledger.get_merchant_receipts(merchant_id)
            if not receipts:
                return "SAUTIPAY: Ba ka da wani biya tukunna. / No receipts yet."
            last = receipts[-1]
            return f"SAUTIPAY: Last Receipt #{last['seq']}: ₦{last['amount_ngn']} ({last['value_mode']}). Ref: {last['receipt_hash'][:8]}..."

        # 3. SEND REQUEST (Triggers Call-back for PIN - PIN never accepted in SMS)
        send_match = re.match(r"(?:send|aika)\s+(\d+)\s+(?:to|zuwa)\s+([\+\d]+)", text)
        if send_match:
            amount = int(send_match.group(1))
            dest = send_match.group(2)
            # Create a pending intent
            intent = security_engine.create_intent(merchant_id, amount, action="sms_send_p2p")
            return (
                f"SAUTIPAY: Za mu kira ka don tabbatar da tura ₦{amount} zuwa {dest}. / "
                f"We are calling you back now to confirm ₦{amount} to {dest} with your PIN."
            )

        # 4. LIGHTNING ADDRESS LOOKUP
        if text in ("address", "addr", "karba", "receive"):
            clean_phone = phone.replace("+", "")
            return f"SAUTIPAY: Your Lightning Address is: {clean_phone}@sautipay.ng. Anyone can send you sats from any Lightning app!"

        # 5. HELP / MENU
        return (
            "SAUTIPAY MENU:\n"
            "- Text 'balance' for balance\n"
            "- Text 'history' for last receipt\n"
            "- Text 'send <amount> to <phone>'\n"
            "- Dial *384# for USSD menu"
        )

sms_handler = SMSHandler()

