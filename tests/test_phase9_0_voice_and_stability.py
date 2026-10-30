"""
Phase 9.0 Voice Mode, WebSocket Stability & Test Isolation Test Suite
Validates:
1. generate_text() never invokes _execute_fallback_with_tools() or mutates _session_histories.
2. _create_plan() routes everyday and system commands via heuristics without blocking on _create_plan_general().
3. POST /voice/toggle lazily initializes _voice_mgr without returning 503.
4. POST /voice/listen records, transcribes, routes through brain, and returns response.
5. POST /tasks/reset-state cancels active tasks, clears session histories, and purges test reminders.
6. GET /onboarding/diagnostics flags llm_ready = False when mock or placeholder keys are present.
7. Running the test suite leaves .env and reminders.json completely clean.
"""

import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.brain.reasoning_engine import ReasoningEngine
from core.brain.assistant_orchestrator import AssistantOrchestrator
from core.brain.task_model import TaskStep
from core.brain import Brain
from core.memory import JarvisMemory
from api.server import app, set_server_brain
from api.auth import create_access_token
import api.server as server_module
from tools.everyday_tools import REMINDERS_FILE


@pytest.fixture(autouse=True)
def isolate_phase9_environment():
    """Ensure .env, reminders.json, and personal_todos.json are backed up and restored."""
    env_file = PROJECT_ROOT / ".env"
    env_bak = env_file.read_text(encoding="utf-8") if env_file.exists() else None

    reminders_bak = REMINDERS_FILE.read_text(encoding="utf-8") if REMINDERS_FILE.exists() else None
    todos_file = PROJECT_ROOT / "data" / "tasks" / "personal_todos.json"
    todos_bak = todos_file.read_text(encoding="utf-8") if todos_file.exists() else None

    orig_env = dict(os.environ)

    yield

    os.environ.clear()
    os.environ.update(orig_env)

    if env_bak is not None:
        env_file.write_text(env_bak, encoding="utf-8")

    if reminders_bak is not None:
        REMINDERS_FILE.write_text(reminders_bak, encoding="utf-8")
    elif REMINDERS_FILE.exists():
        try:
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            cleaned = [r for r in data if not any(k in r.get("title", "") for k in ("Test Reminder", "Verifier Test", "Meeting"))]
            with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2)
        except Exception:
            pass

    if todos_bak is not None:
        todos_file.write_text(todos_bak, encoding="utf-8")


@pytest.fixture
def test_setup():
    memory = JarvisMemory()
    brain = Brain(memory=memory)
    set_server_brain(brain, memory)
    client = TestClient(app)
    token, _ = create_access_token(subject="owner", session_id="test_sess_p9")
    return {
        "client": client,
        "token": token,
        "brain": brain,
        "headers": {"Authorization": f"Bearer {token}"}
    }


def test_generate_text_never_calls_fallback_with_tools():
    """Verifies generate_text() never invokes _execute_fallback_with_tools() or mutates session histories."""
    engine = ReasoningEngine(api_key="mock_key", model_name="gemini-2.5-flash")
    session_key = "default:default"
    initial_history = [{"role": "user", "content": "Previous sensitive task"}]
    engine._session_histories[session_key] = list(initial_history)

    # Mock _execute_fallback_with_tools to ensure it is never called
    mock_fallback_tools = MagicMock()
    engine._execute_fallback_with_tools = mock_fallback_tools

    # Force Gemini generation failure
    if engine._client:
        engine._client.models.generate_content = MagicMock(side_effect=Exception("Gemini quota 429"))

    with patch.object(engine, "groq_key", None):
        result = engine.generate_text("Generate a multi-step plan")

    assert mock_fallback_tools.call_count == 0
    assert engine._session_histories[session_key] == initial_history
    assert result == ""


def test_create_plan_heuristic_order():
    """Verifies _create_plan() routes everyday and system tools immediately without LLM planning."""
    memory = JarvisMemory()
    brain = Brain(memory=memory)
    orchestrator = brain.orchestrator

    mock_general_planner = MagicMock()
    orchestrator._create_plan_general = mock_general_planner

    # 1. Reminder command
    plan_rem = orchestrator._create_plan("Remind me in 10 minutes to stretch", "command")
    assert len(plan_rem) == 1
    assert plan_rem[0].tool_name == "create_reminder_or_timer"
    assert mock_general_planner.call_count == 0

    # 2. To-do command
    plan_todo = orchestrator._create_plan("Add buy groceries to my to-do list", "command")
    assert len(plan_todo) == 1
    assert plan_todo[0].tool_name == "manage_personal_notes_and_todos"
    assert mock_general_planner.call_count == 0

    # 3. Clipboard command
    plan_clip = orchestrator._create_plan("What is on my clipboard?", "command")
    assert len(plan_clip) == 1
    assert plan_clip[0].tool_name == "smart_clipboard_assistant"
    assert mock_general_planner.call_count == 0

    # 4. Single app launch
    plan_app = orchestrator._create_plan("Open notepad", "command")
    assert len(plan_app) == 2
    assert plan_app[0].tool_name == "open_application"
    assert mock_general_planner.call_count == 0

    # 5. Multi-step explicit workflow SHOULD consult general planner when requested
    orchestrator._create_plan("First search the docs, and then compile a summary report", "task")
    assert mock_general_planner.call_count == 1


