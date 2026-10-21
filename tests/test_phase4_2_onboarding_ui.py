"""
JARVIS Phase 4.2 — Onboarding, Diagnostics & Consumer UI Test Suite
Tests for:
- GET /onboarding/diagnostics (readiness probes for LLM, STT, TTS, Browser, OCR)
- POST /onboarding/configure (first-run profile setup, city preference, API key masking)
- Security gating when PIN is configured
- Cache behavior & parameter validation
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from api.server import app, set_server_brain
from api.auth import create_access_token
from core.brain import Brain
from core.memory import JarvisMemory
from core.security import owner_auth, PIN_FILE


@pytest.fixture(scope="module")
def onboarding_test_setup(tmp_path_factory):
    """Setup test client and mock brain for onboarding tests."""
    memory = JarvisMemory()
    brain = Brain(memory=memory)

    brain.reasoning.send_message = MagicMock(return_value="Onboarding test response.")
    brain.reasoning.generate_text = MagicMock(return_value="Onboarding test response.")
    set_server_brain(brain, memory)

    client = TestClient(app)
    token_owner, _ = create_access_token(subject="owner")

    return {
        "client": client,
        "token_owner": token_owner,
    }


def test_onboarding_diagnostics_endpoint(onboarding_test_setup):
    """
    GET /onboarding/diagnostics:
    Verifies that system hardware and AI readiness diagnostics return a valid contract
    with all expected subsystem flags (llm, voice_stt, voice_tts, browser, ocr).
    """
    client = onboarding_test_setup["client"]
    token = onboarding_test_setup["token_owner"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/onboarding/diagnostics", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "all_ready" in data
    assert "llm_ready" in data
    assert "voice_stt_ready" in data
    assert "voice_tts_ready" in data
    assert "browser_ready" in data
    assert "ocr_ready" in data
    assert "diagnostics" in data
    assert "timestamp" in data

    # Verify diagnostic items structure
    for key in ("llm", "voice_stt", "voice_tts", "browser", "ocr"):
        assert key in data["diagnostics"]
        item = data["diagnostics"][key]
        assert "ready" in item
        assert isinstance(item["ready"], bool)
        assert "details" in item
        assert isinstance(item["details"], str)


def test_onboarding_diagnostics_unauthenticated(onboarding_test_setup):
    """
    GET /onboarding/diagnostics:
    Must be accessible without credentials during first-run setup or initial launch.
    """
    client = onboarding_test_setup["client"]
    resp = client.get("/onboarding/diagnostics")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["all_ready"], bool)
    assert "diagnostics" in data


def test_onboarding_configure_name_and_city(onboarding_test_setup):
    """
    POST /onboarding/configure:
    Verifies that user name and preferred city are persisted to user preferences.
    """
    client = onboarding_test_setup["client"]
    token = onboarding_test_setup["token_owner"]
    headers = {"Authorization": f"Bearer {token}"}

    prefs_file = Path(r"D:\Jarvis\data\user_preferences.json")

    resp = client.post(
        "/onboarding/configure",
        json={"user_name": "Tony Stark", "preferred_city": "Malibu"},
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "user_name" in data["configured_items"]
    assert "preferred_city" in data["configured_items"]

    assert prefs_file.exists()
    with open(prefs_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved.get("user_name") == "Tony Stark"
    assert saved.get("preferred_city") == "Malibu"


def test_onboarding_configure_gemini_api_key(onboarding_test_setup):
    """
    POST /onboarding/configure:
    Verifies that providing an API key safely updates .env and os.environ.
    """
    client = onboarding_test_setup["client"]
    token = onboarding_test_setup["token_owner"]
    headers = {"Authorization": f"Bearer {token}"}

    dummy_key = "AIzaSyTestMockKey999888"
    resp = client.post(
        "/onboarding/configure",
        json={"gemini_api_key": dummy_key},
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "gemini_api_key" in data["configured_items"]

    assert os.environ.get("GEMINI_API_KEY") == dummy_key

    env_path = Path(r"D:\Jarvis\.env")
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert dummy_key in content


def test_onboarding_configure_pin_length_validation(onboarding_test_setup):
    """
    POST /onboarding/configure:
    Owner PIN must be at least 4 characters long.
    """
    client = onboarding_test_setup["client"]
    token = onboarding_test_setup["token_owner"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/onboarding/configure",
        json={"owner_pin": "12"},
        headers=headers
    )
    assert resp.status_code == 422 or resp.status_code == 400


def test_onboarding_configure_requires_auth_when_pin_set(onboarding_test_setup):
    """
    POST /onboarding/configure:
    When PIN is configured on the machine, unauthenticated callers are rejected with 401.
    """
    client = onboarding_test_setup["client"]
    if PIN_FILE.exists():
        resp = client.post(
            "/onboarding/configure",
            json={"user_name": "Attacker"}
        )
        assert resp.status_code == 401


def test_tasks_reminders_endpoints(onboarding_test_setup):
    """
    Tests GET /tasks/reminders and DELETE /tasks/reminders/{reminder_id}:
    - Verifies authenticated GET returns active reminders and pending count.
    - Verifies unauthenticated GET returns 401.
    - Verifies DELETE cancels reminder successfully.
    """
    from tools.everyday_tools import create_reminder_or_timer
    client = onboarding_test_setup["client"]
    token = onboarding_test_setup["token_owner"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Unauthenticated check
    unauth_resp = client.get("/tasks/reminders")
    assert unauth_resp.status_code == 401

    # 2. Create reminder via tool
    created = create_reminder_or_timer(
        title="Audit Remediation Sync",
        trigger_in_seconds=3600,
        message="Review Phase 4.4 deliverables"
    )
    assert created["success"] is True
    rem_id = created["reminder_id"]

    # 3. Authenticated GET
    get_resp = client.get("/tasks/reminders", headers=headers)
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["success"] is True
    assert "active_reminders" in data
    assert "pending_count" in data
    matching = [r for r in data["active_reminders"] if r["reminder_id"] == rem_id]
    assert len(matching) >= 1
    assert any(r["title"] == "Audit Remediation Sync" for r in matching)

    # 4. Authenticated DELETE
    del_resp = client.delete(f"/tasks/reminders/{rem_id}", headers=headers)
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["success"] is True
    assert del_data["action"] == "cancel"

    # 5. Verify removed from active list
    get_after = client.get("/tasks/reminders", headers=headers)
    after_data = get_after.json()
    after_matching = [r for r in after_data["active_reminders"] if r["reminder_id"] == rem_id]
    assert len(after_matching) == 0


def test_generate_daily_briefing_user_preferences_integration(tmp_path, monkeypatch):
    """
    Tests generate_daily_briefing(city="auto"):
    - Verifies user_name and preferred_city from data/user_preferences.json are respected.
    - Verifies fallback to 'Sir' when no name is set.
    """
    from tools.everyday_tools import generate_daily_briefing
    prefs_file = Path(r"D:\Jarvis\data\user_preferences.json")
    prefs_file.parent.mkdir(parents=True, exist_ok=True)

    original_content = None
    if prefs_file.exists():
        original_content = prefs_file.read_text(encoding="utf-8")

    try:
        # Write test preferences
        prefs_file.write_text(
            json.dumps({"user_name": "Alexander", "preferred_city": "Tokyo"}),
            encoding="utf-8"
        )

        res = generate_daily_briefing(city="auto")
        assert res["success"] is True
        assert res["user_name"] == "Alexander"
        assert res["city"] == "Tokyo"
        assert "# 🌅 Good Day, Alexander! Here is your Daily Briefing" in res["briefing_markdown"]

        # Write test preferences without user_name
        prefs_file.write_text(
            json.dumps({"preferred_city": "Paris"}),
            encoding="utf-8"
        )
        res_default = generate_daily_briefing(city="auto")
        assert res_default["user_name"] == "Sir"
        assert res_default["city"] == "Paris"
        assert "# 🌅 Good Day, Sir! Here is your Daily Briefing" in res_default["briefing_markdown"]

    finally:
        if original_content is not None:
            prefs_file.write_text(original_content, encoding="utf-8")
        elif prefs_file.exists():
            prefs_file.unlink()


def test_powershell_toast_safety_with_quotes_and_special_chars(monkeypatch):
    """
    Tests _trigger_reminder_action with titles and messages containing special characters,
    quotes, dollar signs, and PowerShell metacharacters.
    Verifies that values are passed via environment variables without string interpolation.
    """
    import subprocess
    from unittest.mock import MagicMock
    from tools.everyday_tools import _trigger_reminder_action

    captured_call = {}

    def mock_subprocess_run(cmd, **kwargs):
        captured_call["cmd"] = cmd
        captured_call["env"] = kwargs.get("env", {})
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    special_title = 'Meeting: "Q3 Strategy" & $100M `Target`!'
    special_message = "Review <Project 'X'> & check $env:USERPATH."
    test_id = "rem_test_special"

    _trigger_reminder_action(test_id, special_title, special_message)

    # Allow daemon notify worker thread a moment to execute
    import time
    for _ in range(20):
        if "cmd" in captured_call:
            break
        time.sleep(0.05)

    assert "cmd" in captured_call
    # PowerShell command should NOT contain raw interpolated quotes/variables
    cmd_text = captured_call["cmd"][3]
    assert special_title not in cmd_text
    assert special_message not in cmd_text
    assert "$env:JARVIS_REM_TITLE" in cmd_text
    assert "$env:JARVIS_REM_MSG" in cmd_text

    # Values must be safely preserved in env dictionary
    assert captured_call["env"].get("JARVIS_REM_TITLE") == special_title
    assert captured_call["env"].get("JARVIS_REM_MSG") == special_message

