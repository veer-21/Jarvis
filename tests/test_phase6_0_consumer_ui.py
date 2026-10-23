"""
JARVIS Phase 6.0 — Consumer UI To-Do & Quick Notes Command Center Test Suite
Verifies:
1. desktop/src/App.jsx and ui/index.html Everyday Mode To-Dos & Reminders integration
2. desktop/dist/ production bundle verification
3. Full lifecycle of /tasks/todos API and inclusion in generate_daily_briefing()
4. Consumer launcher scripts (Start_Jarvis.bat & Start_Jarvis_Desktop.bat)
5. Export bundlers unique phase 6 naming (jarvis_phase6_verification.zip & jarvis_phase6_clean_source.zip)
"""

import os
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from api.server import app, set_server_brain
from api.auth import create_access_token
from core.brain import Brain
from core.memory import JarvisMemory
from tools.everyday_tools import (
    manage_personal_notes_and_todos,
    generate_daily_briefing,
    PERSONAL_TODOS_FILE,
    _todos_lock,
)

WORKSPACE_ROOT = Path(r"D:\Jarvis")


@pytest.fixture(autouse=True)
def clean_todos_store():
    """Ensure clean personal_todos.json for test isolation."""
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

    yield

    with _todos_lock:
        if backup_data is not None:
            with open(PERSONAL_TODOS_FILE, "w", encoding="utf-8") as f:
                f.write(backup_data)
        elif PERSONAL_TODOS_FILE.exists():
            PERSONAL_TODOS_FILE.unlink(missing_ok=True)


# ─── Test 1: Desktop App.jsx & Web UI index.html Everyday Mode Integration ───

def test_everyday_mode_ui_source_integration():
    app_jsx_path = WORKSPACE_ROOT / "desktop" / "src" / "App.jsx"
    web_ui_path = WORKSPACE_ROOT / "ui" / "index.html"

    assert app_jsx_path.exists(), "desktop/src/App.jsx must exist"
    assert web_ui_path.exists(), "ui/index.html must exist"

    app_jsx = app_jsx_path.read_text(encoding="utf-8")
    web_ui = web_ui_path.read_text(encoding="utf-8")

    # App.jsx verification
    assert "fetchTodos" in app_jsx, "App.jsx must implement fetchTodos"
    assert "handleAddTodo" in app_jsx, "App.jsx must implement handleAddTodo"
    assert "handleCompleteTodo" in app_jsx, "App.jsx must implement handleCompleteTodo"
    assert "handleDeleteTodo" in app_jsx, "App.jsx must implement handleDeleteTodo"
    assert "todos" in app_jsx, "App.jsx must track todos state"
    assert "newTodoText" in app_jsx, "App.jsx must track newTodoText state"
    assert "My To-Dos" in app_jsx, "App.jsx must render My To-Dos header"
    assert "Show My To-Dos" in app_jsx, "App.jsx must have Show My To-Dos routine card"
    assert "Clipboard Helper" in app_jsx, "App.jsx must have Clipboard Helper routine card"

    # ui/index.html verification
    assert "loadTodos" in web_ui, "ui/index.html must implement loadTodos"
    assert "renderTodosBar" in web_ui, "ui/index.html must implement renderTodosBar"
    assert "handleQuickTodo" in web_ui, "ui/index.html must implement handleQuickTodo"
    assert "completeTodo" in web_ui, "ui/index.html must implement completeTodo"
    assert "deleteTodo" in web_ui, "ui/index.html must implement deleteTodo"
    assert "todos-reminders-bar" in web_ui, "ui/index.html must include todos-reminders-bar"
    assert "quick-todo-input" in web_ui, "ui/index.html must include quick-todo-input"
    assert "Show My To-Dos" in web_ui, "ui/index.html must have Show My To-Dos routine card"
    assert "Clipboard Helper" in web_ui, "ui/index.html must have Clipboard Helper routine card"


# ─── Test 2: Desktop Production Build Verification ───────────────────────────

def test_desktop_dist_bundle_verification():
    dist_index = WORKSPACE_ROOT / "desktop" / "dist" / "index.html"
    assert dist_index.exists(), "desktop/dist/index.html must exist from npm run build"

    dist_assets = WORKSPACE_ROOT / "desktop" / "dist" / "assets"
    assert dist_assets.exists() and any(dist_assets.iterdir()), "desktop/dist/assets must contain built JS/CSS"

    # Check that built JS bundle contains tasks/todos endpoint references
    js_files = list(dist_assets.glob("*.js"))
    assert len(js_files) > 0, "Built JS file must exist in desktop/dist/assets"
    bundled_code = "".join(f.read_text(encoding="utf-8", errors="ignore") for f in js_files)
    assert "/tasks/todos" in bundled_code, "Bundled desktop JS must contain /tasks/todos route integration"


