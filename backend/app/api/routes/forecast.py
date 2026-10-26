import io
import json

import numpy as np
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.auth.deps import require
from app.core.config import settings
from app.forecasting import train as trainer
from app.forecasting.data import calendar, models_dir
from app.pipeline.runner import paths
from app.platform import audit

router = APIRouter(prefix="/forecast", tags=["forecast"])

_cache: dict = {}


def _read(path, loader):
    """Tiny mtime-keyed cache so repeated dashboard calls don't re-read parquet files."""
    if not path.exists():
        return None
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        _cache.clear() if len(_cache) > 12 else None
        _cache[key] = loader(path)
    return _cache[key]


def _masters():
    base = settings.data_dir / "processed"
    stores = _read(base / "stores.csv", pd.read_csv)
    items = _read(base / "items.csv", pd.read_csv)
    return stores, items


def _scope(df: pd.DataFrame, store, item, category) -> pd.DataFrame:
    if store is not None:
        df = df[df["store"] == store]
    if item is not None:
        df = df[df["item"] == item]
    if category:
        _, items = _masters()
        if items is not None:
            df = df[df["item"].isin(items.loc[items["category"] == category, "item"])]
    if df.empty:
        raise HTTPException(404, "No series match the selected filters")
    return df


def _forecasts() -> pd.DataFrame:
    df = _read(models_dir() / "forecasts.parquet", pd.read_parquet)
    if df is None:
        raise HTTPException(404, "No forecasts yet - train the models first")
    return df


