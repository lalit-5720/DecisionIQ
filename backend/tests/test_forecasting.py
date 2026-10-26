import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.forecasting import xgb_model
from app.forecasting.metrics import evaluate
from app.main import app

client = TestClient(app)


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


def weekly_matrix(n=4, days=220, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=days)
    base = np.array([20, 22, 24, 26, 30, 40, 38])[dates.dayofweek]
    y = np.vstack([base * (1 + 0.5 * s) + rng.normal(0, 1, days) for s in range(n)]).clip(0)
    series = pd.DataFrame({"store": [1] * n, "item": range(1, n + 1)})
    return y, dates, series


def test_metrics_perfect_and_biased():
    a = np.array([[10.0, 20.0, 30.0]])
    assert evaluate(a, a)["mape"] == 0
    m = evaluate(a, a * 1.1)
    assert m["mape"] == pytest.approx(10.0)
    assert m["mae"] == pytest.approx(2.0)


def test_xgb_recursive_forecast_learns_weekly_pattern(tmp_data):
    y, dates, series = weekly_matrix()
    T = y.shape[1] - 14
    model = xgb_model.train(y, dates, series, T, n_estimators=80)
    pred = xgb_model.forecast(model, y[:, :T], dates, series, 14)
    assert pred.shape == (4, 14) and (pred >= 0).all()
    assert evaluate(y[:, T:], pred)["mape"] < 15
    assert xgb_model.importance(model)[0]["feature"] in xgb_model.FEATURES


def test_features_use_only_past(tmp_data):
    y, dates, series = weekly_matrix(n=1, days=60)
    from app.forecasting.data import calendar

    cal = calendar(dates)
    X1 = xgb_model.make_features(y, [40], cal, np.array([1]), np.array([1]))
    y2 = y.copy()
    y2[:, 40:] = 999  # changing today/future must not change features for day 40
    X2 = xgb_model.make_features(y2, [40], cal, np.array([1]), np.array([1]))
    assert np.array_equal(X1, X2)


@pytest.fixture
def artifacts(tmp_data):
    proc = tmp_data / "processed"
    (proc / "models").mkdir(parents=True)
    dates = pd.date_range("2024-01-01", periods=120)
    rows = [(d, s, i, 10 + s + i) for d in dates for s in (1, 2) for i in (1, 2)]
    pd.DataFrame(rows, columns=["date", "store", "item", "sales"]).to_parquet(proc / "features.parquet")
    fdates = pd.date_range("2024-04-30", periods=90)
    frows = [(s, i, d, 12.0, 8.0, 16.0) for s in (1, 2) for i in (1, 2) for d in fdates]
    pd.DataFrame(frows, columns=["store", "item", "date", "yhat", "lower", "upper"]).to_parquet(proc / "models" / "forecasts.parquet")
    pd.DataFrame({"store": [1, 1, 2, 2], "item": [1, 2, 1, 2], "sigma": 2.0}).to_parquet(proc / "models" / "sigma.parquet")
    (proc / "models" / "benchmark.json").write_text(json.dumps({"serving": "XGBoost", "version": "t", "models": []}))
    pd.DataFrame({"item": [1, 2], "sku_code": ["a", "b"], "name": ["A", "B"], "category": ["C1", "C2"]}).to_csv(proc / "items.csv", index=False)
    pd.DataFrame({"store": [1, 2], "name": ["S1", "S2"], "city": ["X", "Y"]}).to_csv(proc / "stores.csv", index=False)


def test_series_endpoint_aggregates_and_filters(artifacts):
    r = client.get("/api/forecast/series?horizon=7&history_days=30").json()
    assert len(r["forecast"]) == 7 and len(r["history"]) == 30
    assert r["forecast"][0]["yhat"] == 48.0  # 4 series x 12
    assert r["forecast"][0]["upper"] > r["forecast"][0]["yhat"] > r["forecast"][0]["lower"]
    r = client.get("/api/forecast/series?store=1&item=1&horizon=7").json()
    assert r["forecast"][0]["yhat"] == 12.0
    r = client.get("/api/forecast/series?category=C2&horizon=7").json()
    assert r["forecast"][0]["yhat"] == 24.0
    assert client.get("/api/forecast/series?store=99").status_code == 404


def test_schedule_and_export(artifacts):
    r = client.get("/api/forecast/schedule?horizon=30&page=2&page_size=8").json()
    assert r["total"] == 30 and len(r["rows"]) == 8
    csv = client.get("/api/forecast/export.csv?horizon=10")
    assert csv.status_code == 200 and len(csv.text.strip().splitlines()) == 11


def test_endpoints_without_training(tmp_data):
    assert client.get("/api/forecast/models").json() == {"available": False}
    assert client.get("/api/forecast/series").status_code == 404
    assert client.post("/api/forecast/retrain").status_code == 409  # pipeline not run


@pytest.mark.slow
def test_full_training_quick(tmp_data):
    from app.pipeline.features import build_features
    from app.forecasting.train import run_training

    proc = tmp_data / "processed"
    proc.mkdir(parents=True)
    y, dates, _ = weekly_matrix(n=3, days=500)
    df = pd.DataFrame(
        [(d, 1, i + 1, int(y[i, k])) for i in range(3) for k, d in enumerate(dates)], columns=["date", "store", "item", "sales"]
    )
    build_features(df).to_parquet(proc / "features.parquet")
    st = run_training(quick=True)
    assert st["status"] == "complete", st
    meta = json.loads((proc / "models" / "benchmark.json").read_text())
    assert {m["name"] for m in meta["models"]} == {"XGBoost", "Prophet", "SARIMA", "LSTM"}
    assert (proc / "models" / "forecasts.parquet").exists()


def test_low_confidence_ranks_widest_bands_and_gives_fallback(artifacts):
    import pandas as pd

    p = settings.data_dir / "processed" / "models" / "forecasts.parquet"
    df = pd.read_parquet(p)
    wide = (df.store == 2) & (df.item == 2)
    df.loc[wide, ["lower", "upper"]] = [2.0, 40.0]  # same forecast (12) but a much wider band
    df.to_parquet(p)
    r = client.get("/api/forecast/low-confidence?threshold=60&limit=3").json()
    assert r["series"][0]["store"] == 2 and r["series"][0]["item"] == 2 and r["series"][0]["confidence"] < 60
    assert r["low_count"] == 1 and r["total_series"] == 4
    ex = r["example"]
    assert len(ex["dates"]) == 30 == len(ex["prior"]) and ex["upper"][0] > ex["yhat"][0] > ex["lower"][0]
    assert client.get("/api/forecast/low-confidence?store=1&item=1").json()["example"]["store"] == 1
    assert client.get("/api/forecast/low-confidence?store=9&item=9").status_code == 404
