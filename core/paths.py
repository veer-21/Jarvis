"""
JARVIS — Filesystem locations

Single source of truth for where JARVIS keeps per-user runtime data (memory, keys, tasks,
screenshots, preferences) and logs. Nothing else should hard-code a path like D:\\Jarvis.

Resolution order for the data directory:
  1. ``JARVIS_DATA_DIR`` environment variable (used by tests, portable installs, power users)
  2. ``<project>/data`` if it already exists (existing developer installs keep their data)
  3. ``%LOCALAPPDATA%\\JARVIS`` on Windows, ``~/.local/share/jarvis`` elsewhere (fresh installs)

Logs live in ``JARVIS_LOG_DIR``, else ``<project>/logs`` for legacy installs, else
``<data dir>/logs``.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LEGACY_DATA_DIR = PROJECT_ROOT / "data"
APP_DIR_NAME = "JARVIS"

# The local machine owner. Single-user installs (CLI, voice, desktop app) act as this identity,
# and the API issues tokens for it, so every front-end shares one memory.
LOCAL_OWNER_ID = "owner"


def _platform_data_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_DIR_NAME
        return Path.home() / "AppData" / "Local" / APP_DIR_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / APP_DIR_NAME.lower()


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def uses_legacy_layout() -> bool:
    return not os.environ.get("JARVIS_DATA_DIR") and _LEGACY_DATA_DIR.exists()


def data_dir() -> Path:
    override = os.environ.get("JARVIS_DATA_DIR")
    if override:
        return _ensure(Path(override).expanduser().resolve())
    if _LEGACY_DATA_DIR.exists():
        return _LEGACY_DATA_DIR
    return _ensure(_platform_data_root())


def logs_dir() -> Path:
    override = os.environ.get("JARVIS_LOG_DIR")
    if override:
        return _ensure(Path(override).expanduser().resolve())
    if os.environ.get("JARVIS_DATA_DIR"):
        return _ensure(data_dir() / "logs")
    if uses_legacy_layout():
        return _ensure(PROJECT_ROOT / "logs")
    return _ensure(data_dir() / "logs")


def memory_dir() -> Path:
    return _ensure(data_dir() / "memory")


def security_dir() -> Path:
    return _ensure(data_dir() / "security")


def tasks_dir() -> Path:
    return _ensure(data_dir() / "tasks")


def screenshots_dir() -> Path:
    return _ensure(data_dir() / "screenshots")


def reminders_file() -> Path:
    return tasks_dir() / "reminders.json"


def todos_file() -> Path:
    return tasks_dir() / "personal_todos.json"


def task_history_file() -> Path:
    return tasks_dir() / "task_history.json"


def user_preferences_file() -> Path:
    return data_dir() / "user_preferences.json"


def settings_file() -> Path:
    return data_dir() / "settings.json"
