"""Demo users created on first start when the users table is empty.

The shared demo password comes from DIQ_DEMO_PASSWORD (default below). It is for local demos only -
set the variable, or create real users from Settings, before exposing the app anywhere.
"""
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.db.models import User
from app.db.session import get_engine

DEMO_PASSWORD_DEFAULT = "DecisionIQ@2026"
DEMO_USERS = [
    ("rajesh.nair@sunrisemart.in", "Rajesh Nair", "Admin"),
    ("priya.sharma@sunrisemart.in", "Priya Sharma", "Manager"),
    ("anil.kumar@sunrisemart.in", "Anil Kumar", "Analyst"),
]


def demo_password() -> str:
    return os.environ.get("DIQ_DEMO_PASSWORD", DEMO_PASSWORD_DEFAULT)


def ensure_users() -> int:
    """Create the users table and, if it is empty, the three demo accounts. Returns accounts created."""
    engine = get_engine()
    User.__table__.create(engine, checkfirst=True)
    with Session(engine) as db:
        if db.scalar(select(User.id).limit(1)) is not None:
            return 0
        pw = hash_password(demo_password())
        for email, name, role in DEMO_USERS:
            db.add(User(email=email, full_name=name, role=role, password_hash=pw))
        db.commit()
        return len(DEMO_USERS)
