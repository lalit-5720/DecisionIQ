import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.pipeline.clean import clean
from app.pipeline.schema import detect_mapping

client = TestClient(app)


def make_df(days=60, series=2, seed=0):
    rng = np.random.default_rng(seed)
    rows = [
        (d, s, 1, int(rng.poisson(20)))
        for s in range(1, series + 1)
        for d in pd.date_range("2024-01-01", periods=days)
    ]
    return pd.DataFrame(rows, columns=["txn_date", "store_id", "sku_code", "qty_sold"])


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


def test_mapping_aliases():
    m = detect_mapping(make_df())
    assert m["missing_required"] == []
    assert {x["target"] for x in m["mapping"]} == {"date", "store", "item", "sales"}


def test_mapping_missing_required():
    m = detect_mapping(make_df().drop(columns=["qty_sold"]))
    assert m["missing_required"] == ["sales"]


def test_clean_handles_dirty_data():
    df = make_df().rename(columns={"txn_date": "date", "store_id": "store", "sku_code": "item", "qty_sold": "sales"})
    df = pd.concat([df, df.iloc[:5]], ignore_index=True)  # 5 exact duplicates
    df.iloc[10, df.columns.get_loc("sales")] = np.nan
    df.iloc[40, df.columns.get_loc("sales")] = 5000  # outlier
    out, st = clean(df)
    assert st["duplicates_removed"] == 5
    assert st["missing_imputed"] >= 1
    assert st["outliers_capped"] >= 1
    assert out["sales"].max() < 5000
    assert out["sales"].notna().all()


def test_clean_fills_date_gaps():
    df = make_df(days=30, series=1).rename(
        columns={"txn_date": "date", "store_id": "store", "sku_code": "item", "qty_sold": "sales"}
    )
    out, st = clean(df.drop(df.index[10:15]))
    assert st["gaps_filled"] == 5
    assert len(out) == 30


def test_upload_and_run_pipeline(tmp_data):
    buf = io.BytesIO(make_df().to_csv(index=False).encode())
    r = client.post("/api/pipeline/upload", files={"file": ("mydata.csv", buf, "text/csv")})
    assert r.status_code == 200 and r.json()["missing_required"] == []

    assert client.post("/api/pipeline/run").status_code == 202
    st = client.get("/api/pipeline/status").json()
    assert st["status"] == "complete", st
    assert [s["status"] for s in st["steps"]] == ["done"] * 4
    assert st["quality"]["rows_out"] == 120

    prev = client.get("/api/pipeline/preview?n=3").json()
    assert len(prev["rows"]) == 3
    for col in ("lag_7", "lag_30", "rolling_mean_14", "month_sin", "festival_flag"):
        assert col in prev["columns"]


def test_features_have_no_lookahead(tmp_data):
    df = make_df(days=40, series=1).rename(
        columns={"txn_date": "date", "store_id": "store", "sku_code": "item", "qty_sold": "sales"}
    )
    from app.pipeline.features import build_features

    f = build_features(df)
    assert f["lag_7"].iloc[:7].isna().all()
    assert f["lag_7"].iloc[7] == f["sales"].iloc[0]


def test_upload_rejects_bad_files(tmp_data):
    r = client.post("/api/pipeline/upload", files={"file": ("x.txt", io.BytesIO(b"hi"), "text/plain")})
    assert r.status_code == 415
    bad = make_df().drop(columns=["qty_sold"]).to_csv(index=False).encode()
    r = client.post("/api/pipeline/upload", files={"file": ("bad.csv", io.BytesIO(bad), "text/csv")})
    assert r.status_code == 422


def test_diagnostics_reports_failure_details(tmp_data):
    assert client.get("/api/pipeline/diagnostics").json()["status"] == "idle"
    runner_mod = __import__("app.pipeline.runner", fromlist=["x"])
    runner_mod._write({"status": "failed", "error": "Schema gate failed: missing required columns ['store']", "source": "pos_feed.csv",
                       "steps": [{"key": "mapping", "label": "Schema Mapping", "status": "failed", "detail": "x"}]})
    d = client.get("/api/pipeline/diagnostics").json()
    assert d["failed"] and "[CRITICAL] Schema gate failed" in d["log"] and "pos_feed.csv" in d["log"]
