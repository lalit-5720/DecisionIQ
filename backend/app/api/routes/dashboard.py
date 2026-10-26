import json
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Anomaly, Recommendation
from app.db.session import get_db, get_engine
from app.forecasting.data import models_dir
from app.pipeline import runner
from app.risk import scan

router = APIRouter(tags=["dashboard"])

NAV_PAGES = [("Dashboard", "/"), ("Data Sources", "/data-sources"), ("Forecasting", "/forecasting"), ("Risk & Anomalies", "/risk"),
             ("Recommendations", "/recommendations"), ("What-If Simulator", "/what-if"), ("Explainability", "/explainability"),
             ("Reports", "/reports"), ("Settings", "/settings")]
_cache: dict = {}


def _read(path, loader):
    if not path.exists():
        return None
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        for k in [k for k in _cache if k[0] == key[0]]:
            del _cache[k]
        _cache[key] = loader(path)
    return _cache[key]


def tables(db: Session = Depends(get_db)) -> Session:
    for t in (Anomaly, Recommendation):
        t.__table__.create(get_engine(), checkfirst=True)
    return db


def _meta() -> dict:
    p = models_dir() / "benchmark.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


@router.get("/dashboard/status")
def status(db: Session = Depends(tables)) -> dict:
    pipe, meta, metrics = runner.read_state(), _meta(), scan.read_metrics()
    q = pipe.get("quality") or {}
    open_alerts = db.scalar(select(func.count()).where(Anomaly.status.in_(["Open", "In Review"]))) or 0
    high = db.scalar(select(func.count()).where(Anomaly.status.in_(["Open", "In Review"]), Anomaly.severity == "High")) or 0
    pending = db.scalar(select(func.count()).where(Recommendation.status == "Pending")) or 0
    done = pipe.get("status") == "complete"
    steps = [
        {"key": "data", "label": "Data uploaded", "ok": done, "detail": pipe.get("source", "")},
        {"key": "clean", "label": "Cleaned", "ok": done, "detail": f"quality {q.get('quality_score')}/100" if q else ""},
        {"key": "models", "label": "Models trained", "ok": bool(meta), "detail": f"{meta.get('serving', '')} {meta.get('version', '').split('-')[-1][:8]}".strip()},
        {"key": "forecast", "label": "Forecast ready", "ok": bool(meta), "detail": " → ".join(meta.get("forecast_window", []))},
        {"key": "risk", "label": "Risks scanned", "ok": metrics is not None, "detail": f"{high} high" if metrics else ""},
    ]
    stamps = [s for s in (pipe.get("updated_at"), meta.get("trained_at"), (metrics or {}).get("ran_at")) if s]
    return {"steps": steps, "healthy": all(s["ok"] for s in steps), "synced_at": max(stamps) if stamps else None,
            "open_alerts": open_alerts, "high_alerts": high, "pending_recs": pending,
            "data_range": [pipe.get("features", {}).get("date_min"), meta.get("forecast_window", [None, None])[1]]}


