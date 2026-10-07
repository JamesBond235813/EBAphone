"""Authentication helpers shared by customer and operations endpoints."""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models import AdminUser, Store, User

load_dotenv()

# A development fallback keeps a fresh checkout runnable.  Deployments should
# always provide a long random JWT_SECRET; main.py warns if the fallback is
# used in a production environment.
DEFAULT_JWT_SECRET = "ebaphone-development-secret-change-me"
JWT_SECRET = os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_ISSUER = os.getenv("JWT_ISSUER", "ebaphone")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "ebaphone-web")
JWT_TTL_HOURS = max(1, int(os.getenv("JWT_TTL_HOURS", "24")))

security = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class Principal:
    """The authenticated actor making a request."""

    kind: Literal["customer", "admin"]
    user: User | AdminUser
    # Scalar snapshots avoid accidental lazy loads after a transaction
    # rollback/commit in a route handler.
    user_id: int
    phone: str | None = None
    role: str | None = None
    store_id: int | None = None


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000).hex()
    return f"pbkdf2_sha256${salt.hex()}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password without raising for malformed legacy hashes."""

    try:
        algorithm, salt_hex, digest = encoded.split("$", 2)
        if algorithm != "pbkdf2_sha256" or len(salt_hex) != 32 or len(digest) != 64:
            return False
        salt = bytes.fromhex(salt_hex)
        check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000).hex()
        return secrets.compare_digest(check, digest)
    except (AttributeError, TypeError, ValueError):
        return False


def token(subject: str, kind: str, role: str | None = None) -> str:
    """Issue a typed JWT with issuer/audience and unique id claims."""

    now = datetime.now(timezone.utc)
    data: dict[str, object] = {
        "sub": str(subject),
        "kind": kind,
        "iat": now,
        "exp": now + timedelta(hours=JWT_TTL_HOURS),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "jti": secrets.token_hex(16),
    }
    if role:
        data["role"] = role
    return jwt.encode(data, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Sign in required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        data = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            options={"require": ["sub", "kind", "iat", "exp", "iss", "aud", "jti"]},
        )
    except (jwt.PyJWTError, TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if (
        data.get("kind") not in {"customer", "admin"}
        or not isinstance(data.get("sub"), str)
        or not isinstance(data.get("jti"), str)
        or not data["jti"]
    ):
        raise HTTPException(status_code=401, detail="Invalid token claims")
    return data


async def authenticate(credentials: HTTPAuthorizationCredentials | None, db: AsyncSession) -> Principal:
    data = _decode(credentials)
    try:
        subject_id = int(data["sub"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject")

    if data["kind"] == "customer":
        user = await db.get(User, subject_id)
        if not user or not user.active:
            raise HTTPException(status_code=401, detail="Customer account unavailable")
        return Principal(kind="customer", user=user, user_id=user.id, phone=user.phone)

    admin = await db.get(AdminUser, subject_id)
    if not admin or not admin.active:
        raise HTTPException(status_code=401, detail="Admin user unavailable")
    # A store-scoped account must lose access as soon as its assigned store is
    # paused or removed.  Checking this on every authenticated request also
    # invalidates already-issued JWTs instead of waiting for token expiry.
    if admin.store_id is not None and admin.role != "super_admin":
        store = await db.get(Store, admin.store_id)
        if not store or not store.active:
            raise HTTPException(status_code=401, detail="Assigned store is inactive")
    # The database role is authoritative; stale JWT role claims are ignored.
    return Principal(kind="admin", user=admin, user_id=admin.id, role=admin.role, store_id=admin.store_id)


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    principal = await authenticate(credentials, db)
    if principal.kind != "customer":
        raise HTTPException(status_code=403, detail="Customer token required")
    return principal.user  # type: ignore[return-value]


async def current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    principal = await authenticate(credentials, db)
    if principal.kind != "admin":
        raise HTTPException(status_code=403, detail="Admin token required")
    return principal.user  # type: ignore[return-value]


async def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    return await authenticate(credentials, db)


async def optional_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Principal | None:
    """Return an actor when a bearer token is supplied, otherwise ``None``.

    Invalid credentials are rejected rather than silently downgraded to a
    guest request.
    """

    if not credentials:
        return None
    return await authenticate(credentials, db)
