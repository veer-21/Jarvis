# JARVIS Unified Execution Architecture (v3.5)

## 1. Architectural Philosophy: One Assistant Core

JARVIS v3.5 eliminates divergent execution paths and architectural competition. Regardless of whether a request originates from **Text**, **Continuous Voice**, **Token Streaming**, **REST API**, or the **Desktop UI**, execution converges into **one centralized cognitive pipeline**:

```
                       USER INPUT
    [Text CLI / REST / WebSocket / Desktop UI / Continuous Voice (STT)]
                               │
                               ▼
                    ┌─────────────────────────┐
                    │  AssistantOrchestrator   │
                    │   (Single Cognitive Core)│
                    └──────────┬──────────────┘
                               │
                ┌──────────────┴──────────────┐
                ▼                             ▼
       [Cooperative Cancel?]        [Local Fast Path?] (<1ms)
         ("stop", "abort")            ("what time is it", date)
                │                             │
                ▼                             ▼
         Halt & Exit                   Return Instant
                                       Verified Output
                │
                ▼
    ┌───────────────────────────┐
    │       Task Ingestion      │ ──► Persist Initial State (TaskStore)
    │     (AssistantTask Model) │
    └───────────┬───────────────┘
                │
                ▼
    ┌───────────────────────────┐
    │     Task DAG Planner      │ ──► Tool Metadata & Schemas
    │  (General LLM / Fast DAG) │
    └───────────┬───────────────┘
                │
                ▼
    ┌───────────────────────────┐
    │      Plan Validation      │ ──► Rejects Non-Existent Tools, Cycles,
    │    (validate_plan DFS)    │     Missing Dependencies, Bad Parameters
    └───────────┬───────────────┘
                │
                ▼
    ┌───────────────────────────┐
    │  Topological DAG Executor │ ◄── Cooperative Cancellation Token Check
    │   (Resolves Dependencies) │
    └───────────┬───────────────┘
                │
         For Each Ready Step:
                │
                ▼
    ┌───────────────────────────┐
    │       Security Gate       │
    │      (SecurityGuard)      │
    └───────────┬───────────────┘
                ├── SAFE / READ_ONLY ──────► Pass
                ├── MODERATE_RISK ─────────► Permission Granted (Audited)
                └── HIGH_RISK / CRITICAL ──► Non-Blocking Event Bridge:
                                             WAITING_FOR_CONFIRMATION
                                             ├─ WebSocket / REST Broadcast
                                             ├─ UI Approval / Denial
                                             └─ Fallback to CLI Input (CLI Mode)
                │
                ▼
    ┌───────────────────────────┐
    │        ToolRouter         │ ◄── Persistent Single-Worker Pool (Thread Affinity)
    │  (Enforces Hard Timeouts) │ ◄── Cancellation Token Check Before & After
    └───────────┬───────────────┘
                │
                ▼
    ┌───────────────────────────┐
    │      Result Verifier      │
    │ (Levels 1, 2, 3, and 4)   │
    └───────────┬───────────────┘
                ├── Level 1: Tool Returned Without Exception
                ├── Level 2: Expected System State Changed (PID, File Bytes)
                ├── Level 3: Expected User-Visible State Changed (Window / DOM)
                └── Level 4: Task Objective Verified Achieved
                │
                ├── On Failure ────────────► Heuristic Safe Recovery Attempt
                │
                ▼
    ┌───────────────────────────┐
    │      Memory Boundary      │
    │   (MemoryPolicy Tiering)  │
    └───────────┬───────────────┘
                ├── Ephemeral Turn ────────► Sliding Window Context Only
                └── Fact / Preference ─────► Long-Term Semantic ChromaDB/JSON
                │
                ▼
    ┌───────────────────────────┐
    │    Task History Store     │
    │     (Atomic TaskStore)    │ ──► Sensitive Data Masked & Persisted
    └───────────┬───────────────┘
                │
                ▼
    ┌───────────────────────────┐
    │      Response Engine      │
    │    (Token Stream / Text)  │
    └───────────┬───────────────┘
                ├── Streaming ─────────────► SSE / WebSocket Token Chunks
                ├── Voice ─────────────────► Token Generator ──► TTS Stream
                └── Standard ──────────────► Clean Markdown / Natural Text
```

---

## 2. Ingestion Unification

Prior to Phase 3.5, streaming and voice requests bypassed `AssistantOrchestrator`, creating competing business logic. In v3.5, **streaming and voice are purely presentation transformations**:

1. **Text**:
   User input arrives via CLI, Desktop UI, or `POST /chat` -> routes directly to `AssistantOrchestrator.process()`.
2. **Continuous Voice**:
   VAD triggers -> Silero STT transcribes speech -> calls `brain.process_input_stream(command, interrupt_event=interrupt_event)` -> routes to `AssistantOrchestrator.process_stream()` -> chunks flow directly into `VoiceInterface.speak_stream()`.
