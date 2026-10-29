import pytest
from app.receipt_chain import compute_receipt_hash, verify_receipt, GENESIS_HASH

def test_receipt_hash_determinism():
    h1 = compute_receipt_hash("m1", 1, "inv1", 2000, 1.84, "lock_ngn", 2000, GENESIS_HASH)
    h2 = compute_receipt_hash("m1", 1, "inv1", 2000, 1.84, "lock_ngn", 2000, GENESIS_HASH)
    assert h1 == h2
    assert len(h1) == 64

def test_verify_receipt_tamper():
    h = compute_receipt_hash("m1", 1, "inv1", 2000, 1.84, "lock_ngn", 2000, GENESIS_HASH)
    receipt = {
        "merchant_id": "m1",
        "seq": 1,
        "invoice_id": "inv1",
        "amount_ngn": 2000,
        "sats_per_ngn": 1.84,
        "value_mode": "lock_ngn",
        "value_locked_ngn": 2000,
        "prev_receipt_hash": GENESIS_HASH,
        "receipt_hash": h
    }
    assert verify_receipt(receipt) is True

    # Tamper with amount
    tampered_amount = dict(receipt)
    tampered_amount["amount_ngn"] = 2500
    assert verify_receipt(tampered_amount) is False

    # Tamper with sats_per_ngn
    tampered_rate = dict(receipt)
    tampered_rate["sats_per_ngn"] = 1.85
    assert verify_receipt(tampered_rate) is False

    # Tamper with prev_receipt_hash
    tampered_prev = dict(receipt)
    tampered_prev["prev_receipt_hash"] = "a" * 64
    assert verify_receipt(tampered_prev) is False