@router.get("/dashboard/summary")
def summary(db: Session = Depends(tables)) -> dict:
    base = settings.data_dir / "processed"
    out: dict = {"ready": False}
    hist = _read(runner.paths()["features"], lambda p: pd.read_parquet(p, columns=["date", "store", "item", "sales"]))
    fc = _read(models_dir() / "forecasts.parquet", pd.read_parquet)
    stores = _read(base / "stores.csv", pd.read_csv)
    items = _read(base / "items.csv", pd.read_csv)
    meta = _meta()
    if hist is None or fc is None or stores is None or items is None:
        return out
    last = hist["date"].max()
    cur, prev = hist[hist["date"] > last - pd.Timedelta(days=30)], hist[(hist["date"] <= last - pd.Timedelta(days=30)) & (hist["date"] > last - pd.Timedelta(days=60))]
    f30 = fc[fc["date"] < fc["date"].min() + pd.Timedelta(days=30)]
    a30, p30, fc30 = cur["sales"].sum(), prev["sales"].sum(), f30["yhat"].sum()
    out.update(ready=True, as_of=last.date().isoformat(),
               kpis={"units_30d": int(a30), "units_prev_30d": int(p30), "growth_pct": round((a30 / p30 - 1) * 100, 1) if p30 else None,
                     "forecast_30d": round(float(fc30)), "forecast_growth_pct": round((fc30 / a30 - 1) * 100, 1) if a30 else None},
               model={"serving": meta.get("serving"), "version": meta.get("version"),
                      **{k: next((m.get("full_set", {}).get(k) for m in meta.get("models", []) if m["name"] == meta.get("serving")), None) for k in ("mape", "r2", "wape")}})

    city = stores.set_index("store")["city"]
    reg = pd.DataFrame({"actual": cur.groupby(cur["store"].map(city))["sales"].sum(), "forecast": f30.groupby(f30["store"].map(city))["yhat"].sum()}).fillna(0)
    reg["stores"] = stores.groupby("city").size()
    reg = reg.sort_values("actual", ascending=False)
    out["regions"] = [{"city": c, "stores": int(r.stores), "actual": int(r.actual), "forecast": round(float(r.forecast)), "share_pct": round(r.actual / reg["actual"].sum() * 100, 1)} for c, r in reg.iterrows()]

    try:  # inventory health from current stock vs forecast demand
        from app.simulate import engine as sim

        S, F, _ = sim._state()
        cover = (S["pos"] / S["avg30"]).to_numpy()
        value = float((S["on_hand"] * S["cost"]).sum())
        buckets = {"Low stock (<3 days)": int((cover < 3).sum()), "Healthy (3-45 days)": int(((cover >= 3) & (cover <= 45)).sum()), "Overstock (>45 days)": int((cover > 45).sum())}
        out["inventory"] = {"total_skus": int(len(S)), "stock_value": round(value), "buckets": buckets}
    except Exception:
        out["inventory"] = None

    sev = case({"High": 0, "Medium": 1, "Low": 2}, value=Anomaly.severity, else_=3)
    names = items.set_index("item")["name"].to_dict()
    snames = stores.set_index("store")["name"].to_dict()
    out["attention"] = [{"id": a.id, "alert_id": f"ALT-{a.id:04d}", "type": a.anomaly_type, "severity": a.severity, "amount": round(a.amount),
                         "store": snames.get(a.store), "item": names.get(a.item), "explanation": a.explanation, "date": a.date.isoformat()}
                        for a in db.scalars(select(Anomaly).where(Anomaly.status.in_(["Open", "In Review"])).order_by(sev, Anomaly.amount.desc()).limit(3))]
    out["open_alerts"] = db.scalar(select(func.count()).where(Anomaly.status.in_(["Open", "In Review"]))) or 0
    out["high_exposure"] = round(float(db.scalar(select(func.coalesce(func.sum(Anomaly.amount), 0)).where(Anomaly.status.in_(["Open", "In Review"]), Anomaly.severity == "High")) or 0))
    risky = db.scalars(select(Recommendation).where(Recommendation.status == "Pending", Recommendation.kind == "reorder")).all()
    out["stockout_risk"] = {"series": sum(1 for r in risky if (r.payload or {}).get("runout_days", 99) < 5), "reorders": len(risky)}
    top = db.scalars(select(Recommendation).where(Recommendation.status == "Pending").order_by(Recommendation.impact_inr.desc()).limit(3)).all()
    out["recommendations"] = [{"id": r.id, "kind": r.kind, "title": r.title, "detail": r.detail, "impact_inr": round(r.impact_inr), "impact_label": r.impact_label, "confidence": r.confidence} for r in top]
    out["pending_recs"] = db.scalar(select(func.count()).where(Recommendation.status == "Pending")) or 0
    return out


@router.get("/search")
def search(q: str = Query("", max_length=60), db: Session = Depends(tables)) -> dict:
    q = q.strip().lower()
    if len(q) < 2:
        return {"results": []}
    base = settings.data_dir / "processed"
    items, stores = _read(base / "items.csv", pd.read_csv), _read(base / "stores.csv", pd.read_csv)
    res = [{"type": "Page", "label": n, "path": p} for n, p in NAV_PAGES if q in n.lower()]
    if items is not None:
        m = items[items["name"].str.lower().str.contains(q, regex=False) | items["sku_code"].str.lower().str.contains(q, regex=False)].head(5)
        res += [{"type": "Product", "label": f"{r.sku_code} · {r.name}", "path": f"/forecasting?item={r.item}"} for r in m.itertuples()]
    if stores is not None:
        m = stores[stores["name"].str.lower().str.contains(q, regex=False) | stores["city"].str.lower().str.contains(q, regex=False)].head(4)
        res += [{"type": "Store", "label": r.name, "path": f"/forecasting?store={r.store}"} for r in m.itertuples()]
    if q.startswith("alt"):
        digits = "".join(c for c in q if c.isdigit())
        if digits:
            a = db.get(Anomaly, int(digits))
            if a:
                res.append({"type": "Alert", "label": f"ALT-{a.id:04d} · {a.anomaly_type.replace('_', ' ')}", "path": f"/risk?alert={a.id}"})
    return {"results": res[:12]}
