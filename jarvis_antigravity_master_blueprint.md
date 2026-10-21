# JARVIS v4.0 — Consumer Usability Roadmap & Antigravity IDE Master Prompt Suite

This blueprint provides the step-by-step operating guide, packaging scripts, and copy-paste prompts for **Antigravity IDE** to evolve **JARVIS (v3.6.9)** from a hardened technical prototype into an everyday **Personal AI Assistant for Normal Users**—complete with automated `.zip` verification bundles so every code change can be audited and verified.

## 0. Step-by-Step Quick Start: What You Need to Do Right Now

Follow these exact steps on your Windows PC:

1. **Place This File in Your Project Folder**: Move your downloaded `jarvis_antigravity_master_blueprint.md` file directly into `D:\Jarvis\jarvis_antigravity_master_blueprint.md` so Antigravity IDE can see it in your workspace.
2. **Open Antigravity IDE**: Launch **Antigravity IDE** and open your `D:\Jarvis` folder (`File -> Open Folder -> D:\Jarvis`).
3. **Create a Baseline Backup ZIP (Optional but Recommended)**: Before running any changes, open the terminal inside Antigravity IDE (`Ctrl + ~`), paste the PowerShell snippet from **Section 3** below, and press Enter. This creates `D:\Jarvis\jarvis_clean_source.zip` (a lightweight 1–3 MB backup of your current code). You can also upload `jarvis_clean_source.zip` to our chat right now if you want me to inspect your starting code at the same time.
4. **Run Phase 4.1 in Antigravity IDE**: Open the AI Agent / Composer chat panel inside Antigravity IDE, copy the entire code block under **Prompt 1 (Phase 4.1)** in **Section 4** below, paste it into the Antigravity IDE chat box, and press Enter.
5. **Approve Terminal Commands in Antigravity IDE**: When Antigravity IDE finishes writing `scripts/export_verification_bundle.py`, `tools/everyday_tools.py`, and the new tests, it will ask to run `pytest` and the bundler script. Click **Run / Accept**.
6. **Upload the Verification ZIP Back Here**: Once Antigravity IDE finishes Prompt 1, you will find a new file at **`D:\Jarvis\jarvis_phase_verification.zip`**. Upload that `.zip` file back into our chat here.
7. **Audit & Next Phase**: I will open `jarvis_phase_verification.zip`, verify every modified file and test log, confirm that Phase 4.1 is solid (or give you a quick fix prompt if Antigravity missed anything), and tell you when to paste **Prompt 2 (Phase 4.2)**!

## 1. Strategic Architecture Assessment: Where JARVIS Stands Today

Based on your uploaded documentation (`JARVIS_ARGON_MASTER_DOSSIER.md`, `JARVIS_ASSISTANT_ARCHITECTURE.md`, `JARVIS_EXECUTION_ARCHITECTURE.md`, `JARVIS_CURRENT_STATE_AUDIT.md`, `JARVIS_STABILIZATION_REPORT.md`, and `phase3_6_9_verification_outputs.txt`), your backend foundation is already in the top 1% of open-source agentic systems:

| Architectural Layer | Current Status (v3.6.9) | Readiness for Everyday Non-Technical Users |
| :--- | :--- | :--- |
| **Core Orchestration (`AssistantOrchestrator`)** | 9-stage deterministic lifecycle (`UNDERSTAND` to `RESPOND`) with 127/127 passing tests | **Backend Ready** — Needs everyday consumer task templates and active-window awareness |
| **Security & Verification (`SecurityGuard` + `ResultVerifier`)** | 5-tier risk gates, AST quarantine, `psutil`/disk verification, multi-session isolation | **Backend Ready** — Needs Recycle Bin (`send2trash`) undo safety and plain-English confirmation cards |
| **Everyday Consumer Tools (`tools/`)** | 31 tools focused heavily on developer/system tasks (`git`, `grep`, raw file ops, shell) | **Gap Identified** — Missing daily-life tools (smart Downloads organizer, Windows toast reminders/timers, media/volume/system settings, document/clipboard assistant) |
| **User Experience (`desktop/` & `ui/index.html`)** | Cyberpunk developer HUD showing raw agent bus telemetry, ChromaDB vectors, and ANSI terminal | **Gap Identified** — Needs a First-Run Setup Wizard, a clean "Everyday Assistant Mode" alongside "Pro HUD Mode", and a global `Alt+Space` floating launcher |
| **Verification & Audit Loop** | Manual pytest runs in local terminal | **Gap Identified** — Needs an automated `export_verification_bundle.py` script so Antigravity IDE outputs a clean `.zip` for external code review |

