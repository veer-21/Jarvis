# JARVIS — a private, local-first personal AI assistant for Windows

JARVIS is a desktop assistant that chats with you, remembers what matters, and helps with
everyday computer tasks (reminders, to-dos, files, web lookups, app control) — and **asks
before it changes anything on your PC**.

> **Status: beta.** Windows 10/11 only. "JARVIS" is a working title; the public product name is
> still to be chosen (the name is a trademark of Marvel/Disney).

- **Using JARVIS?** Read the [User Guide](USER_GUIDE.md) and the [Privacy Policy](PRIVACY.md).
- **Releasing JARVIS?** See [docs/RELEASING.md](docs/RELEASING.md).

---

## What it does

| Area | Examples |
|---|---|
| Conversation & memory | Natural chat with your chosen AI; remembers preferences and facts you share; "forget …" removes them |
| Everyday | Reminders & timers, to-do list, daily briefing, clipboard helper, email drafts |
| Files | List / read / search / write / organize (with undo), never touching secrets |
| Web | Search, read and summarize pages, weather, news |
| Computer | Open apps, system status, window control, optional voice |

### Safety model

- The backend only listens on `127.0.0.1` and rejects requests from other websites (Origin/Host checks).
- Anything that writes, deletes, runs code or types into other apps shows a **permission prompt**.
  High-risk actions always ask; low-risk ones can be "always allowed" by you.
- After reading web content, state-changing actions need confirmation (prompt-injection defence).
- Secrets (`.env`, SSH keys, browser data, JARVIS' own keys) are never read or searched.
- API keys live in **Windows Credential Manager**; the memory encryption key is protected with DPAPI.
- Every action is recorded in the **Activity** panel.

---

## Developer setup

Requirements: Windows 10/11, [uv](https://docs.astral.sh/uv/) (Python 3.10 is installed by uv), Node.js 20+.

```powershell
uv sync --extra dev --extra voice      # Python deps from uv.lock (add --extra browser for Playwright)
cd desktop; npm ci; npm run build; cd ..
```

Run it:

| How | Command |
|---|---|
| Desktop app (starts its own backend) | `Start_Jarvis_Desktop.bat` or `cd desktop; npm run electron:prod` |
| Desktop app with hot reload | `cd desktop; npm run electron:dev` |
| Browser UI | `Start_Jarvis.bat` (backend + http://127.0.0.1:7799) |
| Terminal chat | `uv run python main.py --text` |

AI keys: use the setup wizard / Settings in the app (stored in Credential Manager), or put them in
`.env` (see [.env.example](.env.example)). Model names are self-healing: if a provider retires a
model, JARVIS picks a current one and saves it to `settings.json`.

### Where data lives

| What | Location |
|---|---|
| Memory, tasks, settings, activity, keys (DPAPI) | `%LOCALAPPDATA%\JARVIS` (existing dev installs keep using `<repo>\data`) |
| Logs | `<data dir>\logs` (dev installs: `<repo>\logs`) |
| Desktop-app backend log | `%APPDATA%\JARVIS\logs\backend.log` |
| API keys | Windows Credential Manager → "JARVIS/…" |

Override with `JARVIS_DATA_DIR` / `JARVIS_LOG_DIR`.

---

## Architecture

```
desktop/ (Electron + React)          browser (same React build served at /)
   │  spawns backend, local-token login        │  PIN login
   └──────────────► api/server.py (FastAPI, 127.0.0.1:7799, REST + WebSocket)
                        │
                core/brain/brain.py ── AssistantOrchestrator (plan → execute → verify → remember)
                        │                 ├─ IntentClassifier (instant local answers)
                        │                 ├─ heuristic planner + chat session with safe tools
                        │                 └─ ToolRouter → SecurityGuard (risk, confirmation, audit)
                        ├─ ReasoningEngine → llm_providers (Gemini, Groq/OpenAI/Ollama, circuit breakers)
                        ├─ memory (ChromaDB + crash-safe JSON mirror, owner-scoped, secrets redacted)
                        └─ tools/ (files, web, everyday, automation, UIA/COM, REPL)
```

Key modules: `core/paths.py` (all locations), `core/settings.py` + `core/secrets_store.py`
(configuration), `core/security.py` (policy), `core/activity.py` (activity journal),
`core/os_adapter.py` (OS integrations), `core/diagnostics.py` (support bundle, opt-in crash reports).

---

## Tests & quality gates

```powershell
uv run pytest -q                       # isolated temp data dir, no live AI calls
uv run python scripts/run_eval.py      # routing evaluation (expected path for realistic requests)
uvx ruff@0.8.4 check .                 # lint gate
```

Opt-in suites: `JARVIS_RUN_DESKTOP_TESTS=1` (launches real apps), `JARVIS_RUN_INTEGRATION_TESTS=1`
(live web/browser). CI runs lint, the UI build, tests and the eval on every push
(`.github/workflows/ci.yml`).

## Building the installer

```powershell
uv sync --extra packaging --extra voice
uv run python scripts/build_installer.py          # -> desktop\release\JARVIS Setup <version>.exe
```

The backend is bundled with PyInstaller (no Python needed on users' PCs) and the app is packaged
with electron-builder (NSIS). Tagging `v*` builds and publishes a release automatically.

## Maintenance scripts

- `scripts/memory_maintenance.py` — report, clean test data, adopt unowned records, rebuild the
  semantic index from the JSON mirror (preview unless `--apply`).
- `scripts/legacy/` — old one-off scripts kept for reference (not part of the product or tests).
