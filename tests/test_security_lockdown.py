"""
Phase 0 security lockdown — regression tests.

Covers the network exposure, auth, command-guard, shell-injection, file-secrets and
broadcast-leak fixes. None of these tests touch the real desktop, network or user files.
"""

import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api import server as server_module
from api.server import app
from api.ws_manager import WebSocketManager
from core.security import guard, hard_block_reason, RiskLevel


@pytest.fixture
def client():
    return TestClient(app)


# ─── Network exposure ────────────────────────────────────────────────────────

def test_api_binds_to_loopback_by_default(monkeypatch):
    from core import config
    monkeypatch.delenv("JARVIS_API_HOST", raising=False)
    assert config.get_api_host() == "127.0.0.1"


def test_request_without_origin_is_allowed(client):
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("origin", ["http://localhost:7799", "http://127.0.0.1:7799", "http://localhost:3000", "file://"])
def test_own_ui_origins_are_allowed(client, origin):
    assert client.get("/health", headers={"Origin": origin}).status_code == 200


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost:7799.evil.example"])
def test_foreign_origin_is_rejected(client, origin):
    resp = client.get("/health", headers={"Origin": origin})
    assert resp.status_code == 403


def test_foreign_origin_cannot_log_in(client):
    resp = client.post("/auth/login", json={"pin": ""}, headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403


def test_dns_rebinding_host_is_rejected():
    rebinding_client = TestClient(app, base_url="http://evil.example:7799")
    assert rebinding_client.get("/health").status_code == 403


def test_cors_does_not_allow_wildcard(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_websocket_from_foreign_origin_is_rejected(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/jarvis", headers={"Origin": "https://evil.example"}) as ws:
            ws.receive_json()


# ─── Auth ────────────────────────────────────────────────────────────────────

def test_login_is_throttled_after_repeated_failures(client):
    saved = dict(server_module._login_throttle)
    server_module._login_throttle.update({"failures": 0, "locked_until": 0.0})
    try:
        with patch.object(server_module.owner_auth, "verify_pin", return_value=False):
            codes = [client.post("/auth/login", json={"pin": "0000"}).status_code
                     for _ in range(server_module._LOGIN_MAX_FAILURES + 1)]
        assert codes[:server_module._LOGIN_MAX_FAILURES] == [401] * server_module._LOGIN_MAX_FAILURES
        assert codes[-1] == 429
    finally:
        server_module._login_throttle.clear()
        server_module._login_throttle.update(saved)


def test_jwt_secret_is_persistent_across_imports():
    from api import auth
    assert auth.SECRET_KEY == auth._load_or_create_jwt_secret()


# ─── WebSocket broadcast privacy ─────────────────────────────────────────────

class _FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)


def test_broadcast_skips_unauthenticated_sockets():
    mgr = WebSocketManager()
    anon, owner = _FakeSocket(), _FakeSocket()
    for s in (anon, owner):
        mgr.active_connections.append(s)
        mgr.connection_meta[s] = {"session_id": f"s{id(s)}", "authenticated": False, "token": None}
    mgr.authenticate_connection(owner, token="t", user_id="owner")

    asyncio.run(mgr.broadcast({"type": "stream_chunk", "chunk": "private"}))

    assert anon.sent == []
    assert owner.sent == [{"type": "stream_chunk", "chunk": "private"}]


# ─── Command guard ───────────────────────────────────────────────────────────

def test_check_command_no_longer_crashes_on_risky_commands():
    # Used to raise NameError (cmd_lower undefined) for every non-SAFE command.
    allowed, reason = guard.check_command("del /f important.txt", interactive=False)
    assert allowed is False
    assert isinstance(reason, str)


def test_server_context_never_blocks_on_terminal_input():
    with patch.object(guard, "_confirmation_handler", None), \
         patch("core.security._stdin_is_interactive", return_value=False), \
         patch("builtins.input", side_effect=AssertionError("input() must not be called")):
        allowed, *_ = guard.evaluate_tool_execution(
            "some_tool", {}, declared_risk=RiskLevel.HIGH_RISK, interactive=True
        )
    assert allowed is False


def test_hard_block_reason_for_critical_processes():
    assert hard_block_reason("taskkill /F /IM lsass.exe") is not None
    assert hard_block_reason("Stop-Process -Name explorer.exe") is not None
    assert hard_block_reason("dir C:\\Users") is None


def test_declared_requires_confirmation_is_enforced():
    allowed, _risk, requires_conf, _ = guard.evaluate_tool_execution(
        "write_file", {"path": "x.txt", "content": "hi"},
        declared_risk=RiskLevel.MODERATE_RISK,
        interactive=False,
        declared_requires_confirmation=True,
    )
    assert requires_conf is True
    assert allowed is False


def test_execute_command_does_not_reprompt_after_router_approval():
    from tools import system_tools
    with patch.object(system_tools.guard, "check_command",
                      side_effect=AssertionError("must not re-prompt")), \
         patch.object(system_tools.subprocess, "run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""
        out = system_tools.execute_command("echo ok")
    assert out.startswith("Success")


def test_execute_command_still_hard_blocks_critical_process_kill():
    from tools import system_tools
    with patch.object(system_tools.subprocess, "run") as run:
        out = system_tools.execute_command("taskkill /F /IM lsass.exe")
    run.assert_not_called()
    assert "blocked" in out.lower()


# ─── open_application shell injection ────────────────────────────────────────

@pytest.mark.parametrize("payload", [
    "notepad & calc",
    "notepad && powershell -enc AAAA",
    "notepad | whoami",
    'notepad" & calc',
    "calc\r\nwhoami",
])
def test_open_application_rejects_shell_metacharacters(payload):
    from tools import automation_tools
    with patch.object(automation_tools.os, "startfile", create=True) as startfile, \
         patch.object(automation_tools.subprocess, "Popen") as popen:
        out = automation_tools.open_application(payload)
    startfile.assert_not_called()
    popen.assert_not_called()
    assert "not allowed" in out


def test_open_application_launches_alias_without_shell():
    from tools import automation_tools
    with patch.object(automation_tools.os, "startfile", create=True) as startfile, \
         patch.object(automation_tools.subprocess, "Popen") as popen:
        out = automation_tools.open_application("calculator")
    startfile.assert_called_once_with("calc")
    popen.assert_not_called()
    assert "Launched" in out


# ─── File secrets ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", [
    ".env", ".env.local", ".ssh/id_rsa", "proj/server.pem", "keys/backup.pfx",
    "AppData/Local/Google/Chrome/User Data/Default/Login Data",
    "Jarvis/data/security/.jarvis.key",
])
def test_sensitive_paths_are_detected(tmp_path, rel):
    from tools.file_tools import _is_sensitive
    assert _is_sensitive(str(tmp_path / rel))


@pytest.mark.parametrize("rel", ["notes.txt", "Documents/report.docx", "code/app.py", "envelope.txt"])
def test_normal_paths_are_not_sensitive(tmp_path, rel):
    from tools.file_tools import _is_sensitive
    assert not _is_sensitive(str(tmp_path / rel))


def test_read_file_refuses_env_files(tmp_path):
    from tools.file_tools import read_file
    secret = tmp_path / ".env"
    secret.write_text("GEMINI_API_KEY=super-secret", encoding="utf-8")
    out = read_file(str(secret))
    assert "super-secret" not in out
    assert "denied" in out.lower()


def test_read_file_still_reads_normal_files(tmp_path):
    from tools.file_tools import read_file
    f = tmp_path / "notes.txt"
    f.write_text("hello jarvis", encoding="utf-8")
    assert read_file(str(f)) == "hello jarvis"


def test_search_in_files_skips_secret_files(tmp_path):
    from tools.file_tools import search_in_files
    (tmp_path / ".env").write_text("TOKEN=needle-secret", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("needle in notes", encoding="utf-8")
    out = search_in_files(str(tmp_path), "needle", extension="*")
    assert "needle in notes" in out
    assert "needle-secret" not in out
