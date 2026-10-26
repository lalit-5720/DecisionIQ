"""Unsupervised anomaly detection on the *billed* data (units billed, net price, cost).

Three detectors score every store x item x day row; an ensemble averages their rank percentiles.
Labels (`anomaly_type`) are never used for detection - only for evaluation.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neural_network import MLPRegressor

FEATURES = ["z_units", "zd", "margin", "depth"]
COST_DRIFT = 0.03  # standard cost drift per year (ERP cost assumption)
DETECTORS = ["IsolationForest", "Autoencoder", "ZScore", "Ensemble"]


def build_signals(sales: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    """Row-level signals. `sales` needs date, store, item, units_billed, net_price, list_price."""
    sales = sales.sort_values(["store", "item", "date"]).reset_index(drop=True)
    series = sales[["store", "item"]].drop_duplicates().reset_index(drop=True)
    dates = pd.DatetimeIndex(sorted(sales["date"].unique()))
    n, T = len(series), len(dates)
    shape = (n, T)
    U = sales["units_billed"].to_numpy(float).reshape(shape)
    P = sales["net_price"].to_numpy(float).reshape(shape)
    L = sales["list_price"].to_numpy(float).reshape(shape)

    dow = dates.dayofweek.to_numpy()
    dowf = np.array([U[:, dow == d].mean() for d in range(7)])
    dowf /= dowf.mean()
    adj = U / dowf[dow][None, :]
    base = pd.DataFrame(adj.T).rolling(28, min_periods=7).median().shift(1).to_numpy().T
    expected = base * dowf[dow][None, :]

    lr = np.log((U + 1) / (expected + 1))
    med = np.nanmedian(lr, axis=1, keepdims=True)
    sd = np.maximum(np.nanmedian(np.abs(lr - med), axis=1, keepdims=True) * 1.4826, 0.05)
    z_units = (lr - med) / sd
    # sustained drop: both of the last two days well below expectation (a lone dip does not score)
    zd = -np.maximum(z_units, np.concatenate([np.full((n, 1), np.nan), z_units[:, :-1]], axis=1))

    years = (dates - dates[0]).days.to_numpy() / 365.0
    unit_cost = items.set_index("item")["unit_cost"].reindex(series["item"]).to_numpy()
    cost = unit_cost[:, None] * (1 + COST_DRIFT * years[None, :])

    out = pd.DataFrame(
        {
            "date": np.tile(dates.to_numpy(), n),
            "store": np.repeat(series["store"].to_numpy(), T),
            "item": np.repeat(series["item"].to_numpy(), T),
            "units_billed": U.ravel(), "expected": expected.ravel().round(1),
            "net_price": P.ravel(), "list_price": L.ravel(), "unit_cost": cost.ravel().round(2),
            "z_units": z_units.ravel(), "zd": zd.ravel(),
            "margin": ((P - cost) / P).ravel(), "depth": (1 - P / L).ravel(),
        }
    )
    out["valid"] = out[FEATURES].notna().all(axis=1)
    return out


def _standardise(X: np.ndarray) -> np.ndarray:
    return np.clip((X - X.mean(axis=0)) / (X.std(axis=0) + 1e-9), -15, 15)


def score(sig: pd.DataFrame, contamination: float = 0.0015, z_thr: float = 3.0, max_discount: float = 0.25,
          seed: int = 42) -> pd.DataFrame:
    """Adds score_* and flag_* columns.

    - ZScore   : rule thresholds - billing spike z >= z_thr, sustained drop z >= z_thr, discount deeper than policy cap.
    - IsolationForest / Autoencoder : multivariate; flag the top `contamination` share of rows.
    - Ensemble : a row is flagged when at least 2 of the 3 detectors flag it; `score` is the mean rank percentile (0..1).
    """
    sig = sig.copy()
    v = sig["valid"].to_numpy()
    F = sig.loc[v, FEATURES]
    # one-sided "badness" signals: billing spike, sustained drop, thin/negative margin, deep discount
    X = _standardise(np.column_stack([F["z_units"].clip(lower=0), F["zd"].clip(lower=0), -F["margin"], F["depth"]]))
    rng = np.random.default_rng(seed)
    sample = rng.choice(len(X), min(len(X), 150_000), replace=False)

    iforest = IsolationForest(n_estimators=150, random_state=seed, n_jobs=-1).fit(X[sample])
    s_if = -iforest.score_samples(X)
    ae = MLPRegressor(hidden_layer_sizes=(8, 3, 8), activation="tanh", max_iter=40, random_state=seed).fit(X[sample], X[sample])
    s_ae = ((X - ae.predict(X)) ** 2).mean(axis=1)
    s_z = np.maximum.reduce([F["z_units"].to_numpy() / z_thr, F["zd"].to_numpy() / z_thr, F["depth"].to_numpy() / max_discount])

    k = max(1, int(np.ceil(contamination * len(X))))
    top_k = lambda s: np.isin(np.arange(len(s)), np.argsort(-s)[:k])  # noqa: E731
    flags = {"IsolationForest": top_k(s_if), "Autoencoder": top_k(s_ae), "ZScore": s_z >= 1.0}
    flags["Ensemble"] = sum(f.astype(int) for f in flags.values()) >= 2
    scores = {"IsolationForest": s_if, "Autoencoder": s_ae, "ZScore": s_z}
    pct = np.mean([pd.Series(a).rank(pct=True).to_numpy() for a in scores.values()], axis=0)
    scores["Ensemble"] = pct
    for name in scores:
        col, fl = np.zeros(len(sig)), np.zeros(len(sig), dtype=bool)
        col[v], fl[v] = scores[name], flags[name]
        sig[f"score_{name}"], sig[f"flag_{name}"] = col, fl
    sig["score"] = sig["score_Ensemble"]
    return sig


def classify(row, z_thr: float = 3.0) -> str:
    if row.z_units >= z_thr:
        return "duplicate_billing"
    if row.zd >= z_thr:
        return "demand_drop"
    if row.depth > 0.25 or row.margin < 0:
        return "margin_erosion"
    return "unclassified"


def classify_frame(df: pd.DataFrame, z_thr: float = 3.0) -> pd.Series:
    t = np.full(len(df), "unclassified", dtype=object)
    t[(df["depth"] > 0.25) | (df["margin"] < 0)] = "margin_erosion"
    t[df["zd"] >= z_thr] = "demand_drop"
    t[df["z_units"] >= z_thr] = "duplicate_billing"
    return pd.Series(t, index=df.index)


def prf(flag: np.ndarray, truth: np.ndarray) -> dict:
    tp = int((flag & truth).sum())
    fp, fn = int(flag.sum()) - tp, int(truth.sum()) - tp
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn}


def group_events(df: pd.DataFrame, mask: pd.Series, type_col: pd.Series) -> pd.Series:
    """Event id for flagged rows: consecutive days (gap <= 1) of the same series and type form one event."""
    sub = df.loc[mask, ["store", "item", "date"]].assign(t=type_col[mask])
    sub = sub.sort_values(["store", "item", "t", "date"])
    new = (
        (sub["store"] != sub["store"].shift()) | (sub["item"] != sub["item"].shift())
        | (sub["t"] != sub["t"].shift()) | ((sub["date"] - sub["date"].shift()).dt.days > 1)
    )
    return new.cumsum().reindex(df.index)


def detect_cost_spikes(log: pd.DataFrame, z_thr: float = 3.0) -> pd.DataFrame:
    """Weekly freight cost vs trailing 12-week robust baseline per store."""
    log = log.sort_values(["store", "week_start"]).reset_index(drop=True)
    g = log.groupby("store")["freight_cost"]
    base = g.transform(lambda s: s.rolling(12, min_periods=4).median().shift(1))
    mad = g.transform(lambda s: (s - s.rolling(12, min_periods=4).median().shift(1)).abs().rolling(12, min_periods=4).median().shift(1))
    log["baseline"] = base
    log["z"] = (log["freight_cost"] - base) / np.maximum(mad * 1.4826, 0.02 * base)
    log["flag"] = log["z"] > z_thr
    return log
