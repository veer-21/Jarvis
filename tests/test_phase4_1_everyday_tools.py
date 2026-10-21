"""
Test Suite for JARVIS Phase 4.1 Everyday Consumer Tools & Verification
Validates:
- smart_organize_folder (dry-run, execution, collision handling)
- undo_folder_organization (rollback, cleanup)
- create_reminder_or_timer (persistence, scheduling)
- list_and_manage_reminders (list, cancel, clear)
- control_windows_setting (volume, clipboard, risk gating)
- summarize_local_document (txt, md, csv, docx fallback)
- generate_daily_briefing (system metrics, weather, reminders aggregation)
- ResultVerifier deterministic post-conditions
- IntentClassifier & AssistantOrchestrator everyday DAG routing
"""

import os
import sys
import json
import zipfile
import tempfile
import pytest
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.security import guard, RiskLevel
from core.brain.verifier import ResultVerifier, VerificationLevel
from core.brain.intent_classifier import IntentClassifier
from core.brain.assistant_orchestrator import AssistantOrchestrator
from tools.everyday_tools import (
    smart_organize_folder, undo_folder_organization,
    create_reminder_or_timer, list_and_manage_reminders,
    control_windows_setting, summarize_local_document,
    generate_daily_briefing, REMINDERS_FILE
)


