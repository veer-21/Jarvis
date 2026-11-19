"""
JARVIS Brain — Reasoning Engine
Owns the Gemini LLM client, chat session management, model fallback,
and retry logic with exponential backoff.
"""

import time
import asyncio
from typing import Optional, Iterator, Callable, Any, Dict, List
import os

from core.logger import log, error_log
from core.config import (
    get_api_key, get_model_name, get_groq_api_key, 
    get_openai_api_key, get_ollama_host, get_primary_engine, get_groq_model
)


# ─── Gemini SDK ───────────────────────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    log.warning("google-genai not installed. Run: pip install google-genai")

from core.brain.llm_providers import (
    OpenAICompatibleClient, ProviderError, CircuitBreaker, classify_provider_error,
    RATE_LIMIT, BAD_REQUEST, MODEL_NOT_FOUND, pick_replacement_model,
    DEFAULT_GROQ_MODEL, default_request_timeout, default_max_output_tokens,
    default_ollama_model, default_openai_model,
)

# Fallback providers (Groq / OpenAI / Ollama) all speak the OpenAI-compatible API and are
# served by our own httpx client, so the optional `openai` SDK is no longer needed.
HAS_OPENAI = False

# Backward-compatible alias for code/tests that referenced the old ad-hoc client.
FauxOpenAIClient = OpenAICompatibleClient

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"


