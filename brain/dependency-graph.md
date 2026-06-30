# Project Brain — Dependency Graph

This document maps out module dependencies and code relationships.

---

```
main.py (CLI/API Launcher)
 │
 ├── api/server.py (FastAPI Routes)
 │    └── core/brain/brain.py (Brain Co-ordinator)
 │
 └── core/brain/brain.py (Orchestrator)
      │
      ├── core/brain/reasoning_engine.py (LLM GenAI Client)
      ├── core/brain/tool_router.py (Tool Registry & Execution)
      │    └── tools/ (System, File, Web, Browser, Automation Tools)
      │
      ├── core/brain/context_manager.py (Prompt Injection)
      ├── core/brain/memory_manager.py (Memory Interface)
      │    └── core/memory.py (ChromaDB & Fallback JSON)
      │
      ├── core/brain/execution_manager.py (Dual router)
      │    └── core/brain/goal_executor.py (Plan generator & DAG task executor)
      │
      ├── core/prompts/composer.py (Composes prompt layers)
      └── core/agents/agent_bus.py (Event Bus)
           ├── CommanderAgent
           ├── SecurityAgent
           ├── MemoryAgent
           ├── OperatorAgent
           └── RefinerAgent
```
