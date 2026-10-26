"""Explainability for the serving XGBoost model.

Uses XGBoost's native TreeSHAP (`pred_contribs=True`), which is exact for tree ensembles:
base value + sum(feature contributions) == the model's prediction.
"""
import hashlib
import json

import numpy as np
import pandas as pd
import xgboost as xgb

from app.core.config import settings
from app.forecasting import xgb_model
from app.forecasting.data import calendar, extend_dates, load_matrix, models_dir

FEATURES = xgb_model.FEATURES
GROUPS = {
    "Recent run-rate": ["rolling_mean_14", "rolling_std_14", "lag_30"],
    "Weekly pattern": ["lag_7", "dow", "is_weekend"],
    "Seasonality & events": ["month", "month_sin", "month_cos", "day_of_year", "festival_flag"],
    "Store / product baseline": ["store", "item"],
}
PHRASES = {
    "rolling_mean_14": "the recent 14-day run-rate", "rolling_std_14": "recent demand volatility", "lag_30": "the level 30 days ago",
    "lag_7": "sales on the same weekday last week", "dow": "the day of the week", "is_weekend": "the weekend effect",
    "month": "the time of year", "month_sin": "seasonality", "month_cos": "seasonality", "day_of_year": "seasonality",
    "festival_flag": "the festival window", "store": "this store's baseline", "item": "this product's baseline",
}

_cache: dict = {}


class ExplainError(ValueError):
    pass


def _cached(path, loader):
    if not path.exists():
        return None
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        for k in [k for k in _cache if k[0] == key[0]]:
            del _cache[k]
        _cache[key] = loader(path)
    return _cache[key]


def meta() -> dict:
    m = _cached(models_dir() / "benchmark.json", lambda p: json.loads(p.read_text(encoding="utf-8")))
    if m is None:
        raise ExplainError("No trained models - train the forecasting models first")
    if m["serving"] != "XGBoost" or not (models_dir() / "xgb.json").exists():
        raise ExplainError(f"Explanations need the XGBoost model, but the serving model is {m['serving']}")
    return m


def booster() -> xgb.Booster:
    def load(p):
        b = xgb.Booster()
        b.load_model(p)
        return b
    return _cached(models_dir() / "xgb.json", load)


def matrix():
    return _cached(settings.data_dir / "processed" / "features.parquet", lambda p: load_matrix())


def _contribs(X: np.ndarray) -> np.ndarray:
    return booster().predict(xgb.DMatrix(X), pred_contribs=True)  # (n, F + 1); last column = base value


def _series_index(series: pd.DataFrame, store: int, item: int) -> int:
    hit = np.flatnonzero((series["store"] == store) & (series["item"] == item))
    if not len(hit):
        raise ExplainError("Unknown store/item combination")
    return int(hit[0])


def options() -> dict:
    m = meta()
    y, dates, series = matrix()
    return {"history": [dates[30].date().isoformat(), dates[-1].date().isoformat()], "forecast": m["forecast_window"],
            "serving": m["serving"], "model_version": m["version"]}


