"""
JARVIS API — JWT Authentication Middleware
Provides:
  - Token generation on successful PIN authentication
  - FastAPI dependency for protected route enforcement
  - Token validation and decoding
"""

import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Annotated

# pyrefly: ignore [missing-import]
from fastapi import Depends, HTTPException, status
# pyrefly: ignore [missing-import]
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from core.logger import log, audit_log
import core.config  # noqa: F401  — ensures .env is loaded before JARVIS_JWT_SECRET is read

# ─── Optional JWT ─────────────────────────────────────────────────────────────
try:
    import jwt as pyjwt
    HAS_JWT = True
except ImportError:
    HAS_JWT = False
    log.warning("PyJWT not installed — token auth uses simple token store. Run: pip install PyJWT")


# ─── Config ───────────────────────────────────────────────────────────────────
def _load_or_create_jwt_secret() -> str:
    """
    Use JARVIS_JWT_SECRET if set; otherwise persist a random per-install secret so that
    restarting the backend does not log the owner out. Stored next to the other local
    security material (data/security/, which is git-ignored).
    """
    env_secret = os.environ.get("JARVIS_JWT_SECRET")
    if env_secret:
        return env_secret
    try:
        from core.security import SECURITY_DIR
        secret_file = SECURITY_DIR / ".jwt_secret"
        if secret_file.exists():
            existing = secret_file.read_text(encoding="utf-8").strip()
            if len(existing) >= 32:
                return existing
        new_secret = secrets.token_urlsafe(64)
        secret_file.write_text(new_secret, encoding="utf-8")
        return new_secret
    except Exception as e:
        log.warning(f"Could not persist JWT secret ({e}); using an ephemeral one.")
        return secrets.token_urlsafe(64)


SECRET_KEY    = _load_or_create_jwt_secret()
ALGORITHM     = "HS256"
TOKEN_EXPIRE  = int(os.environ.get("JARVIS_TOKEN_EXPIRE_HOURS", "12"))  # hours

# Simple in-memory token store as fallback when PyJWT is not available
_active_tokens: set[str] = set()
_active_tokens_meta: dict[str, dict] = {}

# HTTP Bearer scheme for FastAPI
_bearer_scheme = HTTPBearer(auto_error=False)


# ─── Token Management ─────────────────────────────────────────────────────────

def create_access_token(subject: str = "owner", session_id: Optional[str] = None) -> tuple[str, int]:
    """
    Generate a signed JWT access token bound to subject and optional session_id.

    Returns:
        (token_string, expires_in_seconds)
    """
    expire_seconds = TOKEN_EXPIRE * 3600
    jti = secrets.token_urlsafe(16)
    sess_id = session_id or f"sess_{jti[:8]}"

    if HAS_JWT:
        expire_dt = datetime.now(timezone.utc) + timedelta(seconds=expire_seconds)
        payload = {
            "sub":  subject,
            "session_id": sess_id,
            "iat":  datetime.now(timezone.utc),
            "exp":  expire_dt,
            "jti":  jti,
        }
        token = pyjwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    else:
        # Fallback: opaque random token
        token = secrets.token_urlsafe(48)
        _active_tokens.add(token)
        _active_tokens_meta[token] = {"sub": subject, "session_id": sess_id, "jti": jti}

    audit_log.info({
        "event":      "TOKEN_ISSUED",
        "subject":    subject,
        "session_id": sess_id,
        "expires_in": expire_seconds,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    })
    return token, expire_seconds


def decode_token(token: str) -> Optional[dict]:
    """
    Validate and decode a JWT token.

    Returns:
        Decoded payload dict, or None if invalid/expired.
    """
    if HAS_JWT:
        try:
            payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except pyjwt.ExpiredSignatureError:
            log.warning("Received an expired token.")
            return None
        except pyjwt.InvalidTokenError as e:
            log.warning(f"Invalid token: {e}")
            return None
    else:
        # Fallback: check opaque token set
        if token in _active_tokens:
            return _active_tokens_meta.get(token, {"sub": "owner", "session_id": "sess_default"})
        return None


def revoke_token(token: str) -> None:
    """Revoke a token (fallback store only; JWT uses expiry)."""
    _active_tokens.discard(token)
    audit_log.info({
        "event":     "TOKEN_REVOKED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ─── FastAPI Dependency ───────────────────────────────────────────────────────

async def require_auth(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer_scheme)]
) -> dict:
    """
    FastAPI dependency that enforces owner authentication.
    Inject into any protected route with: `auth: dict = Depends(require_auth)`

    Raises:
        HTTPException 401 if token is missing or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if payload is None:
        audit_log.warning({
            "event":     "AUTH_REJECTED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


# Optional: dependency alias for cleaner route signatures
AuthRequired = Annotated[dict, Depends(require_auth)]