@pytest.fixture
def temp_test_dir():
    """Create a temporary directory with test files and tear it down after test."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# ─── 1. Smart Organize Folder Tests ───────────────────────────────────────────

def test_smart_organize_folder_dry_run(temp_test_dir):
    # Setup test files
    (temp_test_dir / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    (temp_test_dir / "photo.png").write_text("dummy png", encoding="utf-8")
    (temp_test_dir / "script.py").write_text("print('hi')", encoding="utf-8")
    (temp_test_dir / "song.mp3").write_text("audio", encoding="utf-8")

    res = smart_organize_folder(str(temp_test_dir), dry_run=True)
    assert res["success"] is True
    assert res["dry_run"] is True
    assert res["total_files_identified"] == 4

    # Files must NOT be moved in dry-run
    assert (temp_test_dir / "report.pdf").exists()
    assert (temp_test_dir / "photo.png").exists()
    assert not (temp_test_dir / "Documents").exists()


def test_smart_organize_folder_real_and_collision(temp_test_dir):
    # Setup test files
    (temp_test_dir / "notes.txt").write_text("my notes", encoding="utf-8")
    (temp_test_dir / "logo.jpg").write_text("logo img", encoding="utf-8")
    (temp_test_dir / "archive.zip").write_text("zip data", encoding="utf-8")

    # Run organization
    res = smart_organize_folder(str(temp_test_dir), dry_run=False)
    assert res["success"] is True
    assert res["total_organized"] == 3
    assert (temp_test_dir / "Documents" / "notes.txt").exists()
    assert (temp_test_dir / "Images" / "logo.jpg").exists()
    assert (temp_test_dir / "Installers_Archives" / "archive.zip").exists()
    assert (temp_test_dir / "undo_manifest.json").exists()

    # Test collision auto-increment
    (temp_test_dir / "notes.txt").write_text("new notes file", encoding="utf-8")
    res2 = smart_organize_folder(str(temp_test_dir), dry_run=False)
    assert res2["success"] is True
    assert res2["total_organized"] == 1
    assert (temp_test_dir / "Documents" / "notes (1).txt").exists()


def test_undo_folder_organization(temp_test_dir):
    (temp_test_dir / "doc1.pdf").write_text("pdf 1", encoding="utf-8")
    (temp_test_dir / "doc2.docx").write_text("docx 2", encoding="utf-8")

    # Organize
    smart_organize_folder(str(temp_test_dir), dry_run=False)
    assert not (temp_test_dir / "doc1.pdf").exists()
    assert (temp_test_dir / "Documents" / "doc1.pdf").exists()

    # Undo
    undo_res = undo_folder_organization(str(temp_test_dir))
    assert undo_res["success"] is True
    assert undo_res["files_restored"] == 2
    assert (temp_test_dir / "doc1.pdf").exists()
    assert (temp_test_dir / "doc2.docx").exists()
    assert not (temp_test_dir / "Documents").exists()  # Empty folder cleaned up
    assert not (temp_test_dir / "undo_manifest.json").exists()


def test_undo_missing_manifest(temp_test_dir):
    undo_res = undo_folder_organization(str(temp_test_dir))
    assert undo_res["success"] is False
    assert "No undo_manifest.json found" in undo_res["error"]


# ─── 2. Reminder & Timer Tests ───────────────────────────────────────────────

def test_create_reminder_or_timer():
    res = create_reminder_or_timer(title="Test Reminder", trigger_in_seconds=300, message="Testing reminder system")
    assert res["success"] is True
    rem_id = res["reminder_id"]
    assert rem_id.startswith("rem_")

    # Assert persisted in file
    assert REMINDERS_FILE.exists()
    with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        matched = [r for r in data if r.get("reminder_id") == rem_id]
        assert len(matched) == 1
        assert matched[0]["status"] == "pending"


def test_list_and_manage_reminders():
    # 1. Create a reminder
    c_res = create_reminder_or_timer(title="Meeting", trigger_in_seconds=600)
    rem_id = c_res["reminder_id"]

    # 2. List reminders
    l_res = list_and_manage_reminders(action="list")
    assert l_res["success"] is True
    assert any(r["reminder_id"] == rem_id for r in l_res["active_reminders"])

    # 3. Cancel reminder
    cancel_res = list_and_manage_reminders(action="cancel", reminder_id=rem_id)
    assert cancel_res["success"] is True
    assert cancel_res["reminder_id"] == rem_id

    # 4. Verify cancelled status
    l_res2 = list_and_manage_reminders(action="list")
    assert not any(r["reminder_id"] == rem_id for r in l_res2["active_reminders"])

    # 5. Clear cancelled reminders
    clear_res = list_and_manage_reminders(action="clear")
    assert clear_res["success"] is True


# ─── 3. Control Windows Setting Tests ─────────────────────────────────────────

def test_control_windows_setting_volume_and_mute():
    res_up = control_windows_setting("volume_up")
    assert res_up["success"] is True
    assert res_up["setting"] == "volume_up"

    res_down = control_windows_setting("volume_down")
    assert res_down["success"] is True

    res_mute = control_windows_setting("mute_toggle")
    assert res_mute["success"] is True


def test_control_windows_setting_clipboard():
    test_str = "JARVIS_PHASE_4_1_CLIPBOARD_TEST_VAL"
    set_res = control_windows_setting("clipboard_set", value=test_str)
    assert set_res["success"] is True

    get_res = control_windows_setting("clipboard_get")
    assert get_res["success"] is True
    assert get_res["content"] == test_str


def test_control_windows_setting_security_risk_gating():
    # empty_recycle_bin must be graded as HIGH_RISK and require confirmation
    allowed, risk, req_conf, reason = guard.evaluate_tool_execution(
        "control_windows_setting", {"setting": "empty_recycle_bin"}, interactive=False
    )
    assert risk == RiskLevel.HIGH_RISK
    assert req_conf is True
    assert allowed is False  # In unattended mode, HIGH_RISK is blocked

    # volume_up must be LOW_RISK and not require confirmation
    allowed_v, risk_v, req_conf_v, _ = guard.evaluate_tool_execution(
        "control_windows_setting", {"setting": "volume_up"}, interactive=False
    )
    assert risk_v == RiskLevel.LOW_RISK
    assert req_conf_v is False
    assert allowed_v is True


# ─── 4. Document Summarization Tests ──────────────────────────────────────────

def test_summarize_local_document_txt_and_md(temp_test_dir):
    doc_path = temp_test_dir / "project_brief.md"
    doc_path.write_text("# Project Roadmap\nThis is a test project roadmap for everyday users.", encoding="utf-8")

    res = summarize_local_document(str(doc_path))
    assert res["success"] is True
    assert res["filename"] == "project_brief.md"
    assert res["word_count"] > 5
    assert "roadmap" in res["extracted_text"].lower()


def test_summarize_local_document_csv(temp_test_dir):
    csv_path = temp_test_dir / "data.csv"
    csv_path.write_text("Name,Age,Role\nAlice,30,Engineer\nBob,35,Designer", encoding="utf-8")

    res = summarize_local_document(str(csv_path))
    assert res["success"] is True
    assert "Alice" in res["extracted_text"]
    assert "Engineer" in res["extracted_text"]


def test_summarize_local_document_docx_xml_fallback(temp_test_dir):
    # Construct a minimal docx zip containing word/document.xml
    docx_path = temp_test_dir / "contract.docx"
    doc_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>Confidential Agreement for Phase 4.1 Development.</w:t></w:r></w:p>
      </w:body>
    </w:document>"""
    with zipfile.ZipFile(docx_path, "w") as z:
        z.writestr("word/document.xml", doc_xml)

    res = summarize_local_document(str(docx_path))
    assert res["success"] is True
    assert "Confidential Agreement" in res["extracted_text"]


