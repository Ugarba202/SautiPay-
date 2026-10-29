import pytest
import uuid
from app.models import init_db, db_session
from app.security_engine import hash_pin
from app.sms_handler import SMSHandler
from app.voice_handler import VoiceHandler
from app.ledger import Ledger

@pytest.fixture
def phone_channels_fixture(tmp_path, monkeypatch):
    db_file = str(tmp_path / "channels_test.db")
    init_db(db_file)
    merchant_id = str(uuid.uuid4())
    phone = "+2348011223344"

    pin_h, pin_s = hash_pin("1234")
    with db_session(db_file) as conn:
        conn.execute(
            """
            INSERT INTO merchants (id, phone, pin_hash, pin_salt, settlement_mode)
            VALUES (?, ?, ?, ?, 'lock_ngn')
            """,
            (merchant_id, phone, pin_h, pin_s)
        )

    # Seed 1 receipt into ledger
    from app.config import settings
    monkeypatch.setattr(settings, "RATE_OVERRIDE_NGN", 1.847)
    ledger = Ledger(db_file)
    with db_session(db_file) as conn:
        conn.execute(
            """
            INSERT INTO invoices (id, merchant_id, amount_ngn, amount_msat, sats_per_ngn, payment_hash, status)
            VALUES ('inv_1', ?, 2000, 3694000, 1.847, 'hash_1', 'SETTLED')
            """,
            (merchant_id,)
        )
        ledger.append_receipt(merchant_id, "inv_1", 2000, 1.847, "lock_ngn", 2000, "SENT", conn)

    sms = SMSHandler(db_file)
    voice = VoiceHandler(db_file)
    return sms, voice, phone, merchant_id

def test_sms_watch_only_balance(phone_channels_fixture):
    sms, _, phone, _ = phone_channels_fixture
    reply = sms.handle_inbound_sms(phone, "balance")
    assert "Balance:" in reply or "Kudi a asusu" in reply
    assert "Total receipts: 1" in reply

def test_sms_watch_only_history(phone_channels_fixture):
    sms, _, phone, _ = phone_channels_fixture
    reply = sms.handle_inbound_sms(phone, "tarihi")
    assert "Receipt #1" in reply
    assert "₦2000" in reply

def test_sms_send_triggers_callback_safety(phone_channels_fixture):
    sms, _, phone, _ = phone_channels_fixture
    reply = sms.handle_inbound_sms(phone, "send 1500 to 08099887766")
    # Must announce call-back; PIN never requested via SMS
    assert "calling you back" in reply.lower() or "kira ka" in reply.lower()

def test_sms_lightning_address_lookup(phone_channels_fixture):
    sms, _, phone, _ = phone_channels_fixture
    reply = sms.handle_inbound_sms(phone, "address")
    assert "@sautipay.ng" in reply

def test_voice_inbound_welcome(phone_channels_fixture):
    _, voice, phone, _ = phone_channels_fixture
    xml = voice.handle_inbound_call(phone, dtmf_digits=None)
    assert "<GetDigits" in xml
    assert "Welcome to SautiPay" in xml

def test_voice_inbound_balance_with_pin(phone_channels_fixture):
    _, voice, phone, _ = phone_channels_fixture
    # Language select
    xml_lang = voice.handle_inbound_call(phone, dtmf_digits="1")
    assert "enter your 4 digit secret PIN" in xml_lang

    # Valid PIN entry
    xml_bal = voice.handle_inbound_call(phone, dtmf_digits="1234")
    assert "Your SautiPay balance is" in xml_bal
    assert "verified receipts" in xml_bal

def test_voice_bad_pin_fails_closed(phone_channels_fixture):
    _, voice, phone, _ = phone_channels_fixture
    xml = voice.handle_inbound_call(phone, dtmf_digits="9999")
    assert "Incorrect PIN" in xml
    assert "<Hangup/>" in xml
