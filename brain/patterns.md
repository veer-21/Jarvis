# Project Brain — Patterns

This file documents the core implementation patterns and design idioms of JARVIS.

---

## 1. Tool Registration Pattern

Every utility function in the `tools/` folder should be registered with the central `ToolRouter` to expose it to the brain.
* **Auto-Discovery**: `ToolRouter.register_callable` parses the function's docstring and maps parameters dynamically using Pydantic models.
* **Format**:
```python
def my_tool(param1: str, param2: int = 10) -> str:
    """Short summary describing what the tool does (read by LLM)."""
    # Logic goes here...
    return "Result"
```

---

## 2. Multi-Agent Communication Pattern

Agents communicate asynchronously or synchronously on the `AgentBus` using structured messages.
* **Pattern**: An agent subclasses `BaseAgent` and implements `process(message: AgentMessage) -> AgentResponse`.
* **Flow**:
  1. Instantiate agent and register with `agent_bus`.
  2. Send query: `bus.send(AgentMessage(sender="origin", recipient="target", content="data"))`.
  3. Receive `AgentResponse`.

---

## 3. Dynamic Tool Refinement Pattern

To turn repetitive task sequences into automated tools:
1. `MemoryAgent` writes task logs to database memory.
2. `RefinerAgent` scans logs, identifies repetitive parameters, and generates a standalone helper script.
3. Code is saved to `tools/custom/` with clean imports and standard error catching.
4. `ToolRouter` dynamically reloads the new custom tool without system restart.
