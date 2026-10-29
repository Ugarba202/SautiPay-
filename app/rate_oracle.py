import time
import json
import uuid
import requests
from typing import Tuple, Dict, Any, Optional
from datetime import datetime, timezone

from app.config import settings
from app.models import db_session

CACHE_TTL_SECONDS = 60

class RateOracleError(Exception):
    pass

class RateOracle:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._cached_rate: Optional[float] = None
        self._cached_time: float = 0
        self._cached_source: str = "coingecko"

    def get_rate(self) -> Tuple[float, str, bool]:
        """
        Returns (sats_per_ngn, source, is_stale):
        1. If RATE_OVERRIDE_NGN is set -> returns it directly (source='override', is_stale=False).
        2. Else fetch from CoinGecko API and cache for 60s (source='coingecko', is_stale=False).
        3. On fetch failure: return last cached rate with is_stale=True.
        4. If no cached rate exists: raise RateOracleError (INV-4 Decline by default).
        """
        # 1. Manual override check (vital for demo resilience)
        if settings.RATE_OVERRIDE_NGN is not None and settings.RATE_OVERRIDE_NGN > 0:
            return float(settings.RATE_OVERRIDE_NGN), "override", False

        now = time.time()
        # 2. In-memory / DB cache check
        if self._cached_rate is not None and (now - self._cached_time) < CACHE_TTL_SECONDS:
            return self._cached_rate, self._cached_source, False

        # Attempt to fetch live from CoinGecko
        try:
            resp = requests.get(settings.RATE_API_URL, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                btc_ngn_price = float(data["bitcoin"]["ngn"])
                # 1 BTC = 100,000,000 sats
                # sats_per_ngn = 100,000,000 / btc_ngn_price
                sats_per_ngn = round(100_000_000.0 / btc_ngn_price, 4)
                
                self._cached_rate = sats_per_ngn
                self._cached_time = now
                self._cached_source = "coingecko"

                # Persist rate quote for audit
                self._record_quote(sats_per_ngn, "coingecko", json.dumps(data))
                return sats_per_ngn, "coingecko", False
        except Exception as e:
            pass # Fall through to cache fallback or fail

        # 3. Check DB for previous cached rate if in-memory empty
        if self._cached_rate is None:
            last_db_rate = self._get_last_db_rate()
            if last_db_rate:
                self._cached_rate = last_db_rate
                self._cached_time = now - CACHE_TTL_SECONDS - 1 # Mark as stale

        # If we have a cached rate, return with is_stale=True
        if self._cached_rate is not None:
            return self._cached_rate, self._cached_source, True

        # 4. Fail closed (INV-4)
        raise RateOracleError("Unable to fetch exchange rate and no cached rate available.")

    def stamp_invoice(self, amount_ngn: int) -> Tuple[int, float]:
        """
        Calculates amount_msat and stamps rate:
        amount_msat = int(amount_ngn * sats_per_ngn * 1000)
        (1 sat = 1000 msat).
        Returns: (amount_msat, sats_per_ngn)
        """
        sats_per_ngn, _, _ = self.get_rate()
        amount_msat = int(amount_ngn * sats_per_ngn * 1000)
        return amount_msat, sats_per_ngn

    def _record_quote(self, sats_per_ngn: float, source: str, raw_json: str):
        try:
            with db_session(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO rate_quotes (id, source, sats_per_ngn, raw)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), source, sats_per_ngn, raw_json)
                )
        except Exception:
            pass

    def _get_last_db_rate(self) -> Optional[float]:
        try:
            with db_session(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT sats_per_ngn FROM rate_quotes ORDER BY fetched_at DESC LIMIT 1"
                )
                row = cursor.fetchone()
                if row:
                    return float(row["sats_per_ngn"])
        except Exception:
            pass
        return None

rate_oracle = RateOracle()