class ReasoningEngine:
    """
    Manages the Gemini LLM client, chat sessions, and all direct LLM calls.
    Provides retry with exponential backoff and seamless multi-provider fallback.
    """

    MAX_RETRIES  = 3
    BACKOFF_BASE = 2.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self._api_key    = api_key or get_api_key()
        self._model_name = model_name or get_model_name()
        
        self.groq_key = get_groq_api_key()
        self.openai_key = get_openai_api_key()
        self.ollama_host = get_ollama_host()

        self.is_offline = os.getenv("JARVIS_OFFLINE") == "1"
        self.request_timeout = default_request_timeout()
        self.max_output_tokens = default_max_output_tokens()
        self.ollama_model = default_ollama_model()
        self.openai_model = default_openai_model()

        # Per-provider health. A failure opens the breaker for a cool-down, after which the
        # provider is retried automatically (it is never disabled for the whole session).
        self._breakers: dict[str, CircuitBreaker] = {
            name: CircuitBreaker(name) for name in ("gemini", "groq", "openai", "ollama")
        }
        self._last_error: Optional[str] = None
        self._model_recovery_at: dict[str, float] = {}

        if HAS_GEMINI and self._api_key and not self.is_offline:
            try:
                self._client = genai.Client(
                    api_key=self._api_key,
                    http_options=types.HttpOptions(timeout=int(self.request_timeout * 1000)),
                )
            except Exception as e:
                error_log.error(f"Could not create Gemini client: {e}")
                self._client = None
        else:
            self._client = None

        self._tool_router = None
        self._tools  = []
        self._system_prompt = ""
        self._session_chats: dict[str, Any] = {}
        self._session_histories: dict[str, list[dict]] = {}
        
        self.primary_engine = get_primary_engine()
        self.groq_model = get_groq_model()

        # Preferred provider from settings (PRIMARY_ENGINE). The *current* provider is derived
        # from this preference plus live provider health — see the _current_provider property.
        if self.is_offline:
            self._preferred_provider = "ollama"
        elif self.primary_engine == "groq" and self.groq_key:
            self._preferred_provider = "groq"
        else:
            self._preferred_provider = "gemini"

        # Phase 3 Hardware Power Budgeting
        self._power_profile: str = "NORMAL"
        try:
            from core.sentinel import hardware_sentinel
            hardware_sentinel.register_profile_listener(self.set_power_profile)
            self._power_profile = hardware_sentinel.get_last_metrics().power_profile.value
        except Exception:
            pass

        log.info(f"ReasoningEngine initialized (Primary: {self._current_provider}, Model: {self._model_name}, Offline: {self.is_offline}, Power: {self._power_profile})")

    # ─── Provider selection ───────────────────────────────────────────────────

    @property
    def _current_provider(self) -> str:
        """
        "gemini"   — Gemini is preferred, configured and healthy.
        "groq"     — PRIMARY_ENGINE=groq (served through the fallback chain, Groq first).
        "ollama"   — offline mode.
        "fallback" — Gemini is preferred but unavailable right now (no client or cooling down).
        """
        if self._preferred_provider in ("ollama", "groq"):
            return self._preferred_provider
        if self._client is not None and self._breakers["gemini"].allow():
            return "gemini"
        return "fallback"

    @_current_provider.setter
    def _current_provider(self, value: str) -> None:
        # Kept for backward compatibility with code that assigned this attribute directly.
        if value == "gemini":
            self._preferred_provider = "gemini"
            self._breakers["gemini"].reset()
        elif value == "fallback":
            self._breakers["gemini"].trip("manual")
        elif value in ("groq", "ollama"):
            self._preferred_provider = value

    def provider_health(self) -> dict:
        """Snapshot of every provider's availability (for status endpoints and the UI)."""
        return {
            "preferred": self._preferred_provider,
            "current": self._current_provider,
            "providers": {name: b.snapshot() for name, b in self._breakers.items()},
        }

    def _record_provider_failure(self, provider: str, error: Any) -> str:
        kind = classify_provider_error(error)
        self._last_error = str(error)
        self._breakers[provider].record_failure(kind, error)
        if kind != BAD_REQUEST:
            log.warning(f"[ReasoningEngine] {provider} unavailable ({kind}); retrying it in "
                        f"{self._breakers[provider].seconds_until_retry():.0f}s. Error: {str(error)[:120]}")
        return kind

    # ─── Self-healing model selection ─────────────────────────────────────────

    _MODEL_ATTR = {"gemini": "_model_name", "groq": "groq_model", "openai": "openai_model", "ollama": "ollama_model"}
    _MODEL_SETTING = {"gemini": "gemini_model", "groq": "groq_model", "openai": "openai_model", "ollama": "ollama_model"}

    def _list_models(self, provider: str) -> list:
        import httpx
        if provider == "gemini":
            if self._client is None:
                return []
            out = []
            for m in self._client.models.list():
                actions = getattr(m, "supported_actions", None) or []
                if not actions or "generateContent" in actions:
                    out.append(m.name)
            return out
        if provider == "ollama":
            url = f"{(self.ollama_host or '').rstrip('/')}/api/tags"
            r = httpx.get(url, timeout=10)
            return [m.get("name", "") for m in r.json().get("models", [])]
        base, key = (GROQ_BASE_URL, self.groq_key) if provider == "groq" else (OPENAI_BASE_URL, self.openai_key)
        r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=15)
        r.raise_for_status()
        return [m.get("id", "") for m in r.json().get("data", [])]

    def _recover_model(self, provider: str) -> Optional[str]:
        """
        The provider says the configured model does not exist (retired or renamed). Pick a
        current model from its live list, persist it to settings.json and return it.
        At most one attempt per provider every 5 minutes.
        """
        now = time.monotonic()
        if now - self._model_recovery_at.get(provider, -1e9) < 300:
            return None
        self._model_recovery_at[provider] = now
        attr = self._MODEL_ATTR[provider]
        current = getattr(self, attr, None)
        try:
            available = self._list_models(provider)
        except Exception as e:
            log.warning(f"[ReasoningEngine] Could not list {provider} models to replace '{current}': {e}")
            return None
        new_model = pick_replacement_model(provider, available, failed=current)
        if not new_model or new_model == current:
            return None
        setattr(self, attr, new_model)
        try:
            from core.settings import update_settings
            update_settings({self._MODEL_SETTING[provider]: new_model})
        except Exception as e:
            log.warning(f"[ReasoningEngine] Could not save model choice: {e}")
        log.warning(f"[ReasoningEngine] {provider} model '{current}' is no longer available; "
                    f"switched to '{new_model}' and saved it to settings.")
        self._breakers[provider].reset()
        if provider == "gemini":
            self._session_chats.clear()   # chats are bound to the old model
        return new_model

    def _make_session_key(self, session_id: Optional[str] = None, user_id: Optional[str] = None) -> str:
        sid = session_id or "default"
        uid = user_id or "default"
        return f"{uid}:{sid}"

    def set_tool_router(self, tool_router) -> None:
        """Attach the authoritative ToolRouter instance to enforce unified execution."""
        self._tool_router = tool_router

    @property
    def client(self):
        return self._client

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def chat(self):
        return self._session_chats.get("default:default")

    @property
    def _chat(self):
        return self._session_chats.get("default:default")

    @_chat.setter
    def _chat(self, value):
        self._session_chats["default:default"] = value

    @property
    def _conversation_history(self) -> list[dict]:
        return self._session_histories.setdefault("default:default", [])

    @_conversation_history.setter
    def _conversation_history(self, val: list[dict]):
        self._session_histories["default:default"] = val

    def set_power_profile(self, profile: Any) -> None:
        """Set the active hardware power profile and adjust token/iteration budgeting."""
        if hasattr(profile, "value"):
            self._power_profile = str(profile.value).upper()
        else:
            self._power_profile = str(profile).upper()
        log.info(f"[ReasoningEngine] Power profile updated to: {self._power_profile}")

    def get_power_profile(self) -> str:
        """Return active power profile."""
        return self._power_profile

    # ─── Chat Session ─────────────────────────────────────────────────────────

    def create_chat_session(
        self,
        system_prompt: str,
        tools: list,
        model_name: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        self._system_prompt = system_prompt
        self._tools = tools
        key = self._make_session_key(session_id, user_id)
        self._session_histories[key] = []
        model = model_name or self._model_name

        chat = None
        if self._client:
            try:
                chat = self._client.chats.create(
                    model=model,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.4,
                        tools=tools,
                        max_output_tokens=self.max_output_tokens,
                    ),
                )
                # NOTE: creating a session must not override PRIMARY_ENGINE or provider health.
                log.info(f"Chat session created for [{key}] with model: {model}, {len(tools)} tools")
            except Exception as e:
                error_log.error(f"Failed to create chat session with {model}: {e}")
                self._record_provider_failure("gemini", e)

        self._session_chats[key] = chat
        return chat

    def reset_session(
        self,
        system_prompt: str,
        tools: list,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        try:
            key = self._make_session_key(session_id, user_id)
            self.create_chat_session(system_prompt, tools, session_id=session_id, user_id=user_id)
            log.info(f"Chat session reset for [{key}].")
            return "Chat session reset. Previous conversation context cleared."
        except Exception as e:
            return f"Failed to reset chat: {str(e)}"

    def switch_model(self, model_name: str, system_prompt: str, tools: list) -> str:
        try:
            self.create_chat_session(system_prompt, tools, model_name=model_name)
            self._model_name = model_name
            log.info(f"Model switched to: {model_name}")
            return f"Model switched to {model_name}. Chat session reset."
        except Exception as e:
            return f"Failed to switch model: {str(e)}"

    # ─── Fallback Logic ───────────────────────────────────────────────────────

    def _callable_to_openai_schema(self, func: Callable) -> dict:
        import inspect
        sig = inspect.signature(func)
        parameters = {
            "type": "object",
            "properties": {},
            "required": []
        }
        for name, param in sig.parameters.items():
            if name in ("self", "cls"): continue
            ptype = "string"
            if param.annotation == int: ptype = "integer"
            elif param.annotation == bool: ptype = "boolean"
            elif param.annotation == float: ptype = "number"
            elif param.annotation == list: ptype = "array"
            elif param.annotation == dict: ptype = "object"
            parameters["properties"][name] = {"type": ptype, "description": f"Parameter {name}"}
            if param.default == inspect.Parameter.empty:
                parameters["required"].append(name)
                
        return {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": (func.__doc__ or "").strip().split("\n")[0] if func.__doc__ else "No description",
                "parameters": parameters
            }
        }

    def _execute_fallback_with_tools(self, client, model_name: str, messages: list, session_key: str = "default:default") -> str:
        import json
        openai_tools = [self._callable_to_openai_schema(f) for f in self._tools] if self._tools else None
        
        # Phase 3: Adaptive Resource Budgeting based on PowerProfile
        max_iter = 15
        default_tokens = 800
        if self._power_profile == "POWER_SAVER":
            max_iter = 8
            default_tokens = 350
        elif self._power_profile == "CRITICAL_SAVER":
            max_iter = 5
            default_tokens = 200

        for _ in range(max_iter): # Adaptive max iterations
            kwargs = {"model": model_name, "messages": messages, "temperature": 0.4, "max_tokens": default_tokens}
            if openai_tools:
                kwargs["tools"] = openai_tools
                
            try:
                res = client.chat.completions.create(**kwargs)
            except Exception as e:
                # If Groq validation fails (e.g. hallucinated tool, OTPM, rate limit), retry without tools and smaller max_tokens
                error_str = str(e)
                is_tool_err = "tool_use_failed" in error_str or "invalid_request_error" in error_str or "attempted to call tool" in error_str
                is_rate_limit = "429" in error_str or "rate_limit" in error_str or "tokens" in error_str or "OTPM" in error_str or "Request too large" in error_str
                if (is_tool_err or is_rate_limit) and ("tools" in kwargs or kwargs.get("max_tokens", 800) > 400):
                    log.warning(f"Groq API issue ({error_str[:60]}). Retrying with trimmed parameters...")
                    kwargs.pop("tools", None)
                    kwargs["max_tokens"] = 400
                    time.sleep(2)
                    try:
                        res = client.chat.completions.create(**kwargs)
                    except Exception as e2:
                        # Raise so _fallback_generate can move on to the next provider tier.
                        raise e2 if isinstance(e2, ProviderError) else ProviderError(
                            getattr(client, "provider", "fallback"), "error", str(e2)) from e2
                else:
                    raise e if isinstance(e, ProviderError) else ProviderError(
                        getattr(client, "provider", "fallback"), "error", error_str) from e
                
            msg = res.choices[0].message
            
            # ─── Fix for Ollama raw JSON tool calls ───
            if not getattr(msg, "tool_calls", None) and msg.content:
                # Sometimes models output: {"name": "...", "parameters": {...}}; {"name": ...}
                import re
                content_str = msg.content.strip()
                # Check if it looks like our raw json tool calls
                if content_str.startswith('{"name":') and '"parameters":' in content_str:
                    # Try to parse it
                    faux_tool_calls = []
                    parts = content_str.split(';')
                    for i, part in enumerate(parts):
                        part = part.strip()
                        if not part: continue
                        try:
                            parsed = json.loads(part)
                            if "name" in parsed and "parameters" in parsed:
                                class FauxFunction:
                                    def __init__(self, name, arguments):
                                        self.name = name
                                        self.arguments = arguments
                                class FauxToolCall:
                                    def __init__(self, id, function):
                                        self.id = id
                                        self.function = function
                                
                                faux_tool_calls.append(FauxToolCall(
                                    id=f"call_{i}",
                                    function=FauxFunction(parsed["name"], json.dumps(parsed["parameters"]))
                                ))
                        except Exception:
                            pass
                    
                    if faux_tool_calls:
                        msg.tool_calls = faux_tool_calls
                        msg.content = ""
            # ──────────────────────────────────────────

            if hasattr(msg, "tool_calls") and msg.tool_calls:
                # Add assistant message with tool calls
                assistant_msg = {"role": "assistant", "content": msg.content or "", "tool_calls": []}
                for tc in msg.tool_calls:
                    assistant_msg["tool_calls"].append({
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    })
                messages.append(assistant_msg)
                
                # Execute tools
                for tc in msg.tool_calls:
                    func_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {}
                        
                    if self._tool_router:
                        tool_res = self._tool_router.execute_tool(name=func_name, args=args, interactive=False)
                        result = tool_res.output if tool_res.success else f"Error: {tool_res.error}"
                    else:
                        target_func = next((f for f in self._tools if f.__name__ == func_name), None)
                        if target_func:
                            try:
                                result = target_func(**args)
                            except Exception as e:
                                result = f"Error: {e}"
                        else:
                            result = f"Error: Tool '{func_name}' not found."
                        
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": func_name,
                        "content": str(result)[:2000]
                    })
            else:
                self._session_histories.setdefault(session_key, []).append({"role": "assistant", "content": msg.content or ""})
                return str(msg.content or "")
                
        return "Error: Maximum tool call iterations reached."

    def _clean_last_chat_turn(self, raw_message: str, chat: Optional[Any] = None):
        """Reset the text of the last user message in Gemini history to be the raw (non-RAG) message."""
        target_chat = chat or self._session_chats.get("default:default")
        if not target_chat:
            return
        try:
            for hist in [getattr(target_chat, "_comprehensive_history", []), getattr(target_chat, "_curated_history", [])]:
                for content in reversed(hist):
                    if getattr(content, "role", None) == "user":
                        parts = getattr(content, "parts", [])
                        # Skip tool function response turns
                        if any(getattr(p, "function_response", None) is not None for p in parts):
                            continue
                        for part in parts:
                            if hasattr(part, "text") and part.text is not None and not getattr(part, "function_response", None) and not getattr(part, "inline_data", None):
                                part.text = raw_message
                                break
                            elif isinstance(part, dict) and "text" in part:
                                part["text"] = raw_message
                                break
                        break
        except Exception as e:
            log.warning(f"Failed to clean last chat turn in Gemini history: {e}")

    def _fallback_generate(
        self,
        message: str,
        raw_message: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        key = self._make_session_key(session_id, user_id)
        history = self._session_histories.setdefault(key, [])
        raw_msg = (raw_message or message)[:1200]
        history.append({"role": "user", "content": raw_msg})
        if len(history) > 6:
            self._session_histories[key] = history[-6:]
            history = self._session_histories[key]
        
        # Ensure system prompt and turns don't blow up token limits for fast fallback models
        sys_prompt = self._system_prompt[:2500] if len(self._system_prompt) > 2500 else self._system_prompt
        messages = [{"role": "system", "content": sys_prompt}]
        for turn in history[:-1]:
            content = turn.get("content", "")
            if len(content) > 1200:
                turn_copy = dict(turn)
                turn_copy["content"] = content[:1200] + "..."
                messages.append(turn_copy)
            else:
                messages.append(turn)
        messages.append({"role": "user", "content": message[:2500]})

        had_auth_or_quota_error = False
        api_key_str = str(self._api_key or "")
        if "AIzaSyTestMockKey" in api_key_str or "TestMockKey" in api_key_str:
            had_auth_or_quota_error = True
        if self._last_error and classify_provider_error(self._last_error) in (RATE_LIMIT, "auth"):
            had_auth_or_quota_error = True

        # Fallback chain: Groq → OpenAI → local Ollama. Providers whose circuit breaker is
        # open (recent failure) are skipped until their cool-down passes.
        tiers: list[tuple[str, str, str, str]] = []
        if not self.is_offline:
            if self.groq_key:
                tiers.append(("groq", self.groq_key, GROQ_BASE_URL, self.groq_model))
            if self.openai_key:
                tiers.append(("openai", self.openai_key, OPENAI_BASE_URL, self.openai_model))
        if self.ollama_host and self._breakers["ollama"].allow() and self._ollama_reachable():
            tiers.append(("ollama", "ollama", f"{self.ollama_host.rstrip('/')}/v1", self._ollama_model_name()))

        for provider, provider_key, base_url, model in tiers:
            breaker = self._breakers[provider]
            if not breaker.allow():
                log.debug(f"Skipping {provider}: cooling down for {breaker.seconds_until_retry():.0f}s")
                continue
            client = OpenAICompatibleClient(api_key=provider_key, base_url=base_url,
                                            provider=provider, timeout=self.request_timeout)
            try:
                log.info(f"Serving via {provider} fallback ({model}) with tools")
                try:
                    result = self._execute_fallback_with_tools(client, model, messages, session_key=key)
                except Exception as first_err:
                    if classify_provider_error(first_err) != MODEL_NOT_FOUND:
                        raise
                    new_model = self._recover_model(provider)
                    if not new_model:
                        raise
                    result = self._execute_fallback_with_tools(client, new_model, messages, session_key=key)
                breaker.record_success()
                return result
            except Exception as e:
                kind = self._record_provider_failure(provider, e)
                if kind in (RATE_LIMIT, "auth"):
                    had_auth_or_quota_error = True
                if provider == "ollama" and self.is_offline:
                    return (f"Offline Engine Error: Make sure Ollama is running and the model "
                            f"'{model}' is pulled! Error: {e}")

        # When Groq is the primary engine, Gemini is the last cloud resort.
        if (self._preferred_provider == "groq" and self._client is not None
                and self._breakers["gemini"].allow()):
            try:
                text = self._gemini_oneshot(messages)
                if text:
                    self._breakers["gemini"].record_success()
                    history.append({"role": "assistant", "content": text})
                    return text
            except Exception as e:
                if self._record_provider_failure("gemini", e) in (RATE_LIMIT, "auth"):
                    had_auth_or_quota_error = True

        if had_auth_or_quota_error:
            return ("⚠️ AI Provider Limit or Invalid API Key: Primary LLM rejected the request "
                    "(check your GEMINI_API_KEY in Setup Wizard / .env or wait for rate limit reset).")

        return ("Sir, every AI provider is unavailable right now (Gemini, the cloud fallbacks and "
                "local Ollama). I will retry them automatically in a moment.")

    def _ollama_reachable(self) -> bool:
        """Fast 1.5-second socket check before attempting a slow completion."""
        try:
            import urllib.parse
            import socket
            parsed = urllib.parse.urlparse(self.ollama_host or "")
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 11434
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.5)
                return sock.connect_ex((host, port)) == 0
        except Exception as sock_err:
            log.debug(f"Ollama socket check failed: {sock_err}")
            return False

    def _ollama_model_name(self) -> str:
        # Never send a Gemini model name to Ollama.
        if self._model_name and not self._model_name.lower().startswith("gemini") and self.is_offline:
            return self._model_name
        return self.ollama_model

    def _gemini_oneshot(self, messages: list[dict]) -> str:
        """Single Gemini completion from OpenAI-style messages (no tools, no chat session)."""
        newline = chr(10)
        system = newline.join(m["content"] for m in messages if m.get("role") == "system" and m.get("content"))
        transcript = (newline * 2).join(
            f"{m['role'].upper()}: {m.get('content', '')}" for m in messages if m.get("role") != "system"
        )
        res = self._client.models.generate_content(
            model=self._model_name,
            contents=transcript,
            config=types.GenerateContentConfig(
                system_instruction=system or None,
                temperature=0.4,
                max_output_tokens=self.max_output_tokens,
            ),
        )
        return (getattr(res, "text", None) or "").strip()

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Direct text completion without conversational history or function tools.
        Used for planning, DAG generation, structured extraction, and summarization.
        NEVER calls _fallback_generate (to prevent re-executing previous tasks).
        """
        if self._current_provider == "gemini" and self._client:
            try:
                config = types.GenerateContentConfig(
                    system_instruction=system_prompt or None,
                    temperature=0.2,
                    max_output_tokens=self.max_output_tokens,
                )
                try:
                    res = self._client.models.generate_content(model=self._model_name, contents=prompt, config=config)
                except Exception as first_err:
                    if classify_provider_error(first_err) != MODEL_NOT_FOUND or not self._recover_model("gemini"):
                        raise
                    res = self._client.models.generate_content(model=self._model_name, contents=prompt, config=config)
                self._breakers["gemini"].record_success()
                if res and res.text:
                    return res.text
            except Exception as e:
                self._record_provider_failure("gemini", e)
                log.warning(f"Gemini generate_text failed: {e}. Falling back to Groq text completion...")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Groq as a pure, stateless 1-shot completion WITHOUT tools and WITHOUT session history.
        if self.groq_key and not self.is_offline and self._breakers["groq"].allow():
            try:
                groq_model = self.groq_model or DEFAULT_GROQ_MODEL
                client = OpenAICompatibleClient(api_key=self.groq_key, base_url=GROQ_BASE_URL,
                                                provider="groq", timeout=min(self.request_timeout, 15.0))
                token_budget = 1000
                if self._power_profile == "POWER_SAVER":
                    token_budget = 400
                elif self._power_profile == "CRITICAL_SAVER":
                    token_budget = 200
                res = client.chat.completions.create(model=groq_model, messages=messages, temperature=0.2, max_tokens=token_budget)
                self._breakers["groq"].record_success()
                if res and res.choices and res.choices[0].message:
                    content = str(res.choices[0].message.content or "")
                    if content.strip():
                        return content
            except Exception as e:
                self._record_provider_failure("groq", e)
                log.warning(f"Groq generate_text failed: {e}")
                return ""

        # NEVER call self._fallback_generate(prompt)! Return "" immediately so caller falls back to deterministic heuristics in <1s.
        return ""

    # ─── Send with Retry ──────────────────────────────────────────────────────

    def _should_retry_gemini(self, error: Any, attempt: int) -> bool:
        """Only short-lived rate limits are retried in place; everything else falls back now."""
        text = str(error)
        return (classify_provider_error(error) == RATE_LIMIT
                and "GenerateRequestsPerDay" not in text
                and attempt < self.MAX_RETRIES - 1)

    def send_message(
        self,
        message: str,
        raw_message: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        raw_msg = raw_message or message
        key = self._make_session_key(session_id, user_id)
        chat = self._session_chats.get(key)
        if chat is None and self._client and self._current_provider == "gemini":
            chat = self.create_chat_session(self._system_prompt, self._tools, session_id=session_id, user_id=user_id)

        history = self._session_histories.setdefault(key, [])

        if self._current_provider == "gemini" and chat:
            delay = self.BACKOFF_BASE
            for attempt in range(self.MAX_RETRIES):
                try:
                    response = chat.send_message(message)
                    self._breakers["gemini"].record_success()
                    self._clean_last_chat_turn(raw_msg, chat=chat)
                    text = getattr(response, "text", None)
                    history.append({"role": "user", "content": raw_msg})
                    history.append({"role": "assistant", "content": text or ""})
                    return text or "[JARVIS returned an empty response]"
                except Exception as e:
                    if classify_provider_error(e) == MODEL_NOT_FOUND and self._recover_model("gemini"):
                        chat = self.create_chat_session(self._system_prompt, self._tools,
                                                        session_id=session_id, user_id=user_id)
                        if chat is not None:
                            continue
                    if self._should_retry_gemini(e, attempt):
                        self._last_error = str(e)
                        log.warning(f"Rate limit hit (attempt {attempt+1}/{self.MAX_RETRIES}). Retrying in {delay:.1f}s...")
                        time.sleep(delay)
                        delay *= self.BACKOFF_BASE
                        continue
                    # Fall back for THIS request; Gemini is retried after its cool-down.
                    self._record_provider_failure("gemini", e)
                    return self._fallback_generate(message, raw_message=raw_msg, session_id=session_id, user_id=user_id)
            return self._fallback_generate(message, raw_message=raw_msg, session_id=session_id, user_id=user_id)
        else:
            return self._fallback_generate(message, raw_message=raw_msg, session_id=session_id, user_id=user_id)

    # ─── Streaming ────────────────────────────────────────────────────────────

    def stream_message(
        self,
        message: str,
        system_prompt: str,
        raw_message: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Iterator[str]:
        raw_msg = raw_message or message
        key = self._make_session_key(session_id, user_id)
        chat = self._session_chats.get(key)
        if chat is None and self._client and self._current_provider == "gemini":
            chat = self.create_chat_session(system_prompt, self._tools, session_id=session_id, user_id=user_id)

        history = self._session_histories.setdefault(key, [])

        if self._current_provider != "gemini" or not self._client:
            yield self._fallback_generate(message, raw_message=raw_msg, session_id=session_id, user_id=user_id)
            return

        delay = self.BACKOFF_BASE
        for attempt in range(self.MAX_RETRIES):
            full_response = ""
            try:
                if chat:
                    response = chat.send_message_stream(message)
                    for chunk in response:
                        if chunk.text:
                            full_response += chunk.text
                            yield chunk.text
                    self._clean_last_chat_turn(raw_msg, chat=chat)
                else:
                    response = self._client.models.generate_content_stream(
                        model=self._model_name,
                        contents=message,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=0.4,
                            max_output_tokens=self.max_output_tokens,
                        ),
                    )
                    for chunk in response:
                        if chunk.text:
                            full_response += chunk.text
                            yield chunk.text

                self._breakers["gemini"].record_success()
                history.append({"role": "user", "content": raw_msg})
                history.append({"role": "assistant", "content": full_response})
                return
            except Exception as e:
                if (not full_response and classify_provider_error(e) == MODEL_NOT_FOUND
                        and self._recover_model("gemini")):
                    chat = self.create_chat_session(system_prompt, self._tools, session_id=session_id, user_id=user_id)
                    continue
                if not full_response and self._should_retry_gemini(e, attempt):
                    time.sleep(delay)
                    delay *= self.BACKOFF_BASE
                    continue

                self._record_provider_failure("gemini", e)
                if not full_response:
                    # Nothing reached the user yet: answer this request via the fallback chain.
                    yield self._fallback_generate(message, raw_message=raw_msg, session_id=session_id, user_id=user_id)
                    return

                error_log.error(f"Streaming error after partial output: {e}")
                yield chr(10) + f"[Stream interrupted: {str(e)[:200]}]"
                return

    # ─── Introspection ────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "model": self._model_name,
            "provider": self._current_provider,
            "provider_health": self.provider_health(),
            "tools_count": len(self._tools),
            "has_session": self._chat is not None,
        }
