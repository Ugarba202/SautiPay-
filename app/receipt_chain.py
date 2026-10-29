import hashlib
from typing import Optional, Dict, Any

GENESIS_HASH = "0" * 64

def compute_receipt_hash(
    merchant_id: str,
    seq: int,
    invoice_id: str,
    amount_ngn: int,
    sats_per_ngn: float,
    value_mode: str,
    value_locked_ngn: Optional[int],
    prev_receipt_hash: str
) -> str:
    """
    Computes canonical receipt hash:
    SHA256(merchant_id || seq || invoice_id || amount_ngn || sats_per_ngn || value_mode || value_locked_ngn || prev_receipt_hash)
    Joined deterministically with '|'.
    """
    locked_str = str(value_locked_ngn) if value_locked_ngn is not None else "None"
    payload = f"{merchant_id}|{seq}|{invoice_id}|{amount_ngn}|{sats_per_ngn}|{value_mode}|{locked_str}|{prev_receipt_hash}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def verify_receipt(receipt: Dict[str, Any]) -> bool:
    """Verifies a single receipt hash against its own content fields."""
    expected_hash = compute_receipt_hash(
        merchant_id=receipt["merchant_id"],
        seq=receipt["seq"],
        invoice_id=receipt["invoice_id"],
        amount_ngn=receipt["amount_ngn"],
        sats_per_ngn=receipt["sats_per_ngn"],
        value_mode=receipt["value_mode"],
        value_locked_ngn=receipt.get("value_locked_ngn"),
        prev_receipt_hash=receipt["prev_receipt_hash"]
    )
    return expected_hash == receipt["receipt_hash"]

