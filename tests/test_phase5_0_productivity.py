"""
JARVIS Phase 5.0 — Personal Productivity Suite & Consumer Launchers Test Suite
Tests for:
1. manage_personal_notes_and_todos (add, list, complete, delete, fuzzy match, persistence)
2. generate_daily_briefing inclusion of pending to-dos
3. smart_clipboard_assistant (read, write, history ring-buffer, sensitive data masking)
4. read_and_summarize_webpage (clean text extraction, clutter removal, character capping)
5. AssistantOrchestrator heuristic routing for to-dos, clipboard, and webpages
6. ResultVerifier Level 2 post-conditions for Phase 5.0 everyday tools
7. SecurityGuard risk tier gating (READ_ONLY vs LOW_RISK)
8. FastAPI /tasks/todos REST endpoints
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from tools.everyday_tools import (
    manage_personal_notes_and_todos,
    smart_clipboard_assistant,
    read_and_summarize_webpage,
    generate_daily_briefing,
    PERSONAL_TODOS_FILE,
    _CLIPBOARD_HISTORY,
    _todos_lock,
    _clipboard_lock,
)
from core.brain.assistant_orchestrator import AssistantOrchestrator
from core.brain.verifier import ResultVerifier, VerificationLevel, TOOL_LEVEL_REGISTRY
from core.security import guard, RiskLevel
from api.server import app, set_server_brain
from api.auth import create_access_token
from core.brain import Brain
from core.memory import JarvisMemory


@pytest.fixture(autouse=True)
def clean_todos_and_clipboard():
    """Backup and restore personal_todos.json and clipboard history for isolated tests."""
    backup_data = None
    if PERSONAL_TODOS_FILE.exists():
        try:
            with open(PERSONAL_TODOS_FILE, "r", encoding="utf-8") as f:
                backup_data = f.read()
        except Exception:
            backup_data = None

    with _todos_lock:
        PERSONAL_TODOS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PERSONAL_TODOS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    with _clipboard_lock:
        _CLIPBOARD_HISTORY.clear()

    yield

    with _todos_lock:
        if backup_data is not None:
            with open(PERSONAL_TODOS_FILE, "w", encoding="utf-8") as f:
                f.write(backup_data)
        elif PERSONAL_TODOS_FILE.exists():
            PERSONAL_TODOS_FILE.unlink(missing_ok=True)

    with _clipboard_lock:
        _CLIPBOARD_HISTORY.clear()


# ─── Test 1: To-Dos CRUD Lifecycle ──────────────────────────────────────────

def test_todos_crud_lifecycle():
    # 1. Add to-do
    res_add = manage_personal_notes_and_todos(
        action="add",
        title="Buy groceries for dinner",
        category="todo"
    )
    assert res_add["success"] is True
    assert res_add["action"] == "add"
    assert res_add["category"] == "todo"
    todo_id = res_add["item_id"]
    assert todo_id.startswith("todo_")

    # 2. List to-dos
    res_list = manage_personal_notes_and_todos(action="list")
    assert res_list["success"] is True
    assert res_list["pending_todos_count"] == 1
    assert res_list["pending_todos"][0]["item_id"] == todo_id
    assert res_list["pending_todos"][0]["status"] == "pending"

    # 3. Complete to-do
    res_comp = manage_personal_notes_and_todos(action="complete", item_id=todo_id)
    assert res_comp["success"] is True
    assert res_comp["action"] == "complete"
    assert res_comp["status"] == "completed"

    # Verify completed status
    res_list2 = manage_personal_notes_and_todos(action="list")
    assert res_list2["pending_todos_count"] == 0
    assert len(res_list2["completed_todos"]) == 1
    assert res_list2["completed_todos"][0]["status"] == "completed"

    # 4. Delete to-do
    res_del = manage_personal_notes_and_todos(action="delete", item_id=todo_id)
    assert res_del["success"] is True
    assert res_del["action"] == "delete"

    # Verify empty
    res_list3 = manage_personal_notes_and_todos(action="list")
    assert res_list3["total_items"] == 0


# ─── Test 2: Quick Notes Lifecycle ──────────────────────────────────────────

def test_notes_crud_lifecycle():
    res_note = manage_personal_notes_and_todos(
        action="add",
        content="Meeting with frontend team on Thursday at 2 PM",
        category="note"
    )
    assert res_note["success"] is True
    assert res_note["category"] == "note"
    note_id = res_note["item_id"]
    assert note_id.startswith("note_")

    res_list = manage_personal_notes_and_todos(action="list")
    assert len(res_list["notes"]) == 1
    assert res_list["notes"][0]["item_id"] == note_id

    res_del = manage_personal_notes_and_todos(action="delete", item_id=note_id)
    assert res_del["success"] is True


# ─── Test 3: Fuzzy Matching for Completion and Deletion ─────────────────────

def test_todos_fuzzy_completion_and_deletion():
    manage_personal_notes_and_todos(action="add", title="Schedule doctor appointment")
    manage_personal_notes_and_todos(action="add", title="Pay electricity bill")

    # Complete by substring
    res_comp = manage_personal_notes_and_todos(action="complete", content="doctor appointment")
    assert res_comp["success"] is True
    assert res_comp["status"] == "completed"

    # Delete by substring
    res_del = manage_personal_notes_and_todos(action="delete", content="electricity")
    assert res_del["success"] is True

    res_list = manage_personal_notes_and_todos(action="list")
    assert res_list["pending_todos_count"] == 0


# ─── Test 4: To-Dos Validation & Error Handling ─────────────────────────────

def test_todos_validation_and_errors():
    # Missing content
    res_empty = manage_personal_notes_and_todos(action="add", content="")
    assert res_empty["success"] is False
    assert "required" in res_empty["error"]

    # Unknown action
    res_invalid = manage_personal_notes_and_todos(action="unknown_action")
    assert res_invalid["success"] is False
    assert "Unknown action" in res_invalid["error"]

    # Non-existent item
    res_not_found = manage_personal_notes_and_todos(action="complete", item_id="non_existent_123")
    assert res_not_found["success"] is False


# ─── Test 5: Daily Briefing Includes Pending To-Dos ─────────────────────────

def test_daily_briefing_includes_todos():
    manage_personal_notes_and_todos(action="add", title="Refactor authentication layer")
    manage_personal_notes_and_todos(action="add", title="Review pull request #42")

    briefing = generate_daily_briefing(city="auto")
    assert briefing["success"] is True
    briefing_text = briefing.get("briefing_text") or str(briefing)

    # Verify to-dos are represented
    assert "Pending To-Do Items" in briefing_text
    assert "Refactor authentication layer" in briefing_text
    assert "Review pull request #42" in briefing_text


# ─── Test 6: Smart Clipboard Write and Read ─────────────────────────────────

def test_smart_clipboard_write_and_read():
    test_msg = "JARVIS clipboard testing payload 2026"
    res_write = smart_clipboard_assistant(action="write", text_to_copy=test_msg)
    assert res_write["success"] is True
    assert res_write["action"] == "write"
    assert res_write["character_count"] == len(test_msg)

    res_read = smart_clipboard_assistant(action="read")
    assert res_read["success"] is True
    assert res_read["action"] == "read"
    assert res_read["character_count"] >= len(test_msg)


# ─── Test 7: Clipboard History Ring Buffer & Sensitive Data Masking ──────────

def test_smart_clipboard_history_ring_buffer_and_masking():
    # Fill buffer with 15 items including API keys
    for i in range(12):
        if i == 5:
            # Sensitive key
            smart_clipboard_assistant(action="write", text_to_copy="API key is sk-1234567890abcdef12345678")
        else:
            smart_clipboard_assistant(action="write", text_to_copy=f"Item number {i}")

    res_hist = smart_clipboard_assistant(action="history")
    assert res_hist["success"] is True
    assert res_hist["count"] <= 10  # Max 10 items in ring-buffer
    
    # Check that sensitive pattern is masked
    history_texts = [h["text"] for h in res_hist["history"]]
    for txt in history_texts:
        assert "sk-1234567890abcdef12345678" not in txt


# ─── Test 8: Clipboard Error Handling ───────────────────────────────────────

def test_smart_clipboard_error_handling():
    res_invalid = smart_clipboard_assistant(action="invalid_cmd")
    assert res_invalid["success"] is False
    assert "Unknown action" in res_invalid["error"]

    res_empty_write = smart_clipboard_assistant(action="write", text_to_copy=None, content=None)
    assert res_empty_write["success"] is False


# ─── Test 9: Webpage Reading & Clutter Removal ──────────────────────────────

def test_read_and_summarize_webpage_extraction():
    fake_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Modern AI Operating Systems</title></head>
    <body>
        <nav><a href="/home">Home</a><a href="/login">Login</a></nav>
        <header><h1>Welcome to AI OS</h1></header>
        <article>
            <p>Artificial intelligence systems are rapidly evolving into autonomous personal assistants.</p>
            <p>JARVIS v3.0 introduces everyday productivity and active context capabilities.</p>
        </article>
        <script>console.log("tracking");</script>
        <style>body { color: red; }</style>
        <footer>Copyright 2026 All Rights Reserved</footer>
    </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.text = fake_html
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.Session.get", return_value=mock_resp):
        res = read_and_summarize_webpage(url="https://example.com/ai-os-article")
        assert res["success"] is True
        assert res["title"] == "Modern AI Operating Systems"
        assert res["word_count"] > 10
        assert "Artificial intelligence systems are rapidly evolving" in res["extracted_text"]
        assert "console.log" not in res["extracted_text"]
        assert "body { color: red; }" not in res["extracted_text"]


# ─── Test 10: Webpage Error Handling ────────────────────────────────────────

def test_read_and_summarize_webpage_errors():
    res_empty = read_and_summarize_webpage(url="")
    assert res_empty["success"] is False

    with patch("requests.Session.get", side_effect=Exception("Connection refused")):
        res_fail = read_and_summarize_webpage(url="https://non-existent-domain-xyz.local")
        assert res_fail["success"] is False
        assert "Failed to fetch" in res_fail["error"]


# ─── Test 11: Orchestrator Heuristic Routing for To-Dos ─────────────────────

def test_orchestrator_routing_for_todos():
    ao = AssistantOrchestrator()

    # Add to-do
    plan_add = ao._heuristic_plan_decomposition("Add buy groceries to my to-do list")
    assert len(plan_add) >= 1
    assert plan_add[0].tool_name == "manage_personal_notes_and_todos"
    assert plan_add[0].input_variables["action"] == "add"

    # Show to-dos
    plan_list = ao._heuristic_plan_decomposition("Show my to-do list")
    assert len(plan_list) >= 1
    assert plan_list[0].tool_name == "manage_personal_notes_and_todos"
    assert plan_list[0].input_variables["action"] == "list"

    # Complete to-do
    plan_comp = ao._heuristic_plan_decomposition("Mark buy groceries as done")
    assert len(plan_comp) >= 1
    assert plan_comp[0].tool_name == "manage_personal_notes_and_todos"
    assert plan_comp[0].input_variables["action"] == "complete"

    # Delete to-do
    plan_del = ao._heuristic_plan_decomposition("Delete buy groceries from my to-do list")
    assert len(plan_del) >= 1
    assert plan_del[0].tool_name == "manage_personal_notes_and_todos"
    assert plan_del[0].input_variables["action"] == "delete"


# ─── Test 12: Orchestrator Heuristic Routing for Clipboard ──────────────────

def test_orchestrator_routing_for_clipboard():
    ao = AssistantOrchestrator()

    # Read clipboard
    plan_read = ao._heuristic_plan_decomposition("What's on my clipboard?")
    assert len(plan_read) == 1
    assert plan_read[0].tool_name == "smart_clipboard_assistant"
    assert plan_read[0].input_variables["action"] == "read"

    # Write clipboard
    plan_write = ao._heuristic_plan_decomposition("Copy this secret code to clipboard: Alpha123")
    assert len(plan_write) == 1
    assert plan_write[0].tool_name == "smart_clipboard_assistant"
    assert plan_write[0].input_variables["action"] == "write"

    # Clipboard history
    plan_hist = ao._heuristic_plan_decomposition("Show my clipboard history")
    assert len(plan_hist) == 1
    assert plan_hist[0].tool_name == "smart_clipboard_assistant"
    assert plan_hist[0].input_variables["action"] == "history"


# ─── Test 13: Orchestrator Heuristic Routing for Webpages ────────────────────

def test_orchestrator_routing_for_webpages():
    ao = AssistantOrchestrator()

    plan_web = ao._heuristic_plan_decomposition("Summarize https://github.com/features/actions")
    assert len(plan_web) == 2
    assert plan_web[0].tool_name == "read_and_summarize_webpage"
    assert "https://github.com/features/actions" in plan_web[0].input_variables["url"]
    assert plan_web[1].capability == "reasoning"
    assert plan_web[1].dependencies == ["step_1"]


# ─── Test 14: SecurityGuard Risk Tier Classification ────────────────────────

def test_security_guard_risk_levels_for_phase5_tools():
    # manage_personal_notes_and_todos
    assert guard.evaluate_tool_execution("manage_personal_notes_and_todos", {"action": "list"})[1] == RiskLevel.READ_ONLY
    assert guard.evaluate_tool_execution("manage_personal_notes_and_todos", {"action": "add"})[1] == RiskLevel.LOW_RISK
    assert guard.evaluate_tool_execution("manage_personal_notes_and_todos", {"action": "complete"})[1] == RiskLevel.LOW_RISK
    assert guard.evaluate_tool_execution("manage_personal_notes_and_todos", {"action": "delete"})[1] == RiskLevel.LOW_RISK

    # smart_clipboard_assistant
    assert guard.evaluate_tool_execution("smart_clipboard_assistant", {"action": "read"})[1] == RiskLevel.READ_ONLY
    assert guard.evaluate_tool_execution("smart_clipboard_assistant", {"action": "history"})[1] == RiskLevel.READ_ONLY
    assert guard.evaluate_tool_execution("smart_clipboard_assistant", {"action": "write"})[1] == RiskLevel.LOW_RISK

    # read_and_summarize_webpage
    assert guard.evaluate_tool_execution("read_and_summarize_webpage", {"url": "https://example.com"})[1] == RiskLevel.READ_ONLY


# ─── Test 15: ResultVerifier Level 2 Checks ──────────────────────────────────

def test_result_verifier_for_phase5_tools():
    verifier = ResultVerifier()

    # Ensure all 3 tools are registered at LEVEL_2
    assert TOOL_LEVEL_REGISTRY.get("manage_personal_notes_and_todos") == VerificationLevel.LEVEL_2
    assert TOOL_LEVEL_REGISTRY.get("smart_clipboard_assistant") == VerificationLevel.LEVEL_2
    assert TOOL_LEVEL_REGISTRY.get("read_and_summarize_webpage") == VerificationLevel.LEVEL_2

    # Verification of manage_personal_notes_and_todos
    valid_todo_res = {
        "success": True,
        "action": "add",
        "item_id": "todo_1234",
        "content": "Verify Level 2",
        "category": "todo"
    }
    v1 = verifier.verify_tool_result("manage_personal_notes_and_todos", {"action": "add"}, valid_todo_res)
    assert v1.verified is True

    # Verification of smart_clipboard_assistant
    valid_clip_res = {
        "success": True,
        "action": "read",
        "content": "Test payload",
        "character_count": 12
    }
    v2 = verifier.verify_tool_result("smart_clipboard_assistant", {"action": "read"}, valid_clip_res)
    assert v2.verified is True

    # Verification of read_and_summarize_webpage
    valid_web_res = {
        "success": True,
        "url": "https://example.com",
        "extracted_text": "Sample article text",
        "character_count": 19
    }
    v3 = verifier.verify_tool_result("read_and_summarize_webpage", {"url": "https://example.com"}, valid_web_res)
    assert v3.verified is True


# ─── Test 16: API /tasks/todos REST Endpoints ───────────────────────────────

def test_api_todos_endpoints():
    memory = JarvisMemory()
    brain = Brain(memory=memory)
    set_server_brain(brain, memory)
    client = TestClient(app)

    token_owner, _ = create_access_token(subject="owner")
    headers = {"Authorization": f"Bearer {token_owner}"}

    # 1. POST /tasks/todos
    resp_create = client.post(
        "/tasks/todos",
        json={"title": "Prepare presentation slides", "notes": "Include metrics", "category": "work"},
        headers=headers
    )
    assert resp_create.status_code == 200
    data_create = resp_create.json()
    assert data_create["success"] is True
    item_id = data_create["item_id"]

    # 2. GET /tasks/todos
    resp_get = client.get("/tasks/todos", headers=headers)
    assert resp_get.status_code == 200
    data_get = resp_get.json()
    assert data_get["success"] is True
    assert data_get["pending_todos_count"] >= 1

    # 3. POST /tasks/todos/{item_id}/complete
    resp_comp = client.post(f"/tasks/todos/{item_id}/complete", headers=headers)
    assert resp_comp.status_code == 200
    assert resp_comp.json()["status"] == "completed"

    # 4. DELETE /tasks/todos/{item_id}
    resp_del = client.delete(f"/tasks/todos/{item_id}", headers=headers)
    assert resp_del.status_code == 200
    assert resp_del.json()["success"] is True

    # 5. GET /health
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["healthy"] is True
