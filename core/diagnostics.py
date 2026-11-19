"""
JARVIS — Support diagnostics and opt-in crash reporting.

* build_diagnostics_zip(): a support bundle the user can export from Settings. Contains system
  info, non-secret settings, which keys are configured (yes/no only), provider health, recent
  activity and the tail of the logs with secrets redacted. Never includes API keys, memories,
  conversations or file contents.
* init_crash_reporting(): sends crash reports to Sentry ONLY when the user enabled
  "crash reports" in Settings AND a DSN is configured (SENTRY_DSN) AND sentry-sdk is installed.
  Reports are scrubbed of request bodies, local variables and secrets.
"""

from __future__ import annotations

import io
import json
import os
import platform
import sys
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

from core.logger import log

APP_VERSION = "0.9.0"


def _redact(text: str) -> str:
    from core.security import redact_secrets
    return redact_secrets(text)[0]


def _tail(path, max_lines: int = 300) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-max_lines:]
        return _redact("".join(lines))
    except OSError:
        return ""


def build_diagnostics_zip(provider_health: Optional[dict] = None) -> bytes:
    from core.activity import recent
    from core.paths import data_dir, logs_dir
    from core.secrets_store import backend_name, resolve
    from core.settings import MANAGED_SECRETS, load_settings

    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app_version": APP_VERSION,
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "data_dir": str(data_dir()),
        "settings": load_settings().model_dump(),
        "secrets_configured": {name: bool(resolve(name)) for name in MANAGED_SECRETS},
        "secret_backend": backend_name(),
        "provider_health": provider_health,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("summary.json", json.dumps(summary, indent=2, default=str))
        z.writestr("activity.json", json.dumps(recent(200), indent=2, default=str))
        for name in ("jarvis.log", "error.log"):
            z.writestr(f"logs/{name}", _tail(logs_dir() / name))
        z.writestr("README.txt", "JARVIS diagnostics. Contains no API keys, memories, conversations or "
                                 "file contents. Log lines are scanned and credentials are redacted.\n")
    return buf.getvalue()


def _scrub_event(event: dict, hint: Any = None) -> Optional[dict]:
    """Sentry before_send hook: drop request data and local variables, redact messages."""
    event.pop("request", None)
    event.pop("user", None)
    for exc in (event.get("exception") or {}).get("values", []) or []:
        if exc.get("value"):
            exc["value"] = _redact(str(exc["value"]))
        for frame in (exc.get("stacktrace") or {}).get("frames", []) or []:
            frame.pop("vars", None)
    for crumb in (event.get("breadcrumbs") or {}).get("values", []) or []:
        if crumb.get("message"):
            crumb["message"] = _redact(str(crumb["message"]))
    return event


def init_crash_reporting() -> bool:
    """Returns True only if opt-in crash reporting was actually enabled."""
    try:
        from core.settings import load_settings
        if not load_settings().crash_reports_enabled:
            return False
        dsn = os.environ.get("SENTRY_DSN")
        if not dsn:
            log.info("Crash reports are enabled in settings but no SENTRY_DSN is configured; nothing is sent.")
            return False
        import sentry_sdk  # optional dependency (pip install sentry-sdk)
        sentry_sdk.init(dsn=dsn, release=f"jarvis@{APP_VERSION}", send_default_pii=False,
                        include_local_variables=False, before_send=_scrub_event, traces_sample_rate=0.0)
        log.info("Opt-in crash reporting enabled.")
        return True
    except ImportError:
        log.info("Crash reports enabled but sentry-sdk is not installed; nothing is sent.")
        return False
    except Exception as e:
        log.warning(f"Crash reporting could not start: {e}")
        return False
