# Project Brain — Architecture Decisions Log

This document lists the significant engineering decisions, rationales, and alternatives investigated during the development of JARVIS.

---

## 1. Modular Brain Components (v3.0 Re-architect)

* **Decision**: Decouple the monolithic `system_prompt.py` and modularize the coordinator logic into 7 specialized sub-managers (`ReasoningEngine`, `ToolRouter`, `ContextManager`, `MemoryManager`, `ExecutionManager`, `ResponseGenerator`, `StreamingManager`).
* **Rationale**: Single monolithic files became impossible to maintain, difficult to test individually, and diluted the context window by passing all instructions to all prompts.
* **Alternatives**: Keeping a monolithic system, which was rejected due to frequent prompt collision and test regression issues.

---

## 2. ChromaDB Vector Memory with JSON Fallback

* **Decision**: Implement ChromaDB for semantic search indexing, but include a fallback to structured JSON keyword indexing if dependencies are missing.
* **Rationale**: Installs on lightweight or specialized environments (e.g. headless setups, certain Windows configurations) can fail or block on compiling C++ dependencies required by vector libraries.
* **Alternatives**: Requiring Postgres pgvector (heavyweight) or relying purely on SQLite/JSON (slow, poor matching).

---

## 3. Fast-Path Intent Classifier

* **Decision**: Implement a local regex intent checker to bypass the LLM for simple actions (e.g. opening Chrome).
* **Rationale**: Cuts down processing latency for trivial local operations from ~1500ms (LLM request) to <10ms, saving tokens and improving responsiveness.
* **Alternatives**: Full semantic classification models (high memory footprint, slower startup times).
