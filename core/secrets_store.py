"""
JARVIS — Secret storage

API keys belong in the operating system's credential vault, not in a plain-text .env file.

Backends (``JARVIS_SECRET_BACKEND`` overrides the automatic choice):
  * ``wincred`` — Windows Credential Manager via pywin32 (default on Windows). Each secret is a
    generic credential named ``JARVIS/<NAME>``, protected by the user's Windows login (DPAPI).
  * ``memory``  — in-process dict; used by the test suite so tests never touch the real vault.
  * ``env``     — no vault available; secrets only come from environment variables / .env.

Lookup order used by core.config: vault first, then environment / .env. That way a key saved
from the setup wizard always wins over a stale value left in an old .env file.
"""

from __future__ import annotations

import os
from typing import Optional

from core.logger import log

SERVICE_PREFIX = "JARVIS"

try:  # pragma: no cover - availability depends on the platform
    import pywintypes
    import win32cred
    _HAS_WINCRED = True
except Exception:  # ImportError, or pywin32 present but broken
    _HAS_WINCRED = False

_memory_backend: dict[str, str] = {}


def backend_name() -> str:
    forced = os.environ.get("JARVIS_SECRET_BACKEND", "").strip().lower()
    if forced in ("memory", "env", "wincred"):
        if forced == "wincred" and not _HAS_WINCRED:
            return "env"
        return forced
    if os.name == "nt" and _HAS_WINCRED:
        return "wincred"
    return "env"


def is_vault_available() -> bool:
    return backend_name() in ("wincred", "memory")


def _target(name: str) -> str:
    return f"{SERVICE_PREFIX}/{name}"


def get_secret(name: str) -> Optional[str]:
    backend = backend_name()
    if backend == "memory":
        return _memory_backend.get(name)
    if backend == "wincred":
        try:
            cred = win32cred.CredRead(_target(name), win32cred.CRED_TYPE_GENERIC)
        except pywintypes.error:
            return None
        except Exception as e:
            log.warning(f"Could not read secret {name} from Credential Manager: {e}")
            return None
        blob = cred.get("CredentialBlob")
        if isinstance(blob, bytes):
            try:
                return blob.decode("utf-16-le")
            except UnicodeDecodeError:
                return blob.decode("utf-8", errors="replace")
        return str(blob) if blob else None
    return None


def set_secret(name: str, value: str) -> Optional[str]:
    """
    Store a secret. Returns the backend used ("wincred" / "memory"), or None when no vault is
    available (callers may then fall back to writing .env).
    """
    backend = backend_name()
    if backend == "memory":
        _memory_backend[name] = value
        return backend
    if backend == "wincred":
        try:
            win32cred.CredWrite({
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": _target(name),
                "UserName": name,
                "CredentialBlob": value,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                "Comment": "Stored by JARVIS personal assistant",
            }, 0)
            return backend
        except Exception as e:
            log.warning(f"Could not store secret {name} in Credential Manager: {e}")
            return None
    return None


def delete_secret(name: str) -> bool:
    backend = backend_name()
    if backend == "memory":
        return _memory_backend.pop(name, None) is not None
    if backend == "wincred":
        try:
            win32cred.CredDelete(_target(name), win32cred.CRED_TYPE_GENERIC)
            return True
        except Exception:
            return False
    return False


def resolve(name: str, *aliases: str) -> Optional[str]:
    """Vault first, then environment variables (including values loaded from .env)."""
    for key in (name, *aliases):
        value = get_secret(key)
        if value:
            return value
    for key in (name, *aliases):
        value = os.environ.get(key)
        if value:
            return value
    return None
