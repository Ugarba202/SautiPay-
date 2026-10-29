import pytest
from unittest.mock import patch, MagicMock
from app.config import settings
from app.models import init_db, db_session
from app.rate_oracle import RateOracle, RateOracleError

@pytest.fixture
def rate_db(tmp_path):
    db_file = str(tmp_path / "rate_test.db")
    init_db(db_file)
    return db_file

def test_override_rate_wins(rate_db, monkeypatch):
    oracle = RateOracle(rate_db)
    monkeypatch.setattr(settings, "RATE_OVERRIDE_NGN", 1.847)

    rate, source, is_stale = oracle.get_rate()
    assert rate == 1.847
    assert source == "override"
    assert is_stale is False

    msat, stamped_rate = oracle.stamp_invoice(2000)
    assert stamped_rate == 1.847
    # 2000 NGN * 1.847 sats/NGN * 1000 msat/sat = 3,694,000 msat
    assert msat == 3694000

def test_coingecko_fetch_success(rate_db, monkeypatch):
    oracle = RateOracle(rate_db)
    monkeypatch.setattr(settings, "RATE_OVERRIDE_NGN", None)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"bitcoin": {"ngn": 100_000_000.0}}

    with patch("requests.get", return_value=mock_resp):
        rate, source, is_stale = oracle.get_rate()
        assert rate == 1.0 # 100,000,000 / 100,000,000
        assert source == "coingecko"
        assert is_stale is False

def test_api_failure_fallback_to_cache(rate_db, monkeypatch):
    oracle = RateOracle(rate_db)
    monkeypatch.setattr(settings, "RATE_OVERRIDE_NGN", None)

    # First seed a successful fetch in cache
    oracle._cached_rate = 1.55
    oracle._cached_source = "coingecko"
    oracle._cached_time = 0 # Expired

    with patch("requests.get", side_effect=Exception("Network error")):
        rate, source, is_stale = oracle.get_rate()
        assert rate == 1.55
        assert is_stale is True

def test_api_failure_without_cache_raises_inv4(rate_db, monkeypatch):
    oracle = RateOracle(rate_db)
    monkeypatch.setattr(settings, "RATE_OVERRIDE_NGN", None)
    oracle._cached_rate = None

    with patch("requests.get", side_effect=Exception("Network error")):
        with pytest.raises(RateOracleError, match="Unable to fetch exchange rate"):
            oracle.get_rate()

