import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.forecasting import xgb_model
from app.main import app

client = TestClient(app)
H = 14


@pytest.fixture
def trained(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    proc = tmp_path / "processed"
    mdir = proc / "models"
    mdir.mkdir(parents=True)
    rng = np.random.default_rng(0)
    dates = pd.date_range("2024-01-01", periods=260)
    base = np.array([20, 22, 24, 26, 30, 45, 42])[dates.dayofweek]
    y = np.vstack([base * (1 + 0.5 * s) + rng.normal(0, 1, len(dates)) for s in range(4)]).clip(0)
    series = pd.DataFrame({"store": [1, 1, 2, 2], "item": [1, 2, 1, 2]})
    pd.DataFrame({"date": np.tile(dates, 4), "store": np.repeat(series["store"], len(dates)), "item": np.repeat(series["item"], len(dates)),
                  "sales": y.ravel()}).to_parquet(proc / "features.parquet")
    pd.DataFrame({"store": [1, 2], "name": ["S1", "S2"], "city": "X"}).to_csv(proc / "stores.csv", index=False)
    model = xgb_model.train(y, dates, series, len(dates), n_estimators=60)
    model.save_model(mdir / "xgb.json")
    fc = xgb_model.forecast(model, y, dates, series, H)
    bt = pd.DataFrame({"store": np.repeat(series["store"], 10), "item": np.repeat(series["item"], 10),
                       "date": np.tile(dates[-10:], 4), "actual": y[:, -10:].ravel(), "pred": y[:, -10:].ravel() * 1.05})
    bt.to_parquet(mdir / "backtest.parquet")
    meta = {"serving": "XGBoost", "version": "v-test", "trained_at": "2026-01-01T00:00:00", "horizon_days": H,
            "backtest_window": ["a", "b"], "forecast_window": [str((dates[-1] + pd.Timedelta(days=1)).date()), str((dates[-1] + pd.Timedelta(days=H)).date())],
            "models": [{"name": "XGBoost", "full_set": {"r2": 0.9, "mape": 10.0, "wape": 9.0}}]}
    (mdir / "benchmark.json").write_text(json.dumps(meta))
    return {"y": y, "dates": dates, "fc": fc}


def test_local_explanation_is_exact_and_matches_the_forecast(trained):
    d = trained["dates"][-1] + pd.Timedelta(days=5)  # 5th forecast day -> needs recursion replay
    r = client.get(f"/api/explain/local?store=2&item=1&date={d.date()}").json()
    assert r["balance_check"] < 1e-3
    assert abs(r["base_value"] + sum(c["shap"] for c in r["contributions"]) - r["prediction"]) < 0.2
    assert r["prediction"] == pytest.approx(float(trained["fc"][2, 4]), abs=0.1)  # same number the forecast page shows
    assert r["waterfall"][0]["kind"] == "base" and r["waterfall"][-1]["kind"] == "final"
    assert abs(r["waterfall"][-1]["end"] - r["prediction"]) < 0.06 and "units" in r["summary"]
    assert {g["group"] for g in r["groups"]} >= {"Recent run-rate", "Weekly pattern"}


def test_local_explanation_for_history_day(trained):
    d = trained["dates"][-20]
    r = client.get(f"/api/explain/local?store=1&item=1&date={d.date()}").json()
    assert r["in_history"] and r["actual"] == pytest.approx(float(trained["y"][0, -20]))


def test_local_validation(trained):
    assert client.get("/api/explain/local?store=1&item=1&date=2030-01-01").status_code == 422
    assert client.get("/api/explain/local?store=9&item=9&date=2024-06-01").status_code == 422
    assert client.get("/api/explain/dependence?feature=nope").status_code == 422


def test_global_importance_and_dependence(trained):
    g = client.get("/api/explain/global").json()
    assert sum(f["share_pct"] for f in g["features"]) == pytest.approx(100, abs=1.5)
    assert g["groups"][0]["group"] in ("Weekly pattern", "Recent run-rate")
    d = client.get("/api/explain/dependence?feature=dow").json()
    assert len(d["grid"]) == 7 == len(d["pdp"]) and d["pdp"][5] > d["pdp"][0]  # weekends sell more in this data
    assert client.get("/api/explain/dependence?feature=rolling_mean_14&store=1&item=1").json()["ice"]


def test_governance(trained):
    g = client.get("/api/explain/governance").json()
    assert 0 <= g["parity_index"] <= 100 and len(g["artifact_sha256"]) == 64
    assert {d["feature"] for d in g["drift"]} >= {"lag_7", "sales (target)"} and g["drift_status"] in ("Nominal", "Moderate", "Significant")
    assert [s["name"] for s in g["stores"]] == ["S1", "S2"]


def test_requires_xgboost_serving_model(trained, tmp_path):
    p = tmp_path / "processed" / "models" / "benchmark.json"
    m = json.loads(p.read_text())
    m["serving"] = "LSTM"
    p.write_text(json.dumps(m))
    assert client.get("/api/explain/global").status_code == 409


def test_no_models(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert client.get("/api/explain/options").status_code == 409