def explain_local(store: int, item: int, date: str) -> dict:
    m = meta()
    y, dates, series = matrix()
    i = _series_index(series, store, item)
    d, T, H = pd.Timestamp(date), len(dates), m["horizon_days"]
    all_dates = extend_dates(dates, H)
    if d in dates:
        t, in_hist = dates.get_loc(d), True
        if t < xgb_model.MIN_T:
            raise ExplainError("Not enough history before this date")
    elif d in all_dates:
        t, in_hist = all_dates.get_loc(d), False
    else:
        raise ExplainError(f"Date must be between {dates[30].date()} and {all_dates[-1].date()}")
    cal = calendar(all_dates)
    sid, iid = np.array([store]), np.array([item])
    yr = np.concatenate([y[i : i + 1], np.zeros((1, H))], axis=1)
    for s in range(T, t):  # replay the recursive forecast up to the target day
        yr[:, s] = np.clip(booster().predict(xgb.DMatrix(xgb_model.make_features(yr, [s], cal, sid, iid))), 0, None)
    X = xgb_model.make_features(yr, [t], cal, sid, iid)
    c = _contribs(X)[0]
    base, shap = float(c[-1]), c[:-1]
    pred = float(c.sum())
    rows = [{"feature": f, "value": float(X[0, k]), "shap": float(shap[k])} for k, f in enumerate(FEATURES)]
    total_abs = sum(abs(r["shap"]) for r in rows) or 1
    for r in rows:
        r["share_pct"] = round(r["shap"] / total_abs * 100, 1)
    rows.sort(key=lambda r: -abs(r["shap"]))

    groups = [{"group": g, "shap": float(sum(r["shap"] for r in rows if r["feature"] in fs)),
               "features": [r["feature"] for r in rows if r["feature"] in fs]} for g, fs in GROUPS.items()]
    top = rows[:6]
    steps, cum = [{"label": "Base E[f(x)]", "value": base, "start": 0.0, "end": base, "kind": "base"}], base
    for r in top:
        steps.append({"label": r["feature"], "value": r["shap"], "start": cum, "end": cum + r["shap"], "kind": "up" if r["shap"] >= 0 else "down"})
        cum += r["shap"]
    rest = float(sum(r["shap"] for r in rows[6:]))
    if abs(rest) > 1e-6:
        steps.append({"label": "other", "value": rest, "start": cum, "end": cum + rest, "kind": "up" if rest >= 0 else "down"})
        cum += rest
    steps.append({"label": "f(x) final", "value": pred, "start": 0.0, "end": pred, "kind": "final"})

    return {
        "store": store, "item": item, "date": d.date().isoformat(), "in_history": in_hist,
        "prediction": round(pred, 1), "base_value": round(base, 1), "actual": float(y[i, t]) if in_hist else None,
        "delta_pct": round((pred / base - 1) * 100, 1) if base else None,
        "contributions": rows, "groups": groups, "waterfall": steps,
        "balance_check": round(abs(base + sum(r["shap"] for r in rows) - pred), 6),
        "summary": _summary(rows, pred, base, d),
    }


def _summary(rows, pred, base, d) -> str:
    pos = [r for r in rows if r["shap"] > 0.5][:2]
    neg = [r for r in rows if r["shap"] < -0.5][:1]
    diff = pred - base
    head = f"Demand on {d:%d %b %Y} is projected at {pred:.0f} units, "
    head += f"{abs(diff / base) * 100:.0f}% {'above' if diff >= 0 else 'below'} the network-wide average of {base:.0f}" if base else "".join([])
    parts = []
    if pos:
        parts.append("mainly driven by " + " and ".join(f"{PHRASES[r['feature']]} (+{r['shap']:.0f})" for r in pos))
    if neg:
        parts.append(f"partly offset by {PHRASES[neg[0]['feature']]} ({neg[0]['shap']:.0f})")
    return head + (", " + ", ".join(parts) if parts else "") + "."


def _sample_rows(store=None, item=None, n_days=40, seed=0) -> np.ndarray:
    y, dates, series = matrix()
    T = len(dates)
    cal = calendar(dates)
    rng = np.random.default_rng(seed)
    if store is not None and item is not None:
        i = _series_index(series, store, item)
        t_idx = np.arange(max(xgb_model.MIN_T, T - 365), T)
        return xgb_model.make_features(y[i : i + 1], t_idx, cal, np.array([store]), np.array([item]))
    t_idx = rng.choice(np.arange(xgb_model.MIN_T, T), n_days, replace=False)
    return xgb_model.make_features(y, t_idx, cal, series["store"].to_numpy(), series["item"].to_numpy())


def _global_importance() -> dict:
    X = _sample_rows()
    c = _contribs(X)[:, :-1]
    mean_abs = np.abs(c).mean(axis=0)
    total = mean_abs.sum() or 1
    feats = sorted(({"feature": f, "mean_abs_shap": round(float(v), 3), "share_pct": round(float(v / total * 100), 1)} for f, v in zip(FEATURES, mean_abs)),
                   key=lambda r: -r["share_pct"])
    groups = [{"group": g, "share_pct": round(sum(r["share_pct"] for r in feats if r["feature"] in fs), 1)} for g, fs in GROUPS.items()]
    b = meta()
    full = next(m for m in b["models"] if m["name"] == "XGBoost").get("full_set", {})
    return {"features": feats, "groups": sorted(groups, key=lambda g: -g["share_pct"]), "sample_rows": int(len(X)),
            "model": {"version": b["version"], "r2": full.get("r2"), "mape": full.get("mape"), "wape": full.get("wape")}}


