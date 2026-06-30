# Project Brain — Architecture Reference

This document maps out the systems and layers of JARVIS.

---

## 1. Technological Stack

* **Language**: Python 3.10+
* **Backend Framework**: FastAPI (Uvicorn server)
* **Web Scraping & Automation**: Playwright (Python wrapper)
* **Vector Store**: ChromaDB (hnsw:space = cosine similarity)
* **API Client**: Google GenAI SDK (Gemini models)
* **Voice Subsystems**: Porcupine (hotword), SpeechRecognition (STT), Pyttsx3 (TTS)
* **Security & Auth**: Bcrypt (PIN hashing), PyJWT (token generation), Cryptography Fernet (symmetric database encryption)

---

## 2. Structural Layers

### Core Subsystems (`core/`)
* `JarvisBrain`: Coordinates overall system logic and sub-engines.
* `ReasoningEngine`: Direct connection to GenAI SDK for chat/task generation.
* `ToolRouter`: Gathers callable functions from the system and custom scripts, generates Pydantic parameter validators, and checks confirmation permissions.
* `ContextManager`: Enriches the raw user prompt with relevant history and semantic memories.
* `ExecutionManager` & `GoalExecutor`: Analyzes task complexity and builds DAGs for automated workflow loops.
* `PromptComposer`: Manages system prompt layers dynamically.

### Tools Layer (`tools/`)
* `system_tools.py`: Command line running.
* `file_tools.py`: CRUD file operations.
* `web_tools.py`: DuckDuckGo query integration and news scrapers.
* `browser_tools.py`: Browser navigation, click, and page analysis.
* `automation_tools.py`: Screenshot execution and keyboard control.

### API Layer (`api/`)
* `server.py`: Defines REST routes, handles HTTP POST commands, and sets up real-time SSE or WebSocket channels.
* `models.py`: Pydantic interface structures.
* `auth.py`: Owner credentials authentication.

### Frontend UI (`ui/` & `desktop/`)
* `ui/index.html`: Static fallback control dash.
* `desktop/`: Complete Electron container wrapping Vite + React dashboard modules.