## 2. Choosing the Best Workflow Path

Because JARVIS relies on native Windows 11 APIs (`winocr`, `pywinauto`, `pyttsx3` SAPI5, `psutil` Windows PIDs, and Electron), while my verification sandbox runs in an isolated container, **Path 1 (The Closed-Loop Hybrid Workflow)** is the most effective engineering approach.

| Workflow Option | How It Works | Pros | Cons |
| :--- | :--- | :--- | :--- |
| **Path 1: Closed-Loop Hybrid (Recommended)** | You paste the phased Master Prompts below into **Antigravity IDE** on your Windows PC. Antigravity IDE edits the files, runs `pytest` on Windows, and automatically runs a packaging script to generate `jarvis_phase_verification.zip`. You upload that `.zip` here, and I inspect every changed file, diff, and test log to certify or refine it. | Full access to Windows 11 hardware, OCR, audio, Playwright, and Electron + line-by-line architectural verification here. | Requires uploading the generated `.zip` bundle here after each phase. |
| **Path 2: Direct Sandbox Development** | You run the PowerShell script in Section 3 on your PC to zip your source code (excluding `venv` and `node_modules`) and upload `jarvis_clean_source.zip` here. I write and modify the Python/React code directly in my workspace and export the updated `.zip` for you to unzip and run on Windows. | Zero prompting needed in Antigravity IDE; I write all code directly. | Windows-only hardware calls (`winocr`, audio, GUI windows) must be tested by you after unzipping on your PC. |

## 3. How to Package Your Project Folder (Clean Source ZIP)

Never zip your raw `d:\Jarvis` folder directly with Windows Explorer—`venv/`, `node_modules/`, `.git/`, and `data/memory/chroma/` will bloat the zip to 1–3 GB.

Run this single PowerShell command inside `d:\Jarvis` to generate a clean, lightweight **`jarvis_clean_source.zip`** (typically 1–3 MB) that you can keep as a backup or upload directly to me:

```powershell
# Run in PowerShell from D:\Jarvis
$exclude = @('venv', '.venv', 'node_modules', '.git', '__pycache__', '.pytest_cache', 'dist', 'build', 'chroma')
$files = Get-ChildItem -Path "D:\Jarvis" -Recurse -File | Where-Object {
    $fullPath = $_.FullName
    -not ($exclude | Where-Object { $fullPath -match "\\$_(\\|$)" })
}
$tempDir = Join-Path $env:TEMP "jarvis_export_staging"
if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
foreach ($f in $files) {
    $rel = $f.FullName.Substring("D:\Jarvis\".Length)
    $dest = Join-Path $tempDir $rel
    New-Item -ItemType Directory -Path (Split-Path $dest) -Force | Out-Null
    Copy-Item $f.FullName -Destination $dest -Force
}
Compress-Archive -Path "$tempDir\*" -DestinationPath "D:\Jarvis\jarvis_clean_source.zip" -Force
Remove-Item $tempDir -Recurse -Force
Write-Host "Created D:\Jarvis\jarvis_clean_source.zip successfully!" -ForegroundColor Green
```

## 4. Master Prompt Suite for Antigravity IDE

Copy and paste these prompts **one phase at a time** into **Antigravity IDE**. Each prompt enforces your v3.6.9 architecture invariants (`AssistantOrchestrator`, `ToolRouter`, `SecurityGuard`, `ResultVerifier`, and 127/127 passing tests) and ends by generating `D:\Jarvis\jarvis_phase_verification.zip` for me to audit.

### Prompt 1: Everyday Consumer Tool Pack & Verification Bundler (Phase 4.1)

Paste this prompt first into Antigravity IDE:

```text
You are acting as Principal AI Systems Architect working on the JARVIS v3.6.9 repository in D:\Jarvis.

CRITICAL ARCHITECTURAL INVARIANTS (DO NOT VIOLATE):
1. Do NOT rewrite or bypass `AssistantOrchestrator` (`core/brain/assistant_orchestrator.py`), `ToolRouter` (`core/brain/tool_router.py`), `SecurityGuard` (`core/security.py`), `ResultVerifier` (`core/brain/verifier.py`), or `JarvisMemory` (`core/memory.py`).
2. Every new tool MUST be registered through `ToolRouter`, have strict Pydantic parameter validation, declare an explicit `RiskLevel` in `SecurityGuard`, and have a deterministic post-condition verifier in `ResultVerifier`.
3. All existing 127 tests (`venv\Scripts\python.exe -m pytest -q`) MUST continue to pass with 0 regressions.

YOUR OBJECTIVE (PHASE 4.1 — EVERYDAY CONSUMER ASSISTANTS & VERIFICATION BUNDLER):
Transform JARVIS so non-technical everyday users can complete real day-to-day tasks effortlessly, and build an automated verification bundler so an external Principal Architect can audit all changes.

STEP 1: Create the Automated Verification Bundler (`scripts/export_verification_bundle.py`)
Write a standalone Python script `scripts/export_verification_bundle.py` that produces `D:\Jarvis\jarvis_phase_verification.zip` containing:
1. All modified and newly created source files across `core/`, `api/`, `tools/`, `desktop/src/`, `desktop/electron/`, `ui/`, `tests/`, and `scripts/` (preserving relative directory structure, strictly excluding `venv/`, `node_modules/`, `.git/`, `__pycache__/`, and `data/memory/chroma/`).
2. `verification_manifest.json` containing:
   - Timestamp, Python version, git status, and `git diff` output.
   - SHA-256 hashes and line counts of every modified/created file.
   - Full stdout/stderr and exit codes of:
     a) `venv\Scripts\python.exe -m compileall -q core api tools main.py tests`
     b) `venv\Scripts\python.exe -m pytest -v`

STEP 2: Build the Everyday Personal Assistant Tool Suite (`tools/everyday_tools.py`)
Create `tools/everyday_tools.py` and register the following consumer-friendly tools into `ToolRouter` and `tools/__init__.py`:
1. `smart_organize_folder(directory_path: str, dry_run: bool = False)`:
   - Safely organizes cluttered folders (such as `Downloads` or `Desktop`) into clean subfolders (`Documents`, `Images`, `Installers_Archives`, `Media`, `Code_Data`) by file extension and age.
   - Never overwrites existing files (auto-increments filenames if a collision occurs).
   - Writes an `undo_manifest.json` inside the target folder so the operation can be reversed in one click.
   - Risk Level: `MODERATE_RISK`. Deterministic Verifier: confirms all target files exist at their new paths and `undo_manifest.json` is non-empty.
2. `undo_folder_organization(directory_path: str)`:
   - Reads `undo_manifest.json` and restores every file to its original path.
   - Risk Level: `MODERATE_RISK`. Deterministic Verifier: confirms original paths are restored.
3. `create_reminder_or_timer(title: str, trigger_in_seconds: int, message: str = "")`:
   - Schedules a non-blocking local reminder/timer persisted to `data/tasks/reminders.json` that fires a native Windows Toast notification (using PowerShell `Windows.UI.Notifications` / `BurntToast` or `ctypes` message box fallback + WebSocket broadcast `reminder_triggered` to the UI and TTS announcement).
   - Risk Level: `LOW_RISK`. Deterministic Verifier: confirms the reminder ID is persisted in `data/tasks/reminders.json` and scheduled in the background timer registry.
4. `list_and_manage_reminders(action: str = "list", reminder_id: Optional[str] = None)`:
   - Lists active reminders/timers or cancels a specific reminder by ID.
   - Risk Level: `READ_ONLY` for `list`, `LOW_RISK` for `cancel`.
5. `control_windows_setting(setting: str, value: Optional[str] = None)`:
   - Allows natural everyday OS controls: `volume_up`, `volume_down`, `mute_toggle`, `open_task_manager`, `open_settings`, `empty_recycle_bin` (gated as `HIGH_RISK`), `lock_workstation` (gated as `MODERATE_RISK`), and `clipboard_get` / `clipboard_set`.
6. `summarize_local_document(file_path: str, focus_query: Optional[str] = None)`:
   - Extracts text from `.pdf` (via `pypdf`), `.docx` (via `python-docx` or XML zip extraction fallback), `.txt`, `.md`, or `.csv` files on the user's PC (including Desktop/Downloads/Documents paths when explicitly requested by the user) and returns structured text ready for LLM summarization or Q&A.
   - Risk Level: `READ_ONLY`.
7. `generate_daily_briefing(city: str = "auto")`:
   - Combines local date/time, system health summary, pending reminders/tasks from `data/tasks/reminders.json`, stored user preferences, and live weather (`get_weather`) into a cohesive morning/daily briefing payload.
   - Risk Level: `READ_ONLY`.

STEP 3: Upgrade `IntentClassifier` & `AssistantOrchestrator` for Natural Everyday Requests
Update `core/brain/intent_classifier.py` and `core/brain/assistant_orchestrator.py` so natural requests like:
- "Clean up my Downloads folder"
- "Remind me in 10 minutes to check the oven"
- "Give me my daily briefing"
- "Summarize the PDF on my desktop"
- "Mute my volume"
route cleanly through `AssistantOrchestrator` and `ToolRouter` with full `ResultVerifier` checks.

STEP 4: Write Comprehensive Automated Tests (`tests/test_phase4_1_everyday_tools.py`)
Write at least 15 unit and integration tests covering every new tool, undo manifest rollback, reminder persistence, document extraction, and `ResultVerifier` post-conditions.

STEP 5: Execute Verification & Build the Audit ZIP
1. Run `venv\Scripts\python.exe -m compileall -q core api tools main.py tests`
2. Run `venv\Scripts\python.exe -m pytest -q` (must pass 127 + new tests with 0 failures)
3. Run `venv\Scripts\python.exe scripts/export_verification_bundle.py` to generate `D:\Jarvis\jarvis_phase_verification.zip` and report the exact path and summary of results.
```

