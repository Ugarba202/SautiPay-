import pytest
import uuid
import time
from app.models import init_db, db_session
from app.security_engine import SecurityEngine, hash_pin, SecurityError

@pytest.fixture
def sec_db(tmp_path):
    db_file = str(tmp_path / "security_test.db")
    init_db(db_file)
    merchant_id = str(uuid.uuid4())
    
    # PIN: 1234
    pin_hash, pin_salt = hash_pin("1234")

    with db_session(db_file) as conn:
        conn.execute(
            """
            INSERT INTO merchants (id, phone, pin_hash, pin_salt, settlement_mode, daily_limit_ngn)
            VALUES (?, ?, ?, ?, 'lock_ngn', 50000)
            """,
            (merchant_id, "+2348000000001", pin_hash, pin_salt)
        )
    return db_file, merchant_id

def test_pin_hashing():
    h1, s1 = hash_pin("1234")
    assert len(h1) == 128 # 64 bytes scrypt in hex
    assert len(s1) == 32 # 16 bytes salt in hex
    # Same pin with same salt reproduces identical hash
    h2, _ = hash_pin("1234", salt=s1)
    assert h1 == h2

def test_create_and_consume_intent_happy_path(sec_db):
    db_file, merchant_id = sec_db
    engine = SecurityEngine(db_file)

    intent = engine.create_intent(merchant_id, 2000, ttl_seconds=60)
    assert intent["status"] == "ACTIVE"

    consumed = engine.consume_intent(intent["nonce"], merchant_id, "1234")
    assert consumed["status"] == "USED"

def test_replay_blocked(sec_db):
    db_file, merchant_id = sec_db
    engine = SecurityEngine(db_file)

    intent = engine.create_intent(merchant_id, 2000)
    # First consume succeeds
    engine.consume_intent(intent["nonce"], merchant_id, "1234")

    # Second consume is REPLAY BLOCKED
    with pytest.raises(SecurityError) as exc_info:
        engine.consume_intent(intent["nonce"], merchant_id, "1234")
    assert exc_info.value.code == "replay_blocked"

def test_wrong_pin_and_locking(sec_db):
    db_file, merchant_id = sec_db
    engine = SecurityEngine(db_file)

    intent = engine.create_intent(merchant_id, 2000)

    # Attempt 1 wrong
    with pytest.raises(SecurityError) as exc1:
        engine.consume_intent(intent["nonce"], merchant_id, "9999")
    assert exc1.value.code == "bad_pin"

    # Attempt 2 wrong
    with pytest.raises(SecurityError) as exc2:
        engine.consume_intent(intent["nonce"], merchant_id, "9999")
    assert exc2.value.code == "bad_pin"

    # Attempt 3 wrong
    with pytest.raises(SecurityError) as exc3:
        engine.consume_intent(intent["nonce"], merchant_id, "9999")
    assert exc3.value.code == "bad_pin"

    # Attempt 4 should be locked
    with pytest.raises(SecurityError) as exc4:
        engine.consume_intent(intent["nonce"], merchant_id, "1234")
    assert exc4.value.code == "locked"

def test_expiry(sec_db):
    db_file, merchant_id = sec_db
    engine = SecurityEngine(db_file)

    # Create intent with 1 second TTL
    intent = engine.create_intent(merchant_id, 2000, ttl_seconds=1)
    time.sleep(1.2)

    with pytest.raises(SecurityError) as exc_info:
        engine.consume_intent(intent["nonce"], merchant_id, "1234")
    assert exc_info.value.code == "expired"

def test_tx_and_daily_limits(sec_db):
    db_file, merchant_id = sec_db
    engine = SecurityEngine(db_file)

    # Exceed per-tx cap (default 10,000)
    intent_over_tx = engine.create_intent(merchant_id, 15000)
    with pytest.raises(SecurityError) as exc_tx:
        engine.consume_intent(intent_over_tx["nonce"], merchant_id, "1234")
    assert exc_tx.value.code == "over_tx_limit"

    # Exceed daily limit (50,000) by simulating past settled invoices
    with db_session(db_file) as conn:
        conn.execute(
            """
            INSERT INTO invoices (id, merchant_id, amount_ngn, amount_msat, sats_per_ngn, payment_hash, status)
            VALUES ('inv_prior', ?, 45000, 80000000, 1.8, 'hash_prior', 'SETTLED')
            """,
            (merchant_id,)
        )

    # Now an intent of 6,000 should exceed daily limit (45k + 6k = 51k > 50k)
    intent_daily = engine.create_intent(merchant_id, 6000)
    with pytest.raises(SecurityError) as exc_daily:
        engine.consume_intent(intent_daily["nonce"], merchant_id, "1234")
    assert exc_daily.value.code == "over_daily_limit"

def test_decline_by_default_unknown_nonce(sec_db):
    db_file, merchant_id = sec_db
    engine = SecurityEngine(db_file)

    with pytest.raises(SecurityError) as exc_info:
        engine.consume_intent("random_non_existent_nonce", merchant_id, "1234")
    assert exc_info.value.code == "unknown"