# ─── Test 3: API /tasks/todos Full Lifecycle & Daily Briefing Integration ─────

def test_todos_api_lifecycle_and_daily_briefing():
    memory = JarvisMemory()
    brain = Brain(memory=memory)
    set_server_brain(brain, memory)
    client = TestClient(app)

    token_owner, _ = create_access_token(subject="owner")
    headers = {"Authorization": f"Bearer {token_owner}"}

    # 1. Add quick to-do via POST /tasks/todos using { content, category }
    resp_post = client.post(
        "/tasks/todos",
        json={"content": "Finalize Q4 AI Strategy Briefing", "category": "todo"},
        headers=headers
    )
    assert resp_post.status_code == 200
    data_post = resp_post.json()
    assert data_post["success"] is True
    todo_id = data_post["item_id"]
    assert todo_id.startswith("todo_")

    # 2. Verify via GET /tasks/todos
    resp_get = client.get("/tasks/todos", headers=headers)
    assert resp_get.status_code == 200
    data_get = resp_get.json()
    assert data_get["success"] is True
    assert data_get["pending_todos_count"] >= 1
    found = any(t["item_id"] == todo_id for t in data_get["pending_todos"])
    assert found is True

    # 3. Verify inclusion in generate_daily_briefing
    briefing = generate_daily_briefing()
    assert briefing["success"] is True
    briefing_text = briefing.get("briefing_markdown", "")
    assert "Finalize Q4 AI Strategy Briefing" in briefing_text or briefing.get("pending_todos_count", 0) >= 1

    # 4. Mark to-do completed via POST /tasks/todos/{item_id}/complete
    resp_comp = client.post(f"/tasks/todos/{todo_id}/complete", headers=headers)
    assert resp_comp.status_code == 200
    assert resp_comp.json()["status"] == "completed"

    # Verify pending count dropped
    resp_get_after = client.get("/tasks/todos", headers=headers)
    assert resp_get_after.json()["pending_todos_count"] == 0

    # 5. Delete to-do via DELETE /tasks/todos/{item_id}
    resp_del = client.delete(f"/tasks/todos/{todo_id}", headers=headers)
    assert resp_del.status_code == 200
    assert resp_del.json()["success"] is True

    # Verify total items is 0
    resp_get_final = client.get("/tasks/todos", headers=headers)
    assert resp_get_final.json()["total_items"] == 0


# ─── Test 4: Launcher Batch Scripts Validation ───────────────────────────────

def test_consumer_launcher_scripts():
    web_bat = WORKSPACE_ROOT / "Start_Jarvis.bat"
    desktop_bat = WORKSPACE_ROOT / "Start_Jarvis_Desktop.bat"

    assert web_bat.exists(), "Start_Jarvis.bat must exist"
    assert desktop_bat.exists(), "Start_Jarvis_Desktop.bat must exist"

    web_text = web_bat.read_text(encoding="utf-8")
    desktop_text = desktop_bat.read_text(encoding="utf-8")

    # Health check polling validation
    assert "http://127.0.0.1:7799/health" in web_text
    assert "http://127.0.0.1:7799/health" in desktop_text

    # Python backend start validation
    assert "main.py" in web_text
    assert "main.py" in desktop_text

    # Web browser launch in Start_Jarvis.bat
    assert ("http://127.0.0.1:7799" in web_text) or ("http://localhost:7799" in web_text)

    # Electron launch in Start_Jarvis_Desktop.bat
    assert "npm run electron:start" in desktop_text or "electron" in desktop_text


# ─── Test 5: Bundler Scripts Unique Phase 6 Archive Names ────────────────────

def test_export_scripts_unique_phase6_naming():
    verif_script = WORKSPACE_ROOT / "scripts" / "export_verification_bundle.py"
    clean_script = WORKSPACE_ROOT / "scripts" / "export_clean_source.py"

    assert verif_script.exists()
    assert clean_script.exists()

    verif_text = verif_script.read_text(encoding="utf-8")
    clean_text = clean_script.read_text(encoding="utf-8")

    assert "jarvis_phase6_verification.zip" in verif_text, "export_verification_bundle.py must generate jarvis_phase6_verification.zip"
    assert "jarvis_phase6_clean_source.zip" in clean_text, "export_clean_source.py must generate jarvis_phase6_clean_source.zip"
