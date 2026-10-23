"""
Phase 7.0 Reliability & Everyday Comms Automated Test Suite
Validates:
- restore_pending_reminders_on_startup() for future and overdue reminders
- compose_and_launch_message() clipboard copying, URL encoding for Gmail & mailto
- SecurityGuard LOW_RISK permission gating
- ResultVerifier LEVEL_2 verification
- AssistantOrchestrator heuristic plan routing for drafting emails/messages
- Existence and syntax of scripts/create_desktop_shortcut.ps1
- Auto-discovery in get_tool_registry() and get_tool_categories()
"""

import os
import sys
import time
import json
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.security import guard, RiskLevel
from core.brain.verifier import ResultVerifier, VerificationLevel
from core.brain.assistant_orchestrator import AssistantOrchestrator
from tools import get_tool_registry, get_tool_categories
import tools.everyday_tools as everyday_tools
from tools.everyday_tools import (
    restore_pending_reminders_on_startup,
    compose_and_launch_message,
    _active_timer_threads,
    _reminders_lock,
)


@pytest.fixture(autouse=True)
def cleanup_active_timers():
    """Ensure no background timers leak between test cases."""
    yield
    with _reminders_lock:
        for tid, timer in list(_active_timer_threads.items()):
            try:
                timer.cancel()
            except Exception:
                pass
        _active_timer_threads.clear()


# ─── 1. Reminder Recovery on Startup ──────────────────────────────────────────

def test_restore_pending_reminders_future(tmp_path, monkeypatch):
    """Verifies that future pending reminders are correctly rescheduled as threading.Timer."""
    test_reminders_file = tmp_path / "reminders.json"
    now = time.time()
    future_data = [
        {
            "reminder_id": "rem_future_01",
            "title": "Drink Water",
            "message": "Stay hydrated",
            "duration_seconds": 300,
            "trigger_epoch": now + 200,
            "status": "pending"
        }
    ]
    test_reminders_file.write_text(json.dumps(future_data), encoding="utf-8")
    monkeypatch.setattr(everyday_tools, "REMINDERS_FILE", test_reminders_file)

    res = restore_pending_reminders_on_startup()

    assert res["restored_count"] == 1
    assert res["triggered_overdue_count"] == 0
    assert "rem_future_01" in everyday_tools._active_timer_threads
    # Clean up
    everyday_tools._active_timer_threads["rem_future_01"].cancel()


def test_restore_pending_reminders_overdue(tmp_path, monkeypatch):
    """Verifies that overdue pending reminders (remaining <= 1s) trigger background action without being lost."""
    test_reminders_file = tmp_path / "reminders.json"
    now = time.time()
    overdue_data = [
        {
            "reminder_id": "rem_overdue_01",
            "title": "Meeting Alert",
            "message": "Team standup was scheduled",
            "duration_seconds": 60,
            "trigger_epoch": now - 30,  # 30 seconds overdue
            "status": "pending"
        }
    ]
    test_reminders_file.write_text(json.dumps(overdue_data), encoding="utf-8")
    monkeypatch.setattr(everyday_tools, "REMINDERS_FILE", test_reminders_file)

    mock_trigger = MagicMock()
    monkeypatch.setattr(everyday_tools, "_trigger_reminder_action", mock_trigger)

    res = restore_pending_reminders_on_startup()

    assert res["restored_count"] == 0
    assert res["triggered_overdue_count"] == 1
    assert "rem_overdue_01" not in everyday_tools._active_timer_threads


def test_restore_pending_reminders_mixed_and_non_pending(tmp_path, monkeypatch):
    """Verifies proper partitioning of mixed future, overdue, and non-pending reminders."""
    test_reminders_file = tmp_path / "reminders.json"
    now = time.time()
    mixed_data = [
        {
            "reminder_id": "rem_future_02",
            "title": "Upcoming Event",
            "message": "In 5 minutes",
            "trigger_epoch": now + 300,
            "status": "pending"
        },
        {
            "reminder_id": "rem_overdue_02",
            "title": "Past Event",
            "message": "Should have triggered",
            "trigger_epoch": now - 10,
            "status": "pending"
        },
        {
            "reminder_id": "rem_already_done",
            "title": "Completed",
            "message": "Already finished",
            "trigger_epoch": now - 100,
            "status": "triggered"
        }
    ]
    test_reminders_file.write_text(json.dumps(mixed_data), encoding="utf-8")
    monkeypatch.setattr(everyday_tools, "REMINDERS_FILE", test_reminders_file)

    mock_trigger = MagicMock()
    monkeypatch.setattr(everyday_tools, "_trigger_reminder_action", mock_trigger)

    res = restore_pending_reminders_on_startup()

    assert res["restored_count"] == 1
    assert res["triggered_overdue_count"] == 1
    assert "rem_future_02" in everyday_tools._active_timer_threads
    everyday_tools._active_timer_threads["rem_future_02"].cancel()


