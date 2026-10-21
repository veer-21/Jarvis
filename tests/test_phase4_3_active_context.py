"""
JARVIS — Phase 4.3 Test Suite: Active Window & Screen Context
Tests foreground window inspection, OCR fallback safety, deictic phrase recognition,
deterministic DAG plan formation, security compliance, and ResultVerifier validation.
"""

import sys
import pytest
from unittest.mock import MagicMock, patch

from tools.context_tools import get_active_window_context
from core.brain.context_tracker import ContextTracker
from core.brain.verifier import ResultVerifier, VerificationLevel
from core.security import SecurityGuard, RiskLevel, guard, owner_auth
from core.brain.assistant_orchestrator import AssistantOrchestrator, TaskStatus


# ─── 1. Context Tools Direct Invocation Tests ─────────────────────────────────

def test_get_active_window_context_live_or_fallback():
    """Verify get_active_window_context returns all contract keys on the current system."""
    res = get_active_window_context(include_ocr=False, include_clipboard=False)
    assert isinstance(res, dict)
    assert res.get("success") is True
    assert "window_title" in res
    assert "process_name" in res
    assert "pid" in res
    assert "clipboard_text" in res
    assert "ocr_text" in res
    assert "has_selection" in res
    assert "summary" in res
    assert res["ocr_text"] == ""
    assert res["clipboard_text"] == ""


def test_get_active_window_context_flags():
    """Verify include_ocr and include_clipboard flags toggle extraction."""
    with patch("pyperclip.paste", return_value="Selected text for test"):
        res = get_active_window_context(include_ocr=False, include_clipboard=True)
        assert res["success"] is True
        assert res["clipboard_text"] == "Selected text for test"
        assert res["has_selection"] is True


def test_get_active_window_context_sensitive_masking():
    """Verify secret tokens in clipboard or window title are masked before returning."""
    leak_token = "sk-1234567890abcdef1234567890abcdef12345678"
    with patch("pyperclip.paste", return_value=f"Token: {leak_token}"):
        res = get_active_window_context(include_ocr=False, include_clipboard=True)
        assert leak_token not in res["clipboard_text"]
        assert leak_token not in res["summary"]
        assert "[MASKED_TOKEN]" in res["clipboard_text"]


def test_get_active_window_context_headless_safety():
    """Verify that when GetForegroundWindow returns 0 (e.g. CI or headless), fallback succeeds."""
    if sys.platform == "win32":
        with patch("ctypes.windll.user32.GetForegroundWindow", return_value=0):
            res = get_active_window_context(include_ocr=False, include_clipboard=False)
            assert res["success"] is True
            assert res["window_title"] == "Desktop / Active Workspace"
            assert res["process_name"] == "explorer.exe"


def test_get_active_window_context_ocr_exception_safety():
    """Verify OCR or screenshot failures do not crash the tool and return graceful empty OCR."""
    with patch("tools.context_tools._extract_ocr_from_image", side_effect=RuntimeError("OCR failure")):
        res = get_active_window_context(include_ocr=True, include_clipboard=False)
        assert res["success"] is True
        assert res["ocr_text"] == ""


# ─── 2. ContextTracker Deictic Pattern & Cache Tests ─────────────────────────

def test_context_tracker_deictic_patterns():
    """Verify ContextTracker detects deictic screen/window query patterns."""
    tracker = ContextTracker()

    deictic_queries = [
        "What's on my screen?",
        "Read my screen",
        "Summarize what's on my screen",
        "Explain this window",
        "Summarize this window",
        "Draft a reply to this",
        "Help me reply to this",
        "What does this error mean?",
        "Look at my screen",
        "Summarize this",
        "Explain this",
    ]

    for q in deictic_queries:
        assert tracker.is_active_context_request(q) is True, f"Failed to match: {q}"

    non_deictic_queries = [
        "What is the capital of France?",
        "Open notepad and write notes",
        "Search the web for python 3.12 release notes",
        "Empty the recycle bin",
        "List all files in Downloads",
    ]

    for q in non_deictic_queries:
        assert tracker.is_active_context_request(q) is False, f"False positive on: {q}"