def test_voice_toggle_lazy_initialization(test_setup):
    """Verifies POST /voice/toggle lazily initializes _voice_mgr without returning 503."""
    client = test_setup["client"]
    headers = test_setup["headers"]

    server_module._voice_mgr = None

    # First toggle: should initialize and start
    res1 = client.post("/voice/toggle", headers=headers)
    assert res1.status_code == 200
    assert server_module._voice_mgr is not None
    assert server_module._voice_mgr.is_running is True

    # Second toggle: should pause
    res2 = client.post("/voice/toggle", headers=headers)
    assert res2.status_code == 200
    assert server_module._voice_mgr.is_running is False

    # Cleanup
    if server_module._voice_mgr:
        server_module._voice_mgr.stop()
        server_module._voice_mgr = None


def test_voice_listen_endpoint(test_setup):
    """Verifies POST /voice/listen captures microphone input and returns brain response."""
    client = test_setup["client"]
    headers = test_setup["headers"]

    with patch("core.voice.VoiceInterface.listen", return_value="What is system status?"), \
         patch("core.voice.VoiceInterface.speak", return_value=True):
        res = client.post("/voice/listen", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["transcript"] == "What is system status?"
        assert "response" in data and len(data["response"]) > 0


def test_tasks_reset_state_endpoint(test_setup):
    """Verifies POST /tasks/reset-state cancels tasks, clears session histories, and purges test reminders."""
    client = test_setup["client"]
    headers = test_setup["headers"]

    # Inject test reminders
    test_reminders = [
        {"reminder_id": "rem_test_1", "title": "Test Reminder", "status": "pending"},
        {"reminder_id": "rem_test_2", "title": "Verifier Test", "status": "pending"},
        {"reminder_id": "rem_valid_1", "title": "Real Reminder", "status": "pending"},
    ]
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(test_reminders, f, indent=2)

    res = client.post("/tasks/reset-state", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

    # Verify reminders.json is cleansed of test entries
    with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
        remaining = json.load(f)
    remaining_titles = [r.get("title") for r in remaining]
    assert "Test Reminder" not in remaining_titles
    assert "Verifier Test" not in remaining_titles
    assert "Real Reminder" in remaining_titles


def test_diagnostics_flags_mock_and_placeholder_keys(test_setup, monkeypatch):
    """Verifies GET /onboarding/diagnostics flags llm_ready = False when mock key is configured."""
    client = test_setup["client"]
    headers = test_setup["headers"]

    # Clear diagnostics cache
    server_module._DIAGNOSTICS_CACHE["data"] = None

    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTestMockKey999888")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OLLAMA_HOST", "")

    res = client.get("/onboarding/diagnostics", headers=headers)
    assert res.status_code == 200
    diag = res.json()
    assert diag["llm_ready"] is False
    assert diag["diagnostics"]["llm"]["ready"] is False


def test_voice_tts_fast_and_non_blocking(test_setup):
    """
    Verifies that POST /voice/tts completes in <2 seconds without deadlocking
    the async event loop and without re-initializing WhisperModel.
    """
    import time
    client = test_setup["client"]
    headers = test_setup["headers"]

    # Provide a mock voice interface to verify no Whisper re-init and fast non-blocking response
    mock_voice = MagicMock()
    mock_voice._speak_windows_sapi = MagicMock(return_value=True)
    server_module._voice_interface_singleton = mock_voice

    start_time = time.time()
    res = client.post("/voice/tts", json={"text": "**Hello**, this is a *fast* non-blocking TTS test."}, headers=headers)
    elapsed = time.time() - start_time

    assert res.status_code == 200
    assert elapsed < 2.0
    assert mock_voice._last_spoken_text == "Hello, this is a fast non-blocking TTS test."
    assert res.json()["success"] is True

