"""Single-password authentication.

The password comes from ``COLLANDER_PASSWORD`` if set, otherwise it is chosen on
the first-run setup screen and stored as a salted scrypt hash. Sessions are signed
cookies; changing the password invalidates existing sessions.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import deque

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .services.settings_store import get_value, set_value

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_hash(password: str, stored: str) -> bool:
    try:
        _algo, n, r, p, salt, digest = stored.split("$")
        calc = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(calc.hex(), digest)
    except (ValueError, TypeError):
        return False


def password_from_env() -> bool:
    return bool(get_settings().password)


def setup_required(db: Session) -> bool:
    return not password_from_env() and not get_value(db, "password_hash")


def check_password(db: Session, password: str) -> bool:
    env_pw = get_settings().password
    if env_pw:
        return hmac.compare_digest(password.encode(), env_pw.encode())
    stored = get_value(db, "password_hash")
    return bool(stored) and verify_hash(password, stored)


def session_version(db: Session) -> str:
    v = get_value(db, "session_version")
    if not v:
        v = secrets.token_hex(8)
        set_value(db, "session_version", v)
        db.commit()
    return v


def set_password(db: Session, password: str) -> None:
    set_value(db, "password_hash", hash_password(password))
    set_value(db, "session_version", secrets.token_hex(8))
    db.commit()


def login_session(request: Request, db: Session) -> None:
    request.session.clear()
    request.session["v"] = session_version(db)
    request.session["t"] = int(time.time())


def is_authenticated(request: Request, db: Session) -> bool:
    v = request.session.get("v")
    t = request.session.get("t", 0)
    if not v or not hmac.compare_digest(str(v), session_version(db)):
        return False
    return time.time() - t < get_settings().session_days * 86400


def require_auth(request: Request, db: Session = Depends(get_db)) -> None:
    if not is_authenticated(request, db):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")


# Very small brute-force throttle: at most 10 failed attempts per minute.
_failures: deque[float] = deque()


def throttle_check() -> None:
    now = time.time()
    while _failures and now - _failures[0] > 60:
        _failures.popleft()
    if len(_failures) >= 10:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts; wait a minute.")


def record_failure() -> None:
    _failures.append(time.time())
