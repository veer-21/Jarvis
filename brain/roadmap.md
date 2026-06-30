# Project Brain — Roadmap

This document outlines the milestones and roadmap phases for the development of JARVIS.

---

## 1. Phase 1-5 (Core Foundations)
* **Status**: Complete.
* **Deliverables**:
  * Modular system prompt composer.
  * Extensible tool execution wrapper.
  * ChromaDB vector memory layer.
  * FastAPI server and responsive WebSocket connection.
  * AgentBus routing with specialised Security and Refiner agents.

---

## 2. Phase 6 (Memory Evolution)
* **Status**: In Progress.
* **Deliverables**:
  * Integration of **Project Brain** memory schemas.
  * Auto-updating repository state from execution logs.
  * Experience replay (caching and reusing successful task plans).

---

## 3. Phase 7-10 (Desktop Integration & Hardening)
* **Status**: Planned.
* **Deliverables**:
  * Deep OS native integrations via Electron IPC bridge.
  * Background cron-like scheduler daemon.
  * AES memory encryption at rest.
  * Sandboxing execution folders (e.g. running python scripts in Docker containers).
