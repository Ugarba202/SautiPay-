import pytest
import uuid
from app.models import init_db, db_session
from app.security_engine import SecurityEngine, hash_pin
from app.rate_oracle import RateOracle
from app.lightning_service import LightningService
from app.ussd_handler import USSDHandler, ussd_sessions

class MockLndUSSD(LightningService):
    def create_invoice(self, amount_msat: int, memo: str = "", expiry_seconds: int = 600):
        return "abcdef1234567890" * 4, "lnbc100u1dummybolt11invoice"

@pytest.fixture
def ussd_fixture(tmp_path):
    db_file = str(tmp_path / "ussd_test.db")
    init_db(db_file)
    merchant_id = str(uuid.uuid4())
    phone = "+2348033334444"

    pin_hash, pin_salt = hash_pin("1234")
    with db_session(db_file) as conn:
        conn.execute(
            """
            INSERT INTO merchants (id, phone, pin_hash, pin_salt, settlement_mode)
            VALUES (?, ?, ?, ?, 'lock_ngn')
            """,
            (merchant_id, phone, pin_hash, pin_salt)
        )

    sec_engine = SecurityEngine(db_file)
    oracle = RateOracle(db_file)
    oracle._cached_rate = 1.847
    oracle._cached_time = 9999999999.0
    lnd = MockLndUSSD()

    handler = USSDHandler(db_file, sec_engine, oracle, lnd)
    return handler, phone, merchant_id, db_file

def test_ussd_unregistered_phone(ussd_fixture):
    handler, _, _, _ = ussd_fixture
    resp = handler.handle("sess_unknown", "+2340000000000", "")
    assert "Ba a yi rijistar" in resp

def test_ussd_request_payment_flow(ussd_fixture):
    handler, phone, merchant_id, db_file = ussd_fixture
    sess_id = "sess_pay_1"

    # 1. Entry
    resp1 = handler.handle(sess_id, phone, "")
    assert resp1.startswith("CON SautiPay")

    # 2. Select option 1 (Request Payment)
    resp2 = handler.handle(sess_id, phone, "1")
    assert resp2 == "CON Shiga adadin Naira (e.g. 2000):"

    # 3. Enter amount 2000
    resp3 = handler.handle(sess_id, phone, "1*2000")
    assert resp3 == "CON Shiga PIN ɗinka:"

    # 4. Enter valid PIN 1234
    resp4 = handler.handle(sess_id, phone, "1*2000*1234")
    assert resp4.startswith("END SAUTIPAY: Invoice ₦2000 ready. Ref abcdef")

    # Verify invoice was created in DB
    with db_session(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM invoices WHERE merchant_id = ?", (merchant_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["amount_ngn"] == 2000
        assert row["status"] == "OPEN"

def test_ussd_request_payment_bad_pin_fails(ussd_fixture):
    handler, phone, _, _ = ussd_fixture
    sess_id = "sess_bad_pin"

    handler.handle(sess_id, phone, "")
    handler.handle(sess_id, phone, "1")
    handler.handle(sess_id, phone, "1*2000")
    resp = handler.handle(sess_id, phone, "1*2000*9999")
    assert "PAYMENT BLOCKED — bad_pin" in resp

def test_ussd_switch_mode(ussd_fixture):
    handler, phone, merchant_id, db_file = ussd_fixture
    sess_id = "sess_mode"

    handler.handle(sess_id, phone, "")
    resp = handler.handle(sess_id, phone, "3")
    assert "1. Adana sats" in resp

    resp2 = handler.handle(sess_id, phone, "3*1")
    assert "An sauya mode zuwa keep_sats" in resp2

    with db_session(db_file) as conn:
        row = conn.execute("SELECT settlement_mode FROM merchants WHERE id = ?", (merchant_id,)).fetchone()
        assert row["settlement_mode"] == "keep_sats"

def test_ussd_balance_check(ussd_fixture):
    handler, phone, merchant_id, db_file = ussd_fixture
    sess_id = "sess_bal"

    handler.handle(sess_id, phone, "")
    resp = handler.handle(sess_id, phone, "2")
    assert resp == "CON Shiga PIN ɗinka:"

    resp2 = handler.handle(sess_id, phone, "2*1234")
    assert "Balance:" in resp2
    assert "Tarihi:" in resp2

