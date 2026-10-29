import pytest
import sqlite3
import uuid
from app.models import init_db, db_session
from app.ledger import Ledger
from app.receipt_chain import GENESIS_HASH

@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "ledger_test.db")
    init_db(db_file)
    # Seed a merchant
    merchant_id = str(uuid.uuid4())
    with db_session(db_file) as conn:
        conn.execute(
            """
            INSERT INTO merchants (id, phone, pin_hash, pin_salt, settlement_mode)
            VALUES (?, ?, ?, ?, ?)
            """,
            (merchant_id, "+2348011112222", "hash", "salt", "lock_ngn")
        )
        # Seed dummy invoices
        for i in range(1, 4):
            conn.execute(
                """
                INSERT INTO invoices (id, merchant_id, amount_ngn, amount_msat, sats_per_ngn, payment_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"inv_{i}", merchant_id, 2000 * i, 2000 * i * 1840, 1.84, f"hash_{i}")
            )
    return db_file, merchant_id

def test_ledger_append_and_verify_chain(test_db):
    db_file, merchant_id = test_db
    ledger = Ledger(db_file)

    # Empty chain verifies true
    assert ledger.verify_chain(merchant_id) is True

    # Append 3 receipts
    r1 = ledger.append_receipt(merchant_id, "inv_1", 2000, 1.84, "lock_ngn", 2000)
    assert r1["seq"] == 1
    assert r1["prev_receipt_hash"] == GENESIS_HASH

    r2 = ledger.append_receipt(merchant_id, "inv_2", 4000, 1.84, "keep_sats", None)
    assert r2["seq"] == 2
    assert r2["prev_receipt_hash"] == r1["receipt_hash"]

    r3 = ledger.append_receipt(merchant_id, "inv_3", 6000, 1.84, "lock_ngn", 6000)
    assert r3["seq"] == 3
    assert r3["prev_receipt_hash"] == r2["receipt_hash"]

    # Full chain verification passes
    assert ledger.verify_chain(merchant_id) is True

def test_ledger_detects_tamper_in_chain(test_db):
    db_file, merchant_id = test_db
    ledger = Ledger(db_file)

    ledger.append_receipt(merchant_id, "inv_1", 2000, 1.84, "lock_ngn", 2000)
    ledger.append_receipt(merchant_id, "inv_2", 4000, 1.84, "keep_sats", None)
    ledger.append_receipt(merchant_id, "inv_3", 6000, 1.84, "lock_ngn", 6000)

    assert ledger.verify_chain(merchant_id) is True

    # Tamper with an existing record in SQLite directly
    with db_session(db_file) as conn:
        conn.execute("UPDATE receipts SET amount_ngn = 9999 WHERE seq = 2 AND merchant_id = ?", (merchant_id,))

    # Verification must fail!
    assert ledger.verify_chain(merchant_id) is False

def test_ledger_detects_seq_gap(test_db):
    db_file, merchant_id = test_db
    ledger = Ledger(db_file)

    ledger.append_receipt(merchant_id, "inv_1", 2000, 1.84, "lock_ngn", 2000)
    ledger.append_receipt(merchant_id, "inv_2", 4000, 1.84, "keep_sats", None)

    # Force a sequence gap directly
    with db_session(db_file) as conn:
        conn.execute("UPDATE receipts SET seq = 5 WHERE seq = 2 AND merchant_id = ?", (merchant_id,))

    assert ledger.verify_chain(merchant_id) is False

