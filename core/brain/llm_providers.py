"""
JARVIS — LLM provider plumbing

* ``OpenAICompatibleClient`` — a small httpx client for any OpenAI-compatible
  ``/chat/completions`` endpoint (OpenAI, Groq, OpenRouter, Ollama). It mirrors the
  ``client.chat.completions.create(...)`` call shape used by
  ``ReasoningEngine._execute_fallback_with_tools`` so no extra SDK is required.
* ``ProviderError`` — raised for any transport / HTTP failure, with a classified ``kind``.
* ``CircuitBreaker`` — per-provider cool-down. A failing provider is skipped for a while and
  then retried automatically, instead of being disabled for the rest of the session.
* ``classify_provider_error`` — maps an exception / error text to a failure kind.
"""

from __future__ import annotations

import json
import os
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable, Optional

import httpx

# ─── Error classification ────────────────────────────────────────────────────

RATE_LIMIT = "rate_limit"
AUTH = "auth"
SERVICE = "service"
BAD_REQUEST = "bad_request"
MODEL_NOT_FOUND = "model_not_found"   # configured model was retired/renamed: recoverable
OTHER = "other"

_RATE_LIMIT_MARKERS = ("429", "resource_exhausted", "quota", "rate limit", "rate_limit",
                       "generaterequestsperday", "too many requests", "otpm")
_AUTH_MARKERS = ("401", "403", "api_key_invalid", "api key not valid", "invalid_api_key",
                 "invalid api key", "permission_denied", "unauthenticated", "unauthorized")
_SERVICE_MARKERS = ("500", "502", "503", "504", "unavailable", "high demand", "server error",
                    "deadline", "timeout", "timed out", "connection", "connecterror",
                    "temporarily", "overloaded")
_BAD_REQUEST_MARKERS = ("400", "invalid_argument", "bad request", "invalid_request_error")
_MODEL_NOT_FOUND_MARKERS = ("model_not_found", "no longer available", "decommissioned",
                            "does not exist", "not_found", "404", "unknown model",
                            "model not found", "is not supported")


def classify_provider_error(error: Any) -> str:
    """Classify an exception or error string into a failure kind."""
    kind = getattr(error, "kind", None)
    if kind:
        return kind
    text = str(error).lower()
    if any(m in text for m in _RATE_LIMIT_MARKERS):
        return RATE_LIMIT
    if any(m in text for m in _AUTH_MARKERS):
        return AUTH
    if "model" in text and any(m in text for m in _MODEL_NOT_FOUND_MARKERS):
        return MODEL_NOT_FOUND
    if any(m in text for m in _SERVICE_MARKERS):
        return SERVICE
    if any(m in text for m in _BAD_REQUEST_MARKERS):
        return BAD_REQUEST
    return OTHER


class ProviderError(RuntimeError):
    """A provider call failed. ``kind`` is one of the classification constants above."""

    def __init__(self, provider: str, status: Any, message: str, kind: Optional[str] = None):
        self.provider = provider
        self.status = status
        self.kind = kind or classify_provider_error(f"{status} {message}")
        super().__init__(f"{provider} API error {status}: {message}")


