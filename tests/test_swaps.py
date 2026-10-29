import pytest
import uuid
from app.models import init_db, db_session
from app.swap_service import SwapService, SwapError
from app.ledger import Ledger
from app.rate_oracle import rate_oracle

@pytest.fixture
def swap_fixture(tmp_path, monkeypatch):
    db_file = str(tmp_path / "swap_test.db")
    init_db(db_file)
    merchant_id = str(uuid.uuid4())

    with db_session(db_file) as conn:
        conn.execute(
            """
            INSERT INTO merchants (id, phone, pin_hash, pin_salt, settlement_mode)
            VALUES (?, '+2348099887766', 'hash', 'salt', 'keep_sats')
            """,
            (merchant_id,)
        )

    # Mock rate oracle
    from app.config import settings
    monkeypatch.setattr(settings, "RATE_OVERRIDE_NGN", 1.847)

    service = SwapService(db_file)
    return service, merchant_id, db_file

def test_swap_quote(swap_fixture):
    service, _, _ = swap_fixture
    quote = service.get_swap_quote("ln_to_btc", 10000)
    assert quote["direction"] == "ln_to_btc"
    assert quote["amount_sats"] == 10000
    assert quote["fee_sats"] == 100 # 0.5% or min 100
    assert quote["net_sats"] == 9900
    assert quote["timeout_block"] == 144

def test_swap_quote_limits(swap_fixture):
    service, _, _ = swap_fixture
    with pytest.raises(SwapError, match="below minimum"):
        service.get_swap_quote("ln_to_btc", 500)

    with pytest.raises(SwapError, match="exceeds maximum"):
        service.get_swap_quote("ln_to_btc", 1000000)

def test_create_and_claim_swap_lifecycle(swap_fixture):
    service, merchant_id, db_file = swap_fixture
    
    # 1. Create swap
    swap = service.create_swap(
        merchant_id=merchant_id,
        direction="ln_to_btc",
        amount_sats=50000,
        destination_address="tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"
    )
    assert swap["status"] == "CREATED"
    assert len(swap["payment_hash"]) == 64

    # 2. Claim swap (preimage revealed on-chain)
    settled_swap = service.execute_and_claim_swap(swap["swap_id"])
    assert settled_swap["status"] == "SUCCESS"
    assert "receipt_hash" in settled_swap

    # 3. Check ledger has minted receipt
    ledger = Ledger(db_file)
    assert ledger.verify_chain(merchant_id) is True
    receipts = ledger.get_merchant_receipts(merchant_id)
    assert len(receipts) == 1

def test_refund_swap(swap_fixture):
    service, merchant_id, _ = swap_fixture
    swap = service.create_swap(
        merchant_id=merchant_id,
        direction="btc_to_ln",
        amount_sats=20000,
        destination_address="tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7"
    )

    refunded = service.refund_expired_swap(swap["swap_id"])
    assert refunded["status"] == "REFUNDED"

    # Cannot claim a refunded swap
    with pytest.raises(SwapError, match="Cannot claim swap"):
        service.execute_and_claim_swap(swap["swap_id"])

