"""
Phase 1 ("one brain") regression tests: provider health & fallback, the conversational chat
path, routing fixes, memory safety and the local owner identity. No network access.
"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from core.brain.llm_providers import (
    CircuitBreaker, OpenAICompatibleClient, ProviderError, classify_provider_error,
    RATE_LIMIT, AUTH, SERVICE, BAD_REQUEST,
)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ─── Provider error classification & circuit breaker ─────────────────────────

@pytest.mark.parametrize("text,kind", [
    ("429 RESOURCE_EXHAUSTED quota", RATE_LIMIT),
    ("400 API_KEY_INVALID API key not valid", AUTH),
    ("503 UNAVAILABLE model overloaded", SERVICE),
    ("400 INVALID_ARGUMENT bad schema", BAD_REQUEST),
])
def test_classify_provider_error(text, kind):
    assert classify_provider_error(text) == kind


def test_breaker_opens_then_recovers_after_cooldown():
    clock = FakeClock()
    b = CircuitBreaker("gemini", clock=clock)
    assert b.allow()
    b.record_failure(SERVICE)
    assert not b.allow()
    clock.t += CircuitBreaker.COOLDOWNS[SERVICE] + 0.1
    assert b.allow(), "provider must be retried after the cool-down, not disabled forever"
    b.record_success()
    assert b.consecutive_failures == 0


def test_breaker_backs_off_exponentially_and_ignores_bad_requests():
    clock = FakeClock()
    b = CircuitBreaker("groq", clock=clock)
    b.record_failure(BAD_REQUEST)
    assert b.allow()
    b.record_failure(SERVICE)
    first = b.seconds_until_retry()
    clock.t += first + 0.1
    b.record_failure(SERVICE)
    assert b.seconds_until_retry() == pytest.approx(first * 2, rel=0.01)


# ─── OpenAI-compatible client ────────────────────────────────────────────────

def test_openai_compatible_client_normalises_tool_calls(monkeypatch):
    payload = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": {"query": "x"}}}
    ]}}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json=payload))
    res = OpenAICompatibleClient("k", "https://example.invalid/v1", provider="groq").chat.completions.create(
        model="m", messages=[{"role": "user", "content": "hi"}])
    call = res.choices[0].message.tool_calls[0]
    assert call.function.name == "web_search"
    assert json.loads(call.function.arguments) == {"query": "x"}


def test_openai_compatible_client_raises_classified_errors(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(429, text="rate limited"))
    with pytest.raises(ProviderError) as exc:
        OpenAICompatibleClient("k", "https://example.invalid/v1", provider="groq").chat.completions.create(
            model="m", messages=[])
    assert exc.value.kind == RATE_LIMIT

    def _timeout(*a, **k):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(httpx, "post", _timeout)
    with pytest.raises(ProviderError) as exc:
        OpenAICompatibleClient("k", "https://example.invalid/v1").chat.completions.create(model="m", messages=[])
    assert exc.value.kind == SERVICE


# ─── ReasoningEngine provider selection ──────────────────────────────────────

def _engine(**overrides):
    from core.brain.reasoning_engine import ReasoningEngine
    engine = ReasoningEngine(api_key="")
    for k, v in overrides.items():
        setattr(engine, k, v)
    return engine


def test_gemini_failure_is_temporary_not_permanent():
    engine = _engine()
    clock = FakeClock()
    engine._breakers["gemini"] = CircuitBreaker("gemini", clock=clock)

    class FailingChat:
        def send_message(self, msg):
            raise RuntimeError("503 UNAVAILABLE high demand")

    engine._client = SimpleNamespace()          # pretend Gemini is configured
    engine._session_chats["default:default"] = FailingChat()
    engine._fallback_generate = lambda *a, **k: "served by fallback"

    assert engine._current_provider == "gemini"
    assert engine.send_message("hello") == "served by fallback"
    assert engine._current_provider == "fallback"
    clock.t += 3600
    assert engine._current_provider == "gemini", "Gemini must come back after its cool-down"


def test_primary_engine_groq_is_honoured(monkeypatch):
    monkeypatch.setenv("PRIMARY_ENGINE", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_not_real")
    engine = _engine()
    assert engine._current_provider == "groq"
    engine.create_chat_session("system", [])
    assert engine._current_provider == "groq", "creating a chat session must not override PRIMARY_ENGINE"


def test_ollama_never_receives_a_gemini_model_name():
    engine = _engine(_model_name="gemini-2.5-flash")
    assert not engine._ollama_model_name().startswith("gemini")


def test_fallback_chain_moves_to_next_provider(monkeypatch):
    from core.brain import reasoning_engine as re_mod

    class FakeClient:
        def __init__(self, api_key, base_url, provider, timeout):
            self.provider = provider
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            if self.provider == "groq":
                raise ProviderError("groq", 503, "unavailable")
            msg = SimpleNamespace(content=f"answer from {self.provider}", tool_calls=None, role="assistant")
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    monkeypatch.setattr(re_mod, "OpenAICompatibleClient", FakeClient)
    engine = _engine(groq_key="g", openai_key="o", ollama_host=None)
    assert engine._fallback_generate("hi") == "answer from openai"
    assert not engine._breakers["groq"].allow()
    assert engine._breakers["openai"].allow()


# ─── Conversational chat path ────────────────────────────────────────────────

class _FakeContext:
    async def build_enriched_prompt(self, text, session_id=None, user_id=None):
        return f"[memory for {user_id}] {text}"


class _FakeReasoning:
    def __init__(self):
        self.calls = []

    def send_message(self, message, raw_message=None, session_id=None, user_id=None):
        self.calls.append(dict(message=message, raw=raw_message, session=session_id, user=user_id))
        return "Persona reply"

    def generate_text(self, prompt, system_prompt=None):
        return "stateless reply"


def test_plain_chat_uses_chat_session_with_memory_and_identity():
    from core.brain.assistant_orchestrator import AssistantOrchestrator
    from core.brain.task_model import ExecutionContext

    reasoning = _FakeReasoning()
    brain = SimpleNamespace(reasoning=reasoning, context=_FakeContext(), intent_classifier=None,
                            tools=None, memory_manager=None)
    orch = AssistantOrchestrator(brain=brain, tool_router=None, memory_manager=None, reasoning_engine=reasoning)
    ctx = ExecutionContext(user_id="owner", session_id="local", store_memory=False)

    reply = orch.process("tell me something nice about rainy days", context=ctx)

    assert reply == "Persona reply"
    assert reasoning.calls, "plain chat must go through the chat session (send_message)"
    call = reasoning.calls[-1]
    assert call["message"].startswith("[memory for owner]")
    assert call["raw"] == "tell me something nice about rainy days"
    assert (call["session"], call["user"]) == ("local", "owner")


def test_run_coro_sync_is_safe_inside_a_running_loop():
    from core.brain.assistant_orchestrator import AssistantOrchestrator

    async def value():
        return 42

    async def outer():
        # Called from code that is itself running on an event loop thread.
        return AssistantOrchestrator._run_coro_sync(value())

    assert asyncio.run(outer()) == 42
    assert AssistantOrchestrator._run_coro_sync(value()) == 42


def test_brain_local_context_acts_as_owner():
    from core.brain.brain import Brain
    ctx = Brain._local_context()
    assert ctx.user_id == "owner"
    assert ctx.session_id == "local"


# ─── Routing ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,opens_browser", [
    ("search my files for TODO", False),
    ("search for my resume", False),
    ("search the web for react docs and summarize them", False),
    ("search the web for python tips", True),
    ("google best laptops", True),
])
def test_search_shortcut_only_for_explicit_web_searches(text, opens_browser):
    from core.brain.intent_classifier import IntentClassifier
    match = IntentClassifier().classify(text)
    assert (match is not None and match[0] == "_open_url_local") is opens_browser


# ─── Memory safety ───────────────────────────────────────────────────────────

def test_corrupt_memory_file_is_preserved_not_wiped(tmp_path):
    from core.memory import JSONMemoryStore
    path = tmp_path / "memory_fallback.json"
    path.write_text("{ this is not json", encoding="utf-8")
    store = JSONMemoryStore(path)
    assert store._data == {}
    backups = list(tmp_path.glob("memory_fallback.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{ this is not json"


def test_json_store_writes_atomically_and_finds_natural_language(tmp_path):
    from core.memory import JSONMemoryStore
    store = JSONMemoryStore(tmp_path / "m.json")
    store.add("1", "My favourite programming language is Rust", {"user_id": "owner"})
    store.add("2", "The cat sat on the mat", {"user_id": "owner"})
    assert not list(tmp_path.glob(".*.tmp"))
    hits = store.search("which programming language do I like", user_id="owner")
    assert hits and hits[0]["id"] == "1"
    assert hits[0]["distance"] < 0.6
    assert store.search("rust", user_id="someone_else") == []


@pytest.mark.parametrize("text", [
    "my password is hunter2",
    "use this key sk-abcdefghijklmnopqrstuvwxyz123456",
    "the api key: AIzaSyA1234567890abcdefghijklmnopqrstuv",
    "card 4111 1111 1111 1111",
])
def test_secrets_are_redacted(text):
    from core.security import redact_secrets
    redacted, found = redact_secrets(text)
    assert found
    assert "[REDACTED]" in redacted
    for secret in ("hunter2", "sk-abcdefghijklmnop", "AIzaSyA1234567890", "4111 1111"):
        assert secret not in redacted


def test_conversation_turns_never_store_credentials(tmp_path):
    from core.memory import ConversationStore
    store = ConversationStore(tmp_path / "c.json")
    store.add_turn("user", "remember my wifi password is S3cret!", user_id="owner")
    saved = (tmp_path / "c.json").read_text(encoding="utf-8")
    assert "S3cret!" not in saved


def test_memory_policy_sensitive_and_memory_card():
    from core.brain.memory_policy import MemoryPolicy, MemoryTier
    assert MemoryPolicy.classify_interaction("my pin is 4821") == (MemoryTier.DO_NOT_STORE, "sensitive")
    assert MemoryPolicy.classify_interaction("remove the memory card from the camera")[1] != "delete_request"
    assert MemoryPolicy.classify_interaction("forget my coffee preference")[1] == "delete_request"


# ─── Self-healing model selection (providers retire models) ──────────────────

def test_retired_model_errors_are_classified():
    from core.brain.llm_providers import MODEL_NOT_FOUND
    assert classify_provider_error(
        "404 NOT_FOUND. This model models/gemini-2.5-flash is no longer available to new users") == MODEL_NOT_FOUND
    assert classify_provider_error(
        "groq API error 400: The model `llama-3.3-70b-versatile` has been decommissioned") == MODEL_NOT_FOUND


def test_pick_replacement_model_prefers_stable_aliases():
    from core.brain.llm_providers import pick_replacement_model
    gemini = ["models/gemini-2.5-flash", "models/gemini-3.5-flash", "models/gemini-3.8-flash-tts",
              "models/gemini-flash-latest", "models/gemini-3.1-flash-image"]
    assert pick_replacement_model("gemini", gemini, failed="gemini-2.5-flash") == "gemini-flash-latest"
    assert pick_replacement_model("gemini", gemini[:3], failed="gemini-2.5-flash") == "gemini-3.5-flash"
    groq = ["whisper-large-v3", "meta-llama/llama-prompt-guard-2-22m", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
    assert pick_replacement_model("groq", groq, failed="llama-3.3-70b-versatile") == "openai/gpt-oss-120b"


def test_send_message_recovers_from_retired_model(monkeypatch):
    engine = _engine()
    engine._client = SimpleNamespace()
    engine._model_name = "gemini-2.5-flash"
    saved = {}
    monkeypatch.setattr("core.settings.update_settings", lambda changes: saved.update(changes))

    class RetiredChat:
        def send_message(self, msg):
            raise RuntimeError("404 NOT_FOUND This model models/gemini-2.5-flash is no longer available")

    class WorkingChat:
        def send_message(self, msg):
            return SimpleNamespace(text="hello from the new model")

    engine._session_chats["default:default"] = RetiredChat()
    engine._list_models = lambda provider: ["models/gemini-flash-latest", "models/gemini-2.5-flash"]
    engine.create_chat_session = lambda *a, **k: WorkingChat()
    engine._fallback_generate = lambda *a, **k: "fallback should not be needed"

    assert engine.send_message("hi") == "hello from the new model"
    assert engine.model_name == "gemini-flash-latest"
    assert saved == {"gemini_model": "gemini-flash-latest"}