# ─── 2. compose_and_launch_message Tool Tests ─────────────────────────────────

def test_compose_and_launch_message_clipboard_only():
    """Verifies message drafting and clipboard copying without opening external clients."""
    result = compose_and_launch_message(
        recipient="alice@example.com",
        subject="Project Status",
        body="Dear Alice,\nThe project is progressing according to schedule.\nBest regards.",
        channel="clipboard",
        open_client=False
    )

    assert result["success"] is True
    assert result["recipient"] == "alice@example.com"
    assert result["subject"] == "Project Status"
    assert "progressing according to schedule" in result["body"]
    assert result["copied_to_clipboard"] is True
    assert result["client_launched"] is False
    assert result["url"] == ""


def test_compose_and_launch_message_gmail_url_encoding(monkeypatch):
    """Verifies that the Gmail compose URL correctly quotes recipient, subject, and body."""
    mock_browser = MagicMock()
    monkeypatch.setattr("webbrowser.open", mock_browser)

    recip = "partner.acme@domain.org"
    subj = "Q4 Financials: Review & Sign"
    body = "Please review the financial spreadsheet attached:\n- Item 1: OK\n- Item 2: Ready"

    result = compose_and_launch_message(
        recipient=recip,
        subject=subj,
        body=body,
        channel="gmail",
        open_client=True
    )

    assert result["success"] is True
    assert result["open_client"] is True
    assert result["client_launched"] is True
    assert result["channel"] == "gmail"

    url = result["url"]
    assert url.startswith("https://mail.google.com/mail/?view=cm&fs=1&to=")
    assert f"to={urllib.parse.quote(recip)}" in url
    assert f"su={urllib.parse.quote(subj)}" in url
    assert f"body={urllib.parse.quote(body)}" in url
    mock_browser.assert_called_once_with(url)


def test_compose_and_launch_message_mailto_url_encoding(monkeypatch):
    """Verifies that mailto channel generates a compliant mailto link with encoded parameters."""
    mock_browser = MagicMock()
    monkeypatch.setattr("webbrowser.open", mock_browser)

    recip = "support@service.io"
    subj = "Issue Report #402"
    body = "Steps to reproduce: 1. Click button. 2. Observe error."

    result = compose_and_launch_message(
        recipient=recip,
        subject=subj,
        body=body,
        channel="mailto",
        open_client=True
    )

    assert result["success"] is True
    assert result["client_launched"] is True
    assert result["url"].startswith("mailto:support@service.io?")
    assert f"subject={urllib.parse.quote(subj)}" in result["url"]
    assert f"body={urllib.parse.quote(body)}" in result["url"]
    mock_browser.assert_called_once_with(result["url"])


def test_compose_and_launch_message_email_alias(monkeypatch):
    """Verifies channel='email' defaults to the standard mailto scheme."""
    mock_browser = MagicMock()
    monkeypatch.setattr("webbrowser.open", mock_browser)

    result = compose_and_launch_message(
        recipient="hr@company.com",
        subject="Leave Application",
        body="Applying for PTO tomorrow.",
        channel="email",
        open_client=True
    )

    assert result["success"] is True
    assert result["url"].startswith("mailto:hr@company.com?")
    mock_browser.assert_called_once_with(result["url"])


def test_compose_and_launch_message_empty_body_fallback():
    """Verifies that when body is empty, formatted_body synthesizes a professional template."""
    result = compose_and_launch_message(
        recipient="leads@sales.com",
        subject="Product Inquiry",
        body="",
        channel="clipboard"
    )

    assert result["success"] is True
    assert "Product Inquiry" in result["body"]
    assert "Hi Leads" in result["body"]
    assert result["copied_to_clipboard"] is True


# ─── 3. SecurityGuard & ResultVerifier Verification ───────────────────────────