def _aggregate_forecast(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    first = df["date"].min()
    df = df[df["date"] < first + pd.Timedelta(days=horizon)].copy()
    df["half"] = ((df["upper"] - df["yhat"]) ** 2)
    g = df.groupby("date").agg(yhat=("yhat", "sum"), half=("half", "sum")).reset_index()
    g["half"] = np.sqrt(g["half"])
    g["lower"] = (g["yhat"] - g["half"]).clip(lower=0)
    g["upper"] = g["yhat"] + g["half"]
    return g.drop(columns="half").round(1)


def _schedule_frame(store, item, category, horizon) -> pd.DataFrame:
    g = _aggregate_forecast(_scope(_forecasts(), store, item, category), horizon)
    cal = calendar(pd.DatetimeIndex(g["date"]))
    drivers = np.where(cal["festival_flag"] == 1, "Festival window", np.where(cal["is_weekend"] == 1, "Weekend lift", "Baseline trend"))
    g["day"] = g["date"].dt.strftime("%a")
    g["driver"] = drivers
    return g


@router.get("/options")
def options() -> dict:
    stores, items = _masters()
    return {
        "stores": [] if stores is None else stores.rename(columns={"store": "id"}).to_dict("records"),
        "items": [] if items is None else items.rename(columns={"item": "id", "sku_code": "sku"})[["id", "sku", "name", "category"]].to_dict("records"),
        "categories": [] if items is None else sorted(items["category"].unique().tolist()),
        "horizons": [7, 30, 90],
    }


@router.get("/models")
def models() -> dict:
    p = models_dir() / "benchmark.json"
    if not p.exists():
        return {"available": False}
    return {"available": True, **json.loads(p.read_text(encoding="utf-8"))}


@router.get("/train-status")
def train_status() -> dict:
    s = trainer.read_state()
    s["running"] = trainer.is_running()
    return s


@router.post("/retrain", status_code=202, dependencies=[Depends(require("run_analysis"))])
def retrain(background: BackgroundTasks) -> dict:
    if trainer.is_running():
        raise HTTPException(409, "Training already running")
    if not paths()["features"].exists():
        raise HTTPException(409, "Run the data pipeline first")
    audit.record("Started model retraining", "model")
    background.add_task(trainer.run_training)
    return {"status": "started"}


@router.get("/series")
def series(
    store: int | None = None, item: int | None = None, category: str | None = None,
    horizon: int = Query(30, ge=1, le=90), history_days: int = Query(180, ge=7, le=1826),
) -> dict:
    fc = _aggregate_forecast(_scope(_forecasts(), store, item, category), horizon)

    hist = _read(paths()["features"], lambda p: pd.read_parquet(p, columns=["date", "store", "item", "sales"]))
    h = _scope(hist, store, item, category).groupby("date")["sales"].sum().reset_index()
    h = h[h["date"] > h["date"].max() - pd.Timedelta(days=history_days)]

    bt = _read(models_dir() / "backtest.parquet", pd.read_parquet)
    backtest = []
    if bt is not None:
        b = _scope(bt, store, item, category).groupby("date")[["actual", "pred"]].sum().reset_index().round(1)
        backtest = [{"date": d.strftime("%Y-%m-%d"), "actual": a, "pred": p} for d, a, p in b.itertuples(index=False)]

    last7 = float(h["sales"].tail(7).mean())
    peak = fc.loc[fc["yhat"].idxmax()]
    meta = models()
    return {
        "history": [{"date": d.strftime("%Y-%m-%d"), "actual": float(v)} for d, v in h.itertuples(index=False)],
        "forecast": [
            {"date": r.date.strftime("%Y-%m-%d"), "yhat": r.yhat, "lower": r.lower, "upper": r.upper} for r in fc.itertuples()
        ],
        "backtest": backtest,
        "summary": {
            "peak_units": float(peak["yhat"]), "peak_date": peak["date"].strftime("%Y-%m-%d"),
            "total_units": float(fc["yhat"].sum()),
            "run_rate_wow_pct": round((float(fc["yhat"].head(7).mean()) / last7 - 1) * 100, 1) if last7 else None,
            "model": meta.get("serving"), "version": meta.get("version"),
        },
    }


@router.get("/low-confidence")
def low_confidence(threshold: int = Query(40, ge=10, le=95), limit: int = Query(8, ge=1, le=50), store: int | None = None, item: int | None = None) -> dict:
    """Series whose forecast band is widest relative to the forecast (uncertain), with a category-average fallback for comparison."""
    fc = _forecasts()
    f30 = fc[fc["date"] < fc["date"].min() + pd.Timedelta(days=30)]
    g = f30.groupby(["store", "item"])
    half = g.apply(lambda d: ((d["upper"] - d["lower"]) / 2).mean(), include_groups=False)
    mean = g["yhat"].mean()
    stat = pd.DataFrame({"mean": mean, "rel": half / mean.clip(lower=0.5)}).reset_index()
    stat["confidence"] = (100 * (1 - stat["rel"])).clip(0, 99).round(1)
    stores, items = _masters()
    sn = stores.set_index("store")["name"] if stores is not None else {}
    im = items.set_index("item") if items is not None else None
    stat["category"] = stat["item"].map(im["category"]) if im is not None else ""
    worst = stat.sort_values("confidence").head(limit)
    pick = stat[(stat["store"] == store) & (stat["item"] == item)] if store is not None and item is not None else worst.head(1)
    if pick.empty:
        raise HTTPException(404, "Unknown store/item")
    s0 = pick.iloc[0]
    one = f30[(f30["store"] == s0["store"]) & (f30["item"] == s0["item"])].sort_values("date")
    peers = stat[(stat["store"] == s0["store"]) & (stat["category"] == s0["category"]) & (stat["item"] != s0["item"])]
    peer_ids = set(peers["item"])
    prior_level = float(f30[(f30["store"] == s0["store"]) & (f30["item"].isin(peer_ids))].groupby("date")["yhat"].mean().mean()) if peer_ids else float(one["yhat"].mean())
    # scale the category-average prior to this series' own volume
    prior = [round(prior_level * float(s0["mean"]) / max(float(peers["mean"].mean()) if len(peers) else float(s0["mean"]), 0.5), 1)] * len(one)
    return {
        "threshold": threshold, "total_series": int(len(stat)), "low_count": int((stat["confidence"] < threshold).sum()),
        "median_confidence": round(float(stat["confidence"].median()), 1),
        "series": [{"store": int(r.store), "item": int(r.item), "store_name": sn.get(r.store, str(r.store)),
                    "item_name": im.loc[r.item, "name"] if im is not None else str(r.item), "sku": im.loc[r.item, "sku_code"] if im is not None else "",
                    "category": r.category, "avg_daily": round(float(r.mean), 1), "confidence": float(r.confidence),
                    "band_pct": round(float(r.rel) * 100, 1)} for r in worst.itertuples()],
        "example": {"store": int(s0["store"]), "item": int(s0["item"]), "confidence": float(s0["confidence"]), "category": s0["category"],
                    "dates": [d.strftime("%Y-%m-%d") for d in one["date"]], "yhat": one["yhat"].round(1).tolist(),
                    "lower": one["lower"].round(1).tolist(), "upper": one["upper"].round(1).tolist(), "prior": prior,
                    "label": f"{im.loc[s0['item'], 'name'] if im is not None else s0['item']} · {sn.get(s0['store'], s0['store'])}"},
    }


@router.get("/schedule")
def schedule(
    store: int | None = None, item: int | None = None, category: str | None = None,
    horizon: int = Query(30, ge=1, le=90), page: int = Query(1, ge=1), page_size: int = Query(8, ge=1, le=90),
) -> dict:
    g = _schedule_frame(store, item, category, horizon)
    total = len(g)
    part = g.iloc[(page - 1) * page_size : page * page_size]
    return {
        "total": total, "page": page, "page_size": page_size,
        "rows": [
            {"date": r.date.strftime("%d %b %Y"), "day": r.day, "forecast": r.yhat, "lower": r.lower, "upper": r.upper, "driver": r.driver}
            for r in part.itertuples()
        ],
    }


@router.get("/export.csv")
def export_csv(
    store: int | None = None, item: int | None = None, category: str | None = None, horizon: int = Query(30, ge=1, le=90)
):
    g = _schedule_frame(store, item, category, horizon)
    out = g.assign(date=g["date"].dt.strftime("%Y-%m-%d"))[["date", "day", "yhat", "lower", "upper", "driver"]]
    buf = io.StringIO()
    out.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=forecast.csv"})
