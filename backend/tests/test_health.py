from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'

def test_readiness_checks_database():
    r = client.get('/health/ready')
    assert r.status_code == 200
    assert r.json()['status'] == 'ready'
