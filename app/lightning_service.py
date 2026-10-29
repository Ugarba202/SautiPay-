import base64
import requests
import json
from typing import Tuple, Dict, Any, Optional
from app.config import settings

class LightningError(Exception):
    pass

class LightningService:
    def __init__(
        self,
        rest_url: Optional[str] = None,
        macaroon_hex: Optional[str] = None,
        tls_cert_path: Optional[str] = None
    ):
        self.rest_url = (rest_url or settings.LND_REST_URL).rstrip("/")
        self.macaroon_hex = macaroon_hex or settings.LND_MACAROON_HEX
        self.tls_cert_path = tls_cert_path or settings.LND_TLS_CERT_PATH

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.macaroon_hex:
            headers["Grpc-Metadata-macaroon"] = self.macaroon_hex
        return headers

    def create_invoice(self, amount_msat: int, memo: str = "", expiry_seconds: int = 600) -> Tuple[str, str]:
        """
        Creates a Lightning invoice via LND REST: POST /v1/invoices.
        Returns: (payment_hash_hex, payment_request_bolt11)
        """
        url = f"{self.rest_url}/v1/invoices"
        payload = {
            "value_msat": str(amount_msat),
            "memo": memo,
            "expiry": str(expiry_seconds)
        }
        try:
            resp = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                verify=False, # Voltage/cloud testnet or self-signed cert
                timeout=10
            )
            if resp.status_code != 200:
                raise LightningError(f"LND invoice creation failed ({resp.status_code}): {resp.text}")
            data = resp.json()
            r_hash_b64 = data.get("r_hash")
            payment_request = data.get("payment_request")
            payment_hash = base64.b64decode(r_hash_b64).hex()
            return payment_hash, payment_request
        except requests.RequestException as e:
            raise LightningError(f"LND node connection error: {e}")

    def lookup_invoice(self, payment_hash_hex: str) -> Tuple[str, Optional[str]]:
        """
        Looks up an invoice by payment hash via LND REST.
        Returns: (state, preimage_hex)
        State is one of: 'OPEN', 'SETTLED', 'CANCELED', 'ACCEPTED'
        """
        # Convert hex payment hash to base64 URL safe or standard for LND lookup
        r_hash_bytes = bytes.fromhex(payment_hash_hex)
        r_hash_b64url = base64.urlsafe_b64encode(r_hash_bytes).decode("ascii")

        url = f"{self.rest_url}/v1/invoice/{r_hash_b64url}"
        try:
            resp = requests.get(
                url,
                headers=self._headers(),
                verify=False,
                timeout=10
            )
            if resp.status_code != 200:
                raise LightningError(f"LND invoice lookup failed ({resp.status_code}): {resp.text}")
            data = resp.json()
            state = data.get("state", "OPEN")
            r_preimage_b64 = data.get("r_preimage")
            preimage_hex = None
            if r_preimage_b64:
                raw_preimage = base64.b64decode(r_preimage_b64)
                if any(raw_preimage): # Non-zero bytes
                    preimage_hex = raw_preimage.hex()

            return state, preimage_hex
        except requests.RequestException as e:
            raise LightningError(f"LND node connection error: {e}")

lightning_service = LightningService()

