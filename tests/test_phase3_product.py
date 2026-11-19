"""
Phase 3 regression tests: desktop-app login, activity journal, always-allow permissions,
provider key checks, WebSocket reply delivery, friendly replies, voice defaults, Electron security.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import server as server_module
from api.server import app
from core.paths import PROJECT_ROOT
from core.security import guard, RiskLevel

DESKTOP = PROJECT_ROOT / "desktop"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def clean_settings():
    from core.paths import settings_file
    settings_file().unlink(missing_ok=True)
    yield
    settings_file().unlink(missing_ok=True)


def _auth_headers():
    from api.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token()[0]}"}


# ─── Desktop-app local login ─────────────────────────────────────────────────

def test_local_token_login(client, monkeypatch):
    secret = "a" * 64
    monkeypatch.setenv("JARVIS_LOCAL_TOKEN", secret)
    ok = client.post("/auth/local", json={"token": secret})
    assert ok.status_code == 200 and ok.json()["access_token"]
    assert client.post("/auth/local", json={"token": "b" * 64}).status_code == 401


def test_local_login_disabled_without_spawned_secret(client, monkeypatch):
    monkeypatch.delenv("JARVIS_LOCAL_TOKEN", raising=False)
    assert client.post("/auth/local", json={"token": "x" * 64}).status_code == 401
    monkeypatch.setenv("JARVIS_LOCAL_TOKEN", "short")
    assert client.post("/auth/local", json={"token": "short"}).status_code == 401


# ─── Activity journal ────────────────────────────────────────────────────────

def test_activity_records_tool_runs_with_masked_args(client):
    from core.brain.tool_router import ToolRouter

    def save_note(text: str, api_key: str = "") -> str:
        """Fake tool."""
        return "saved"

    router = ToolRouter()
    router.register_callable(save_note, category="notes", risk_level=RiskLevel.READ_ONLY)
    router.execute_tool("save_note", {"text": "hello", "api_key": "sk-supersecretvalue1234567890"}, interactive=False)

    entries = client.get("/activity", headers=_auth_headers()).json()["entries"]
    entry = next(e for e in entries if e.get("tool") == "save_note")
    assert entry["kind"] == "tool" and entry["ok"] is True
    assert "supersecret" not in json.dumps(entry)
    assert client.get("/activity").status_code == 401


# ─── "Always allow" permissions ──────────────────────────────────────────────

def test_always_allow_skips_prompt_only_for_lower_risk(clean_settings):
    from core.settings import update_settings
    update_settings({"always_allow_tools": ["write_file", "execute_command"]})

    allowed, _r, req, _ = guard.evaluate_tool_execution(
        "write_file", {"path": "a.txt"}, declared_risk=RiskLevel.MODERATE_RISK,
        interactive=False, declared_requires_confirmation=True)
    assert allowed and not req

    allowed, _r, req, _ = guard.evaluate_tool_execution(
        "execute_command", {"command": "dir"}, declared_risk=RiskLevel.HIGH_RISK,
        interactive=False, declared_requires_confirmation=True)
    assert req and not allowed, "HIGH-risk actions always ask"

    allowed, _r, req, _ = guard.evaluate_tool_execution(
        "write_file", {"path": "a.txt"}, declared_risk=RiskLevel.MODERATE_RISK,
        interactive=False, declared_requires_confirmation=True, untrusted_context=True)
    assert req and not allowed, "after reading web content the owner is asked again"


def test_permission_decision_saves_always_allow_only_when_eligible(clean_settings):
    from core.settings import load_settings
    server_module._record_permission_decision({"tool_name": "write_file", "risk_level": "MODERATE_RISK"}, True, True)
    server_module._record_permission_decision({"tool_name": "execute_command", "risk_level": "HIGH_RISK"}, True, True)
    server_module._record_permission_decision({"tool_name": "type_text", "risk_level": "LOW_RISK"}, False, True)
    assert load_settings().always_allow_tools == ["write_file"]


# ─── Provider key check ──────────────────────────────────────────────────────

def test_provider_check_returns_friendly_messages(client, monkeypatch):
    def rejected(provider, key, host):
        raise RuntimeError("400 INVALID_ARGUMENT API key not valid. API_KEY_INVALID")

    monkeypatch.setattr(server_module, "_check_provider", rejected)
    res = client.post("/settings/test-provider", json={"provider": "gemini", "api_key": "x"}, headers=_auth_headers()).json()
    assert res["ok"] is False and "rejected" in res["message"]
    assert "INVALID_ARGUMENT" not in res["message"]

    monkeypatch.setattr(server_module, "_check_provider", lambda p, k, h: {"models": ["m1"]})
    res = client.post("/settings/test-provider", json={"provider": "groq", "api_key": "x"}, headers=_auth_headers()).json()
    assert res["ok"] is True and res["models"] == ["m1"]


def test_diagnostics_export_contains_no_secrets(client):
    import io
    import zipfile
    from core import secrets_store
    secrets_store.set_secret("GEMINI_API_KEY", "AIzaSyDIAGNOSTICSsecret0000000000000000")
    try:
        res = client.get("/diagnostics/export", headers=_auth_headers())
        assert res.status_code == 200
        z = zipfile.ZipFile(io.BytesIO(res.content))
        assert {"summary.json", "activity.json", "README.txt"} <= set(z.namelist())
        blob = b"".join(z.read(n) for n in z.namelist())
        assert b"AIzaSyDIAGNOSTICS" not in blob
        assert json.loads(z.read("summary.json"))["secrets_configured"]["GEMINI_API_KEY"] is True
    finally:
        secrets_store.delete_secret("GEMINI_API_KEY")


def test_crash_reporting_is_off_by_default(clean_settings):
    from core.diagnostics import init_crash_reporting
    assert init_crash_reporting() is False


# ─── Replies reach the app ───────────────────────────────────────────────────

def test_websocket_delivers_instant_answers(client):
    from core.brain.brain import Brain
    server_module.set_server_brain(Brain())
    from api.auth import create_access_token
    token = create_access_token()[0]
    with client.websocket_connect("/ws/jarvis") as ws:
        ws.send_json({"command": "auth", "token": token})
        ws.send_json({"command": "chat", "token": token, "message": "what time is it"})
        chunks = []
        for _ in range(30):
            msg = ws.receive_json()
            if msg.get("type") == "stream_chunk" or "chunk" in msg:
                chunks.append(msg.get("chunk", ""))
            if msg.get("type") == "stream_done":
                break
    assert any("current time" in c for c in chunks), chunks


def test_tool_results_are_humanized_without_a_model():
    from datetime import datetime, timedelta, timezone
    from core.brain.assistant_orchestrator import AssistantOrchestrator
    from core.brain.task_model import TaskStep
    when = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    task = SimpleNamespace(plan=[TaskStep(step_id="s1", description="", capability="everyday", tool_name="create_reminder_or_timer")])
    text = AssistantOrchestrator._humanize_result(task, {"s1": {"success": True, "title": "stretch", "trigger_at": when}})
    assert text.startswith("Okay, I'll remind you to stretch at ")
    assert AssistantOrchestrator._humanize_result(task, {"s1": {"success": False, "error": "disk full"}}) == "That didn't work: disk full."


# ─── Voice defaults ──────────────────────────────────────────────────────────

def test_voice_is_offline_by_default(clean_settings, monkeypatch):
    from core import config, voice
    monkeypatch.delenv("VOICE_ENGINE", raising=False)
    monkeypatch.delenv("JARVIS_CLOUD_SPEECH_FALLBACK", raising=False)
    assert config.get_voice_engine() == "sapi"
    assert voice._cloud_speech_allowed() is False


# ─── Electron shell security ─────────────────────────────────────────────────

def test_electron_window_is_sandboxed_and_isolated():
    main = (DESKTOP / "electron" / "main.js").read_text(encoding="utf-8")
    assert "sandbox: true" in main and "contextIsolation: true" in main and "nodeIntegration: false" in main
    assert "requestSingleInstanceLock" in main and "new Tray(" in main
    assert "fromOwnWindow(event) ? LOCAL_TOKEN : null" in main
    assert "'/T', '/F'" in main and "/IM" not in main, "only our own backend tree is stopped"
    pkg = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    assert all("--no-sandbox" not in cmd for cmd in pkg["scripts"].values())
    assert pkg["build"]["win"]["target"] == ["nsis"]
