# Project Brain — Central Memory

This file stores the high-level summary of JARVIS, including its core value proposition, key features, and active engineering tasks.

---

## 1. Project Overview

JARVIS (Just A Rather Very Intelligent System) is a production-grade, modular, secure, voice-enabled personal AI operating system. It leverages Google Gemini models to orchestrate tasks, automate system workflows, store long-term context, and interact with desktop applications.

---

## 2. Key Features

* **Dual-Routing Execution**: Small, direct commands bypass LLM computation using local intent classifiers, while large goals are parsed into tasks.
* **Tiered Memory System**: Implements a semantic vector store (ChromaDB), episodic summarized interaction logs, and a local rolling window of raw dialogue.
* **Dynamic Custom Tools**: Autonomous code optimization agents analyze history and construct new tool scripts dynamically.
* **Futuristic Dashboard**: Electron/React web interface providing WebSocket telemetry, execution statuses, and memory logs.
* **Multi-Modal Voice Loop**: Background listening for hotwords with STT translation and TTS vocal feedback.

---

## 3. Current State

JARVIS is at v3.0, with core backend sub-modules split into clean testable components. The CLI interfaces and API servers are operational.

---

## 4. Active Work

* **Project Brain Implementation**: Creating the workspace persistent memory directories (`brain/` and `AGENTS.md`) and updating codebases (`PromptComposer`, `MemoryAgent`, CLI commands) to consume it.
* **Local-First Intent Refinement**: Upgrading intent classification to use lightweight NLP models instead of fragile regular expressions.
