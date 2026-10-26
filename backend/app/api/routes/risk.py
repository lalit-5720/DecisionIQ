import numpy as np
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.auth.deps import require
from app.core.config import settings
from app.db.models import Anomaly
from app.db.session import get_db, get_engine
from app.platform import audit, config_store
from app.risk import scan

router = APIRouter(prefix="/risk", tags=["risk"])

STATUSES = ["Open", "In Review", "Resolved", "False Positive"]
SEVERITIES = ["High", "Medium", "Low"]
SEV_ORDER = case({"High": 0, "Medium": 1, "Low": 2}, value=Anomaly.severity, else_=3)


def ensure_table(db: Session = Depends(get_db)) -> Session:
    Anomaly.__table__.create(get_engine(), checkfirst=True)
    return db


def _names():
    base = settings.data_dir / "processed"
    stores = pd.read_csv(base / "stores.csv").set_index("store")["name"].to_dict() if (base / "stores.csv").exists() else {}
    items = pd.read_csv(base / "items.csv").set_index("item")["name"].to_dict() if (base / "items.csv").exists() else {}
    return stores, items


def _alert(a: Anomaly, stores: dict, items: dict) -> dict:
    return {
        "id": a.id, "alert_id": f"ALT-{a.id:04d}", "type": a.anomaly_type, "type_label": scan.TYPE_LABELS.get(a.anomaly_type, a.anomaly_type),
        "store": a.store, "store_name": stores.get(a.store, f"Store {a.store}"),
        "item": a.item, "item_name": items.get(a.item) if a.item else None,
        "date": a.date.isoformat(), "end_date": a.end_date.isoformat() if a.end_date else None,
        "amount": round(a.amount, 2), "score": round(a.score, 3), "severity": a.severity, "status": a.status,
        "assignee": a.assignee, "explanation": a.explanation,
    }


@router.get("/summary")
def summary(db: Session = Depends(ensure_table)) -> dict:
    open_q = Anomaly.status.in_(["Open", "In Review"])
    n_open = db.scalar(select(func.count()).where(open_q)) or 0
    high = db.execute(select(func.count(), func.coalesce(func.sum(Anomaly.amount), 0)).where(open_q, Anomaly.severity == "High")).one()
    by_type = dict(db.execute(select(Anomaly.anomaly_type, func.count()).where(open_q).group_by(Anomaly.anomaly_type)).all())
    m = scan.read_metrics()
    return {
        "open_alerts": n_open, "high_open": high[0], "high_exposure": round(float(high[1]), 2),
        "open_by_type": by_type, "total_alerts": db.scalar(select(func.count(Anomaly.id))) or 0,
        "metrics": m, "scanned": m is not None,
    }


@router.get("/alerts")
def alerts(
    status: str | None = None, severity: str | None = None, type: str | None = None, store: int | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), db: Session = Depends(ensure_table),
) -> dict:
    q = select(Anomaly)
    if status == "unresolved":
        q = q.where(Anomaly.status.in_(["Open", "In Review"]))
    elif status:
        q = q.where(Anomaly.status == status)
    if severity:
        q = q.where(Anomaly.severity == severity)
    if type:
        q = q.where(Anomaly.anomaly_type == type)
    if store:
        q = q.where(Anomaly.store == store)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(SEV_ORDER, Anomaly.score.desc(), Anomaly.date.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    stores, items = _names()
    return {"total": total, "page": page, "page_size": page_size, "alerts": [_alert(a, stores, items) for a in rows]}


@router.get("/timeline")
def timeline(db: Session = Depends(ensure_table)) -> list[dict]:
    rows = db.execute(select(Anomaly.id, Anomaly.date, Anomaly.amount, Anomaly.severity, Anomaly.status, Anomaly.anomaly_type)).all()
    return [{"id": r.id, "date": r.date.isoformat(), "amount": round(r.amount, 2), "severity": r.severity, "status": r.status, "type": r.anomaly_type} for r in rows]


def _series_context(a: Anomaly) -> dict:
    """Distribution + surrounding days of the flagged series, read from the scan's billed.parquet."""
    p = scan.risk_dir() / "billed.parquet"
    if a.item is None or not p.exists():
        return {}
    df = pd.read_parquet(p, filters=[("store", "==", a.store), ("item", "==", a.item)]).sort_values("date")
    ev = a.evidence or {}
    counts, edges = np.histogram(df["units_billed"], bins=14)
    lo, hi = pd.Timestamp(a.date) - pd.Timedelta(days=2), pd.Timestamp(a.end_date or a.date) + pd.Timedelta(days=1)
    win = df[(df["date"] >= lo) & (df["date"] <= hi)]
    return {
        "distribution": {"edges": [round(float(e), 1) for e in edges], "counts": counts.tolist(),
                         "median": float(df["units_billed"].median()), "value": ev.get("units_billed")},
        "window": [
            {"date": r.date.strftime("%d %b %Y"), "units_billed": float(r.units_billed), "expected": float(r.expected),
             "net_price": float(r.net_price), "flagged": bool(r.flag_Ensemble)}
            for r in win.itertuples()
        ],
    }


@router.get("/alerts/{alert_id}")
def alert_detail(alert_id: int, db: Session = Depends(ensure_table)) -> dict:
    a = db.get(Anomaly, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    stores, items = _names()
    return {**_alert(a, stores, items), "evidence": a.evidence, **_series_context(a)}


class AlertUpdate(BaseModel):
    status: str | None = None
    assignee: str | None = None


@router.patch("/alerts/{alert_id}", dependencies=[Depends(require("approve_actions"))])
def update_alert(alert_id: int, body: AlertUpdate, db: Session = Depends(ensure_table)) -> dict:
    a = db.get(Anomaly, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    if body.status is not None:
        if body.status not in STATUSES:
            raise HTTPException(422, f"status must be one of {STATUSES}")
        audit.record(f"Alert ALT-{a.id:04d} status {a.status} -> {body.status}", "risk", f"alert #{a.id}")
        a.status = body.status
    if body.assignee is not None:
        a.assignee = body.assignee or None
    db.commit()
    stores, items = _names()
    return _alert(a, stores, items)


class ScanParams(BaseModel):
    contamination: float | None = Field(None, gt=0, le=0.05)  # None = value from Settings
    z_threshold: float | None = Field(None, ge=1.5, le=6)


@router.post("/scan", status_code=202, dependencies=[Depends(require("run_analysis"))])
def start_scan(background: BackgroundTasks, params: ScanParams | None = None) -> dict:
    if scan.is_running():
        raise HTTPException(409, "Scan already running")
    if not (settings.data_dir / "processed" / "sales.csv").exists():
        raise HTTPException(409, "Billed data missing - run ml/prepare_data.py")
    p = params or ScanParams()
    cfg = config_store.get_all()["risk"]
    contamination, z = p.contamination or cfg["contamination"], p.z_threshold or cfg["z_threshold"]
    audit.record(f"Started risk scan (z={z}, contamination={contamination})", "risk")
    background.add_task(scan.run_scan, contamination, z)
    return {"status": "started"}


@router.get("/scan-status")
def scan_status() -> dict:
    s = scan.read_state()
    s["running"] = scan.is_running()
    return s
