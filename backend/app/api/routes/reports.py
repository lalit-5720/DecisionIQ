import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Anomaly, Recommendation, Report
from app.db.session import get_db, get_engine
from app.platform import audit
from app.reports import builders

router = APIRouter(prefix="/reports", tags=["reports"])


def tables(db: Session = Depends(get_db)) -> Session:
    for t in (Report, Anomaly, Recommendation):
        t.__table__.create(get_engine(), checkfirst=True)
    return db


def _row(r: Report) -> dict:
    return {"id": r.id, "title": r.title, "template": r.template, "format": r.format, "scope": r.scope, "size_bytes": r.size_bytes,
            "sha256": r.sha256, "status": r.status, "generated_by": r.generated_by, "created_at": r.created_at.isoformat(timespec="seconds")}


@router.get("/templates")
def templates(db: Session = Depends(tables)) -> dict:
    out = []
    for key, t in builders.TEMPLATES.items():
        last = db.scalars(select(Report).where(Report.template == key).order_by(Report.created_at.desc()).limit(1)).first()
        out.append({"key": key, **t, "last_run": last.created_at.isoformat(timespec="seconds") if last else None,
                    "runs": db.scalar(select(func.count()).where(Report.template == key)) or 0})
    return {"templates": out, "formats": list(builders.WRITERS)}


class GenerateIn(BaseModel):
    template: Literal["forecast_summary", "risk_dossier", "replenishment_plan"]
    format: Literal["pdf", "xlsx", "json"] = "pdf"


@router.post("/generate", status_code=201)
def generate(body: GenerateIn, db: Session = Depends(tables)) -> dict:
    meta = builders.TEMPLATES[body.template]
    try:
        content = builders.COLLECTORS[body.template](db)
    except FileNotFoundError as e:
        raise HTTPException(409, f"Required data is missing - run the pipeline and train models first ({e.filename or e})")
    writer, _ = builders.WRITERS[body.format]
    data = writer(content)
    out_dir = settings.data_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{stamp}_{body.template}.{body.format}"
    path.write_bytes(data)
    r = Report(title=f"{meta['title']}", template=body.template, format=body.format, scope="All stores", file_path=str(path),
               size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), status="Ready", generated_by=audit.current_user()[0])
    db.add(r)
    db.commit()
    audit.record(f"Generated report: {meta['title']} ({body.format.upper()}, {len(data) // 1024} KB)", "report", f"report #{r.id}")
    return _row(r)


@router.get("")
def ledger(template: str | None = None, days: int = Query(30, ge=1, le=3650), q: str | None = None,
           page: int = Query(1, ge=1), page_size: int = Query(8, ge=1, le=50), db: Session = Depends(tables)) -> dict:
    stmt = select(Report).where(Report.created_at >= datetime.utcnow() - timedelta(days=days))
    if template:
        stmt = stmt.where(Report.template == template)
    if q:
        stmt = stmt.where(Report.title.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Report.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    used = db.scalar(select(func.coalesce(func.sum(Report.size_bytes), 0))) or 0
    return {"total": total, "page": page, "page_size": page_size, "storage_bytes": int(used), "reports": [_row(r) for r in rows]}


@router.get("/{report_id}/download")
def download(report_id: int, db: Session = Depends(tables)):
    r = db.get(Report, report_id)
    if not r or not r.file_path or not Path(r.file_path).exists():
        raise HTTPException(404, "Report file not found")
    audit.record(f"Downloaded report #{r.id} ({r.title})", "report", f"report #{r.id}")
    return FileResponse(r.file_path, media_type=builders.WRITERS[r.format][1], filename=Path(r.file_path).name)
