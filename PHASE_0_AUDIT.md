# JARVIS AI OS — Phase 0: Full System Audit

This document constitutes the Phase 0 Full System Audit as requested by the Lead Architect. It maps the current architecture, identifies bottlenecks across all subsystems, and formalizes the roadmap for upgrading JARVIS into a proactive personal AI operating system.

---

## 1. Current Architecture Map

JARVIS currently utilizes a modular, multi-layered architecture:

* **Entrypoints**: `main.py` orchestrates CLI, Voice, Task, and API modes.
* **Backend Layer**: `api/server.py` runs a FastAPI server providing REST endpoints and WebSocket (`/ws/jarvis`) streaming.
* **Frontend Layer**: A React/Vite web application (`desktop/src/App.jsx`) wrapped in Electron, alongside a legacy static HTML UI (`ui/index.html`).
* **Brain Orchestrator (`core/brain/`)**:
  * `ReasoningEngine`: LLM session management.
  * `ToolRouter`: Registry and execution of 22 tools.
  * `IntentClassifier`: Zero-latency local fast-path interception.
  * `ExecutionManager`: Action-First autonomous task loop.
  * `MemoryManager` & `ContextManager`: RAG and prompt enrichment.
* **Agent Bus (`core/agents/`)**: Specialized agents (`CommanderAgent`, `SecurityAgent`, `MemoryAgent`, `OperatorAgent`, `RefinerAgent`) communicating via `AgentMessage`.
* **Memory System (`core/memory.py`)**: Tiered semantic memory utilizing ChromaDB with importance scoring and auto-pruning.
* **Voice System (`core/voice_manager.py`)**: Background continuous listening loop using Porcupine (wake word) and standard STT/TTS.

---

## 2. Existing Features

* **Zero-Latency Local Execution**: `IntentClassifier` successfully intercepts simple commands (e.g., "open Chrome", "take screenshot", "get weather") using regex fuzzy matching, bypassing the LLM completely.
* **Agentic Routing**: The `CommanderAgent` intercepts user requests and routes them to standard chat or the `ExecutionManager`.
* **Real-time Streaming**: Full token-by-token WebSocket streaming to the React dashboard.
* **Tiered Memory**: Differentiates between Semantic (facts), Episodic (summaries), and Conversational (sliding window) memory, employing an `importance_score` filter to prevent database pollution.

---

## 3. Missing Features

* **Voice**: True streaming STT/TTS, hardware-level Voice Activity Detection (VAD), and barge-in (interruption) capabilities.
* **Operator**: The current `OperatorAgent` is rudimentary. It can execute basic tools and scaffold projects, but lacks comprehensive application orchestration, autonomous form-filling, or DOM interaction.
* **Goal Execution**: The current `ExecutionManager` relies on a monolithic LLM prompt ("Action-First Execution Rules"). It lacks explicit planning, task decomposition, and verification sub-loops.
* **Dashboard Completeness**: The UI lacks visual workflow builders, a dedicated memory browser, interactive agent monitors, and a granular logs viewer.
* **Proactivity**: JARVIS is entirely reactive. There are no background daemons generating reports, cleaning files, or suggesting automations unprompted.

---

## 4. Technical Debt

* **Intent Regex Heaviness**: `IntentClassifier` relies heavily on hardcoded regex patterns, making it brittle to unexpected conversational variations.
* **Monolithic Task Execution**: `ExecutionManager` does not maintain a formal state machine, making error recovery during long-running tasks unreliable.
* **Voice Fallback Blocking**: When Porcupine is unavailable, the fallback STT engine blocks the main voice thread, introducing significant lag.
* **Dependency Fragmentation**: Both `ui/index.html` and `desktop/src` exist, causing fragmentation in UI updates.

---

## 5. Performance Bottlenecks

* **LLM Tool Hallucinations**: In offline mode (Llama 3.2), complex tool schemas cause massive latency and hallucination, forcing the system to strip tools entirely for local chat.
* **Sequential Tool Execution**: `ToolRouter` executes tools sequentially. Parallel tool calls are not supported at the routing layer.

---

## 6. Voice Bottlenecks

* **Non-Streaming Pipelines**: Audio capture waits for the user to stop speaking before sending chunks to STT. TTS waits for full generation before playback.
* **Interruption Failure**: The WebSocket stub exists (`elif cmd == "interrupt"` in `server.py`) but contains no logic to halt the `pyttsx3` or LLM generation loops.

---

## 7. UI Bottlenecks

* **Lack of IPC Native Hooks**: The Electron app acts primarily as a glorified web wrapper around the `localhost:7799` API. It does not utilize Electron IPC for deep OS integrations.
* **Visual Density**: The current React app (`App.jsx`) is beautiful but lacks deep data visualization (e.g., rendering markdown tables, code diffs, or execution trees).

---

## 8. Automation Bottlenecks

* **Browser Limitations**: Playwright tools (`browser_tools.py`) are effective for headless scraping but lack visual element grounding, making autonomous UI navigation across dynamic sites prone to failure.
* **Keyboard/Mouse Granularity**: `type_text` and `press_key` exist, but screen coordinate tracking (Computer Use APIs) is absent.

---

## 9. Security Concerns

* **Raw Command Execution**: `execute_command` (Terminal tool) is inherently dangerous. While guarded by `SecurityAgent`, advanced prompt injection could theoretically bypass regex-based security filters.
* **Action Approval Gap**: Currently, only `safe_delete_file` requires user confirmation. Execution of arbitrary python scripts or web forms lacks a Human-in-the-Loop (HITL) pause.
* **Data at Rest**: ChromaDB vector stores are unencrypted at the filesystem level.

---

## 10. Recommended Upgrade Sequence

I fully agree with the 10-phase sequence outlined. Based on this audit, here is how we will approach the integration:

1. **Phase 1 (Dashboard Integration)**: Expand `App.jsx` to include missing Mission Control panels (Memory, Tasks, Agent Status).
2. **Phase 2 (Voice Rebuild)**: Replace blocking STT with `faster-whisper` and implement WebRTC/WebSocket audio streaming with VAD and barge-in logic.
3. **Phase 3 (Local-First Engine)**: Enhance `IntentClassifier` with lightweight local NLP (e.g., SpaCy or a tiny ONNX model) to replace brittle regexes.
4. **Phase 4 (Operator Agent)**: Integrate PyAutoGUI and vision-based element detection for true digital hands.
5. **Phase 5 (Goal Executor)**: Build a structured DAG (Directed Acyclic Graph) execution engine to replace the monolithic `ExecutionManager`.
6. **Phase 6 (Memory Evolution)**: Implement experience replay so the system caches and re-uses successful DAG plans.
7. **Phase 7 (Electron Desktop)**: Bridge Node.js IPC with Python to give the UI deep OS access.
8. **Phase 8 (Proactive Assistant)**: Implement background Cron triggers and state-monitoring agents.
9. **Phase 9 (Security Hardening)**: Introduce Docker sandboxing for terminal execution and AES encryption for memory stores.
