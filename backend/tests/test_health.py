from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_dataset_summary():
    r = client.get("/api/data/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["stores"] == 10
    assert body["items"] == 50
