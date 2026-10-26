"""Password hashing (scrypt) and JWT helpers. No credentials are ever logged or returned."""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

ALGORITHM = "HS256"
MIN_PASSWORD_LEN = 10


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), digest)
    except (ValueError, TypeError):
        return False


def jwt_secret() -> str:
    """DIQ_JWT_SECRET if set, otherwise a random secret generated once and kept in data/.jwt_secret (git-ignored)."""
    if settings.jwt_secret:
        return settings.jwt_secret
    path = settings.data_dir / ".jwt_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()


def create_token(user_id: int, role: str, remember: bool = False) -> tuple[str, int]:
    ttl = timedelta(days=30) if remember else timedelta(hours=settings.token_hours)
    now = datetime.now(timezone.utc)
    token = jwt.encode({"sub": str(user_id), "role": role, "iat": now, "exp": now + ttl}, jwt_secret(), algorithm=ALGORITHM)
    return token, int(ttl.total_seconds())


def decode_token(token: str) -> dict:
    return jwt.decode(token, jwt_secret(), algorithms=[ALGORITHM])