3. **Token Streaming**:
   `Brain.process_input_stream()` yields chunks directly from `AssistantOrchestrator.process_stream()`, maintaining identical task creation, DAG validation, and audit tracking.
4. **Autonomous Tasks**:
   `POST /task` and `brain.execute_task()` route directly through `AssistantOrchestrator.process()`.

---

## 3. The 9 Core Execution Stages

### Stage 1: Understanding & Cancellation
- User raw text is inspected by `ContextTracker`.
- If a cooperative cancellation directive is recognized (`stop`, `cancel that`, `never mind`, `abort`), the active task's `cancellation_token` is tripped, stopping subsequent DAG steps.
- Built-in deterministic functions (`what time is it`, `what is today's date`) execute in `<1ms` without spinning up an LLM session.

### Stage 2: Task Planning & DAG Representation
- The planner decomposes user requests into explicit `TaskStep` nodes.
- Steps explicitly declare their prerequisites in `dependencies: list[str]`.
- Independent steps (e.g., `step_1: web_search` and `step_2: read_file`) have empty dependencies and are eligible for concurrent/topological scheduling.
- Synthesis steps (e.g., `step_3: reasoning`) explicitly declare `dependencies: ["step_1", "step_2"]`.

### Stage 3: Strict Plan Validation
Before a single tool callable is invoked, `validate_plan()` runs:
1. **Tool Existence**: Validates that all `tool_name` entries match registered tools in `ToolRouter`.
2. **Cycle Detection**: Executes depth-first search (DFS) over the step dependency graph to ensure no circular references exist.
3. **Dependency Integrity**: Confirms every dependency ID refers to an existing step in the plan.
4. **Capability Whitelisting**: Rejects steps specifying unsupported capabilities.

### Stage 4: Parameter Resolution & Missing Input Gate
- Step input parameters containing `{{step_N.var}}` tokens are dynamically interpolated from the outputs of completed antecedent steps.
- Canonical parameter names (`path` vs. `file_path`) are reconciled against the registered tool's schema.
- If a strictly required parameter is missing or empty, the task transitions to `TaskStatus.WAITING_FOR_INPUT` and prompts the user without crashing.

### Stage 5: Non-Blocking Security Gate
- The security policy assesses tool execution risk (`SAFE`, `LOW_RISK`, `MODERATE_RISK`, `HIGH_RISK`, `CRITICAL`).
- High-risk operations (`execute_command`, `safe_delete_file`, `browser_fill`) require authorization.
- In desktop/server mode, `SecurityGuard` issues a `WAITING_FOR_CONFIRMATION` event with a unique `confirmation_id` over WebSockets and REST.
- The thread waits cooperatively on a threading event without blocking FastAPI's async event loop.
- In terminal CLI mode, standard interactive console confirmation is maintained as a fallback.

### Stage 6: Tool Execution & Timeout Enforcement
- Tools execute on a dedicated single-worker thread pool (`_worker_pool`) in `ToolRouter`.
- **Thread Affinity**: Playwright (`sync_api`) and COM/Win32 sub-systems execute on the same persistent worker thread, preventing thread-switch exceptions.
- **Enforced Timeouts**: Tool schemas declare `timeout_seconds`. Execution is wrapped in `future.result(timeout=timeout_sec)`. If the timeout is exceeded, the step fails with a structured timeout error; success is never simulated.
- **Cancellation Checks**: The cooperative `cancellation_token` is checked immediately before tool dispatch and after execution completes.

### Stage 7: Deterministic Result Verification
Execution output passes through `ResultVerifier`, which classifies evidence into four verification levels:
- **Level 1 (Tool Returned)**: Callable returned without exception.
- **Level 2 (System State Changed)**: Process PID is active in OS process table, or file on disk exists with non-zero size.
- **Level 3 (User-Visible Changed)**: Window title is visible in desktop window hierarchy, or browser DOM contains expected text.
- **Level 4 (Objective Achieved)**: Autonomous goal criteria satisfied with verifiable artifact evidence.

If a tool reports execution failure, `_attempt_recovery()` triggers a safe heuristic retry (e.g. simplifying web query terms or alternate path lookups).

### Stage 8: Memory Boundary
- Task state does not automatically bleed into long-term semantic memory.
- `MemoryPolicy` classifies user intent:
  - Ephemeral task interactions are appended only to the sliding-window conversation turns.
  - User preferences (`"Remember that I prefer..."`) and durable facts are committed to ChromaDB vector storage and the fast local cache.
  - Preference deletion (`"Forget that preference"`) surgically purges cached and persistent preferences.

### Stage 9: Task History Persistence & Truthful Response
- The complete task record is sanitized via `mask_sensitive_data()` (API keys, passwords, bearer tokens scrubbed).
- Written atomically to disk (`data/tasks/task_history.json`) via `TaskStore`.
- The final response is delivered via text or token streaming. Jarvis never reports "Done" unless the underlying step post-conditions have been verified.