def test_context_tracker_window_context_cache():
    """Verify ContextTracker can store and retrieve cached window context."""
    tracker = ContextTracker()
    assert tracker.get_window_context() is None

    mock_ctx = {
        "window_title": "Visual Studio Code - main.py",
        "process_name": "Code.exe",
        "pid": 5432,
        "ocr_text": "def test_example(): pass"
    }
    tracker.set_window_context(mock_ctx)
    cached = tracker.get_window_context()
    assert cached is not None
    assert cached["process_name"] == "Code.exe"
    assert cached["pid"] == 5432


# ─── 3. ResultVerifier Post-Condition Tests ─────────────────────────────────

def test_result_verifier_active_window_context():
    """Verify ResultVerifier supports and validates get_active_window_context at LEVEL_2."""
    assert ResultVerifier.get_tool_verification_level("get_active_window_context") == VerificationLevel.LEVEL_2

    success_raw = {
        "success": True,
        "window_title": "Slack - General",
        "process_name": "slack.exe",
        "pid": 9876,
        "clipboard_text": "",
        "ocr_text": "Team standup at 10 AM",
        "has_selection": False,
        "summary": "Active window: Slack - General"
    }
    res = ResultVerifier.verify_tool_result("get_active_window_context", {}, success_raw)
    assert res.verified is True
    assert res.level == VerificationLevel.LEVEL_2
    assert res.evidence["process_name"] == "slack.exe"

    failure_raw = {"success": False, "error": "Access denied to window manager"}
    err_res = ResultVerifier.verify_tool_result("get_active_window_context", {}, failure_raw)
    assert err_res.verified is False
    assert err_res.level == VerificationLevel.LEVEL_1


# ─── 4. Security Policy & Permissions Tests ──────────────────────────────────

def test_security_guard_evaluates_read_only():
    """Verify SecurityGuard evaluates get_active_window_context as READ_ONLY without confirmation."""
    allowed, effective_risk, requires_conf, reason = guard.evaluate_tool_execution(
        "get_active_window_context",
        {"include_ocr": True, "include_clipboard": True},
        declared_risk=RiskLevel.READ_ONLY,
        interactive=True
    )
    assert allowed is True
    assert effective_risk == RiskLevel.READ_ONLY
    assert requires_conf is False


# ─── 5. AssistantOrchestrator Plan Decomposition & Execution Tests ───────────

def test_orchestrator_heuristic_plan_decomposition_for_screen_queries():
    """Verify AssistantOrchestrator generates a 2-step DAG for deictic screen queries."""
    orchestrator = AssistantOrchestrator(brain=None)
    steps = orchestrator._heuristic_plan_decomposition("What does this error mean?")
    
    assert len(steps) == 2
    assert steps[0].step_id == "step_1"
    assert steps[0].tool_name == "get_active_window_context"
    assert steps[0].capability == "everyday"
    assert steps[0].input_variables == {"include_ocr": True, "include_clipboard": True}
    assert steps[0].dependencies == []

    assert steps[1].step_id == "step_2"
    assert steps[1].capability == "reasoning"
    assert steps[1].dependencies == ["step_1"]


def test_orchestrator_end_to_end_screen_context_execution():
    """Verify AssistantOrchestrator executes get_active_window_context and caches context."""
    from core.brain.tool_router import ToolRouter

    tools = ToolRouter()
    mock_ctx_data = {
        "success": True,
        "window_title": "Stack Overflow - TypeError in Python",
        "process_name": "chrome.exe",
        "pid": 3210,
        "clipboard_text": "TypeError: unsupported operand type(s)",
        "ocr_text": "Traceback (most recent call last):\nTypeError",
        "has_selection": True,
        "summary": "Active window: Stack Overflow"
    }
    tools.register_callable(
        lambda include_ocr=True, include_clipboard=True: mock_ctx_data,
        name="get_active_window_context",
        category="everyday",
        risk_level=RiskLevel.READ_ONLY,
        requires_confirmation=False
    )

    mock_reasoning = MagicMock()
    mock_reasoning.generate_text.return_value = "The error indicates a type mismatch in your Python operation."

    mock_brain = MagicMock()
    mock_brain.tools = tools
    mock_brain.reasoning = mock_reasoning
    mock_brain.memory_manager = None
    mock_brain.intent_classifier = None

    orchestrator = AssistantOrchestrator(brain=mock_brain)
    response = orchestrator.process("What does this error mean?")

    assert "The error indicates a type mismatch" in response
    cached = orchestrator.context_tracker.get_window_context()
    assert cached is not None
    assert cached["process_name"] == "chrome.exe"
    assert cached["window_title"] == "Stack Overflow - TypeError in Python"
