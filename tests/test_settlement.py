import pytest
import uuid
import hashlib
from app.models import init_db, db_session
from app.settlement import settle, SettlementError
from app.ledger import Ledger
from app.lightning_service import LightningService

class MockLndClient(LightningService):
    def __init__(self, state="SETTLED", preimage=None):
        self.state = state
        self.preimage = preimage

    def lookup_invoice(self, payment_hash_hex: str):
        return self.state, self.preimage

@pytest.fixture
def settlement_fixture(tmp_path):
    db_file = str(tmp_path / "settlement_test.db")
    init_db(db_file)
    merchant_id = str(uuid.uuid4())
    invoice_id = str(uuid.uuid4())
    
    # Preimage and corresponding payment hash
    real_preimage = "11" * 32
    real_payment_hash = hashlib.sha256(bytes.fromhex(real_preimage)).hexdigest()

    with db_session(db_file) as conn:
        conn.execute(
            """
            INSERT INTO merchants (id, phone, pin_hash, pin_salt, settlement_mode)
            VALUES (?, ?, ?, ?, ?)
            """,
            (merchant_id, "+2348011223344", "scrypt_hash", "salt", "lock_ngn")
        )
        conn.execute(
            """
            INSERT INTO invoices (id, merchant_id, amount_ngn, amount_msat, sats_per_ngn, payment_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, 'OPEN')
            """,
            (invoice_id, merchant_id, 2000, 3680000, 1.84, real_payment_hash)
        )

    return db_file, merchant_id, invoice_id, real_preimage, real_payment_hash

def test_inv1_settlement_proof_happy_path(settlement_fixture):
    db_file, merchant_id, invoice_id, real_preimage, real_payment_hash = settlement_fixture
    mock_lnd = MockLndClient(state="SETTLED", preimage=real_preimage)

    payment = settle(invoice_id, real_preimage, lnd_client=mock_lnd, db_path=db_file)
    assert payment["invoice_id"] == invoice_id
    assert payment["preimage"] == real_preimage

    # Check that invoice is marked SETTLED
    with db_session(db_file) as conn:
        row = conn.execute("SELECT status FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        assert row["status"] == "SETTLED"

    # Verify receipt chain on ledger
    ledger = Ledger(db_file)
    assert ledger.verify_chain(merchant_id) is True
    receipts = ledger.get_merchant_receipts(merchant_id)
    assert len(receipts) == 1
    assert receipts[0]["value_locked_ngn"] == 2000

def test_inv1_preimage_mismatch_fails(settlement_fixture):
    db_file, merchant_id, invoice_id, real_preimage, _ = settlement_fixture
    mock_lnd = MockLndClient(state="SETTLED", preimage=real_preimage)

    fake_preimage = "99" * 32
    with pytest.raises(SettlementError, match="PREIMAGE_MISMATCH"):
        settle(invoice_id, fake_preimage, lnd_client=mock_lnd, db_path=db_file)

    # Invoice must remain OPEN
    with db_session(db_file) as conn:
        row = conn.execute("SELECT status FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        assert row["status"] == "OPEN"

    # No receipt in ledger
    ledger = Ledger(db_file)
    assert len(ledger.get_merchant_receipts(merchant_id)) == 0

def test_inv1_node_unconfirmed_fails(settlement_fixture):
    db_file, merchant_id, invoice_id, real_preimage, _ = settlement_fixture
    mock_lnd = MockLndClient(state="OPEN", preimage=None)

    with pytest.raises(SettlementError, match="NODE_UNCONFIRMED"):
        settle(invoice_id, real_preimage, lnd_client=mock_lnd, db_path=db_file)

    with db_session(db_file) as conn:
        row = conn.execute("SELECT status FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        assert row["status"] == "OPEN"

def test_inv2_idempotency_returns_existing_payment(settlement_fixture):
    db_file, merchant_id, invoice_id, real_preimage, _ = settlement_fixture
    mock_lnd = MockLndClient(state="SETTLED", preimage=real_preimage)

    # First settle
    payment1 = settle(invoice_id, real_preimage, lnd_client=mock_lnd, db_path=db_file)
    # Second settle (duplicate call)
    payment2 = settle(invoice_id, real_preimage, lnd_client=mock_lnd, db_path=db_file)

    assert payment1["id"] == payment2["id"]
    ledger = Ledger(db_file)
    assert len(ledger.get_merchant_receipts(merchant_id)) == 1

