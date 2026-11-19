"""
JARVIS — Activity journal

A plain, user-facing record of what JARVIS did on this computer (tools run, actions blocked,
permissions granted or denied). Shown in the app's Activity panel so people can see and
trust what the assistant is doing. Stored as JSON lines in the data directory, with
arguments masked; the file is trimmed to the most recent entries.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from core.paths import data_dir

MAX_ENTRIES = 2000
_LOCK = threading.Lock()
_writes_since_trim = 0


def _path():
    return data_dir() / "activity.jsonl"


def _clean(value: Any) -> Any:
    from core.security import mask_sensitive_data
    value = mask_sensitive_data(value)
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value][:20]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(getattr(value, "value", value))
    return text if len(text) <= 300 else text[:300] + "…"


def record(kind: str, **fields: Any) -> None:
    """Append an activity entry. Never raises (activity logging must not break actions)."""
    global _writes_since_trim
    try:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind}
        entry.update({k: _clean(v) for k, v in fields.items()})
        line = json.dumps(entry, ensure_ascii=False)
        with _LOCK:
            path = _path()
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            _writes_since_trim += 1
            if _writes_since_trim >= 200:
                _writes_since_trim = 0
                lines = path.read_text(encoding="utf-8").splitlines()
                if len(lines) > MAX_ENTRIES:
                    path.write_text("\n".join(lines[-MAX_ENTRIES:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def recent(limit: int = 100) -> list[dict]:
    """Most recent entries first."""
    path = _path()
    if not path.exists():
        return []
    with _LOCK:
        lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in reversed(lines[-max(1, min(limit, MAX_ENTRIES)):]):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out
