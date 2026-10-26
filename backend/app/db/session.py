from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings

_engines: dict = {}


def get_engine():
    """Engine for the currently configured database_url (cached per URL so tests can switch databases)."""
    url = settings.database_url
    if url not in _engines:
        _engines[url] = create_engine(url, pool_pre_ping=True)
    return _engines[url]


def get_db():
    with Session(get_engine(), autoflush=False) as db:
        yield db
