"""Global XGBoost model with recursive multi-step forecasting across all series."""
import numpy as np
import xgboost as xgb
from numpy.lib.stride_tricks import sliding_window_view

from app.forecasting.data import calendar, extend_dates

FEATURES = [
    "lag_7", "lag_30", "rolling_mean_14", "rolling_std_14", "dow", "is_weekend",
    "month", "month_sin", "month_cos", "day_of_year", "festival_flag", "store", "item",
]
MIN_T = 30


def make_features(y, t_idx, cal, store_ids, item_ids):
    """Features for target days `t_idx` using only y[:, < t]. Returns X of shape (n_series * len(t_idx), F)."""
    n, t_idx = y.shape[0], np.asarray(t_idx)
    win = sliding_window_view(y, 14, axis=1)[:, t_idx - 14, :]
    cols = {
        "lag_7": y[:, t_idx - 7],
        "lag_30": y[:, t_idx - 30],
        "rolling_mean_14": win.mean(axis=2),
        "rolling_std_14": win.std(axis=2, ddof=1),
        "store": np.repeat(store_ids[:, None], len(t_idx), axis=1),
        "item": np.repeat(item_ids[:, None], len(t_idx), axis=1),
    }
    for k, v in cal.items():
        cols[k] = np.broadcast_to(v[t_idx][None, :], (n, len(t_idx)))
    return np.column_stack([np.asarray(cols[f], dtype=np.float32).ravel() for f in FEATURES])


def train(y, dates, series, t_end, **overrides):
    cal = calendar(dates)
    t_idx = np.arange(MIN_T, t_end)
    X = make_features(y, t_idx, cal, series["store"].to_numpy(), series["item"].to_numpy())
    target = y[:, t_idx].ravel().astype(np.float32)
    params = dict(n_estimators=400, max_depth=8, learning_rate=0.08, subsample=0.8, colsample_bytree=0.8,
                  tree_method="hist", n_jobs=-1, random_state=42)
    params.update(overrides)
    model = xgb.XGBRegressor(**params)
    model.fit(X, target)
    return model


def forecast(model, y_hist, dates, series, horizon):
    """Recursive forecast: each predicted day is fed back as history. Returns (n_series, horizon)."""
    n, T = y_hist.shape
    all_dates = extend_dates(dates[:T], horizon)
    cal = calendar(all_dates)
    y = np.concatenate([y_hist, np.zeros((n, horizon))], axis=1)
    sid, iid = series["store"].to_numpy(), series["item"].to_numpy()
    for h in range(horizon):
        t = T + h
        pred = model.predict(make_features(y, [t], cal, sid, iid))
        y[:, t] = np.clip(pred, 0, None)
    return y[:, T:]


def importance(model) -> list[dict]:
    gain = model.get_booster().get_score(importance_type="gain")
    names = {f"f{i}": n for i, n in enumerate(FEATURES)}
    total = sum(gain.values()) or 1
    rows = [{"feature": names.get(k, k), "weight": round(v / total * 100, 1)} for k, v in gain.items()]
    return sorted(rows, key=lambda r: -r["weight"])
