"""
JARVIS Logging System
Provides structured, rotating logs across three channels:
  - jarvis.log    : General operational events
  - audit.log     : Security-sensitive action audit trail
  - error.log     : Errors and exceptions
"""

import logging
import logging.handlers
import os
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


# ─── Log Directory ───────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ─── Custom JSON Formatter ────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects for easy parsing."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


# ─── Console Formatter ────────────────────────────────────────────────────────
class ConsoleFormatter(logging.Formatter):
    """Colorized console output for readability."""

    COLORS = {
        "DEBUG":    "\033[36m",   # Cyan
        "INFO":     "\033[32m",   # Green
        "WARNING":  "\033[33m",   # Yellow
        "ERROR":    "\033[31m",   # Red
        "CRITICAL": "\033[35m",   # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        ts = datetime.now().strftime("%H:%M:%S")
        return (
            f"{color}[{ts}] [{record.levelname}] "
            f"({record.name}) {record.getMessage()}{self.RESET}"
        )


def _make_rotating_handler(filename: str, max_bytes: int = 5_000_000, backup_count: int = 3) -> logging.Handler:
    """Creates a rotating file handler with JSON formatting."""
    path = LOG_DIR / filename
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setFormatter(JsonFormatter())
    return handler


def _make_console_handler(level: int = logging.INFO) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(ConsoleFormatter())
    return handler


# ─── Logger Factory ──────────────────────────────────────────────────────────
def get_logger(name: str, console: bool = False) -> logging.Logger:
    """
    Returns a named logger that writes to jarvis.log and optionally the console.

    Args:
        name: Logger name (e.g., 'jarvis.brain', 'jarvis.memory')
        console: If True, also print to stdout with color formatting.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # Already configured

    logger.setLevel(logging.DEBUG)

    # File handler — general log
    logger.addHandler(_make_rotating_handler("jarvis.log"))

    # Console handler (optional)
    if console:
        logger.addHandler(_make_console_handler(logging.INFO))

    logger.propagate = False
    return logger


def get_audit_logger() -> logging.Logger:
    """
    Returns the security audit logger.
    All security-sensitive actions (tool executions, auth events) must be logged here.
    """
    logger = logging.getLogger("jarvis.audit")

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.addHandler(_make_rotating_handler("audit.log", max_bytes=10_000_000, backup_count=5))
    logger.propagate = False
    return logger


def get_error_logger() -> logging.Logger:
    """Returns the dedicated error logger."""
    logger = logging.getLogger("jarvis.error")

    if logger.handlers:
        return logger

    logger.setLevel(logging.ERROR)
    logger.addHandler(_make_rotating_handler("error.log"))
    logger.addHandler(_make_console_handler(logging.ERROR))
    logger.propagate = False
    return logger


# ─── Convenience Instances ────────────────────────────────────────────────────
# Import these directly in other modules:
#   from core.logger import log, audit_log, error_log
log        = get_logger("jarvis.core", console=True)
audit_log  = get_audit_logger()
error_log  = get_error_logger()
