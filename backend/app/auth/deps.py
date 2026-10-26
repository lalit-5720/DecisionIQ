from contextvars import ContextVar

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import permissions, security
from app.db.models import User
from app.db.session import get_db, get_engine

bearer = HTTPBearer(auto_error=False)
# Who is acting / from where, for the audit trail (set per request by get_current_user)
request_user: ContextVar[tuple[str, str] | None] = ContextVar("request_user", default=None)
request_ip: ContextVar[str | None] = ContextVar("request_ip", default=None)


async def get_current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    try:
        claims = security.decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired or invalid - please sign in again", headers={"WWW-Authenticate": "Bearer"})
    User.__table__.create(get_engine(), checkfirst=True)
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.active:
        raise unauthorized
    request_user.set((user.full_name, user.role))
    request_ip.set(request.client.host if request.client else None)
    return user


def require(capability: str):
    """Dependency factory: 403 unless the signed-in user's role grants `capability`."""
    if capability not in permissions.CAPABILITIES:
        raise ValueError(f"unknown capability {capability}")

    async def checker(user: User = Depends(get_current_user)) -> User:
        if not permissions.can(user.role, capability):
            raise HTTPException(403, f"Your role ({user.role}) is not permitted to: {permissions.CAPABILITIES[capability]}")
        return user

    return checker
