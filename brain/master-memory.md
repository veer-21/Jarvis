# Project Brain — Master Memory

This file serves as the entry point for the persistent intelligence layer of JARVIS. It compresses critical repository context to minimize context loading token costs while ensuring architectural alignment.

---

## 1. Architecture Summary

JARVIS is structured around a central, modular core that decouples reasoning, planning, memory, and automation tools:
* **Entry Point**: `main.py` coordinates CLI, Voice, Task, and API running configurations.
* **Brain Engine (`core/brain/`)**: Coordinated by `Brain` (also aliased as `JarvisBrain`). Delegates requests to `ReasoningEngine`, `ContextManager`, `MemoryManager`, `ToolRouter`, `ExecutionManager`, and `StreamingManager`.
* **Agent Bus (`core/agents/`)**: Hub for specialized message-passing agents (`Commander`, `Security`, `Memory`, `Operator`, `Refiner`).
* **Memory System (`core/memory.py`)**: Uses ChromaDB for vector-based semantic memory with a JSON store fallback. Integrates Episodic Memory and Conversation Stores.
* **API Server (`api/server.py`)**: FastAPI REST + WebSocket backend communicating with Electron/React frontend or legacy static dashboard.

---

## 2. Key Decisions

* **Modular Sub-Engines**: Replaced monolithic prompts and logic by splitting core responsibilities into 7 distinct python sub-modules inside `core/brain/`.
* **Zero-Latency Intent Matching**: Avoids LLM calls completely for simple commands (e.g. launching applications) via the regex-based `IntentClassifier`.
* **Tiered Memory with Importance Filtering**: Prevents vector database clutter by only adding user interactions that meet an importance score threshold of `0.3` (or direct task outcomes).
* **Refiner-Driven Auto-Generation**: Empowers the system to write its own custom Python tools in `tools/custom/` to optimize recurrent tasks.

---

## 3. Important Patterns

* **Tool Registration**: Callables are registered with `ToolRouter` and mapped to schemas with metadata. Risks are graded from `SAFE` to `CRITICAL`.
* **Agent Messages**: Communication on the bus uses `AgentMessage` (specifying sender, recipient, content, and metadata) and returns `AgentResponse`.
* **Prompt Composition**: System prompts are assembled dynamically on-demand using the `PromptComposer` based on interaction modes.

---

## 4. Known Issues (Mistakes Log)

* **Powershell File System Recognition**: Commands running python scripts directly on mapped drives in PowerShell can sometimes cause path resolution failures. Prefer invoking via CMD or using explicit paths.
* **Porcupine Voice Fallback Block**: Continuous voice listener loops can lock standard I/O threads when fallbacks occur. Must decouple audio capture from translation pipelines.

---

## 5. Roadmap Snapshot

* **Phases 1-4 (Complete)**: Foundational logic, modular brain, tool calling, and multi-agent setup.
* **Phase 5 (In Progress)**: Upgrading task loop into Directed Acyclic Graph (DAG) executors and implementing Project Brain repository memory.
* **Phases 6-10 (Planned)**: Memory replay, deep Electron native wrappers, cron background task managers, and memory store encryption.
