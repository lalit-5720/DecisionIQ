"""Feature engineering for the forecasting models. All lag/rolling features are shifted (no look-ahead)."""
import numpy as np
import pandas as pd

from app.core.config import settings

SERIES = ["store", "item"]

FEATURE_CATALOG = [
    {"name": "lag_7", "group": "Time-Series", "description": "Sales 7 days earlier"},
    {"name": "lag_30", "group": "Time-Series", "description": "Sales 30 days earlier"},
    {"name": "rolling_mean_14", "group": "Aggregation", "description": "Mean of previous 14 days"},
    {"name": "rolling_std_14", "group": "Aggregation", "description": "Std-dev of previous 14 days"},
    {"name": "dow", "group": "Calendar", "description": "Day of week (0 = Monday)"},
    {"name": "is_weekend", "group": "Calendar", "description": "Saturday / Sunday indicator"},
    {"name": "month", "group": "Calendar", "description": "Month number"},
    {"name": "month_sin", "group": "Calendar", "description": "Cyclical sine month encoding"},
    {"name": "month_cos", "group": "Calendar", "description": "Cyclical cosine month encoding"},
    {"name": "day_of_year", "group": "Calendar", "description": "Day of year"},
    {"name": "festival_flag", "group": "Regional Event", "description": "Within [-3, +1] days of a festival"},
    {"name": "promo_flag", "group": "Discount", "description": "Active promotion (if present in source)"},
]


def _festival_flag(dates: pd.Series) -> pd.Series:
    path = settings.data_dir / "processed" / "festivals.csv"
    flag = pd.Series(0, index=dates.index)
    if not path.exists():
        return flag
    for d in pd.to_datetime(pd.read_csv(path)["date"]):
        flag[(dates >= d - pd.Timedelta(days=3)) & (dates <= d + pd.Timedelta(days=1))] = 1
    return flag


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(SERIES + ["date"]).reset_index(drop=True)
    g = df.groupby(SERIES, sort=False)["sales"]
    df["lag_7"] = g.shift(7)
    df["lag_30"] = g.shift(30)
    shifted = g.shift(1)
    grp = shifted.groupby([df["store"], df["item"]], sort=False)
    df["rolling_mean_14"] = grp.transform(lambda s: s.rolling(14, min_periods=3).mean())
    df["rolling_std_14"] = grp.transform(lambda s: s.rolling(14, min_periods=3).std())

    d = df["date"]
    df["dow"] = d.dt.dayofweek
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["month"] = d.dt.month
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    df["day_of_year"] = d.dt.dayofyear
    df["festival_flag"] = _festival_flag(d)
    if "promo_flag" not in df:
        df["promo_flag"] = 0
    return df