### Prompt 2: Consumer-Ready UI, First-Run Setup Wizard & Quick Actions (Phase 4.2)

After I verify Phase 4.1, paste this second prompt into Antigravity IDE:

```text
You are acting as Principal Full-Stack & Desktop Systems Architect on JARVIS in D:\Jarvis.

Preserve all existing backend invariants and all passing tests (`pytest`).

YOUR OBJECTIVE (PHASE 4.2 — CONSUMER UI MODE, FIRST-RUN WIZARD & HUMAN-FRIENDLY CONFIRMATIONS):
Make both `ui/index.html` and the Electron/React app (`desktop/src/`) intuitive and welcoming for a non-technical everyday user, while preserving the advanced Cyberpunk HUD for power users.

STEP 1: Add Diagnostic & Quick-Action Endpoints in `api/server.py`
1. Add `GET /onboarding/diagnostics` (authenticated or initial-setup accessible) that returns real-time readiness checks:
   - `llm_ready`: Whether `GEMINI_API_KEY` or fallback LLM is configured and reachable.
   - `voice_stt_ready`: Whether microphone / `faster-whisper` is available.
   - `voice_tts_ready`: Whether `pyttsx3` TTS is operational.
   - `browser_ready`: Whether Playwright Chromium binary exists.
   - `ocr_ready`: Whether `winocr` is available.
2. Add `POST /onboarding/configure` allowing first-run setup of the user's name, preferred city, and API key (masked in logs and saved securely to `.env` only when local/authenticated).

STEP 2: Dual-Mode UI ("Everyday Assistant Mode" vs. "Developer HUD Mode") in `ui/index.html` and `desktop/src/App.jsx`
1. Add a prominent top-bar mode switch: **[Everyday Mode | Pro HUD Mode]** (defaulting to **Everyday Mode** for clean usability, persisted in `localStorage`).
2. In **Everyday Mode**:
   - Hide noisy developer panels (raw ANSI terminal, vector database inspector, manual tool caller).
   - Display a clean, modern conversational layout featuring:
     - **Voice Orb & Natural Input Bar** ("Ask Jarvis to organize files, summarize a document, set a reminder, or search the web...")
     - **1-Click Daily Routine Cards**:
       * "Morning Briefing" (`Give me my daily briefing`)
       * "Organize Downloads" (`Preview organizing my Downloads folder`)
       * "Read My Screen" (`Read and summarize the text on my screen`)
       * "Set a Quick Reminder" (`Remind me in 15 minutes to take a break`)
       * "System Health Check" (`Check my computer's speed, CPU, and memory`)
     - **Active Reminders & Tasks Drawer**: Shows active countdown timers/reminders and current multi-step task progress in plain English.
