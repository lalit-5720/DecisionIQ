"""Cleaning: duplicates, gaps, missing values, outliers. Returns cleaned frame + stats."""
import numpy as np
import pandas as pd

SERIES = ["store", "item"]


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows_in = len(df)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["sales"] = pd.to_numeric(df["sales"], errors="coerce")

    invalid_dates = int(df["date"].isna().sum())
    df = df.dropna(subset=["date", "store", "item"])

    dup_exact = int(df.duplicated().sum())
    df = df.drop_duplicates()
    key = ["date", "store", "item"]
    dup_key = int(df.duplicated(key, keep="last").sum())
    df = df.drop_duplicates(key, keep="last")

    negatives = int((df["sales"] < 0).sum())
    df.loc[df["sales"] < 0, "sales"] = np.nan

    # complete daily grid per series so lag features are well defined
    pairs = df[SERIES].drop_duplicates()
    full_days = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
    idx = pd.MultiIndex.from_frame(
        pairs.reset_index(drop=True).merge(pd.DataFrame({"date": full_days}), how="cross")[SERIES + ["date"]]
    )
    gaps_added = len(idx) - len(df)
    df = df.set_index(SERIES + ["date"]).reindex(idx).reset_index().sort_values(SERIES + ["date"])

    missing = int(df["sales"].isna().sum())
    g = df.groupby(SERIES, sort=False)["sales"]
    df["sales"] = g.transform(lambda s: s.interpolate(limit_direction="both"))
    df["sales"] = df["sales"].fillna(g.transform("median")).fillna(0)

    # IQR x3 outlier capping per series
    g = df.groupby(SERIES, sort=False)["sales"]
    q1, q3 = g.transform(lambda s: s.quantile(0.25)), g.transform(lambda s: s.quantile(0.75))
    iqr = q3 - q1
    upper, lower = q3 + 3 * iqr, (q1 - 3 * iqr).clip(lower=0)
    outliers = int(((df["sales"] > upper) | (df["sales"] < lower)).sum())
    df["sales"] = df["sales"].clip(lower, upper).round().astype(int)

    for col in ("net_price",):
        if col in df:
            df[col] = df.groupby(SERIES, sort=False)[col].transform(lambda s: s.ffill().bfill())
    if "promo_flag" in df:
        df["promo_flag"] = pd.to_numeric(df["promo_flag"], errors="coerce").fillna(0).astype(int)

    rows_out = len(df)
    problems = missing + dup_exact + dup_key + outliers + invalid_dates + negatives
    score = int(round(max(0.0, 100 - 100 * problems / max(rows_in, 1) * 2)))
    stats = {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "invalid_dates": invalid_dates,
        "duplicates_removed": dup_exact + dup_key,
        "negatives_nulled": negatives,
        "gaps_filled": max(gaps_added, 0),
        "missing_imputed": missing,
        "outliers_capped": outliers,
        "quality_score": score,
        "quality_label": "Excellent" if score >= 90 else "Good" if score >= 75 else "Needs attention",
    }
    return df.reset_index(drop=True), stats