# ─── Circuit breaker ─────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Tracks provider health. After a failure the provider is "open" (skipped) for a cool-down
    that depends on the failure kind and doubles on consecutive failures (capped). Once the
    cool-down passes the provider is tried again; a success closes the breaker.

    Bad-request failures do not open the breaker: they are caused by the specific request,
    not by provider health.
    """

    COOLDOWNS = {RATE_LIMIT: 60.0, AUTH: 300.0, SERVICE: 30.0, OTHER: 15.0,
                 MODEL_NOT_FOUND: 300.0, "manual": 60.0}
    MAX_COOLDOWN = 900.0

    def __init__(self, name: str, clock: Callable[[], float] = time.monotonic):
        self.name = name
        self._clock = clock
        self._lock = threading.Lock()
        self._open_until = 0.0
        self.consecutive_failures = 0
        self.last_failure_kind: Optional[str] = None
        self.last_error: Optional[str] = None

    def allow(self) -> bool:
        return self._clock() >= self._open_until

    @property
    def is_open(self) -> bool:
        return not self.allow()

    def seconds_until_retry(self) -> float:
        return max(0.0, self._open_until - self._clock())

    def record_success(self) -> None:
        with self._lock:
            self._open_until = 0.0
            self.consecutive_failures = 0
            self.last_failure_kind = None
            self.last_error = None

    def record_failure(self, kind: str = OTHER, error: Any = None) -> None:
        if kind == BAD_REQUEST:
            return
        with self._lock:
            self.consecutive_failures += 1
            base = self.COOLDOWNS.get(kind, self.COOLDOWNS[OTHER])
            cooldown = min(base * (2 ** (self.consecutive_failures - 1)), self.MAX_COOLDOWN)
            self._open_until = self._clock() + cooldown
            self.last_failure_kind = kind
            self.last_error = str(error)[:300] if error is not None else None

    def trip(self, kind: str = "manual") -> None:
        self.record_failure(kind)

    def reset(self) -> None:
        self.record_success()

    def snapshot(self) -> dict:
        return {
            "provider": self.name,
            "available": self.allow(),
            "retry_in_seconds": round(self.seconds_until_retry(), 1),
            "consecutive_failures": self.consecutive_failures,
            "last_failure_kind": self.last_failure_kind,
        }


# ─── OpenAI-compatible HTTP client ───────────────────────────────────────────

def _to_namespace(obj: Any) -> Any:
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_namespace(v) for v in obj]
    return obj


def _normalise_response(data: dict) -> SimpleNamespace:
    """Shape the JSON response like the OpenAI SDK objects the engine expects."""
    choices = []
    for choice in data.get("choices") or []:
        msg = choice.get("message") or {}
        tool_calls = None
        if msg.get("tool_calls"):
            tool_calls = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                tool_calls.append(SimpleNamespace(
                    id=tc.get("id"),
                    type=tc.get("type", "function"),
                    function=SimpleNamespace(
                        name=fn.get("name"),
                        arguments=json.dumps(args) if isinstance(args, (dict, list)) else str(args or "{}"),
                    ),
                ))
        choices.append(SimpleNamespace(
            message=SimpleNamespace(
                role=msg.get("role", "assistant"),
                content=msg.get("content"),
                tool_calls=tool_calls,
            ),
            finish_reason=choice.get("finish_reason"),
        ))
    return SimpleNamespace(choices=choices, usage=_to_namespace(data.get("usage") or {}), raw=data)


class OpenAICompatibleClient:
    """Minimal synchronous client for OpenAI-compatible chat completion APIs."""

    def __init__(self, api_key: Optional[str], base_url: str, provider: str = "openai-compatible",
                 timeout: Optional[float] = None):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.provider = provider
        self.timeout = timeout if timeout is not None else default_request_timeout()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model: str, messages: list, temperature: float = 0.4,
                tools: Optional[list] = None, max_tokens: Optional[int] = None, **kwargs) -> SimpleNamespace:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "ollama":
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        if tools:
            payload["tools"] = tools
        if max_tokens:
            payload["max_tokens"] = max_tokens

        url = f"{self.base_url}/chat/completions"
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise ProviderError(self.provider, "timeout", str(e) or "request timed out", kind=SERVICE) from e
        except httpx.HTTPError as e:
            raise ProviderError(self.provider, "connection", str(e) or type(e).__name__, kind=SERVICE) from e

        if response.status_code >= 400:
            raise ProviderError(self.provider, response.status_code, response.text[:500])
        try:
            return _normalise_response(response.json())
        except ValueError as e:
            raise ProviderError(self.provider, response.status_code, f"invalid JSON response: {e}", kind=SERVICE) from e


# ─── Settings helpers ────────────────────────────────────────────────────────

def _setting(name: str, default):
    try:
        from core.settings import get_setting
        return get_setting(name, default)
    except Exception:
        return default


def default_request_timeout() -> float:
    """Per-request timeout (seconds) for every LLM call."""
    try:
        return float(_setting("llm_timeout_seconds", 40.0))
    except (TypeError, ValueError):
        return 40.0


def default_max_output_tokens() -> int:
    """Upper bound on generated tokens per LLM call (cost and latency control)."""
    try:
        return int(_setting("max_output_tokens", 4096))
    except (TypeError, ValueError):
        return 4096


def default_ollama_model() -> str:
    return str(_setting("ollama_model", "llama3.2"))


def default_openai_model() -> str:
    return str(_setting("openai_model", "gpt-4o-mini"))


# ─── Model selection (self-healing when providers retire models) ─────────────

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"      # Google-maintained alias for the current Flash
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

_NON_CHAT_MARKERS = ("image", "tts", "transcribe", "embedding", "embed", "guard", "whisper",
                     "orpheus", "robotics", "computer-use", "nano", "audio", "vision-only", "aqa")


def _is_chat_model(model_id: str) -> bool:
    low = model_id.lower()
    return not any(m in low for m in _NON_CHAT_MARKERS)


def _version_key(model_id: str) -> tuple:
    import re as _re
    nums = [int(n) for n in _re.findall(r"\d+", model_id)]
    return tuple(nums) if nums else (0,)


def pick_replacement_model(provider: str, available: list[str], failed: Optional[str] = None) -> Optional[str]:
    """
    Choose a working general-purpose chat model from a provider's live model list.
    Preference: stable "latest" aliases, then the newest non-preview Flash/general model.
    """
    ids = [m.replace("models/", "") for m in available if m]
    ids = [m for m in ids if _is_chat_model(m) and m != failed]
    if not ids:
        return None
    if provider == "gemini":
        for alias in ("gemini-flash-latest", "gemini-pro-latest"):
            if alias in ids:
                return alias
        flash = [m for m in ids if "flash" in m and "lite" not in m and "preview" not in m]
        pool = flash or [m for m in ids if "preview" not in m] or ids
        return sorted(pool, key=_version_key)[-1]
    # OpenAI-compatible providers (Groq, OpenAI, OpenRouter, Ollama)
    preferred = ["openai/gpt-oss-120b", "gpt-4o-mini", "gpt-4.1-mini", "llama3.2", "qwen"]
    for want in preferred:
        for m in ids:
            if m == want or (want == "qwen" and m.startswith("qwen")):
                return m
    return sorted(ids)[0]