3. **Human-Friendly Security Confirmation Card**:
   - When `WAITING_FOR_CONFIRMATION` arrives over WebSocket/REST, display a clear modal card explaining *what* Jarvis wants to do in plain English, *why* it asks for permission, and clear **[Approve Action]** / **[Cancel Safely]** buttons.
4. **First-Run Onboarding Wizard Modal**:
   - Automatically triggers if no PIN or API key is configured, guiding the user through a 3-step check (1. Welcome & Name, 2. AI & Voice Hardware Check via `/onboarding/diagnostics`, 3. Try Your First Command).

STEP 3: Global Hotkey Summoning in Electron (`desktop/electron/main.js`)
- Register global shortcut `Alt+Space` (and fallback `CommandOrControl+Shift+J`) via Electron `globalShortcut` to toggle/focus the Jarvis window from anywhere in Windows.

STEP 4: Verification & Audit Bundle
1. Add E2E API tests for `/onboarding/diagnostics` in `tests/test_phase4_2_onboarding_ui.py`.
2. Build the React frontend (`cd desktop && npm run build`) if Node/npm is present.
3. Re-run `venv\Scripts\python.exe -m pytest -q` and `venv\Scripts\python.exe scripts/export_verification_bundle.py` so `D:\Jarvis\jarvis_phase_verification.zip` is updated with all Phase 4.2 changes and test outputs.
```

### Prompt 3: Active Window Context & Vision-Grounded Screen Assistance (Phase 4.3)

After Phase 4.2 is verified, use this prompt to give JARVIS contextual awareness of whatever the user is currently doing on their screen:

```text
You are acting as Principal AI Systems Architect on JARVIS in D:\Jarvis.

YOUR OBJECTIVE (PHASE 4.3 — ACTIVE WINDOW CONTEXT & ONE-CLICK SCREEN ASSISTANCE):
Enable everyday users to say "Summarize this", "Help me reply to this", or "What does this error mean?" without having to copy-paste paths or URLs.

STEP 1: Active Foreground Window & Selection Inspector (`tools/context_tools.py`)
1. Create `get_active_window_context()` using Win32 APIs (`ctypes.windll.user32` / `pywinauto` + `winocr` fallback):
   - Captures the active foreground window title, process name (`psutil`), current clipboard text (if recently copied), and OCR text of the active window.
   - Masks any detected secrets via `mask_sensitive_data()` before returning.
   - Risk Level: `READ_ONLY`.
2. Integrate contextual resolution into `ContextTracker` (`core/brain/context_tracker.py`) so deictic phrases like `"summarize what's on my screen"`, `"explain this window"`, or `"draft a reply to this"` automatically invoke `get_active_window_context()` as Step 1 of the DAG.

STEP 2: Verification & Audit Bundle
1. Add unit tests in `tests/test_phase4_3_active_context.py` (including headless/mocked window fallback safety).
2. Run `venv\Scripts\python.exe -m pytest -q` and `venv\Scripts\python.exe scripts/export_verification_bundle.py` to generate the updated `D:\Jarvis\jarvis_phase_verification.zip`.
```

## 5. Verification Checklist (What I Will Audit When You Upload the ZIP)

Every time you upload `jarvis_phase_verification.zip` (or `jarvis_clean_source.zip`) back to this chat, I will run an automated audit in my sandbox checking:

1. **Zero Bypass of `ToolRouter` & `SecurityGuard`**: Every new tool has an explicit risk tier and cannot be invoked directly without `SecurityGuard.evaluate_tool_execution()`.
2. **Deterministic Verification (`ResultVerifier`)**: Every state-mutating tool verifies physical OS/disk post-conditions rather than trusting LLM text output.
3. **Multi-User & Session Privacy Invariants**: All new endpoints and reminder stores respect `user_id` / `session_id` isolation.
4. **100% Test Suite Pass Rate**: Zero broken existing tests (`127/127` baseline) plus full coverage of all new consumer features.