# SautiPay SMS Service Boundary
#
# CRITICAL ARCHITECTURAL INVARIANT (INV-6):
# The notification service has NO CODE PATH that sends "PAYMENT RECEIVED" / "SETTLED"
# except a verified settlement event from our Lightning node (preimage hash match +
# settled invoice lookup).
#
# Grep the codebase in CI: send_settled is ONLY imported/called from app/settlement.py.

from typing import Dict, Any, Optional
import requests
from app.config import settings

class SMSService:
    def __init__(self):
        self.username = settings.AT_USERNAME
        self.api_key = settings.AT_API_KEY
        self.sender_id = settings.AT_SENDER_ID
        self.demo_mode = settings.DEMO_MODE

    def send_settled(self, phone: str, amount_ngn: int, receipt_hash: str, value_mode: str, settled_time_str: str) -> bool:
        """
        Sends the verified settlement SMS.
        Template: SAUTIPAY: ₦{amount} RECEIVED — SETTLED {HH:MM}. Ref: {receipt_hash[:6]}… Mode: {value_mode}.
        """
        short_ref = receipt_hash[:6]
        message = (
            f"SAUTIPAY: ₦{amount_ngn} RECEIVED — SETTLED {settled_time_str}. "
            f"Ref: {short_ref}… Mode: {value_mode}."
        )
        return self._dispatch_sms(phone, message)

    def send_blocked(self, phone: str, reason: str, nonce: str) -> bool:
        """
        Sends security alert for blocked transaction (e.g., in demo).
        Template: SAUTIPAY: PAYMENT BLOCKED — {reason}. Ref: {nonce[:6]}
        """
        short_nonce = nonce[:6]
        message = f"SAUTIPAY: PAYMENT BLOCKED — {reason}. Ref: {short_nonce}"
        return self._dispatch_sms(phone, message)

    def _dispatch_sms(self, phone: str, message: str) -> bool:
        # In demo mode or if credentials not present, log / print to stdout & return success
        if not self.api_key or self.username == "sandbox" or self.demo_mode:
            print(f"\n[SMS DISPATCH -> {phone}]: {message}\n")
            return True

        # Africa's Talking REST API
        url = "https://api.africastalking.com/version1/messaging"
        headers = {
            "ApiKey": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        data = {
            "username": self.username,
            "to": phone,
            "message": message,
            "from": self.sender_id
        }
        try:
            resp = requests.post(url, headers=headers, data=data, timeout=10)
            return resp.status_code == 201 or resp.status_code == 200
        except Exception as e:
            print(f"[SMS DISPATCH ERROR]: {e}")
            return False

sms_service = SMSService()

