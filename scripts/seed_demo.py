#!/usr/bin/env python3
"""
scripts/seed_demo.py
Seeds the demo merchant for the live demo:
- Phone: +2348012345678
- PIN: 1234
- Mode: lock_ngn
- Daily Limit: 50,000 NGN
"""
import sys
import os

# Add sautipay to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import init_db, db_session
from app.security_engine import hash_pin
from app.config import settings

DEMO_MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
DEMO_PHONE = "+2348012345678"
DEMO_PIN = "1234"

def seed():
    init_db()
    pin_hash, pin_salt = hash_pin(DEMO_PIN)
    
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM merchants WHERE phone = ?", (DEMO_PHONE,))
        existing = cursor.fetchone()
        if existing:
            conn.execute(
                """
                UPDATE merchants SET
                    pin_hash = ?,
                    pin_salt = ?,
                    settlement_mode = 'lock_ngn',
                    daily_limit_ngn = 50000
                WHERE phone = ?
                """,
                (pin_hash, pin_salt, DEMO_PHONE)
            )
        else:
            conn.execute(
                """
                INSERT INTO merchants (id, phone, pin_hash, pin_salt, settlement_mode, daily_limit_ngn)
                VALUES (?, ?, ?, ?, 'lock_ngn', 50000)
                """,
                (DEMO_MERCHANT_ID, DEMO_PHONE, pin_hash, pin_salt)
            )
        print(f"✓ Seeded demo merchant: Phone={DEMO_PHONE}, PIN={DEMO_PIN}")

if __name__ == "__main__":
    seed()
