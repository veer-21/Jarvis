# JARVIS — Personal AI Operating System (v4.0–v8.0 Consumer Edition)

```
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
  Just A Rather Very Intelligent System — Consumer Edition
```

> **JARVIS v4.0–v8.0 Consumer Edition**: 210 Automated Tests (100% Passing) • Everyday Mode Glassmorphic UI • 40+ Verified Tools • 9-Stage Cognitive Orchestrator • Persistent Reminder Recovery on Boot • 1-Click Desktop Shortcut • Smart Email Composer

📖 **For everyday usage instructions, see [USER_GUIDE.md](file:///D:/Jarvis/USER_GUIDE.md).**

---

## Architecture

```
jarvis/
├── main.py                  ← Unified entry point (CLI + API launcher)
├── requirements.txt
├── .env                     ← API keys & config
│
├── core/
│   ├── brain.py             ← AI reasoning engine (Gemini + tools)
│   ├── memory.py            ← ChromaDB semantic memory
│   ├── planner.py           ← Multi-step autonomous task planner
│   ├── voice.py             ← STT + TTS interface
│   ├── security.py          ← Encryption, auth, audit log
│   ├── logger.py            ← Rotating JSON logs
│   ├── config.py            ← Environment config
│   └── system_prompt.py     ← JARVIS personality & rules
│
├── tools/
│   ├── system_tools.py      ← Shell command execution (security-gated)
│   ├── file_tools.py        ← File read/write/delete/search
│   ├── web_tools.py         ← Web search, page fetch, weather, news
│   ├── browser_tools.py     ← Playwright browser automation
│   └── automation_tools.py  ← Screenshot, keyboard, mouse, system info
│
├── api/
│   ├── server.py            ← FastAPI REST + WebSocket backend
│   ├── models.py            ← Pydantic schemas
│   └── auth.py              ← JWT authentication
│
├── ui/
│   └── index.html           ← Futuristic dashboard UI
│
├── data/                    ← Created automatically at runtime
│   ├── memory/              ← ChromaDB + conversation JSON
│   └── security/            ← Encrypted PIN + Fernet key
│
└── logs/                    ← Rotating log files
    ├── jarvis.log
    ├── audit.log
    └── error.log
```

---

## Quick Start

### 1. Set up Environment

```bash
# Clone / navigate to the project
cd "d:\Home\H.W. OR Self\Jarvis"

# Create virtual environment (already done)
python -m venv venv
venv\Scripts\activate

# Install all dependencies
pip install -r requirements.txt

# Install Playwright browser (for web automation)
playwright install chromium
```

### 2. Configure `.env`

Edit `.env` and set your Gemini API key:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.0-flash
```

### 3. Run JARVIS

```bash
# Text mode (default)
python main.py

# Voice mode
python main.py --voice

# Execute a single autonomous task
python main.py --task "Search the web for AI news and write a summary"

# Start the API server + UI
python main.py --api

# System status only
python main.py --status
```

### 4. Open the Dashboard

With `python main.py --api` running:

1. Open `ui/index.html` in your browser (double-click the file or run `start ui\index.html` in your terminal).
2. The authentication screen will appear. If this is your **first run**, you can leave the PIN blank and just click "AUTHENTICATE" to proceed. Otherwise, enter your PIN.
3. The UI will connect to the backend at `http://localhost:7799`.

---

## Troubleshooting

### "Invalid or expired token" Error
If you see a `System Error: {"detail":"Invalid or expired token."}` in the UI:
1. **Cause:** Your security session (JWT token) has expired (default is 12 hours) or the server restarted and the token in your browser no longer matches.
2. **Solution:** 
   - Click the **LOGOUT** button in the top right corner of the dashboard.
   - This will clear the expired token from your browser's local storage.
   - Re-authenticate with your PIN (or leave blank if none was set).
   - *(Note: We've recently patched the UI to handle this automatically, so you should simply be redirected to the login screen going forward).*

### API Server Not Connecting
- Ensure `python main.py --api` is running in your terminal.
- Check that the `.env` file exists and `JARVIS_API_PORT` matches what the UI expects (7799).

---

## Available Tools (20 registered)

| Category | Tools |
|----------|-------|
| **System** | `execute_command` |
| **Files** | `read_file`, `write_file`, `list_directory`, `safe_delete_file`, `get_file_info`, `search_in_files` |
| **Web** | `web_search`, `fetch_webpage`, `get_weather`, `search_news` |
| **Automation** | `open_application`, `take_screenshot`, `get_system_info`, `press_key`, `type_text` |
| **Browser** | `open_url`, `get_page_text`, `browser_screenshot`, `browser_click`, `browser_fill` |

---

## API Reference

Base URL: `http://localhost:7799`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | Authenticate, get JWT token |
| POST | `/auth/set-pin` | Set owner PIN |
| POST | `/chat` | Chat (sync) |
| POST | `/chat/stream` | Chat (SSE streaming) |
| WS | `/ws/stream` | WebSocket real-time chat |
| GET | `/history` | Conversation history |
| POST | `/task` | Autonomous task execution |
| POST | `/memory/search` | Semantic memory search |
| POST | `/memory` | Store memory |
| POST | `/memory/preference` | Set preference |
| GET | `/status` | System health |
| GET | `/docs` | Auto-generated API docs |

---

## Security Model

- **Owner PIN** — bcrypt-hashed, stored in `data/security/`
- **Fernet Encryption** — Sensitive memory encrypted at rest
- **JWT Sessions** — 12-hour expiry, issued on successful auth
- **Command Gating** — All shell commands assessed by risk level (SAFE→CRITICAL)
- **Audit Log** — All tool executions logged to `logs/audit.log`
- **File Restrictions** — System paths (`C:\Windows`, etc.) blocked from write/delete
- **Action Confirmation** — Destructive actions always require interactive `yes/no`

---

## Memory System

JARVIS uses **ChromaDB** for semantic vector memory when installed, falling back to JSON keyword search.

**Categories:**
- `conversation` — Turn-by-turn dialogue
- `preference` — Owner preferences
- `task` — Completed tasks
- `knowledge` — General learned information
- `workflow` — Saved automation sequences

Memory is injected into each prompt automatically (top-5 relevant entries).

---

## Built-in CLI Commands

While in text mode:

| Command | Action |
|---------|--------|
| `exit` / `quit` | Shutdown JARVIS |
| `status` | Print system status |
| `task: <description>` | Execute autonomous task |
| `reset` | Reset chat session |
| `memory stats` | Show memory statistics |

---

## Development Phases

- [x] **Phase 1** — Foundation (structure, config, logging)
- [x] **Phase 2** — Core AI (Gemini brain, streaming, retry)
- [x] **Phase 3** — Voice (STT + TTS, Google + Whisper)
- [x] **Phase 4** — Tools (system, file, web, browser, automation)
- [x] **Phase 5** — Memory (ChromaDB + JSON fallback)
- [x] **Phase 6** — Agent Planner (decompose + execute + retry)
- [x] **Phase 7** — UI/UX (futuristic dashboard)
- [x] **Phase 8** — Security (auth, encryption, audit)
- [ ] **Phase 9** — Vision (OCR, screenshot analysis)
- [ ] **Phase 10** — Advanced Agents (LangGraph multi-agent)
