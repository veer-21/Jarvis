# JARVIS v5.0 / v6.0 — Complete Audit & Final Consumer Command Center Blueprint

This updated blueprint documents the execution audit of **Phases 4.1 through 5.0** (now at **180 / 180 passing tests**) and provides **Prompt 6 (Phase 6.0 — Interactive To-Do & Quick Notes UI Panel + Unique ZIP Naming)** so normal users can visually manage their daily tasks, notes, and reminders directly inside **Everyday Mode**.

## 1. Cumulative Progress Audit (Phases 3.6.9 → 5.0)

| Phase | Core Capabilities Delivered | Verified Test Count | Status |
| :--- | :--- | :--- | :--- |
| **Phase 3.6.9 (Baseline)** | 9-Stage `AssistantOrchestrator`, `ToolRouter`, 5-Tier `SecurityGuard`, `ResultVerifier`, Multi-User Isolation | 127 / 127 | **COMPLETE** |
| **Phase 4.1 (Everyday Tools)** | Smart Downloads/Desktop Organizer + 1-Click Undo, Reminders/Timers, Windows Controls, Document Reader, Daily Briefing | +17 (144 / 144) | **COMPLETE** |
| **Phase 4.2 (Onboarding & Dual UI)** | `/onboarding/diagnostics`, `/onboarding/configure`, `Alt+Space` Electron Hotkey, Everyday vs. Pro HUD Mode Switcher | +6 (150 / 150) | **COMPLETE** |
| **Phase 4.3 (Active Screen Context)** | `get_active_window_context()` (Win32 HWND/PID + Clipboard + `winocr` + Secret Masking) + Deictic 2-Step DAG Routing | +11 (161 / 161) | **COMPLETE** |
| **Phase 4.4 (Surgical Polish)** | Fixed `/tasks/reminders` route ordering, Active Reminders UI Bar, `user_preferences.json` in Daily Briefing, `$env` Toast Safety | +3 (164 / 164) | **COMPLETE** |
| **Phase 5.0 (Productivity & Launchers)** | `manage_personal_notes_and_todos`, `smart_clipboard_assistant`, `read_and_summarize_webpage`, `/tasks/todos` API, `Start_Jarvis.bat` & `Start_Jarvis_Desktop.bat` | +16 (**180 / 180**) | **COMPLETE** |

## 2. Important Note on Uploading Updated ZIPs in This Chat

When you upload a `.zip` file with the **exact same filename** as an earlier attachment in the same chat (`jarvis_phase_verification.zip` and `jarvis_clean_source.zip`), the chat attachment cache reuses the earlier file (`314,657` bytes from Turn 3) instead of replacing it with the new `150,987` byte file.

To make sure I always receive your newest ZIP files:
1. Either rename the current files on your PC to **`jarvis_phase5_verification.zip`** and **`jarvis_phase5_source.zip`** and attach them here, **OR**
2. Run **Prompt 6 (Phase 6.0)** below first—it updates `scripts/export_verification_bundle.py` and `scripts/export_clean_source.py` to automatically output uniquely named archives (**`jarvis_phase6_verification.zip`** and **`jarvis_phase6_clean_source.zip`**) so the chat uploader never caches an old version!

## 3. What to Build Next: Phase 6.0 (Visual To-Do & Quick Notes Panel in Everyday Mode UI)

In Phase 5.0, Antigravity IDE built the complete backend for `manage_personal_notes_and_todos` and added `GET /tasks/todos`, `POST /tasks/todos`, `POST /tasks/todos/{item_id}/complete`, and `DELETE /tasks/todos/{item_id}` to `api/server.py`, **but it did not yet wire those `/tasks/todos` endpoints into `desktop/src/App.jsx` or `ui/index.html`**.

Adding a sleek, interactive **My To-Dos & Quick Notes Drawer** in **Everyday Mode** (right alongside the Active Reminders Bar) plus a 1-click **"Webpage Summarizer"** & **"Clipboard Helper"** action card completes the visual experience for everyday users.

### Prompt 6: Visual To-Do & Notes Command Center + Unique ZIP Export (Phase 6.0)

Copy and paste this command into **Antigravity IDE**:

