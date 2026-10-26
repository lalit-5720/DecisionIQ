"""Hash-chained audit trail. `record` never raises: auditing must not break the action it describes."""
import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog
from app.db.session import get_engine

GENESIS = "0" * 64
SYSTEM_USER = ("System", "Admin")


def current_user() -> tuple[str, str]:
    """The signed-in user of the current request (set by app.auth.deps), or the system account for background work."""
    from app.auth.deps import request_user

    return request_user.get() or SYSTEM_USER


def _hash(prev: str, ts: datetime, user: str, role: str, action: str, entity: str | None, ip: str | None) -> str:
    return hashlib.sha256("|".join([prev, ts.isoformat(), user, role, action, entity or "", ip or ""]).encode()).hexdigest()


def record(action: str, category: str = "system", entity: str | None = None, user: tuple | None = None, ip: str | None = None) -> None:
    from app.auth.deps import request_ip

    name, role = user or current_user()
    ip = ip or request_ip.get()
    try:
        engine = get_engine()
        AuditLog.__table__.create(engine, checkfirst=True)
        with Session(engine) as db:
            last = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).first()
            prev = last.entry_hash if last else GENESIS
            ts = datetime.utcnow().replace(microsecond=0)
            action = action[:300]
            db.add(AuditLog(timestamp=ts, user_name=name, role=role, action=action, category=category, entity=entity,
                            ip_address=ip, prev_hash=prev, entry_hash=_hash(prev, ts, name, role, action, entity, ip)))
            db.commit()
    except Exception:  # noqa: BLE001
        pass


def verify(db: Session) -> dict:
    prev, n = GENESIS, 0
    for e in db.scalars(select(AuditLog).order_by(AuditLog.id)):
        n += 1
        if e.prev_hash != prev or e.entry_hash != _hash(prev, e.timestamp, e.user_name, e.role, e.action, e.entity, e.ip_address):
            return {"ok": False, "entries": n, "broken_at": e.id, "head": prev}
        prev = e.entry_hash
    return {"ok": True, "entries": n, "broken_at": None, "head": prev}
