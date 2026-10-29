import sqlite3
import os
from contextlib import contextmanager
from app.config import settings

def get_connection(db_path: str = None) -> sqlite3.Connection:
    target_path = db_path or settings.DB_PATH
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    # Enable Write-Ahead Logging (WAL mode) and foreign keys
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

@contextmanager
def db_session(db_path: str = None):
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db(db_path: str = None):
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        
        # merchants table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS merchants (
            id TEXT PRIMARY KEY,
            phone TEXT UNIQUE NOT NULL,
            pin_hash TEXT NOT NULL,
            pin_salt TEXT NOT NULL,
            settlement_mode TEXT CHECK (settlement_mode IN ('keep_sats', 'lock_ngn')) DEFAULT 'lock_ngn',
            daily_limit_ngn INTEGER DEFAULT 50000,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # rate_quotes table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_quotes (
            id TEXT PRIMARY KEY,
            source TEXT CHECK (source IN ('coingecko', 'override')) NOT NULL,
            sats_per_ngn REAL NOT NULL,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            raw TEXT
        );
        """)

        # invoices table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL REFERENCES merchants(id),
            amount_ngn INTEGER NOT NULL,
            amount_msat INTEGER NOT NULL,
            sats_per_ngn REAL NOT NULL,
            memo TEXT,
            payment_hash TEXT UNIQUE NOT NULL,
            payment_request TEXT,
            expiry TIMESTAMP,
            status TEXT CHECK (status IN ('OPEN', 'SETTLED', 'EXPIRED')) DEFAULT 'OPEN',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # payments table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY,
            invoice_id TEXT UNIQUE NOT NULL REFERENCES invoices(id),
            preimage TEXT NOT NULL,
            settled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            settle_source TEXT DEFAULT 'lnd_lookup'
        );
        """)

        # receipts table (append-only, hash-chained per merchant)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seq INTEGER NOT NULL,
            merchant_id TEXT NOT NULL REFERENCES merchants(id),
            invoice_id TEXT NOT NULL REFERENCES invoices(id),
            amount_ngn INTEGER NOT NULL,
            sats_per_ngn REAL NOT NULL,
            value_mode TEXT NOT NULL,
            value_locked_ngn INTEGER,
            prev_receipt_hash TEXT NOT NULL,
            receipt_hash TEXT UNIQUE NOT NULL,
            sms_status TEXT CHECK (sms_status IN ('SENT', 'FAILED')) DEFAULT 'SENT',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(merchant_id, seq)
        );
        """)

        # intents table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS intents (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL REFERENCES merchants(id),
            nonce TEXT UNIQUE NOT NULL,
            action TEXT DEFAULT 'ussd_request_payment',
            amount_ngn INTEGER NOT NULL,
            expiry TIMESTAMP NOT NULL,
            status TEXT CHECK (status IN ('ACTIVE', 'USED', 'EXPIRED', 'REPLAY_BLOCKED')) DEFAULT 'ACTIVE',
            attempts INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # audit_log table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # swaps table (Lightning BTC <-> On-Chain BTC)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS swaps (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL REFERENCES merchants(id),
            direction TEXT CHECK (direction IN ('ln_to_btc', 'btc_to_ln')) NOT NULL,
            amount_sats INTEGER NOT NULL,
            fee_sats INTEGER NOT NULL,
            onchain_address TEXT NOT NULL,
            payment_hash TEXT NOT NULL,
            preimage TEXT,
            status TEXT CHECK (status IN ('CREATED', 'PENDING', 'SUCCESS', 'REFUNDED')) DEFAULT 'CREATED',
            timeout_block INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