```text
You are acting as Principal Full-Stack & AI Systems Architect working on the JARVIS repository in D:\Jarvis.

Preserve all existing architectural invariants (`AssistantOrchestrator`, `ToolRouter`, `SecurityGuard`, `ResultVerifier`) and ensure all 180 existing tests continue to pass.

YOUR OBJECTIVE (PHASE 6.0 — INTERACTIVE TO-DO & QUICK NOTES UI IN EVERYDAY MODE + UNIQUE ZIP BUNDLING):
Connect the Phase 5.0 `/tasks/todos` backend endpoints and productivity tools directly into the Everyday Mode UI (`desktop/src/App.jsx` and `ui/index.html`), and update the bundler scripts to output uniquely named Phase 6 ZIP archives so file upload caches never collide.

STEP 1: Interactive To-Do & Quick Notes Panel in `desktop/src/App.jsx` and `ui/index.html` (Everyday Mode)
1. In `desktop/src/App.jsx`:
   - Add `const [todos, setTodos] = useState([])` and `const [newTodoText, setNewTodoText] = useState('')`.
   - Add `fetchTodos(authToken)` calling `GET http://localhost:7799/tasks/todos` and call it on login, after chat responses complete, and when toggling items.
   - Add handlers for:
     * Adding a quick to-do (`POST /tasks/todos` with `{ content: newTodoText, category: "todo" }`)
     * Completing a to-do (`POST /tasks/todos/{item_id}/complete`)
     * Deleting a to-do (`DELETE /tasks/todos/{item_id}`)
   - In **Everyday Mode**, render a clean, collapsible or side-by-side **My To-Dos & Reminders Bar** below the 1-Click Routine Cards where users can:
     * See pending To-Dos with a 1-click checkbox (`✓`) to mark done and (`✕`) to delete.
     * Type a quick task into a compact inline input (`+ Add quick task...`) and press Enter without even waiting for an LLM turn.
     * See active countdown Reminders with their 1-click Cancel (`✕`) button.
   - Expand the **1-Click Routine Cards** in Everyday Mode to include quick triggers for the new Phase 5.0 tools (e.g., `"Show My To-Do List"` and `"Check Clipboard History"`).
2. Mirror the exact same To-Do list fetching, inline add/complete/delete controls, and Routine Cards inside `ui/index.html` in Everyday Mode.
3. Run `cd desktop && npm run build` and verify the production Vite bundle builds with 0 errors.

STEP 2: Unique Archive Filenames in `scripts/export_verification_bundle.py` & `scripts/export_clean_source.py`
To prevent chat upload caching collisions when filenames repeat:
1. Update `scripts/export_verification_bundle.py` so it writes `D:\Jarvis\jarvis_phase6_verification.zip` (in addition to `D:\Jarvis\jarvis_phase_verification.zip`).
2. Update `scripts/export_clean_source.py` so it writes `D:\Jarvis\jarvis_phase6_clean_source.zip` (in addition to `D:\Jarvis\jarvis_clean_source.zip`).

STEP 3: Automated Tests & Final Verification
1. Add E2E UI/API verification tests in `tests/test_phase5_0_productivity.py` (or `tests/test_phase6_0_consumer_ui.py`) verifying:
   - `desktop/dist/index.html` and `ui/index.html` contain the Everyday Mode To-Do & Reminders integration.
   - Full lifecycle of adding, listing, completing, and deleting To-Dos via `/tasks/todos` and verifying their inclusion in `generate_daily_briefing()`.
   - Verification that `Start_Jarvis.bat` and `Start_Jarvis_Desktop.bat` exist and contain valid health-check polling and launcher commands.
2. Run `venv\Scripts\python.exe -m compileall -q core api tools main.py tests`.
3. Run `venv\Scripts\python.exe -m pytest -q` (all 185+ tests must pass with 0 failures).
4. Run `venv\Scripts\python.exe scripts/export_verification_bundle.py` and `venv\Scripts\python.exe scripts/export_clean_source.py` to generate `D:\Jarvis\jarvis_phase6_verification.zip` and `D:\Jarvis\jarvis_phase6_clean_source.zip`.
```