def dependence(feature: str, store: int | None = None, item: int | None = None) -> dict:
    meta()
    if feature not in FEATURES:
        raise ExplainError(f"feature must be one of {FEATURES}")
    X = _sample_rows(store, item)
    X = X[np.random.default_rng(1).permutation(len(X))[:300]]
    j = FEATURES.index(feature)
    col = X[:, j]
    uniq = np.unique(col)
    grid = uniq if len(uniq) <= 14 else np.unique(np.quantile(col, np.linspace(0.03, 0.97, 15)))
    preds = np.empty((len(X), len(grid)))
    b = booster()
    for g, v in enumerate(grid):
        Xg = X.copy()
        Xg[:, j] = v
        preds[:, g] = b.predict(xgb.DMatrix(Xg))
    return {"feature": feature, "grid": [round(float(v), 3) for v in grid], "pdp": [round(float(v), 2) for v in preds.mean(axis=0)],
            "ice": [[round(float(v), 2) for v in row] for row in preds[:12]], "rows": int(len(X))}


def _psi(ref: np.ndarray, cur: np.ndarray, bins: int = 10) -> float:
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    r = np.histogram(ref, edges)[0] / len(ref) + 1e-6
    c = np.histogram(cur, edges)[0] / len(cur) + 1e-6
    return float(((c - r) * np.log(c / r)).sum())


def _governance() -> dict:
    m = meta()
    y, dates, series = matrix()
    T, cal = len(dates), calendar(dates)
    sid, iid = series["store"].to_numpy(), series["item"].to_numpy()
    ref_t = np.random.default_rng(3).choice(np.arange(xgb_model.MIN_T, T - 90), 40, replace=False)
    Xr = xgb_model.make_features(y, ref_t, cal, sid, iid)
    Xc = xgb_model.make_features(y, np.arange(T - 90, T, 3), cal, sid, iid)
    drift = []
    for f in ["lag_7", "lag_30", "rolling_mean_14", "rolling_std_14"]:
        j = FEATURES.index(f)
        drift.append({"feature": f, "psi": round(_psi(Xr[:, j], Xc[:, j]), 3)})
    drift.append({"feature": "sales (target)", "psi": round(_psi(y[:, ref_t].ravel(), y[:, np.arange(T - 90, T, 3)].ravel()), 3)})
    max_psi = max(d["psi"] for d in drift)

    bt = pd.read_parquet(models_dir() / "backtest.parquet")
    stores = pd.read_csv(settings.data_dir / "processed" / "stores.csv").set_index("store")["name"]
    bt["abs"] = (bt["actual"] - bt["pred"]).abs()
    per = bt.groupby("store").agg(abs=("abs", "sum"), actual=("actual", "sum"), pred=("pred", "sum")).reset_index()
    per["wape"] = per["abs"] / per["actual"] * 100
    per["bias"] = (per["pred"] / per["actual"] - 1) * 100
    parity = float(np.clip(1 - per["wape"].std() / per["wape"].mean(), 0, 1) * 100)
    artifact = (models_dir() / "xgb.json").read_bytes()
    return {
        "model_version": m["version"], "trained_at": m["trained_at"], "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "holdout": m["backtest_window"],
        "parity_index": round(parity, 1),
        "stores": [{"store": int(r.store), "name": stores.get(r.store, str(r.store)), "wape": round(r.wape, 1), "bias": round(r.bias, 1)} for r in per.itertuples()],
        "drift": drift, "max_psi": max_psi,
        "drift_status": "Nominal" if max_psi < 0.1 else "Moderate" if max_psi < 0.25 else "Significant",
        "note": "PSI compares the last 90 days with earlier history; part of any drift is normal seasonality.",
    }


def _memo(name, fn):
    """Global/governance views are expensive and only change when the model or data change."""
    stamp = (name, (models_dir() / "benchmark.json").stat().st_mtime if (models_dir() / "benchmark.json").exists() else 0,
             (settings.data_dir / "processed" / "features.parquet").stat().st_mtime if (settings.data_dir / "processed" / "features.parquet").exists() else 0,
             str(settings.data_dir))
    if stamp not in _cache:
        _cache[stamp] = fn()
    return _cache[stamp]


def global_importance() -> dict:
    meta()
    return _memo("global", _global_importance)


def governance() -> dict:
    meta()
    return _memo("gov", _governance)
