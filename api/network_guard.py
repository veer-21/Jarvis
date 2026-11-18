"""
JARVIS API — Network Guard (ASGI middleware)

The JARVIS API can run shell commands, read files and drive the desktop, so it must
only ever be reachable by the owner's own UI on this machine. This middleware enforces,
for BOTH HTTP and WebSocket traffic (CORS does not apply to WebSockets):

  1. Host allowlist   — rejects DNS-rebinding attacks (evil.example resolving to 127.0.0.1).
  2. Origin allowlist — rejects requests initiated by any other website in the user's browser.

Requests without an Origin header (curl, Python clients, the Electron main process) are
allowed through to normal token authentication; only browsers attach Origin headers, and a
browser page cannot suppress it on cross-origin requests.
"""

from __future__ import annotations

from typing import Iterable, Optional

from core.logger import audit_log


def _header(scope: dict, name: bytes) -> Optional[str]:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            try:
                return value.decode("latin-1")
            except Exception:
                return None
    return None


def _strip_port(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):  # IPv6 literal, e.g. [::1]:7799
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    return host.split(":", 1)[0]


class NetworkGuardMiddleware:
    def __init__(self, app, allowed_origins: Iterable[str], allowed_hosts: Iterable[str]):
        self.app = app
        self.allowed_origins = {o.rstrip("/").lower() for o in allowed_origins}
        self.allowed_hosts = {_strip_port(h) for h in allowed_hosts}

    def _rejection_reason(self, scope: dict) -> Optional[str]:
        host = _header(scope, b"host")
        if host is not None and _strip_port(host) not in self.allowed_hosts:
            return f"host '{host}' not allowed"

        origin = _header(scope, b"origin")
        if origin is not None and origin.rstrip("/").lower() not in self.allowed_origins:
            return f"origin '{origin}' not allowed"
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        reason = self._rejection_reason(scope)
        if reason is None:
            await self.app(scope, receive, send)
            return

        audit_log.warning({
            "event": "NETWORK_GUARD_REJECTED",
            "type": scope["type"],
            "path": scope.get("path"),
            "reason": reason,
        })

        if scope["type"] == "websocket":
            # Closing before accept makes the server answer the handshake with HTTP 403.
            await send({"type": "websocket.close", "code": 1008})
            return

        body = b'{"detail":"Forbidden: request origin is not allowed."}'
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
