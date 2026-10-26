from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import permissions
from app.auth.deps import get_current_user, require
from app.db.models import User
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Setting
from app.db.session import get_db, get_engine
from app.platform import audit, config_store

router = APIRouter(tags=["platform"])


def tables(db: Session = Depends(get_db)) -> Session:
    for t in (AuditLog, Setting):
        t.__table__.create(get_engine(), checkfirst=True)
    return db


@router.get("/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(tables)) -> dict:
    return {"config": config_store.get_all(db), "applied": config_store.APPLIED, "rbac": permissions.matrix(),
            "section_caps": permissions.SETTINGS_SECTION_CAP,
            "user": {"name": user.full_name, "role": user.role, "tier": "Enterprise Store Tier", "scope": "All 10 stores",
                     "capabilities": sorted(permissions.ROLE_CAPS.get(user.role, set()))}}


@router.put("/settings/{section}")
def put_settings(section: str, patch: dict, user: User = Depends(get_current_user), db: Session = Depends(tables)) -> dict:
    if section not in config_store.SECTIONS:
        raise HTTPException(404, f"Unknown section. Use one of {list(config_store.SECTIONS)}")
    cap = permissions.SETTINGS_SECTION_CAP[section]
    if not permissions.can(user.role, cap):
        raise HTTPException(403, f"Your role ({user.role}) is not permitted to: {permissions.CAPABILITIES[cap]}")
    before = config_store.get_all(db)[section]
    try:
        saved = config_store.save_section(db, section, patch)
    except ValueError as e:
        raise HTTPException(422, str(e).splitlines()[0] if str(e) else "Invalid value")
    changed = {k: (before[k], v) for k, v in saved.items() if before.get(k) != v}
    for k, (a, b) in changed.items():
        audit.record(f"Updated setting {section}.{k}: {a} -> {b}", "settings", section)
    return {"section": section, "config": saved, "changed": list(changed)}


@router.post("/settings/reset", dependencies=[Depends(require("modify_thresholds"))])
def reset_settings(db: Session = Depends(tables)) -> dict:
    config_store.reset(db)
    audit.record("Reset all settings to system defaults", "settings")
    return {"config": config_store.get_all(db)}


@router.get("/audit", dependencies=[Depends(require("view_audit"))])
def audit_log(user: str | None = None, category: str | None = None, days: int = Query(7, ge=1, le=3650),
              page: int = Query(1, ge=1), page_size: int = Query(8, ge=1, le=100), db: Session = Depends(tables)) -> dict:
    from datetime import datetime, timedelta

    q = select(AuditLog).where(AuditLog.timestamp >= datetime.utcnow() - timedelta(days=days))
    if user:
        q = q.where(AuditLog.user_name == user)
    if category:
        q = q.where(AuditLog.category == category)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size,
            "users": [u for (u,) in db.execute(select(AuditLog.user_name).distinct())],
            "categories": [c for (c,) in db.execute(select(AuditLog.category).distinct()) if c],
            "entries": [{"id": e.id, "timestamp": e.timestamp.isoformat(timespec="seconds"), "user": e.user_name, "role": e.role, "action": e.action,
                         "category": e.category, "entity": e.entity, "ip": e.ip_address, "hash": e.entry_hash[:12]} for e in rows]}


@router.get("/audit/verify", dependencies=[Depends(require("view_audit"))])
def audit_verify(db: Session = Depends(tables)) -> dict:
    return audit.verify(db)
