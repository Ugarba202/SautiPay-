import os
import pytest
from app.models import init_db, db_session
from app.config import settings

def test_config_defaults():
    assert settings.PORT == 8000
    assert settings.DEMO_MODE is True
    assert settings.AT_USERNAME == "sandbox"

def test_database_init(tmp_path):
    test_db = str(tmp_path / "test_sautipay.db")
    init_db(test_db)
    
    with db_session(test_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row["name"] for row in cursor.fetchall()}
        
    required_tables = {"merchants", "rate_quotes", "invoices", "payments", "receipts", "intents", "audit_log"}
    assert required_tables.issubset(tables)

