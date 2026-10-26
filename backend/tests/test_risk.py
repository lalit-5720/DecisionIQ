import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.risk import detect, scan

client = TestClient(app)

DUP_DAY, EROSION_DAY = 100, 120


@pytest.fixture
def risk_data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'test.db'}")
    proc = tmp_path / "processed"
    proc.mkdir()
    rng = np.random.default_rng(1)
    dates = pd.date_range("2024-01-01", periods=180)
    rows = []
    for store in (1, 2):
        for item in (1, 2, 3):
            base = 40 + 10 * item
            for k, d in enumerate(dates):
                units = max(int(rng.normal(base * (1.3 if d.dayofweek >= 5 else 1), 3)), 0)
                price, lab = 1000.0 * item, ""
                if (store, item) == (1, 1) and k == DUP_DAY:
                    units, lab = units * 2, "duplicate_billing"
                if (store, item) == (2, 3) and k == EROSION_DAY:
                    price, lab = 1200.0, "margin_erosion"  # 60% off list 3000, below cost 2100
                rows.append((d, store, item, units, price, 1000.0 * item if lab != "margin_erosion" else 3000.0, lab, int(lab != "")))
    pd.DataFrame(rows, columns=["date", "store", "item", "units_billed", "net_price", "list_price", "anomaly_type", "is_anomaly"]).to_csv(proc / "sales.csv", index=False)
    pd.DataFrame({"item": [1, 2, 3], "name": ["A", "B", "C"], "unit_cost": [700.0, 1400.0, 2100.0], "category": "x"}).to_csv(proc / "items.csv", index=False)
    pd.DataFrame({"store": [1, 2], "name": ["S1", "S2"], "city": "X"}).to_csv(proc / "stores.csv", index=False)
    weeks = pd.date_range("2024-01-01", periods=26, freq="7D")
    log = pd.DataFrame([(s, w, 42000.0 + 300 * (i % 3), "") for s in (1, 2) for i, w in enumerate(weeks)], columns=["store", "week_start", "freight_cost", "anomaly_type"])
    log.loc[20, ["freight_cost", "anomaly_type"]] = [70000.0, "cost_spike"]
    log.to_csv(proc / "logistics_costs.csv", index=False)
    return dates


def test_cost_spike_detector():
    log = pd.DataFrame({"store": 1, "week_start": pd.date_range("2024-01-01", periods=20, freq="7D"), "freight_cost": 42000.0})
    log.loc[15, "freight_cost"] = 65000.0
    out = detect.detect_cost_spikes(log)
    assert out.loc[out["flag"], "week_start"].tolist() == [log.loc[15, "week_start"]]


def test_prf():
    flag, truth = np.array([1, 1, 0, 0], bool), np.array([1, 0, 1, 0], bool)
    m = detect.prf(flag, truth)
    assert (m["tp"], m["fp"], m["fn"]) == (1, 1, 1) and m["f1"] == 0.5


def test_scan_finds_injected_anomalies_and_api_flow(risk_data):
    st = scan.run_scan(contamination=0.02)
    assert st["status"] == "complete", st

    r = client.get("/api/risk/alerts?page_size=100").json()
    by_type = {}
    for a in r["alerts"]:
        by_type.setdefault(a["type"], []).append(a)
    dup_date = risk_data[DUP_DAY].date().isoformat()
    assert any(a["date"] == dup_date and (a["store"], a["item"]) == (1, 1) for a in by_type.get("duplicate_billing", []))
    erosion_date = risk_data[EROSION_DAY].date().isoformat()
    assert any(a["date"] == erosion_date and (a["store"], a["item"]) == (2, 3) for a in by_type.get("margin_erosion", []))
    assert by_type.get("cost_spike"), "weekly freight spike should raise a cost_spike alert"

    s = client.get("/api/risk/summary").json()
    assert s["open_alerts"] == r["total"] and s["scanned"] and s["metrics"]["detectors"]["Ensemble"]["tp"] >= 1

    dup = next(a for a in by_type["duplicate_billing"] if a["date"] == dup_date)
    d = client.get(f"/api/risk/alerts/{dup['id']}").json()
    assert d["evidence"]["units_billed"] > 1.7 * d["evidence"]["expected"]
    assert d["distribution"]["counts"] and d["window"]

    u = client.patch(f"/api/risk/alerts/{dup['id']}", json={"status": "Resolved", "assignee": "Priya"}).json()
    assert u["status"] == "Resolved" and u["assignee"] == "Priya"
    assert client.patch(f"/api/risk/alerts/{dup['id']}", json={"status": "Bogus"}).status_code == 422
    assert client.get("/api/risk/alerts?status=unresolved").json()["total"] == r["total"] - 1

    scan.run_scan(contamination=0.02)  # rescan keeps analyst decisions
    again = client.get("/api/risk/alerts?status=Resolved").json()
    assert again["total"] == 1 and again["alerts"][0]["assignee"] == "Priya"


def test_alerts_without_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'empty.db'}")
    assert client.get("/api/risk/alerts").json()["total"] == 0
    assert client.get("/api/risk/summary").json()["scanned"] is False
    assert client.get("/api/risk/alerts/999").status_code == 404
