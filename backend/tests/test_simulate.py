import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.simulate import engine
from tests.test_recommend import make_state

client = TestClient(app)


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 's.db'}")
    proc = tmp_path / "processed"
    (proc / "models").mkdir(parents=True)
    st = make_state()
    st["fc"].to_parquet(proc / "models" / "forecasts.parquet")
    st["items"].to_csv(proc / "items.csv", index=False)
    st["stores"].to_csv(proc / "stores.csv", index=False)
    st["hist"].merge(st["cur"][["store", "item", "on_hand", "on_order", "list_price"]], on=["store", "item"]).to_csv(proc / "sales.csv", index=False)


def run(**levers):
    r = client.post("/api/simulate/run", json={"scope": {"item": 2}, "horizon": 30, "levers": levers, "runs": 200})
    assert r.status_code == 200, r.text
    return r.json()


def test_baseline_levers_change_nothing(files):
    r = run()
    assert r["delta"]["units"] == pytest.approx(0, abs=1e-6) and r["delta"]["net_profit"] == pytest.approx(0, abs=1e-6)
    assert r["verdict"]["rating"] == "Neutral" and len(r["trajectory"]["dates"]) == 30


def test_price_changes_move_demand_the_right_way(files):
    cut, rise = run(price_pct=-10), run(price_pct=10)
    assert cut["delta"]["units"] > 0 > rise["delta"]["units"]
    assert cut["delta"]["elasticity_index"] == pytest.approx(0)  # elasticity itself is an input, not an output of the levers
    assert cut["scenario"]["revenue"] != cut["baseline"]["revenue"]


def test_voucher_marketing_and_shocks(files):
    base = run()["scenario"]
    assert run(voucher_pct=15)["scenario"]["units"] > base["units"]
    m = run(marketing="High")
    assert m["scenario"]["units"] > base["units"] and m["scenario"]["marketing_spend"] > base["marketing_spend"]
    assert run(festival_shock=True)["scenario"]["peak_mean"] > base["peak_mean"]
    assert run(competitor_match=True)["scenario"]["units"] < base["units"]


def test_inventory_levers_drive_stockouts(files):
    base = run()
    lean = run(safety_stock_units=0, lead_time_days=14)
    rich = run(safety_stock_units=base["baseline_safety_stock"] * 4)
    assert lean["scenario"]["stockout_risk_pct"] > base["scenario"]["stockout_risk_pct"] >= rich["scenario"]["stockout_risk_pct"]
    assert lean["scenario"]["lost_units"] > base["scenario"]["lost_units"]
    assert rich["scenario"]["holding_cost"] >= base["scenario"]["holding_cost"]


def test_results_are_reproducible_and_structured(files):
    a, b = run(price_pct=-5, marketing="Medium"), run(price_pct=-5, marketing="Medium")
    assert a["scenario"] == b["scenario"]
    assert {"revenue", "units", "gross_margin_pct", "stockout_risk_pct", "peak_p90", "safety_buffer_days", "elasticity_index"} <= set(a["scenario"])
    assert a["stores"] and {"name", "units", "status"} <= set(a["stores"][0])


def test_validation_and_missing_models(files, tmp_path):
    bad = client.post("/api/simulate/run", json={"levers": {"price_pct": 50}})
    assert bad.status_code == 422
    assert client.post("/api/simulate/run", json={"scope": {"store": 99}}).status_code == 422
    assert client.get("/api/simulate/baseline?item=1").json()["baseline_safety_stock"] > 0


def test_no_forecasts(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert client.post("/api/simulate/run", json={}).status_code == 409


def test_saved_scenarios(files):
    assert client.get("/api/simulate/scenarios").json() == {"scenarios": []}
    body = {"name": "Festive Aggressive", "scope": {"item": 2}, "horizon": 30, "runs": 100,
            "levers": {"price_pct": -5, "voucher_pct": 12, "marketing": "High", "festival_shock": True}}
    saved = client.post("/api/simulate/scenarios", json=body)
    assert saved.status_code == 201
    s = saved.json()
    assert s["name"] == "Festive Aggressive" and s["scenario"]["units"] > s["baseline"]["units"] and s["levers"]["voucher_pct"] == 12
    assert len(client.get("/api/simulate/scenarios").json()["scenarios"]) == 1
    assert client.post("/api/simulate/scenarios", json={**body, "name": ""}).status_code == 422
    assert client.delete(f"/api/simulate/scenarios/{s['id']}").status_code == 204
    assert client.delete(f"/api/simulate/scenarios/{s['id']}").status_code == 404
