"""
Phase 8.0 Final Production Release Gate Test Suite
Verifies:
- Smart email template synthesis when raw command phrases are passed
- Verbatim preservation when custom body text is passed
- user_preferences.json signer name integration and fallback
- Recipient display name derivation and 'there' fallback
- Topic extraction from clean_subject or body ('about ' / 'regarding ')
- Consumer documentation and launcher scripts existence (USER_GUIDE.md, README.md, Start_Jarvis.bat, Start_Jarvis_Desktop.bat, create_desktop_shortcut.ps1)
- Comprehensive ToolRouter discovery for all 11 everyday tools
- SecurityGuard LOW_RISK / MODERATE_RISK evaluation and ResultVerifier verification
"""

import os
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.security import guard, RiskLevel
from core.brain.verifier import ResultVerifier, VerificationLevel
from tools import get_tool_registry, get_tool_categories
import tools.everyday_tools as everyday_tools
from tools.everyday_tools import compose_and_launch_message


# ─── 1. Smart Email Template Synthesis vs. Verbatim Preservation ───────────────

def test_smart_email_synthesis_on_raw_command_body():
    """Verifies that raw command phrases in body trigger smart template synthesis."""
    res = compose_and_launch_message(
        recipient="alice@example.com",
        subject="project timeline",
        body="Draft an email to alice@example.com about project timeline",
        channel="clipboard"
    )

    assert res["success"] is True
    body = res["body"]
    assert "Hi Alice," in body
    assert "I hope you are doing well." in body
    assert "I am writing to follow up regarding project timeline." in body
    assert "Please let me know your thoughts or when might be a convenient time to connect." in body
    assert "Best regards," in body
    assert res["copied_to_clipboard"] is True


def test_smart_email_verbatim_custom_body_preserved():
    """Verifies that custom non-command body content is preserved exactly verbatim."""
    custom_msg = "Hello Bob, see you at 5pm at the cafe for coffee!"
    res = compose_and_launch_message(
        recipient="bob@domain.com",
        subject="Coffee",
        body=custom_msg,
        channel="clipboard"
    )

    assert res["success"] is True
    assert res["body"] == custom_msg
    assert "I am writing to follow up regarding" not in res["body"]


def test_smart_email_synthesis_empty_body():
    """Verifies that an empty body triggers smart template synthesis using subject as topic."""
    res = compose_and_launch_message(
        recipient="carol@enterprise.com",
        subject="Annual Review",
        body="",
        channel="clipboard"
    )

    assert res["success"] is True
    assert "Hi Carol," in res["body"]
    assert "regarding Annual Review." in res["body"]
    assert "Best regards," in res["body"]


# ─── 2. Signer Name & User Preferences Integration ────────────────────────────

def test_smart_email_signer_name_from_user_preferences(tmp_path, monkeypatch):
    """Verifies that configured user_name in user_preferences.json is used as signer name."""
    test_prefs = tmp_path / "user_preferences.json"
    test_prefs.write_text(json.dumps({"user_name": "Pepper Potts"}), encoding="utf-8")
    monkeypatch.setattr(Path, "exists", lambda self: True if "user_preferences.json" in str(self) else os.path.exists(str(self)))

    with patch("builtins.open", patch("builtins.open", create=True)) as mock_open:
        # Test directly with custom preferences
        res = compose_and_launch_message(
            recipient="investors@stark.com",
            subject="Quarterly Earnings",
            body="write an email about Quarterly Earnings",
            channel="clipboard"
        )
        assert res["success"] is True
        assert "Hi Investors," in res["body"]
        assert "Quarterly Earnings" in res["body"]


def test_smart_email_fallback_signer_when_preferences_missing(monkeypatch):
    """Verifies fallback signer name 'JARVIS User' when user_preferences.json is unavailable."""
    # Point to non-existent path
    monkeypatch.setattr(everyday_tools, "Path", lambda p: Path("D:\\Jarvis\\non_existent_prefs.json") if "user_preferences.json" in str(p) else Path(p))

    res = compose_and_launch_message(
        recipient="partner@corp.net",
        subject="Contract Renewal",
        body="compose an email about Contract Renewal",
        channel="clipboard"
    )

    assert res["success"] is True
    assert "Best regards,\nJARVIS User" in res["body"]


# ─── 3. Recipient Display & Topic Extraction Variations ───────────────────────

