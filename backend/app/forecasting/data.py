"""Matrix view of the engineered dataset: one row per store x item series, one column per day."""
import numpy as np
import pandas as pd

from app.core.config import settings
from app.pipeline.features import _festival_flag

HOLDOUT_DAYS = 90
HORIZON = 90


def models_dir():
    d = settings.data_dir / "processed" / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_matrix():
    """Returns (y [n_series, n_days], dates, series DataFrame[store, item])."""
    path = settings.data_dir / "processed" / "features.parquet"
    if not path.exists():
        raise FileNotFoundError("features.parquet missing - run the data pipeline first")
    df = pd.read_parquet(path, columns=["date", "store", "item", "sales"]).sort_values(["store", "item", "date"])
    series = df[["store", "item"]].drop_duplicates().reset_index(drop=True)
    dates = pd.DatetimeIndex(sorted(df["date"].unique()))
    if len(df) != len(series) * len(dates):
        raise ValueError("Dataset is not a complete series x day grid")
    return df["sales"].to_numpy(dtype=float).reshape(len(series), len(dates)), dates, series


def extend_dates(dates: pd.DatetimeIndex, horizon: int) -> pd.DatetimeIndex:
    return dates.append(pd.date_range(dates[-1] + pd.Timedelta(days=1), periods=horizon))


def calendar(dates: pd.DatetimeIndex) -> dict:
    """Calendar features known in advance for any date."""
    month = dates.month.to_numpy()
    return {
        "dow": dates.dayofweek.to_numpy(),
        "is_weekend": (dates.dayofweek.to_numpy() >= 5).astype(int),
        "month": month,
        "month_sin": np.sin(2 * np.pi * month / 12),
        "month_cos": np.cos(2 * np.pi * month / 12),
        "day_of_year": dates.dayofyear.to_numpy(),
        "festival_flag": _festival_flag(pd.Series(dates)).to_numpy(),
    }
