"""
Phase 2 regression tests: data/log locations, secrets vault, settings, prompt composer,
OS adapter, COM safety and dependency manifest. No network, no real vault, no real data.
"""

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import paths

RUNTIME_DIRS = ["core", "api", "tools"]


# ─── Paths ───────────────────────────────────────────────────────────────────

def test_data_and_log_dirs_follow_environment():
    assert paths.data_dir() == Path(os.environ["JARVIS_DATA_DIR"]).resolve()
    assert paths.logs_dir() == Path(os.environ["JARVIS_LOG_DIR"]).resolve()
    assert paths.memory_dir().parent == paths.data_dir()
    assert paths.reminders_file().parent == paths.tasks_dir()


def test_fresh_install_uses_local_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "_LEGACY_DATA_DIR", tmp_path / "no-legacy-data")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    if os.name == "nt":
        assert paths.data_dir() == tmp_path / "LocalAppData" / "JARVIS"


def test_no_hard_coded_install_paths_in_runtime_code():
    offenders = []
    pattern = re.compile(r"[dD]:[\\/]+(Jarvis|Home)", re.I)
    for folder in RUNTIME_DIRS + ["main.py"]:
        root = paths.PROJECT_ROOT / folder
        files = [root] if root.is_file() else root.rglob("*.py")
        for f in files:
            if "custom" in f.parts and "_quarantine" in f.parts:
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{f.relative_to(paths.PROJECT_ROOT)}:{n}")
    assert offenders == []


# ─── Secrets vault ───────────────────────────────────────────────────────────

def test_secret_store_memory_backend_roundtrip():
    from core import secrets_store
    assert secrets_store.backend_name() == "memory"
    assert secrets_store.set_secret("GROQ_API_KEY", "gsk_unit_test") == "memory"
    assert secrets_store.get_secret("GROQ_API_KEY") == "gsk_unit_test"
    assert secrets_store.delete_secret("GROQ_API_KEY") is True
    assert secrets_store.get_secret("GROQ_API_KEY") is None


def test_vault_value_wins_over_stale_env(monkeypatch):
    from core import secrets_store, config
    monkeypatch.setenv("OPENAI_API_KEY", "stale-env-value")
    assert config.get_openai_api_key() == "stale-env-value"
    secrets_store.set_secret("OPENAI_API_KEY", "fresh-vault-value")
    try:
        assert config.get_openai_api_key() == "fresh-vault-value"
    finally:
        secrets_store.delete_secret("OPENAI_API_KEY")


# ─── Settings ────────────────────────────────────────────────────────────────

@pytest.fixture
def clean_settings():
    f = paths.settings_file()
    f.unlink(missing_ok=True)
    yield f
    f.unlink(missing_ok=True)


def test_settings_roundtrip_and_precedence(clean_settings, monkeypatch):
    from core import settings, config
    monkeypatch.setenv("GROQ_MODEL", "env-model")
    assert config.get_groq_model() == "env-model"
    settings.update_settings({"groq_model": "settings-model", "primary_engine": "groq"})
    assert config.get_groq_model() == "settings-model"
    assert config.get_primary_engine() == "groq"
    settings.update_settings({"groq_model": None})
    assert config.get_groq_model() == "env-model"


def test_settings_validation(clean_settings):
    from pydantic import ValidationError
    from core import settings
    with pytest.raises(ValidationError):
        settings.update_settings({"primary_engine": "skynet"})
    with pytest.raises(ValidationError):
        settings.update_settings({"llm_timeout_seconds": 1})


def test_corrupt_settings_fall_back_to_defaults(clean_settings):
    from core import settings
    clean_settings.write_text("{oops", encoding="utf-8")
    assert settings.load_settings() == settings.Settings()


def test_settings_api_never_returns_secret_values(clean_settings):
    from api.server import app
    from api.auth import create_access_token
    from core import secrets_store
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token()[0]}"}

    assert client.get("/settings").status_code == 401

    put = client.put("/settings/secrets", json={"name": "GEMINI_API_KEY", "value": "AIza-unit-test-value"}, headers=headers)
    assert put.status_code == 200
    assert "AIza-unit-test-value" not in put.text
    try:
        got = client.get("/settings", headers=headers)
        assert got.status_code == 200
        body = got.json()
        assert body["secrets_configured"]["GEMINI_API_KEY"] is True
        assert "AIza-unit-test-value" not in got.text

        assert client.put("/settings/secrets", json={"name": "PATH", "value": "x"}, headers=headers).status_code == 400
        assert client.put("/settings", json={"primary_engine": "nope"}, headers=headers).status_code == 422
        ok = client.put("/settings", json={"gemini_model": "gemini-2.5-pro"}, headers=headers)
        assert ok.status_code == 200 and ok.json()["settings"]["gemini_model"] == "gemini-2.5-pro"
    finally:
        secrets_store.delete_secret("GEMINI_API_KEY")


# ─── Prompt composer ─────────────────────────────────────────────────────────

def test_project_brain_notes_are_developer_opt_in(monkeypatch):
    from core.prompts.composer import PromptComposer
    monkeypatch.delenv("JARVIS_INCLUDE_PROJECT_BRAIN", raising=False)
    prompt = PromptComposer().compose_for_chat(tool_categories={"web": ["web_search"]}, has_memory=True)
    assert "PROJECT BRAIN" not in prompt
    if (paths.PROJECT_ROOT / "brain" / "architecture.md").exists():
        monkeypatch.setenv("JARVIS_INCLUDE_PROJECT_BRAIN", "1")
        prompt = PromptComposer().compose_for_chat(tool_categories={"web": ["web_search"]}, has_memory=True)
        assert "PROJECT BRAIN" in prompt


# ─── OS adapter ──────────────────────────────────────────────────────────────

def test_notification_text_is_passed_via_environment(monkeypatch):
    import subprocess
    from core import os_adapter
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"], captured["env"] = cmd, kwargs.get("env", {})

        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(os_adapter, "IS_WINDOWS", True)
    title, message = 'Pay "rent" & $bills', "`whoami`; exit"
    os_adapter.show_notification(title, message, background=False)
    assert title not in captured["cmd"][3] and message not in captured["cmd"][3]
    assert captured["env"]["JARVIS_NOTIFY_TITLE"] == title
    assert captured["env"]["JARVIS_NOTIFY_MSG"] == message


# ─── COM safety & dependency manifest ────────────────────────────────────────

def test_com_tools_never_attach_to_users_office_instance():
    src = (paths.PROJECT_ROOT / "tools" / "com_tools.py").read_text(encoding="utf-8")
    assert 'Dispatch("Excel.Application")' not in src.replace("DispatchEx", "")
    assert 'DispatchEx("Excel.Application")' in src
    assert 'DispatchEx("Word.Application")' in src


def test_dependency_manifest_lists_previously_missing_imports():
    text = (paths.PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for dep in ("httpx", "pywin32", "pywinauto", "pyperclip", "openpyxl", "edge-tts", "faster-whisper"):
        assert dep in text, dep
    assert (paths.PROJECT_ROOT / "uv.lock").exists()


def test_memory_encryption_key_is_dpapi_protected():
    from core.security import EncryptionEngine, KEY_FILE
    engine = EncryptionEngine()
    token = engine.encrypt("private note")
    if os.name == "nt":
        assert KEY_FILE.read_bytes().startswith(b"DPAPI1:")
    assert EncryptionEngine().decrypt(token) == "private note"