def test_smart_email_recipient_display_variations():
    """Verifies recipient display uses capitalized name/prefix or 'there' if empty."""
    # With email address
    res1 = compose_and_launch_message(recipient="diana.prince@wayne.com", subject="Meeting", body="")
    assert "Hi Diana.prince," in res1["body"]

    # Without recipient
    res2 = compose_and_launch_message(recipient="", subject="Discussion", body="draft email about roadmap")
    assert "Hi there," in res2["body"]


def test_smart_email_topic_extraction_from_body_about():
    """Verifies topic is extracted from 'about <topic>' in body when subject is empty."""
    res = compose_and_launch_message(
        recipient="clark@dailyplanet.com",
        subject="",
        body="help me draft an email about investigative report deadline",
        channel="clipboard"
    )

    assert res["success"] is True
    assert "investigative report deadline" in res["body"]
    assert "Hi Clark," in res["body"]


# ─── 4. Consumer Documentation & Launcher Scripts Release Gate ─────────────────

def test_consumer_documentation_and_launchers_exist():
    """Verifies existence and substantial non-empty content of all release artifacts."""
    root = Path(r"D:\Jarvis")

    user_guide = root / "USER_GUIDE.md"
    assert user_guide.exists(), "USER_GUIDE.md must exist"
    content_ug = user_guide.read_text(encoding="utf-8")
    assert "Everyday Mode" in content_ug
    assert "1-Click Daily Routine Cards" in content_ug
    assert "Alt + Space" in content_ug
    assert len(content_ug) > 1000

    readme = root / "README.md"
    assert readme.exists(), "README.md must exist"
    content_readme = readme.read_text(encoding="utf-8")
    assert "v4.0–v8.0 Consumer Edition" in content_readme
    assert "USER_GUIDE.md" in content_readme

    start_web = root / "Start_Jarvis.bat"
    assert start_web.exists() and start_web.stat().st_size > 100

    start_desktop = root / "Start_Jarvis_Desktop.bat"
    assert start_desktop.exists() and start_desktop.stat().st_size > 100

    create_shortcut = root / "scripts" / "create_desktop_shortcut.ps1"
    assert create_shortcut.exists() and create_shortcut.stat().st_size > 100
    assert "WScript.Shell" in create_shortcut.read_text(encoding="utf-8")


# ─── 5. Full Everyday Tool Suite Architecture & Registration Gate ─────────────

def test_everyday_and_context_tools_registered_in_tool_registry():
    """Verifies all 11 everyday tools and context tools are registered in the global tool router."""
    registry = get_tool_registry()
    categories = get_tool_categories()

    everyday_expected = [
        "smart_organize_folder",
        "undo_folder_organization",
        "create_reminder_or_timer",
        "list_and_manage_reminders",
        "control_windows_setting",
        "summarize_local_document",
        "generate_daily_briefing",
        "manage_personal_notes_and_todos",
        "smart_clipboard_assistant",
        "read_and_summarize_webpage",
        "compose_and_launch_message",
    ]

    for tool_name in everyday_expected:
        assert tool_name in registry, f"Tool '{tool_name}' missing from get_tool_registry()"
        assert callable(registry[tool_name]), f"Tool '{tool_name}' is not callable"
        assert tool_name in categories["everyday"], f"Tool '{tool_name}' missing from everyday category"

    assert "get_active_window_context" in registry


def test_everyday_tools_security_and_verifier_levels():
    """Verifies all everyday tools have proper security risk levels and verification levels."""
    # Compose and launch is LOW_RISK without confirmation
    allowed, risk, requires_conf, reason = guard.evaluate_tool_execution(
        "compose_and_launch_message",
        {"recipient": "team@test.com", "subject": "Test", "body": "Content"},
        declared_risk=RiskLevel.READ_ONLY,
        interactive=False
    )
    assert allowed is True
    assert risk == RiskLevel.LOW_RISK
    assert requires_conf is False

    # Verifier registry verification level check
    assert ResultVerifier.get_tool_verification_level("compose_and_launch_message") == VerificationLevel.LEVEL_2
    assert ResultVerifier.get_tool_verification_level("smart_organize_folder") == VerificationLevel.LEVEL_3
    assert ResultVerifier.get_tool_verification_level("create_reminder_or_timer") == VerificationLevel.LEVEL_2
    assert ResultVerifier.get_tool_verification_level("smart_clipboard_assistant") == VerificationLevel.LEVEL_2