def test_compose_and_launch_security_guard_low_risk():
    """Verifies SecurityGuard classifies compose_and_launch_message as LOW_RISK without blocking."""
    allowed, effective_risk, requires_conf, reason = guard.evaluate_tool_execution(
        "compose_and_launch_message",
        {"recipient": "colleague@work.com", "subject": "Hello", "body": "Checking in", "channel": "gmail"},
        declared_risk=RiskLevel.READ_ONLY,
        interactive=False
    )

    assert allowed is True
    assert effective_risk == RiskLevel.LOW_RISK
    assert requires_conf is False


def test_compose_and_launch_result_verifier_level_2():
    """Verifies ResultVerifier validates compose_and_launch_message at LEVEL_2."""
    level = ResultVerifier.get_tool_verification_level("compose_and_launch_message")
    assert level == VerificationLevel.LEVEL_2

    # Successful verification
    good_raw = {
        "success": True,
        "recipient": "test@domain.com",
        "channel": "gmail",
        "copied_to_clipboard": True,
        "message": "Message drafted and copied to clipboard."
    }
    ver_res = ResultVerifier.verify_tool_result("compose_and_launch_message", {}, good_raw)
    assert ver_res.verified is True
    assert ver_res.level == VerificationLevel.LEVEL_2
    assert ver_res.evidence["channel"] == "gmail"

    # Failed verification
    bad_raw = {"success": False, "error": "Clipboard unavailable"}
    fail_res = ResultVerifier.verify_tool_result("compose_and_launch_message", {}, bad_raw)
    assert fail_res.verified is False
    assert fail_res.level == VerificationLevel.LEVEL_1


# ─── 4. AssistantOrchestrator Routing Heuristics ──────────────────────────────

def test_orchestrator_routes_draft_email_to():
    """Verifies heuristic decomposition matches 'draft an email to <recipient> about <subject>'."""
    orch = AssistantOrchestrator(None)
    plan = orch._heuristic_plan_decomposition("draft an email to boss@company.com about quarterly budget review")

    assert len(plan) == 1
    step = plan[0]
    assert step.tool_name == "compose_and_launch_message"
    assert step.input_variables["recipient"] == "boss@company.com"
    assert step.input_variables["subject"] == "quarterly budget review"


def test_orchestrator_routes_write_email_about():
    """Verifies heuristic decomposition matches 'write an email about <topic>'."""
    orch = AssistantOrchestrator(None)
    plan = orch._heuristic_plan_decomposition("write an email about project deployment timeline")

    assert len(plan) == 1
    step = plan[0]
    assert step.tool_name == "compose_and_launch_message"
    assert "project deployment timeline" in step.input_variables["subject"]


def test_orchestrator_routes_compose_message_to():
    """Verifies heuristic decomposition matches 'compose a message to <name> regarding <topic>'."""
    orch = AssistantOrchestrator(None)
    plan = orch._heuristic_plan_decomposition("compose a message to Sarah regarding team sync agenda")

    assert len(plan) == 1
    step = plan[0]
    assert step.tool_name == "compose_and_launch_message"
    assert step.input_variables["recipient"] == "Sarah"
    assert "team sync agenda" in step.input_variables["subject"]


# ─── 5. Windows Desktop Shortcut Generator Script ─────────────────────────────

def test_create_desktop_shortcut_script_exists_and_valid():
    """Verifies scripts/create_desktop_shortcut.ps1 exists and uses WScript.Shell with proper target."""
    script_path = Path(r"D:\Jarvis\scripts\create_desktop_shortcut.ps1")
    assert script_path.exists(), "scripts/create_desktop_shortcut.ps1 must exist"

    content = script_path.read_text(encoding="utf-8")
    assert "WScript.Shell" in content
    assert "CreateShortcut" in content
    assert "JARVIS AI Assistant.lnk" in content
    assert "Start_Jarvis.bat" in content
    assert "shell32.dll" in content


# ─── 6. Tool Discovery & Registry Invariants ─────────────────────────────────

def test_tool_registry_and_categories_contain_compose_tool():
    """Verifies compose_and_launch_message is registered across discovery mechanisms."""
    registry = get_tool_registry()
    assert "compose_and_launch_message" in registry
    assert callable(registry["compose_and_launch_message"])

    categories = get_tool_categories()
    assert "everyday" in categories
    assert "compose_and_launch_message" in categories["everyday"]
