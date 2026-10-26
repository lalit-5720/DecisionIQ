"""Generate recommendations and persist them (keeping managers' earlier decisions across regenerations)."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Recommendation
from app.db.session import get_engine
from app.recommend import engine


def rec_key(r: dict) -> str:
    return "|".join(str(r.get(k) or "") for k in ("kind", "store", "store_to", "item", "category"))


def generate_and_store(params: engine.Params | None = None) -> dict:
    recs = engine.generate(p=params)
    db_engine = get_engine()
    Recommendation.__table__.create(db_engine, checkfirst=True)
    with Session(db_engine) as db:
        decided = {r.key: r for r in db.scalars(select(Recommendation)) if r.status != "Pending"}
        db.query(Recommendation).delete()
        kept = 0
        for r in recs:
            k = rec_key(r)
            prev = decided.get(k)
            row = Recommendation(key=k, **r)
            if prev:  # keep the earlier decision and any edits the manager made
                row.status, row.decided_at, row.payload = prev.status, prev.decided_at, prev.payload
                row.impact_inr, row.title = prev.impact_inr, prev.title
                kept += 1
            db.add(row)
        db.commit()
    return {"generated": len(recs), "decisions_kept": kept}


def set_status(db: Session, rec: Recommendation, status: str) -> None:
    rec.status = status
    rec.decided_at = None if status == "Pending" else datetime.utcnow()
