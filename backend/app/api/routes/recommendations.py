import csv
import io
from collections import Counter

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require
from app.core.config import settings
from app.db.models import Recommendation
from app.db.session import get_db, get_engine
from app.platform import audit, config_store
from app.recommend import engine, service

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

STATUSES = ["Pending", "Approved", "Dismissed"]
KIND_LABELS = {"reorder": "Inventory Reorder", "transfer": "Inter-store Transfer", "markdown": "Dynamic Markdown", "budget": "Budget Reallocation"}


def ensure_table(db: Session = Depends(get_db)) -> Session:
    Recommendation.__table__.create(get_engine(), checkfirst=True)
    return db


def _names() -> dict:
    p = settings.data_dir / "processed" / "stores.csv"
    return pd.read_csv(p).set_index("store")["name"].to_dict() if p.exists() else {}


def _rec(r: Recommendation, stores: dict) -> dict:
    return {
        "id": r.id, "kind": r.kind, "kind_label": KIND_LABELS.get(r.kind, r.kind), "title": r.title, "detail": r.detail,
        "store": r.store, "store_name": stores.get(r.store), "store_to": r.store_to, "store_to_name": stores.get(r.store_to),
        "item": r.item, "category": r.category, "sku": (r.payload or {}).get("sku"),
        "impact_inr": round(r.impact_inr, 2), "impact_label": r.impact_label, "confidence": r.confidence,
        "status": r.status, "payload": r.payload,
        "decided_at": r.decided_at.isoformat(timespec="seconds") if r.decided_at else None,
    }


@router.get("/summary")
def summary(db: Session = Depends(ensure_table)) -> dict:
    rows = db.execute(select(Recommendation.status, Recommendation.kind, Recommendation.impact_inr, Recommendation.confidence,
                             Recommendation.store, Recommendation.payload)).all()
    by_status = Counter(r.status for r in rows)
    pending = [r for r in rows if r.status == "Pending"]
    decided = by_status["Approved"] + by_status["Dismissed"]
    risky = [r for r in pending if r.kind == "reorder" and (r.payload or {}).get("runout_days", 99) < 5]
    return {
        "counts": dict(by_status), "total": len(rows), "by_kind": dict(Counter(r.kind for r in pending)),
        "pending_value": round(sum(r.impact_inr for r in pending), 2),
        "approved_value": round(sum(r.impact_inr for r in rows if r.status == "Approved"), 2),
        "avg_confidence": round(sum(r.confidence for r in pending) / len(pending), 2) if pending else None,
        "execution_rate": round(by_status["Approved"] / decided * 100) if decided else None,
        "stockout_risk_series": len(risky), "stockout_risk_stores": len({r.store for r in risky}),
    }


@router.get("")
def list_recs(kind: str | None = None, status: str | None = "Pending", sort: str = "impact", db: Session = Depends(ensure_table)) -> dict:
    q = select(Recommendation)
    if kind:
        q = q.where(Recommendation.kind == kind)
    if status:
        q = q.where(Recommendation.status == status)
    order = Recommendation.confidence.desc() if sort == "confidence" else Recommendation.impact_inr.desc()
    stores = _names()
    return {"recommendations": [_rec(r, stores) for r in db.scalars(q.order_by(order))]}


@router.post("/generate", dependencies=[Depends(require("approve_actions"))])
def generate() -> dict:
    base = settings.data_dir / "processed"
    if not (base / "models" / "forecasts.parquet").exists():
        raise HTTPException(409, "Train the forecasting models first")
    if not (base / "sales.csv").exists():
        raise HTTPException(409, "Inventory data missing - run ml/prepare_data.py")
    inv = config_store.get_all()["inventory"]
    params = engine.Params(lead_time=inv["lead_time_days"], service_z=inv["service_level_z"], overstock_cover_days=inv["overstock_cover_days"],
                           target_cover_days=inv["target_cover_days"], max_discount=inv["max_discount_pct"] / 100)
    res = service.generate_and_store(params)
    audit.record(f"Generated {res['generated']} recommendations", "recommendation")
    return res


class RecUpdate(BaseModel):
    status: str | None = None
    quantity: int | None = None
    discount_pct: float | None = None


@router.patch("/{rec_id}", dependencies=[Depends(require("approve_actions"))])
def update(rec_id: int, body: RecUpdate, db: Session = Depends(ensure_table)) -> dict:
    r = db.get(Recommendation, rec_id)
    if not r:
        raise HTTPException(404, "Recommendation not found")
    if body.status is not None and body.status not in STATUSES:
        raise HTTPException(422, f"status must be one of {STATUSES}")
    if body.quantity is not None and (r.kind not in ("reorder", "transfer") or body.quantity < 1):
        raise HTTPException(422, "quantity applies to reorder/transfer recommendations and must be >= 1")
    if body.discount_pct is not None and (r.kind != "markdown" or not 1 <= body.discount_pct <= 40):
        raise HTTPException(422, "discount_pct applies to markdown recommendations (1-40)")
    if body.quantity is not None or body.discount_pct is not None:
        d = engine.edit({"kind": r.kind, "title": r.title, "impact_inr": r.impact_inr, "payload": r.payload}, body.quantity, body.discount_pct)
        r.title, r.impact_inr, r.payload = d["title"], d["impact_inr"], d["payload"]
    if body.status is not None:
        audit.record(f"{body.status}: {r.title}", "recommendation", f"rec #{r.id}")
        service.set_status(db, r, body.status)
    if body.quantity is not None or body.discount_pct is not None:
        audit.record(f"Edited ({'quantity ' + str(body.quantity) if body.quantity else 'discount ' + str(body.discount_pct) + '%'}): {r.title}", "recommendation", f"rec #{r.id}")
    db.commit()
    return _rec(r, _names())


class Bulk(BaseModel):
    ids: list[int]
    status: str


@router.post("/bulk", dependencies=[Depends(require("approve_actions"))])
def bulk(body: Bulk, db: Session = Depends(ensure_table)) -> dict:
    if body.status not in STATUSES:
        raise HTTPException(422, f"status must be one of {STATUSES}")
    rows = db.scalars(select(Recommendation).where(Recommendation.id.in_(body.ids))).all()
    for r in rows:
        service.set_status(db, r, body.status)
    audit.record(f"Bulk {body.status}: {len(rows)} recommendations worth Rs {sum(r.impact_inr for r in rows):,.0f}", "recommendation")
    db.commit()
    return {"updated": len(rows), "value": round(sum(r.impact_inr for r in rows), 2)}


@router.get("/export.csv")
def export_csv(status: str = Query("Pending"), db: Session = Depends(ensure_table)):
    stores = _names()
    rows = db.scalars(select(Recommendation).where(Recommendation.status == status).order_by(Recommendation.impact_inr.desc())).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "type", "title", "from_store", "to_store", "sku", "quantity", "discount_pct", "impact_inr", "impact_basis", "confidence", "status"])
    for r in rows:
        pl = r.payload or {}
        w.writerow([r.id, r.kind, r.title, stores.get(r.store, ""), stores.get(r.store_to, ""), pl.get("sku", ""), pl.get("qty", ""),
                    pl.get("discount_pct", ""), r.impact_inr, r.impact_label, r.confidence, r.status])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=action_plan.csv"})