def test_summarize_local_document_missing_file():
    res = summarize_local_document("non_existent_doc_12345.pdf")
    assert res["success"] is False
    assert "not found" in res["error"].lower()


# ─── 5. Daily Briefing Tests ─────────────────────────────────────────────────

def test_generate_daily_briefing():
    res = generate_daily_briefing()
    assert res["success"] is True
    assert "datetime" in res
    assert "system_health" in res
    assert "cpu_percent" in res["system_health"]
    assert "ram_percent" in res["system_health"]
    assert "briefing_markdown" in res
    assert "# 🌅 Good Day" in res["briefing_markdown"]


# ─── 6. ResultVerifier Post-Condition Tests ───────────────────────────────────

def test_result_verifier_for_everyday_tools(temp_test_dir):
    # Test smart_organize_folder verifier
    (temp_test_dir / "doc.pdf").write_text("content", encoding="utf-8")
    org_res = smart_organize_folder(str(temp_test_dir), dry_run=False)
    v_org = ResultVerifier.verify_tool_result("smart_organize_folder", {"directory_path": str(temp_test_dir)}, org_res)
    assert v_org.verified is True
    assert v_org.level == VerificationLevel.LEVEL_3

    # Test create_reminder_or_timer verifier
    rem_res = create_reminder_or_timer(title="Verifier Test", trigger_in_seconds=120)
    v_rem = ResultVerifier.verify_tool_result("create_reminder_or_timer", {"title": "Verifier Test"}, rem_res)
    assert v_rem.verified is True
    assert v_rem.level == VerificationLevel.LEVEL_2

    # Test summarize_local_document verifier
    md_file = temp_test_dir / "note.md"
    md_file.write_text("Quick test notes", encoding="utf-8")
    doc_res = summarize_local_document(str(md_file))
    v_doc = ResultVerifier.verify_tool_result("summarize_local_document", {"file_path": str(md_file)}, doc_res)
    assert v_doc.verified is True
    assert v_doc.level == VerificationLevel.LEVEL_2


# ─── 7. IntentClassifier Everyday Intents ────────────────────────────────────

def test_intent_classifier_everyday_intents():
    ic = IntentClassifier()

    match_org = ic.classify("Clean up my Downloads folder")
    assert match_org is not None
    assert match_org[0] == "smart_organize_folder"
    assert match_org[1]["directory_path"].lower() == "downloads"

    match_rem = ic.classify("Remind me in 10 minutes to check the oven")
    assert match_rem is not None
    assert match_rem[0] == "create_reminder_or_timer"
    assert match_rem[1]["trigger_in_seconds"] == 600
    assert "check the oven" in match_rem[1]["title"].lower()

    match_list_rem = ic.classify("List my reminders")
    assert match_list_rem is not None
    assert match_list_rem[0] == "list_and_manage_reminders"

    match_brief = ic.classify("Give me my daily briefing")
    assert match_brief is not None
    assert match_brief[0] == "generate_daily_briefing"

    match_recycle = ic.classify("empty recycle bin")
    assert match_recycle is not None
    assert match_recycle[0] == "control_windows_setting"
    assert match_recycle[1]["setting"] == "empty_recycle_bin"

    match_clip = ic.classify("read clipboard")
    assert match_clip is not None
    assert match_clip[0] == "control_windows_setting"
    assert match_clip[1]["setting"] == "clipboard_get"


# ─── 8. AssistantOrchestrator Everyday Plans ──────────────────────────────────

def test_assistant_orchestrator_everyday_plans():
    ao = AssistantOrchestrator()

    # Plan for folder organization
    plan_org = ao._heuristic_plan_decomposition("Clean up my Downloads folder")
    assert len(plan_org) >= 1
    assert plan_org[0].tool_name == "smart_organize_folder"
    assert plan_org[0].input_variables["directory_path"] == "Downloads"

    # Plan for reminder
    plan_rem = ao._heuristic_plan_decomposition("Remind me in 10 minutes to check the oven")
    assert len(plan_rem) == 1
    assert plan_rem[0].tool_name == "create_reminder_or_timer"
    assert plan_rem[0].input_variables["trigger_in_seconds"] == 600

    # Plan for daily briefing
    plan_brief = ao._heuristic_plan_decomposition("Give me my daily briefing")
    assert len(plan_brief) >= 1
    assert plan_brief[0].tool_name == "generate_daily_briefing"

    # Plan for mute volume
    plan_mute = ao._heuristic_plan_decomposition("Mute my volume")
    assert len(plan_mute) == 1
    assert plan_mute[0].tool_name == "control_windows_setting"
    assert plan_mute[0].input_variables["setting"] == "mute_toggle"
