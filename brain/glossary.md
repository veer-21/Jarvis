# Project Brain — Glossary

This document defines core terminology used in the JARVIS system.

---

* **Agent**: A specialized component subclassing `BaseAgent` that operates on the `AgentBus`.
* **AgentBus**: A centralized message router using `AgentMessage` objects to transfer data between agents.
* **Brain**: The core orchestrator (`core/brain/brain.py`) coordinating all sub-engines.
* **Episodic Memory**: Condensed summaries of conversation turns representing interactions.
* **Memory Importance Score**: A float between `0.0` and `1.0` reflecting the long-term utility of a message.
* **Project Brain**: A persistent intelligence layer consisting of markdown files inside the `brain/` directory representing codebase memory.
* **Refining**: The process of analyzing task logs and writing/injecting custom Python scripts as tools.
* **ToolRouter**: The registry holding all available callables, enforcing risk gating, and executing functions.
