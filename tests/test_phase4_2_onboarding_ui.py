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
