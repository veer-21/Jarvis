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
import core.paths as _paths  # isolated test data dir
from core.paths import PROJECT_ROOT
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

WORKSPACE_ROOT = PROJECT_ROOT


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
    """The single React UI (desktop/src) implements the Everyday Mode to-do and routine features."""
    src_dir = WORKSPACE_ROOT / "desktop" / "src"
    assert (src_dir / "App.jsx").exists(), "desktop/src/App.jsx must exist"
    ui_source = chr(10).join(p.read_text(encoding="utf-8") for p in src_dir.rglob("*.jsx"))
    for needle in ("fetchTodos", "handleAddTodo", "handleCompleteTodo", "handleDeleteTodo", "todos",
                   "newTodoText", "My To-Dos", "Show My To-Dos", "Clipboard Helper"):
        assert needle in ui_source, f"desktop UI must implement {needle}"
    # The legacy standalone HTML dashboard was retired in favour of the one React UI
    assert not (WORKSPACE_ROOT / "ui" / "index.html").exists()


# ─── Test 2: Desktop Production Build Verification ───────────────────────────

def test_desktop_dist_bundle_verification():
    dist_index = WORKSPACE_ROOT / "desktop" / "dist" / "index.html"
    if not dist_index.exists():
        pytest.skip("UI not built (run: cd desktop && npm run build)")
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
    stop_bat = WORKSPACE_ROOT / "Stop_Jarvis.bat"
    for f in (web_bat, desktop_bat, stop_bat):
        assert f.exists(), f"{f.name} must exist"

    web_text = web_bat.read_text(encoding="utf-8")
    desktop_text = desktop_bat.read_text(encoding="utf-8")
    stop_text = stop_bat.read_text(encoding="utf-8")

    # Browser launcher: starts the API only (no extra browser tab / mic / CLI) and waits for health
    assert "http://127.0.0.1:7799/health" in web_text
    assert "main.py --api --no-browser" in web_text
    assert ("http://127.0.0.1:7799" in web_text) or ("http://localhost:7799" in web_text)

    # Desktop launcher: the Electron app manages its own backend
    assert "electron.exe" in desktop_text
    assert "npm run build" in desktop_text

    # Stop script must never kill unrelated Electron apps
    assert "/IM electron.exe" not in stop_text
    assert ":7799" in stop_text


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
