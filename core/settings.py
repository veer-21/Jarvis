"""
JARVIS — User settings (non-secret configuration)

Stored as JSON in the data directory (core.paths.settings_file()). API keys are NOT stored
here; they live in the OS credential vault (core.secrets_store).

Precedence for every value: settings.json (when the user has set it) > environment / .env >
built-in default. A missing settings.json therefore changes nothing for existing installs.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from core.logger import log
from core.paths import settings_file

_LOCK = threading.RLock()


class Settings(BaseModel):
    primary_engine: Optional[Literal["gemini", "groq"]] = None
    gemini_model: Optional[str] = Field(default=None, max_length=100)
    groq_model: Optional[str] = Field(default=None, max_length=100)
    openai_model: Optional[str] = Field(default=None, max_length=100)
    ollama_host: Optional[str] = Field(default=None, max_length=200)
    ollama_model: Optional[str] = Field(default=None, max_length=100)
    llm_timeout_seconds: Optional[float] = Field(default=None, ge=5, le=600)
    max_output_tokens: Optional[int] = Field(default=None, ge=64, le=65536)
    voice_engine: Optional[str] = Field(default=None, max_length=40)
    voice_profile: Optional[str] = Field(default=None, max_length=80)

    model_config = {"extra": "ignore"}


# setting name -> environment variable it overrides
ENV_EQUIVALENT = {
    "primary_engine": "PRIMARY_ENGINE",
    "gemini_model": "GEMINI_MODEL",
    "groq_model": "GROQ_MODEL",
    "openai_model": "OPENAI_MODEL",
    "ollama_host": "OLLAMA_HOST",
    "ollama_model": "OLLAMA_MODEL",
    "llm_timeout_seconds": "JARVIS_LLM_TIMEOUT_SECONDS",
    "max_output_tokens": "JARVIS_MAX_OUTPUT_TOKENS",
    "voice_engine": "VOICE_ENGINE",
    "voice_profile": "VOICE_PROFILE",
}

# Secrets the settings API may write to the vault (values are never returned).
MANAGED_SECRETS = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY", "PICOVOICE_API_KEY")


def load_settings() -> Settings:
    path = settings_file()
    if not path.exists():
        return Settings()
    try:
        with _LOCK:
            raw = json.loads(path.read_text(encoding="utf-8"))
        return Settings.model_validate(raw)
    except (ValueError, ValidationError) as e:
        log.error(f"settings.json is invalid ({e}); using defaults.")
        return Settings()


def save_settings(settings: Settings) -> None:
    path = settings_file()
    payload = json.dumps(settings.model_dump(exclude_none=True), indent=2)
    tmp = path.with_name(f".{path.name}.tmp")
    with _LOCK:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)


def update_settings(changes: dict) -> Settings:
    """Merge changes (None clears a value) and persist. Raises ValidationError on bad input."""
    with _LOCK:
        current = load_settings().model_dump()
        current.update({k: v for k, v in changes.items() if k in Settings.model_fields})
        new = Settings.model_validate(current)
        save_settings(new)
        return new


def get_setting(name: str, default: Any = None) -> Any:
    """settings.json value if set, else the equivalent environment variable, else default."""
    value = getattr(load_settings(), name, None)
    if value is not None:
        return value
    env_name = ENV_EQUIVALENT.get(name)
    if env_name:
        env_value = os.environ.get(env_name)
        if env_value:
            return env_value
    return default
