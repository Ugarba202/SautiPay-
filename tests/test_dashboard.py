import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import init_db, db_session
from app.security_engine import hash_pin
import uuid

@pytest.fixture
def client_fixture(tmp_path):
    db_file = str(tmp_path / "dashboard_test.db")
    init_db(db_file)
    merchant_id = str(uuid.uuid4())
    pin_h, pin_s = hash_pin("1234")

    with db_session(db_file) as conn:
        conn.execute(
            """
            INSERT INTO merchants (id, phone, pin_hash, pin_salt, settlement_mode)
            VALUES (?, '+2348012345678', ?, ?, 'lock_ngn')
            """,
            (merchant_id, pin_h, pin_s)
        )

    # Monkeypatch settings.DB_PATH for TestClient
    from app.config import settings
    settings.DB_PATH = db_file

    with TestClient(app) as client:
        yield client, merchant_id

def test_dashboard_index_renders(client_fixture):
    client, merchant_id = client_fixture
    response = client.get("/")
    assert response.status_code == 200
    assert "SautiPay ⚡ Control Room" in response.text
    assert "Live Hash-Chained Receipt Ledger" in response.text

def test_dashboard_receipts_renders(client_fixture):
    client, merchant_id = client_fixture
    response = client.get(f"/receipts/{merchant_id}")
    assert response.status_code == 200
    assert "Merchant Receipt Ledger" in response.text

def test_dashboard_merchants_renders(client_fixture):
    client, _ = client_fixture
    response = client.get("/merchants")
    assert response.status_code == 200
    assert "Registered Merchants" in response.text
    assert "+2348012345678" in response.text

def test_dashboard_mobile_view(client_fixture):
    client, _ = client_fixture
    response = client.get("/m")
    assert response.status_code == 200
    assert "SautiPay" in response.text
    assert "Merchant Terminal" in response.text

def test_ussd_post_endpoint(client_fixture):
    client, _ = client_fixture
    data = {
        "sessionId": "session_api_1",
        "phoneNumber": "+2348012345678",
        "text": "",
        "serviceCode": "*384#"
    }
    response = client.post("/ussd", data=data)
    assert response.status_code == 200
    assert "CON SautiPay" in response.text

