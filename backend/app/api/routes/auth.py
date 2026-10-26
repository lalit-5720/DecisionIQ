import time
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import permissions, security
from app.auth.deps import get_current_user, require
from app.core.config import settings
from app.db.models import User
from app.db.session import get_db, get_engine
from app.platform import audit

router = APIRouter(tags=["auth"])

MAX_FAILURES, WINDOW_S = 5, 600
_failures: dict[str, list[float]] = defaultdict(list)
_DUMMY_HASH = security.hash_password("not-a-real-password")  # equalises timing for unknown emails


def tables(db: Session = Depends(get_db)) -> Session:
    User.__table__.create(get_engine(), checkfirst=True)
    return db


def user_json(u: User) -> dict:
    return {"id": u.id, "name": u.full_name, "email": u.email, "role": u.role, "active": u.active,
            "capabilities": sorted(permissions.ROLE_CAPS.get(u.role, set())),
            "last_login": u.last_login.isoformat(timespec="seconds") if u.last_login else None}


class LoginIn(BaseModel):
    email: str = Field(max_length=150)
    password: str = Field(max_length=200)
    remember: bool = False


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(tables)) -> dict:
    email = body.email.strip().lower()
    now = time.time()
    _failures[email] = [t for t in _failures[email] if now - t < WINDOW_S]
    if len(_failures[email]) >= MAX_FAILURES:
        audit.record(f"Sign-in blocked (too many failures) for {email}", "auth", user=("Unknown", "-"))
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.", headers={"Retry-After": str(WINDOW_S)})
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    ok = security.verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not (user and user.active and ok):
        _failures[email].append(now)
        audit.record(f"Failed sign-in for {email}", "auth", user=("Unknown", "-"))
        raise HTTPException(401, "Invalid email or password")
    _failures.pop(email, None)
    user.last_login = datetime.utcnow()
    db.commit()
    token, ttl = security.create_token(user.id, user.role, body.remember)
    audit.record("Signed in", "auth", f"user #{user.id}", user=(user.full_name, user.role))
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl, "user": user_json(user)}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return user_json(user)


@router.post("/auth/logout")
def logout(user: User = Depends(get_current_user)) -> dict:
    audit.record("Signed out", "auth", f"user #{user.id}")
    return {"status": "signed out"}  # tokens are stateless: the client discards its copy


@router.get("/auth/personas")
def personas(db: Session = Depends(tables)) -> dict:
    """Demo convenience for the login screen's role tabs. Disabled with DIQ_DEMO_MODE=false."""
    if not settings.demo_mode:
        return {"personas": []}
    out = []
    for role in permissions.ROLES:
        u = db.scalar(select(User).where(User.role == role, User.active.is_(True)).order_by(User.id).limit(1))
        if u:
            out.append({"role": role, "name": u.full_name, "email": u.email})
    return {"personas": out}


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=security.MIN_PASSWORD_LEN, max_length=200)


@router.post("/auth/change-password")
def change_password(body: PasswordIn, user: User = Depends(get_current_user), db: Session = Depends(tables)) -> dict:
    if not security.verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "Current password is incorrect")
    user.password_hash = security.hash_password(body.new_password)
    db.commit()
    audit.record("Changed own password", "auth", f"user #{user.id}")
    return {"status": "password changed"}


# ------------------------------------------------------------------ user administration (Admin only)
@router.get("/users")
def list_users(_: User = Depends(require("manage_users")), db: Session = Depends(tables)) -> dict:
    return {"users": [user_json(u) for u in db.scalars(select(User).order_by(User.id))], "roles": permissions.ROLES}


class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=150)
    full_name: str = Field(min_length=2, max_length=100)
    role: str
    password: str = Field(min_length=security.MIN_PASSWORD_LEN, max_length=200)


@router.post("/users", status_code=201)
def create_user(body: UserIn, admin: User = Depends(require("manage_users")), db: Session = Depends(tables)) -> dict:
    if body.role not in permissions.ROLES:
        raise HTTPException(422, f"role must be one of {permissions.ROLES}")
    if db.scalar(select(User.id).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "A user with this email already exists")
    u = User(email=body.email.strip().lower(), full_name=body.full_name.strip(), role=body.role, password_hash=security.hash_password(body.password))
    db.add(u)
    db.commit()
    audit.record(f"Created user {u.email} with role {u.role}", "users", f"user #{u.id}")
    return user_json(u)


class UserPatch(BaseModel):
    role: str | None = None
    active: bool | None = None
    password: str | None = Field(None, min_length=security.MIN_PASSWORD_LEN, max_length=200)


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, admin: User = Depends(require("manage_users")), db: Session = Depends(tables)) -> dict:
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if body.role is not None and body.role not in permissions.ROLES:
        raise HTTPException(422, f"role must be one of {permissions.ROLES}")
    admins = db.scalar(select(func.count()).where(User.role == "Admin", User.active.is_(True))) or 0
    losing_admin = u.role == "Admin" and u.active and ((body.role and body.role != "Admin") or body.active is False)
    if losing_admin and admins <= 1:
        raise HTTPException(409, "At least one active Admin must remain")
    if u.id == admin.id and body.active is False:
        raise HTTPException(409, "You cannot deactivate your own account")
    if body.role is not None and body.role != u.role:
        audit.record(f"Changed role of {u.email}: {u.role} -> {body.role}", "users", f"user #{u.id}")
        u.role = body.role
    if body.active is not None and body.active != u.active:
        audit.record(f"{'Reactivated' if body.active else 'Deactivated'} user {u.email}", "users", f"user #{u.id}")
        u.active = body.active
    if body.password:
        u.password_hash = security.hash_password(body.password)
        audit.record(f"Reset password of {u.email}", "users", f"user #{u.id}")
    db.commit()
    return user_json(u)
