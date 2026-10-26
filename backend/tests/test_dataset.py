"""Invariants of the generated dataset (run `python ml/prepare_data.py` first)."""
import pandas as pd
import pytest

from app.core.config import settings

PROCESSED = settings.data_dir / "processed"
pytestmark = pytest.mark.skipif(not (PROCESSED / "sales.csv").exists(), reason="processed data not generated")


@pytest.fixture(scope="module")
def sales():
    return pd.read_csv(PROCESSED / "sales.csv", keep_default_na=False)


def test_real_sales_untouched(sales):
    raw = pd.read_csv(settings.data_dir / "raw" / "train.csv").sort_values(["store", "item", "date"])
    got = sales.sort_values(["store", "item", "date"])
    assert len(got) == len(raw)
    assert (got["sales"].to_numpy() == raw["sales"].to_numpy()).all()


def test_non_anomalous_rows_match_real_sales(sales):
    clean = sales[sales.is_anomaly == 0]
    assert (clean["units_billed"] == clean["sales"]).all()


def test_anomaly_labels(sales):
    types = set(sales.loc[sales.is_anomaly == 1, "anomaly_type"])
    assert types == {"duplicate_billing", "margin_erosion", "demand_drop"}
    assert 0 < sales.is_anomaly.mean() < 0.01


def test_prices_and_inventory_sane(sales):
    assert (sales["list_price"] > 0).all()
    assert (sales["on_hand"] >= 0).all()
    assert (sales["units_short"] > 0).any()
