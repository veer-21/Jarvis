"""
JARVIS Brain — Central Assistant Orchestrator (Phase 3.5 Hardened)
Coordinates all capabilities into a single, cohesive personal assistant agent.

Unified Lifecycle:
UNDERSTAND → PLAN → VALIDATE → PERMISSION → EXECUTE → VERIFY → RECOVER → REMEMBER → RESPOND
"""

import os
import time
import json
import uuid
import re
import asyncio
import threading
from typing import Optional, Any, Callable, AsyncIterator
from datetime import datetime, timezone

from core.logger import log, error_log
from core.security import guard, RiskLevel, mask_sensitive_data
from core.brain.task_model import (
    AssistantTask, TaskStep, TaskStatus, TaskStepStatus, ExecutionContext, validate_plan
)
from core.brain.tool_contract import ToolExecutionResult, ConfirmationPolicy, RetryPolicy
from core.brain.verifier import ResultVerifier, VerificationLevel
from core.brain.context_tracker import ContextTracker
from core.brain.memory_policy import MemoryPolicy, MemoryTier
from core.brain.task_store import task_store


def parse_structured_json_array(text: str) -> Optional[list[dict]]:
    """
    Safely extract and parse JSON array from model responses without relying on greedy regex.
    Handles markdown code fences, balanced bracket discovery, and json trailing comma fixes.
    """
    if not text or not text.strip():
        return None
    raw = text.strip()

    # 1. Strip markdown fences if present
    fence_match = re.search(r"```(?:json)?\s*(\[\s*\{.*?\}\s*\])\s*```", raw, re.DOTALL)
    if fence_match:
        raw = fence_match.group(1).strip()
    else:
        # Find start of array
        start_idx = raw.find("[")
        if start_idx == -1:
            return None
        # Balanced bracket search from start_idx
        bracket_count = 0
        in_string = False
        escape = False
        end_idx = -1
        for i in range(start_idx, len(raw)):
            ch = raw[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if not in_string:
                if ch == "[":
                    bracket_count += 1
                elif ch == "]":
                    bracket_count -= 1
                    if bracket_count == 0:
                        end_idx = i
                        break
        if end_idx != -1:
            raw = raw[start_idx:end_idx + 1]

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except Exception:
        # Try fixing common trailing commas
        try:
            cleaned = re.sub(r",\s*([\]\}])", r"\1", raw)
            data = json.loads(cleaned)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return None


class AssistantOrchestrator:
    """
    Central cognitive orchestrator coordinating user intent, task lifecycle,
    general DAG planning, plan validation, unified tool execution, verification,
    recovery, streaming, and persistent memory boundaries.
    """

    def __init__(self, brain=None, tool_router=None, memory_manager=None, reasoning_engine=None):
        self.brain = brain
        self.tool_router = tool_router or (brain.tools if brain else None)
        self.memory_manager = memory_manager or (brain.memory_manager if brain else None)
        self.reasoning = reasoning_engine or (brain.reasoning if brain else None)
        
        self.context_tracker = ContextTracker()
        self._active_tasks: dict[str, AssistantTask] = {}          # keyed by task_id
        self._session_active_tasks: dict[str, AssistantTask] = {}  # keyed by session_id
        self._request_active_tasks: dict[str, AssistantTask] = {}  # keyed by request_id
        self._fallback_active_task: Optional[AssistantTask] = None
        self._execution_history: list[AssistantTask] = []
        
        log.info("AssistantOrchestrator online (Phase 3.5 Hardened).")

    def _register_active_task(self, task: AssistantTask, ctx: Optional[Any] = None) -> None:
        """Register active task consistently across task_id, session_id, and request_id."""
        if not task:
            return
        if ctx:
            if getattr(ctx, "session_id", None):
                task.session_id = ctx.session_id
            if getattr(ctx, "request_id", None):
                task.request_id = ctx.request_id
            if getattr(ctx, "user_id", None):
                task.user_id = ctx.user_id

        self._active_tasks[task.task_id] = task
        if task.session_id:
            self._session_active_tasks[task.session_id] = task
        if task.request_id:
            self._request_active_tasks[task.request_id] = task
        self._fallback_active_task = task

    def _unregister_active_task(self, task_or_id: Any) -> None:
        """Completely purge all registry entries that refer to the terminal task identity-safely."""
        if task_or_id is None:
            return
        target_task: Optional[AssistantTask] = None
        if isinstance(task_or_id, AssistantTask):
            target_task = task_or_id
        elif isinstance(task_or_id, str):
            target_task = (
                self._active_tasks.get(task_or_id)
                or self._session_active_tasks.get(task_or_id)
                or self._request_active_tasks.get(task_or_id)
            )

        if target_task:
            t_id = target_task.task_id
            s_id = target_task.session_id
            r_id = target_task.request_id

            if t_id and self._active_tasks.get(t_id) is target_task:
                self._active_tasks.pop(t_id, None)
            if s_id and self._session_active_tasks.get(s_id) is target_task:
                self._session_active_tasks.pop(s_id, None)
            if r_id and self._request_active_tasks.get(r_id) is target_task:
                self._request_active_tasks.pop(r_id, None)

            for k in list(self._active_tasks.keys()):
                if self._active_tasks[k] is target_task:
                    self._active_tasks.pop(k, None)
            for k in list(self._session_active_tasks.keys()):
                if self._session_active_tasks[k] is target_task:
                    self._session_active_tasks.pop(k, None)
            for k in list(self._request_active_tasks.keys()):
                if self._request_active_tasks[k] is target_task:
                    self._request_active_tasks.pop(k, None)
            if self._fallback_active_task is target_task:
                self._fallback_active_task = None
        elif isinstance(task_or_id, str):
            # Only unregister by ID key if no target_task was resolved
            self._active_tasks.pop(task_or_id, None)
            self._session_active_tasks.pop(task_or_id, None)
            self._request_active_tasks.pop(task_or_id, None)

    @property
    def active_task(self) -> Optional[AssistantTask]:
        """Context/session-aware active task accessor preventing cross-session collisions."""
        from core.brain.task_model import current_execution_context
        ctx = current_execution_context.get()
        if ctx:
            if ctx.request_id and ctx.request_id in self._request_active_tasks:
                return self._request_active_tasks[ctx.request_id]
            if ctx.session_id and ctx.session_id in self._session_active_tasks:
                return self._session_active_tasks[ctx.session_id]
            # P0-2 & P1-6: When a request has an explicit session or request context but no matching task, return None!
            if ctx.session_id or ctx.request_id:
                return None
        # Local CLI / un-contexted fallback ONLY when no explicit session/request context exists
        return self._fallback_active_task

    @active_task.setter
    def active_task(self, task: Optional[AssistantTask]) -> None:
        from core.brain.task_model import current_execution_context
        ctx = current_execution_context.get()
        if task is not None:
            self._register_active_task(task, ctx)
        else:
            target = None
            if ctx:
                if ctx.request_id:
                    target = self._request_active_tasks.get(ctx.request_id)
                if not target and ctx.session_id:
                    target = self._session_active_tasks.get(ctx.session_id)
                # P1-6: Explicit session/request context + no match -> no-op, never touch global fallback
                if not target and (ctx.request_id or ctx.session_id):
                    return
            if not target:
                target = self._fallback_active_task
            self._unregister_active_task(target)

    def set_brain(self, brain) -> None:
        """Attach or update Brain reference and sub-systems."""
        self.brain = brain
        self.tool_router = brain.tools
        self.memory_manager = brain.memory_manager
        self.reasoning = brain.reasoning

    # ─── Synchronous Public Gateway ───────────────────────────────────────────

    def process(self, user_input: str, context: Optional[ExecutionContext] = None) -> str:
        """
        Primary synchronous execution entry point for natural language requests.
        Coordinates the full UNDERSTAND → RESPOND pipeline.
        DAG execution is strictly dependency-aware and sequential for desktop/browser session safety.
        """
        from core.brain.task_model import current_execution_context
        ctx_token = current_execution_context.set(context)
        task = None
        try:
            t_start = time.perf_counter()
            raw_text = user_input.strip()

            # ── 1. CANCELLATION CHECK ──
            if self.context_tracker.is_cancellation(raw_text):
                active = self.active_task
                if active and active.status in (
                    TaskStatus.EXECUTING, TaskStatus.PLANNING, TaskStatus.WAITING_FOR_CONFIRMATION, TaskStatus.UNDERSTANDING
                ):
                    active.cancel("USER_EXPLICIT_STOP")
                    task_store.save_task(active)
                    self._unregister_active_task(active)
                    self.context_tracker.set_active_task(None)
                    return "Understood, Sir. I have stopped the active task."
                return "There is no active task running, Sir."

            # ── 2. MEMORY DELETION CHECK ──
            tier, category = MemoryPolicy.classify_interaction(raw_text)
            if category == "delete_request":
                query = re.sub(r"\b(delete|forget|remove|from|my|memory|preference)\b", "", raw_text, flags=re.I).strip()
                from core.brain.task_model import current_execution_context
                caller_user = context.user_id if context and context.user_id else (
                    current_execution_context.get().user_id if current_execution_context.get() and current_execution_context.get().user_id else None
                )
                if not caller_user:
                    return "I cannot delete memories without verified user identity, Sir."
                if self.memory_manager and query:
                    success = self.memory_manager.delete_memory(query=query, user_id=caller_user)
                    if success:
                        return f"Understood, Sir. I have deleted that information from memory."
                    else:
                        return f"I searched your memory for '{query}', but found no matching records to delete."
                return "Please specify what you would like me to forget, Sir."

            # ── 3. REFERENTIAL FOLLOW-UP CONTEXT RESOLUTION ──
            referenced_entity = self.context_tracker.resolve_reference(raw_text)
            resolved_input = raw_text
            if referenced_entity:
                resolved_input = f"{raw_text} (Target item: {referenced_entity})"
                log.info(f"[Orchestrator] Resolved referential pronoun to: {referenced_entity}")

            # ── 4. UNDERSTAND & TASK INITIALIZATION ──
            task_id = context.task_id if context and context.task_id else f"task_{uuid.uuid4().hex[:8]}"
            task = AssistantTask(
                task_id=task_id,
                user_request=raw_text,
                store_memory=context.store_memory if context else True,
                session_id=context.session_id if context else None,
                user_id=context.user_id if context else None,
                request_id=context.request_id if context else None,
            )
            if context and context.cancellation_token:
                if context.is_cancelled:
                    task.cancel("CONTEXT_PRE_CANCELLED")
                task._cancel_event = context.cancellation_token

            if context is not None:
                context.task = task

            self.active_task = task
            self.context_tracker.set_active_task(task.task_id)
            task.transition_to(TaskStatus.UNDERSTANDING, details={"raw_text": raw_text, "resolved_text": resolved_input})

            # Fast-Path: Built-in local functions (<1ms)
            intent_type = "chat"
            if self.brain and getattr(self.brain, "intent_classifier", None):
                local_match = self.brain.intent_classifier.classify(raw_text)
                if local_match:
                    tool_name, tool_args = local_match
                    from core.brain.intent_classifier import IntentClassifier
                    local_result = IntentClassifier.execute_local(tool_name, tool_args)
                    if local_result is not None:
                        task.intent = "query"
                        task.transition_to(TaskStatus.EXECUTING, "BUILTIN_LOCAL_EXECUTION")
                        task.result = str(local_result)
                        task.transition_to(TaskStatus.COMPLETED)
                        self._handle_memory_persistence(task, local_result, execution_context=context)
                        self.context_tracker.update_exchange(raw_text, str(local_result))
                        task_store.save_task(task)
                        self._unregister_active_task(task)
                        self.context_tracker.set_active_task(None)
                        return str(local_result)

            # ── 5. PLAN & VALIDATE ──
            task.transition_to(TaskStatus.PLANNING)
            plan_steps = self._create_plan(resolved_input, intent_type)
            
            # Enforce Plan Validation
            available_tool_names = list(self.tool_router._registry.keys()) if self.tool_router else None
            tool_schemas = self.tool_router._registry if self.tool_router else None
            is_valid, validation_err = validate_plan(plan_steps, available_tools=available_tool_names, tool_schemas=tool_schemas)
            if not is_valid:
                log.warning(f"[Orchestrator] Plan validation rejected: {validation_err}")
                task.transition_to(TaskStatus.FAILED, details={"validation_error": validation_err})
                task_store.save_task(task)
                self._unregister_active_task(task)
                self.context_tracker.set_active_task(None)
                return f"I could not form a safe execution plan: {validation_err}"

            task.plan = plan_steps
            task.add_audit_event("PLAN_VALIDATED", {"step_count": len(plan_steps)})
            task.transition_to(TaskStatus.EXECUTING)

            # ── 6. EXECUTE DAG LOOP ──
            final_answer, candidates = self._execute_plan_dag(task, resolved_input)

            if task.status == TaskStatus.CANCELLED:
                task_store.save_task(task)
                self._unregister_active_task(task)
                self.context_tracker.set_active_task(None)
                return "Task was cancelled by user directive."

            # ── 8. RESPOND ──
            task.result = final_answer
            if task.status not in (
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.TIMED_OUT,
                TaskStatus.WAITING_FOR_INPUT,
                TaskStatus.WAITING_FOR_CONFIRMATION,
            ):
                task.transition_to(TaskStatus.COMPLETED)
                
            self.context_tracker.update_exchange(raw_text, final_answer, candidates=candidates if candidates else None)

            # ── 9. REMEMBER ──
            self._handle_memory_persistence(task, final_answer, execution_context=context)

            task_store.save_task(task)
            self._execution_history.append(task)
            if task.status not in (TaskStatus.WAITING_FOR_INPUT, TaskStatus.WAITING_FOR_CONFIRMATION):
                self._unregister_active_task(task)
            self.context_tracker.set_active_task(None)
            
            elapsed_s = time.perf_counter() - t_start
            log.info(f"[Orchestrator] Finished task {task.task_id} in {elapsed_s:.2f}s | Steps: {len(task.completed_steps)}/{len(task.plan)}")
            return final_answer
        finally:
            if task and task.status not in (TaskStatus.WAITING_FOR_INPUT, TaskStatus.WAITING_FOR_CONFIRMATION):
                self._unregister_active_task(task)
            current_execution_context.reset(ctx_token)

    # ─── Streaming Public Gateway ─────────────────────────────────────────────

    async def process_stream(
        self,
        user_input: str,
        interrupt_event: Optional[threading.Event] = None,
        context: Optional[ExecutionContext] = None
    ) -> AsyncIterator[str]:
        """
        Asynchronous streaming execution entry point token-by-token.
        Shares the identical AssistantOrchestrator task, security, and verification lifecycle.
        """
        from core.brain.task_model import current_execution_context
        ctx_token = current_execution_context.set(context)
        task = None
        try:
            raw_text = user_input.strip()

            # Merge context cancellation token if provided
            effective_interrupt = interrupt_event
            if effective_interrupt is None and context and context.cancellation_token:
                effective_interrupt = context.cancellation_token

            # 1. Cancellation check
            if self.context_tracker.is_cancellation(raw_text) or (effective_interrupt and effective_interrupt.is_set()):
                active = self.active_task
                if active and active.status in (
                    TaskStatus.EXECUTING, TaskStatus.PLANNING, TaskStatus.WAITING_FOR_CONFIRMATION, TaskStatus.UNDERSTANDING
                ):
                    active.cancel("USER_STREAM_STOP")
                    task_store.save_task(active)
                    self._unregister_active_task(active)
                    self.context_tracker.set_active_task(None)
                    yield "Understood, Sir. I have stopped the active task."
                    return
                yield "There is no active task running, Sir."
                return

            # 2. Memory deletion check
            tier, category = MemoryPolicy.classify_interaction(raw_text)
            if category == "delete_request":
                query = re.sub(r"\b(delete|forget|remove|from|my|memory|preference)\b", "", raw_text, flags=re.I).strip()
                from core.brain.task_model import current_execution_context
                caller_user = context.user_id if context and context.user_id else (
                    current_execution_context.get().user_id if current_execution_context.get() and current_execution_context.get().user_id else None
                )
                if not caller_user:
                    yield "I cannot delete memories without verified user identity, Sir."
                    return
                if self.memory_manager and query:
                    success = self.memory_manager.delete_memory(query=query, user_id=caller_user)
                    if success:
                        yield "Understood, Sir. I have deleted that information from memory."
                    else:
                        yield f"I searched your memory for '{query}', but found no matching records to delete."
                    return
                yield "Please specify what you would like me to forget, Sir."
                return

            # 3. Fast Path: Local Built-ins
            if self.brain and getattr(self.brain, "intent_classifier", None):
                local_match = self.brain.intent_classifier.classify(raw_text)
                if local_match:
                    tool_name, tool_args = local_match
                    from core.brain.intent_classifier import IntentClassifier
                    local_result = IntentClassifier.execute_local(tool_name, tool_args)
                    if local_result is not None:
                        yield str(local_result)
                        return

            # 3. Synchronous execution in background worker with progress events
            # We run the unified DAG pipeline and stream the resulting chunks
            task_id = context.task_id if context and context.task_id else f"task_{uuid.uuid4().hex[:8]}"
            task = AssistantTask(
                task_id=task_id,
                user_request=raw_text,
                store_memory=context.store_memory if context else True,
                session_id=context.session_id if context else None,
                user_id=context.user_id if context else None,
                request_id=context.request_id if context else None,
            )
            if effective_interrupt:
                task._cancel_event = effective_interrupt

            if context is not None:
                context.task = task

            self.active_task = task
            self.context_tracker.set_active_task(task.task_id)

            # If it's a conversational chat without multi-step tools, stream tokens directly
            plan_steps = self._create_plan(raw_text, "chat")
            is_multi_step_tool = any(s.tool_name for s in plan_steps)

            if not is_multi_step_tool:
                task.transition_to(TaskStatus.EXECUTING)
                # Direct streaming via Brain StreamingManager
                if self.brain and hasattr(self.brain, "streaming") and hasattr(self.brain, "context"):
                    try:
                        enriched = await self.brain.context.build_enriched_prompt(
                            raw_text, session_id=task.session_id, user_id=task.user_id, context=context
                        )
                    except TypeError:
                        enriched = await self.brain.context.build_enriched_prompt(raw_text)
                    system_prompt = self.brain._get_system_prompt()
                    full_chunks = []
                    # StreamingManager does not persist directly; persistence is governed below by AssistantOrchestrator
                    async for chunk in self.brain.streaming.stream_response(
                        raw_text, enriched, system_prompt, interrupt_event=effective_interrupt,
                        store_memory=False, context=context
                    ):
                        full_chunks.append(chunk)
                        yield chunk

                    full_answer = "".join(full_chunks)

                    is_interrupted = (
                        (effective_interrupt and effective_interrupt.is_set())
                        or (interrupt_event and interrupt_event.is_set())
                        or (context and hasattr(context, "cancellation_token") and context.cancellation_token and context.cancellation_token.is_set())
                        or (context and getattr(context, "is_interrupted", False))
                        or task.is_cancelled
                    )
                    stream_error = (
                        (context and getattr(context, "stream_error", None))
                        or ("[Stream Error:" in full_answer)
                        or ("[Error:" in full_answer)
                    )
                    is_cleanly_completed = (
                        (context and getattr(context, "stream_completed", False))
                        and not is_interrupted
                        and not stream_error
                    )

                    if is_interrupted:
                        task.result = full_answer
                        task.cancel("USER_STREAM_STOP")
                        task_store.save_task(task)
                        self._unregister_active_task(task)
                        self.context_tracker.set_active_task(None)
                        return
                    elif stream_error:
                        task.result = full_answer
                        err_str = str(getattr(context, "stream_error", None) or stream_error)
                        task.error = err_str
                        task.transition_to(TaskStatus.FAILED, event_name="STREAM_FAILED", details={"error": err_str})
                        task_store.save_task(task)
                        self._unregister_active_task(task)
                        self.context_tracker.set_active_task(None)
                        return
                    elif is_cleanly_completed or (context is None and not is_interrupted and not stream_error):
                        task.result = full_answer
                        task.transition_to(TaskStatus.COMPLETED)
                        self._handle_memory_persistence(task, full_answer, execution_context=context)
                        task_store.save_task(task)
                        self._unregister_active_task(task)
                        self.context_tracker.set_active_task(None)
                        return
                    else:
                        # Abnormal stream termination without explicit completion signal -> Fail closed as FAILED
                        task.result = full_answer
                        task.error = "Stream terminated abnormally without clean completion signal."
                        task.transition_to(TaskStatus.FAILED, event_name="STREAM_ABNORMAL_TERMINATION", details={"error": task.error})
                        task_store.save_task(task)
                        self._unregister_active_task(task)
                        self.context_tracker.set_active_task(None)
                        return

            # For multi-step tasks, yield progress updates and then delegate to process
            yield "[PLANNING] Analyzing goal and decomposing into steps...\n"
            await asyncio.sleep(0)

            # Unregister the stream task shell before delegating to full process DAG
            self._unregister_active_task(task)
            task = None
            response = await asyncio.to_thread(self.process, raw_text, context)
            yield response
        finally:
            if task and task.status not in (TaskStatus.WAITING_FOR_INPUT, TaskStatus.WAITING_FOR_CONFIRMATION):
                self._unregister_active_task(task)
            current_execution_context.reset(ctx_token)

    # ─── Planning & Decomposition ─────────────────────────────────────────────

    def _create_plan(self, user_request: str, intent_type: str) -> list[TaskStep]:
        """
        Create a validated TaskStep DAG plan.
        Combines deterministic fast-path patterns with general LLM-driven planning.
        """
        req_lower = user_request.lower()

        # 1. Fast-Path Heuristic: Single app launch
        if req_lower.startswith("open ") and (" and " not in req_lower or "running" in req_lower):
            app_match = re.search(r"open\s+([a-zA-Z0-9_\-\s]+?)(?:\s+and\s+tell|\s+and\s+verify|$)", req_lower)
            app_name = app_match.group(1).strip() if app_match else "notepad"
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Launch application '{app_name}'",
                    capability="desktop",
                    tool_name="open_application",
                    input_variables={"app_name": app_name},
                    output_variables=["app_status"],
                    dependencies=[]
                ),
                TaskStep(
                    step_id="step_2",
                    description=f"Verify if '{app_name}' is actively running",
                    capability="reasoning",
                    input_variables={"status": "{{step_1.app_status}}"},
                    dependencies=["step_1"]
                )
            ]

        # 2. General LLM-driven planning
        if self.reasoning:
            general_plan = self._create_plan_general(user_request)
            if general_plan:
                return general_plan

        # 3. Fallback Heuristic Decomposition
        return self._heuristic_plan_decomposition(user_request)

    def _create_plan_general(self, user_request: str) -> Optional[list[TaskStep]]:
        """
        General planner: prompts LLM with real tool schemas to generate a structured DAG.
        """
        if not self.tool_router:
            return None

        available_tools = []
        for name, schema in self.tool_router._registry.items():
            params = []
            if schema.pydantic_model:
                for fname, ffield in schema.pydantic_model.model_fields.items():
                    params.append(fname)
            param_str = f" (parameters: {', '.join(params)})" if params else ""
            available_tools.append(f"- {name}: {schema.description}{param_str}")

        tools_prompt_text = "\n".join(available_tools)

        prompt = f"""You are the planning engine of the JARVIS personal assistant.
Decompose the user request into an optimal sequence of executable steps (DAG).
Use ONLY tool names from the AVAILABLE TOOLS list below. Do NOT invent tools.

AVAILABLE TOOLS:
{tools_prompt_text}

USER REQUEST:
"{user_request}"

Return ONLY a valid JSON array of step objects.
Format:
[
  {{
    "step_id": "step_1",
    "description": "Short explanation",
    "capability": "file" | "web" | "browser" | "desktop" | "system" | "reasoning",
    "tool_name": "exact_tool_name_or_null",
    "input_variables": {{"param": "value"}},
    "dependencies": []
  }}
]
JSON:"""

        try:
            raw_json = self.reasoning.generate_text(prompt)
            parsed_steps = parse_structured_json_array(raw_json)
            if parsed_steps:
                steps = []
                for item in parsed_steps:
                    steps.append(TaskStep(
                        step_id=item.get("step_id") or f"step_{uuid.uuid4().hex[:6]}",
                        description=item.get("description", "Execute step"),
                        capability=item.get("capability", "general"),
                        tool_name=item.get("tool_name"),
                        input_variables=item.get("input_variables", {}),
                        dependencies=item.get("dependencies", [])
                    ))
                if steps:
                    return steps
        except Exception as e:
            log.warning(f"[Orchestrator] General planner LLM parse failed: {e}")
        return None

    def _heuristic_plan_decomposition(self, user_request: str) -> list[TaskStep]:
        """Intelligent heuristic fallback plan decomposition."""
        req_lower = user_request.lower()

        # Multi-step: Active Window & Screen Context -> Reasoning (Phase 4.3)
        if (hasattr(self, "context_tracker") and self.context_tracker.is_active_context_request(user_request)) or \
           any(w in req_lower for w in ("on my screen", "read my screen", "summarize this window", "explain this window", "draft a reply to this", "what does this error mean", "look at my screen", "what is on my screen")):
            return [
                TaskStep(
                    step_id="step_1",
                    description="Capture active foreground window and screen context",
                    capability="everyday",
                    tool_name="get_active_window_context",
                    input_variables={"include_ocr": True, "include_clipboard": True},
                    output_variables=["window_context"],
                    dependencies=[]
                ),
                TaskStep(
                    step_id="step_2",
                    description=f"Analyze active window context to assist with request: '{user_request}'",
                    capability="reasoning",
                    input_variables={"context": "{{step_1.window_context}}"},
                    dependencies=["step_1"]
                )
            ]

        # Multi-step: Webpage reading and summarization (Phase 5.0)
        url_match = re.search(r"https?://[^\s\"'<>]+", user_request)
        if url_match and any(w in req_lower for w in ("summarize", "read", "explain", "article", "page", "webpage", "site", "what is on", "what's on", "fetch", "extract", "check")):
            target_url = url_match.group(0).rstrip(".,)>\"'")
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Read and extract text from webpage '{target_url}'",
                    capability="everyday",
                    tool_name="read_and_summarize_webpage",
                    input_variables={"url": target_url},
                    output_variables=["webpage_content"],
                    dependencies=[]
                ),
                TaskStep(
                    step_id="step_2",
                    description=f"Summarize and synthesize key insights from '{target_url}'",
                    capability="reasoning",
                    input_variables={"content": "{{step_1.webpage_content}}"},
                    dependencies=["step_1"]
                )
            ]

        # Multi-step: Web search -> Summarize
        if ("search the web" in req_lower or "search for" in req_lower or "web search" in req_lower) and any(w in req_lower for w in ("summarize", "compare", "latest", "release", "tell me", "documentation", "docs", "react")):
            topic = re.sub(r"^(search the web for|search for|open the browser and search for|find)\s*", "", req_lower)
            topic = re.sub(r"(and summarize.*|and tell me.*)$", "", topic).strip()
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Search the web for '{topic}'",
                    capability="web",
                    tool_name="web_search",
                    input_variables={"query": topic},
                    output_variables=["web_results"],
                    dependencies=[]
                ),
                TaskStep(
                    step_id="step_2",
                    description="Analyze web results and synthesize answer",
                    capability="reasoning",
                    input_variables={"results": "{{step_1.web_results}}"},
                    dependencies=["step_1"]
                )
            ]

        # Multi-step: File search -> Read -> Summarize
        if ("find" in req_lower or "search" in req_lower) and any(w in req_lower for w in ("assignment", "pdf", "readme", "doc", "file")) and any(w in req_lower for w in ("read", "summarize", "checklist", "explain", "questions")):
            target_kw = "assignment" if "assignment" in req_lower else ("README.md" if "readme" in req_lower else "file")
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Search for files matching '{target_kw}'",
                    capability="file",
                    tool_name="list_directory",
                    input_variables={"path": "."},
                    output_variables=["files"],
                    dependencies=[]
                ),
                TaskStep(
                    step_id="step_2",
                    description=f"Read contents of the target {target_kw}",
                    capability="file",
                    tool_name="read_file",
                    input_variables={"path": "README.md" if "readme" in req_lower else "{{step_1.files}}"},
                    output_variables=["content"],
                    dependencies=["step_1"]
                ),
                TaskStep(
                    step_id="step_3",
                    description="Analyze contents and generate checklist or summary",
                    capability="reasoning",
                    input_variables={"content": "{{step_2.content}}"},
                    dependencies=["step_2"]
                )
            ]

        # File listing / directory contents
        if any(w in req_lower for w in ("list files", "list all files", "list directory", "contents of the root directory", "contents of the directory", "current folder")):
            return [
                TaskStep(
                    step_id="step_1",
                    description="List files in directory",
                    capability="file",
                    tool_name="list_directory",
                    input_variables={"path": "."},
                    dependencies=[]
                )
            ]

        # File search / find files
        if ("find" in req_lower or "search" in req_lower) and ("files" in req_lower or "todo" in req_lower):
            query = "TODO" if "todo" in req_lower else ("*.py" if "python" in req_lower else "file")
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Search files for '{query}'",
                    capability="file",
                    tool_name="search_in_files",
                    input_variables={"query": query, "directory": "."},
                    dependencies=[]
                )
            ]

        # File creation / write
        if any(w in req_lower for w in ("create a notes file", "create a file", "write a file", "create notes")):
            m = re.search(r"named\s+([\w\.\-]+)", req_lower)
            filename = m.group(1) if m else "test_notes.txt"
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Create file '{filename}'",
                    capability="file",
                    tool_name="write_file",
                    input_variables={"path": filename, "content": "Daily tasks\n- Review code\n- Run tests"},
                    dependencies=[]
                )
            ]

        # Read file
        if req_lower.startswith("read ") and any(w in req_lower for w in (".txt", ".md", ".json", ".py", "notes", "readme")):
            m = re.search(r"read\s+([\w\.\-]+)", req_lower)
            filename = m.group(1) if m else "README.md"
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Read file '{filename}'",
                    capability="file",
                    tool_name="read_file",
                    input_variables={"path": filename},
                    dependencies=[]
                )
            ]

        # Delete file
        if "delete" in req_lower and any(w in req_lower for w in (".txt", ".md", "file", "notes")):
            m = re.search(r"delete\s+([\w\.\-]+)", req_lower)
            filename = m.group(1) if m else "test_notes.txt"
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Safely delete file '{filename}'",
                    capability="file",
                    tool_name="safe_delete_file",
                    input_variables={"path": filename},
                    dependencies=[]
                )
            ]

        # System info
        if any(w in req_lower for w in ("system status", "system info", "cpu and memory", "cpu usage")):
            return [
                TaskStep(
                    step_id="step_1",
                    description="Get system information",
                    capability="system",
                    tool_name="get_system_info",
                    input_variables={},
                    dependencies=[]
                )
            ]

        # Windows / application active inspection
        if any(w in req_lower for w in ("running windows", "open windows", "list windows")) or ("notepad" in req_lower and any(w in req_lower for w in ("active", "running", "status"))):
            return [
                TaskStep(
                    step_id="step_1",
                    description="List open desktop windows",
                    capability="desktop",
                    tool_name="list_open_windows",
                    input_variables={},
                    dependencies=[]
                )
            ]

        # Weather
        if "weather" in req_lower:
            city_match = re.search(r"weather\s+(?:in|for|at|of)\s+([a-zA-Z\s]+?)(?:\?|$|\.|\s+today|\s+tomorrow)", user_request, re.IGNORECASE)
            city = city_match.group(1).strip() if city_match else None
            query_str = f"weather forecast in {city}" if city else "current weather forecast"
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Search weather forecast{' for ' + city if city else ''}",
                    capability="web",
                    tool_name="web_search",
                    input_variables={"query": query_str},
                    dependencies=[]
                )
            ]

        # ── Everyday Consumer Tools Heuristics (Phases 4.1 & 5.0) ──

        # Personal To-dos & Notes (Phase 5.0)
        if any(p in req_lower for p in ("add to my to-do", "add to my todo", "add to my to dos", "add to todo", "add to to-do", "add a todo", "add a to-do", "new todo", "new to-do", "create a todo", "create a to-do", "create todo", "create to-do")) or \
           (req_lower.startswith("add ") and any(w in req_lower for w in ("todo", "to-do", "task to my list", "item to my list"))):
            title = re.sub(r"^(?:add\s+)?(?:a\s+)?(?:new\s+)?(?:to-?do(?:\s+item)?|task)\s*(?::\s*)?", "", user_request, flags=re.IGNORECASE).strip()
            title = re.sub(r"\s+to\s+my\s+(?:to-?do\s+)?list.*$", "", title, flags=re.IGNORECASE).strip()
            if not title:
                title = "New Task"
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Add personal to-do '{title}'",
                    capability="everyday",
                    tool_name="manage_personal_notes_and_todos",
                    input_variables={"action": "add", "title": title, "category": "personal"},
                    dependencies=[]
                )
            ]

        if any(p in req_lower for p in ("complete todo", "complete to-do", "finish todo", "finish to-do", "mark todo", "mark to-do")) or \
           (any(w in req_lower for w in ("mark", "complete", "finish")) and any(w in req_lower for w in ("done", "completed"))):
            target = re.sub(r"^(?:mark\s+(?:the\s+)?(?:to-?do\s+|task\s+)?|complete\s+(?:the\s+)?(?:to-?do\s+|task\s+)?|finish\s+(?:the\s+)?(?:to-?do\s+|task\s+)?)", "", user_request, flags=re.IGNORECASE).strip()
            target = re.sub(r"\s+as\s+(?:done|completed).*$", "", target, flags=re.IGNORECASE).strip()
            target = re.sub(r"\s+done.*$", "", target, flags=re.IGNORECASE).strip()
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Complete personal to-do '{target}'",
                    capability="everyday",
                    tool_name="manage_personal_notes_and_todos",
                    input_variables={"action": "complete", "item_id": target},
                    dependencies=[]
                )
            ]

        if any(p in req_lower for p in ("delete todo", "delete to-do", "remove todo", "remove to-do", "delete from my to-do", "delete from my todo", "remove from my to-do", "remove from my todo", "delete from to-do", "delete from todo")) or \
           (("from my to-do" in req_lower or "from my todo" in req_lower or "from to-do" in req_lower or "from todo" in req_lower) and any(w in req_lower for w in ("delete", "remove"))):
            target = re.sub(r"^(?:delete|remove)\s+(?:the\s+)?(?:to-?do\s+|task\s+)?", "", user_request, flags=re.IGNORECASE).strip()
            target = re.sub(r"\s+from\s+my\s+(?:to-?do\s+)?list.*$", "", target, flags=re.IGNORECASE).strip()
            target = re.sub(r"\s+from\s+(?:to-?do\s+)?list.*$", "", target, flags=re.IGNORECASE).strip()
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Delete personal to-do '{target}'",
                    capability="everyday",
                    tool_name="manage_personal_notes_and_todos",
                    input_variables={"action": "delete", "item_id": target},
                    dependencies=[]
                )
            ]

        if any(p in req_lower for p in ("show my todo", "show my to-do", "list my todo", "list my to-do", "what are my todo", "what are my to-do", "my todos", "my to-dos", "my todo list", "my to-do list", "check my todo", "check my to-do", "view my todo", "view my to-do")):
            return [
                TaskStep(
                    step_id="step_1",
                    description="List personal to-do items and notes",
                    capability="everyday",
                    tool_name="manage_personal_notes_and_todos",
                    input_variables={"action": "list", "category": "all"},
                    dependencies=[]
                )
            ]

        # Smart Clipboard Assistant (Phase 5.0)
        if any(p in req_lower for p in ("what's on my clipboard", "what is on my clipboard", "read clipboard", "show clipboard", "check clipboard", "get clipboard", "view clipboard", "paste clipboard", "what did i copy", "read my clipboard")):
            return [
                TaskStep(
                    step_id="step_1",
                    description="Read current system clipboard contents",
                    capability="everyday",
                    tool_name="smart_clipboard_assistant",
                    input_variables={"action": "read"},
                    dependencies=[]
                )
            ]

        if any(p in req_lower for p in ("clipboard history", "show clipboard history", "view clipboard history", "list clipboard history", "recent clipboard")):
            return [
                TaskStep(
                    step_id="step_1",
                    description="View clipboard history buffer",
                    capability="everyday",
                    tool_name="smart_clipboard_assistant",
                    input_variables={"action": "history"},
                    dependencies=[]
                )
            ]

        if (("to clipboard" in req_lower or "to my clipboard" in req_lower or "on clipboard" in req_lower or "on my clipboard" in req_lower) and any(w in req_lower for w in ("copy", "put", "set", "write", "save"))) or \
           any(p in req_lower for p in ("copy to clipboard", "put on my clipboard", "put on clipboard", "set clipboard to", "write to clipboard")):
            content = re.sub(r"^(?:copy\s+(?:this\s+)?(?:.*?to\s+(?:my\s+)?clipboard\s*:?\s*)?|put\s+(?:this\s+)?(?:.*?on\s+(?:my\s+)?clipboard\s*:?\s*)?|set\s+clipboard\s+to\s*:?\s*|write\s+to\s+clipboard\s*:?\s*)", "", user_request, flags=re.IGNORECASE).strip()
            if not content:
                content = user_request
            return [
                TaskStep(
                    step_id="step_1",
                    description="Write content to system clipboard",
                    capability="everyday",
                    tool_name="smart_clipboard_assistant",
                    input_variables={"action": "write", "content": content},
                    dependencies=[]
                )
            ]

        # Folder smart organization & undo
        if any(w in req_lower for w in ("clean up", "organize", "declutter")) and any(w in req_lower for w in ("downloads", "desktop", "folder", "documents")):
            target_dir = "Downloads" if "downloads" in req_lower else ("Desktop" if "desktop" in req_lower else "Documents" if "documents" in req_lower else ".")
            dry_run = "preview" in req_lower or "dry run" in req_lower or "would" in req_lower
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Smart organize {target_dir} folder (dry_run={dry_run})",
                    capability="everyday",
                    tool_name="smart_organize_folder",
                    input_variables={"directory_path": target_dir, "dry_run": dry_run},
                    output_variables=["organize_result"],
                    dependencies=[]
                ),
                TaskStep(
                    step_id="step_2",
                    description="Summarize organization results and report to user",
                    capability="reasoning",
                    input_variables={"result": "{{step_1.organize_result}}"},
                    dependencies=["step_1"]
                )
            ]

        if any(w in req_lower for w in ("undo folder organization", "undo organization", "undo cleanup", "rollback organization")):
            target_dir = "Downloads" if "downloads" in req_lower else ("Desktop" if "desktop" in req_lower else ".")
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Undo folder organization in {target_dir}",
                    capability="everyday",
                    tool_name="undo_folder_organization",
                    input_variables={"directory_path": target_dir},
                    output_variables=["restore_result"],
                    dependencies=[]
                ),
                TaskStep(
                    step_id="step_2",
                    description="Report restored file status",
                    capability="reasoning",
                    input_variables={"result": "{{step_1.restore_result}}"},
                    dependencies=["step_1"]
                )
            ]

        # Reminders & timers
        if "remind" in req_lower or "timer" in req_lower:
            m_sec = re.search(r"(?:in|for)\s+(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)", req_lower)
            if not m_sec and any(phrase in req_lower for phrase in ("list", "show", "check my", "what are my", "active reminders", "my reminders", "my timers")):
                return [
                    TaskStep(
                        step_id="step_1",
                        description="List active reminders and timers",
                        capability="everyday",
                        tool_name="list_and_manage_reminders",
                        input_variables={"action": "list"},
                        dependencies=[]
                    )
                ]
            duration = 600
            if m_sec:
                val = int(m_sec.group(1))
                unit = m_sec.group(2).lower()
                if unit.startswith("s"):
                    duration = val
                elif unit.startswith("m"):
                    duration = val * 60
                elif unit.startswith("h"):
                    duration = val * 3600
            # Extract title
            title = re.sub(r"^(?:remind me in \d+\s*\w+|set a timer for \d+\s*\w+|set timer for \d+\s*\w+)\s*(?:to\s+)?", "", req_lower).strip()
            title = re.sub(r"(?:in\s+\d+\s*\w+|for\s+\d+\s*\w+)$", "", title).strip() or "Reminder"
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Create reminder '{title}' in {duration}s",
                    capability="everyday",
                    tool_name="create_reminder_or_timer",
                    input_variables={"title": title, "trigger_in_seconds": duration, "message": title},
                    dependencies=[]
                )
            ]

        # Daily Briefing
        if any(w in req_lower for w in ("daily briefing", "morning briefing", "give me my briefing", "daily update")):
            return [
                TaskStep(
                    step_id="step_1",
                    description="Generate comprehensive daily briefing",
                    capability="everyday",
                    tool_name="generate_daily_briefing",
                    input_variables={"city": "auto"},
                    output_variables=["briefing_data"],
                    dependencies=[]
                ),
                TaskStep(
                    step_id="step_2",
                    description="Synthesize personalized daily briefing",
                    capability="reasoning",
                    input_variables={"data": "{{step_1.briefing_data}}"},
                    dependencies=["step_1"]
                )
            ]

        # Document extraction and summarization
        if any(w in req_lower for w in ("summarize", "explain", "read")) and any(w in req_lower for w in ("pdf", "docx", "document", "contract")):
            file_cand = "sample.pdf"
            m_path = re.search(r"([\w\-\./\\]+\.(?:pdf|docx|txt|md|csv))", req_lower)
            if m_path:
                file_cand = m_path.group(1)
            elif "desktop" in req_lower:
                file_cand = str(Path.home() / "Desktop" / "document.pdf")
            return [
                TaskStep(
                    step_id="step_1",
                    description=f"Extract document text from '{file_cand}'",
                    capability="everyday",
                    tool_name="summarize_local_document",
                    input_variables={"file_path": file_cand},
                    output_variables=["doc_data"],
                    dependencies=[]
                ),
                TaskStep(
                    step_id="step_2",
                    description="Analyze and summarize document contents",
                    capability="reasoning",
                    input_variables={"text": "{{step_1.doc_data}}"},
                    dependencies=["step_1"]
                )
            ]

        # Everyday Windows Controls (volume, mute, task manager, settings, recycle bin)
        if any(w in req_lower for w in ("mute my volume", "mute volume", "mute the volume", "unmute volume", "unmute")):
            return [
                TaskStep(
                    step_id="step_1",
                    description="Toggle mute on master volume",
                    capability="everyday",
                    tool_name="control_windows_setting",
                    input_variables={"setting": "mute_toggle"},
                    dependencies=[]
                )
            ]

        if any(w in req_lower for w in ("empty recycle bin", "empty the recycle bin", "clean recycle bin")):
            return [
                TaskStep(
                    step_id="step_1",
                    description="Empty Windows Recycle Bin",
                    capability="everyday",
                    tool_name="control_windows_setting",
                    input_variables={"setting": "empty_recycle_bin"},
                    dependencies=[]
                )
            ]

        if any(w in req_lower for w in ("open settings", "windows settings")):
            return [
                TaskStep(
                    step_id="step_1",
                    description="Open Windows Settings app",
                    capability="everyday",
                    tool_name="control_windows_setting",
                    input_variables={"setting": "open_settings"},
                    dependencies=[]
                )
            ]

        # Conversational fallback
        return [
            TaskStep(
                step_id="step_1",
                description="Process user request and respond",
                capability="reasoning",
                input_variables={"request": user_request},
                dependencies=[]
            )
        ]

    # ─── DAG Execution Engine ─────────────────────────────────────────────────

    def _execute_plan_dag(self, task: AssistantTask, resolved_input: str) -> tuple[str, list[str]]:
        """
        Executes a plan respecting dependencies, parameter validation, security, and verification.
        Returns: (final_answer, candidate_items)
        """
        completed_set: set[str] = set()
        failed_set: set[str] = set()
        step_outputs: dict[str, Any] = {}
        candidate_items: list[str] = []
        final_answer = ""

        while len(completed_set) + len(failed_set) < len(task.plan):
            if task.is_cancelled:
                for s in task.plan:
                    if s.step_id not in completed_set and s.step_id not in failed_set:
                        s.status = TaskStepStatus.SKIPPED
                if task.status != TaskStatus.CANCELLED:
                    task.transition_to(TaskStatus.CANCELLED, details={"reason": "Interrupted by cancellation directive"})
                try:
                    from api.ws_manager import ws_manager
                    if task.session_id:
                        ws_manager.safe_send_to_session(task.session_id, {"type": "TASK_CANCELLED", "task_id": task.task_id, "status": "CANCELLED"})
                    else:
                        log.info(f"[Orchestrator] Task {task.task_id} cancelled (no session_id to notify).")
                except Exception:
                    pass
                return "Task cancelled by user directive.", candidate_items

            # Find ready steps whose dependencies are all completed
            ready_steps = [
                s for s in task.plan
                if s.step_id not in completed_set and s.step_id not in failed_set
                and all(dep in completed_set for dep in s.dependencies)
            ]

            if not ready_steps:
                # Deadlock or broken dependencies
                for s in task.plan:
                    if s.step_id not in completed_set and s.step_id not in failed_set:
                        s.status = TaskStepStatus.SKIPPED
                        failed_set.add(s.step_id)
                break

            for step in ready_steps:
                if task.is_cancelled:
                    for s in task.plan:
                        if s.step_id not in completed_set and s.step_id not in failed_set:
                            s.status = TaskStepStatus.SKIPPED
                    if task.status != TaskStatus.CANCELLED:
                        task.transition_to(TaskStatus.CANCELLED, details={"reason": "Interrupted by cancellation directive"})
                    try:
                        from api.ws_manager import ws_manager
                        if task.session_id:
                            ws_manager.safe_send_to_session(task.session_id, {"type": "TASK_CANCELLED", "task_id": task.task_id, "status": "CANCELLED"})
                        else:
                            log.info(f"[Orchestrator] Task {task.task_id} cancelled (no session_id to notify).")
                    except Exception:
                        pass
                    return "Task cancelled by user directive.", candidate_items

                task.current_step = next((i for i, s in enumerate(task.plan) if s.step_id == step.step_id), 0)
                step.status = TaskStepStatus.RUNNING
                task.add_audit_event("STEP_START", {"step_id": step.step_id, "desc": step.description, "tool": step.tool_name})

                # Reasoning step
                if step.capability == "reasoning" or not step.tool_name:
                    step_res = self._execute_reasoning_step(step, step_outputs, resolved_input)
                    if step_res.get("success"):
                        step.status = TaskStepStatus.COMPLETED
                        step.result = step_res.get("output")
                        step_outputs[step.step_id] = step.result
                        completed_set.add(step.step_id)
                        task.completed_steps.append(step.step_id)
                        final_answer = str(step.result)
                    else:
                        step.status = TaskStepStatus.FAILED
                        step.error = step_res.get("error", "Reasoning failed")
                        failed_set.add(step.step_id)
                        task.failed_steps.append(step.step_id)
                    continue

                # Tool step
                tool_name = step.tool_name
                tool_args = self._resolve_step_args(step.input_variables, step_outputs, tool_name=tool_name)

                missing = self._check_missing_parameters(tool_name, tool_args)
                if missing:
                    task.transition_to(TaskStatus.WAITING_FOR_INPUT, details={"missing": missing, "tool": tool_name})
                    return f"Sir, to {step.description.lower()}, I need you to provide the {', '.join(missing)}.", candidate_items

                exec_res = self.tool_router.execute_tool(
                    name=tool_name,
                    args=tool_args,
                    interactive=True,
                    cancellation_token=task.cancellation_token
                )
                step.result = exec_res.output
                step.evidence = exec_res.evidence
                step.error = exec_res.error

                if task.is_cancelled:
                    step.status = TaskStepStatus.CANCELLED
                    for s in task.plan:
                        if s.step_id not in completed_set and s.step_id not in failed_set:
                            s.status = TaskStepStatus.SKIPPED
                    if task.status != TaskStatus.CANCELLED:
                        task.transition_to(TaskStatus.CANCELLED, details={"reason": "Interrupted during tool execution"})
                    try:
                        from api.ws_manager import ws_manager
                        if task.session_id:
                            ws_manager.safe_send_to_session(task.session_id, {"type": "TASK_CANCELLED", "task_id": task.task_id, "status": "CANCELLED"})
                        else:
                            log.info(f"[Orchestrator] Task {task.task_id} cancelled (no session_id to notify).")
                    except Exception:
                        pass
                    return "Task cancelled by user directive.", candidate_items


                if exec_res.success:
                    step.status = TaskStepStatus.COMPLETED
                    completed_set.add(step.step_id)
                    task.completed_steps.append(step.step_id)
                    step_outputs[step.step_id] = exec_res.output
                    task.add_audit_event("STEP_SUCCESS", {
                        "step_id": step.step_id,
                        "evidence": exec_res.evidence,
                        "verified": exec_res.verified
                    })
                    if tool_name == "get_active_window_context" and isinstance(exec_res.output, dict):
                        if hasattr(self, "context_tracker"):
                            self.context_tracker.set_window_context(exec_res.output)
                    extracted = self._extract_candidates(tool_name, exec_res.output)
                    if extracted:
                        candidate_items.extend(extracted)
                else:
                    # Failure recovery attempt
                    task.transition_to(TaskStatus.RECOVERING, details={"step_id": step.step_id, "error": exec_res.error})
                    recovered_res = self._attempt_recovery(step, tool_args, exec_res.error, step_outputs)
                    if recovered_res and recovered_res.success:
                        step.status = TaskStepStatus.COMPLETED
                        step.result = recovered_res.output
                        step.evidence = recovered_res.evidence
                        completed_set.add(step.step_id)
                        task.completed_steps.append(step.step_id)
                        step_outputs[step.step_id] = recovered_res.output
                        task.add_audit_event("STEP_RECOVERED", {"step_id": step.step_id, "output": str(recovered_res.output)[:100]})
                    else:
                        step.status = TaskStepStatus.FAILED
                        failed_set.add(step.step_id)
                        task.failed_steps.append(step.step_id)
                        if getattr(exec_res, "timed_out", False):
                            task.transition_to(TaskStatus.TIMED_OUT, details={"failed_step": step.step_id, "error": exec_res.error})
                        else:
                            task.transition_to(TaskStatus.FAILED, details={"failed_step": step.step_id, "error": exec_res.error})
                        return f"Sir, I encountered an issue while attempting to {step.description.lower()}: {exec_res.error}.", candidate_items

        if not final_answer:
            final_answer = self._generate_final_response(resolved_input, task, step_outputs)

        return final_answer, candidate_items

    # ─── Execution Helpers ───────────────────────────────────────────────────

    def _resolve_step_args(self, input_vars: dict, step_outputs: dict, tool_name: Optional[str] = None) -> dict:
        """Resolve {{step_N.var}} interpolations from previous step outputs and reconcile parameter aliases."""
        resolved = {}
        for k, v in input_vars.items():
            if isinstance(v, str) and "{{" in v and "}}" in v:
                match = re.search(r"\{\{([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\}\}", v)
                if match:
                    step_id = match.group(1)
                    val = step_outputs.get(step_id, v)
                    resolved[k] = val
                    continue
            resolved[k] = v

        # Parameter reconciliation for path / file_path
        if tool_name and self.tool_router:
            schema = self.tool_router.get_tool(tool_name)
            fields = set(schema.pydantic_model.model_fields.keys()) if (schema and schema.pydantic_model) else set(schema.parameters.keys() if schema else [])
            if "file_path" in fields and "path" in resolved and "file_path" not in resolved:
                resolved["file_path"] = resolved.pop("path")
            elif "path" in fields and "file_path" in resolved and "path" not in resolved:
                resolved["path"] = resolved.pop("file_path")
        return resolved

    def _check_missing_parameters(self, tool_name: str, args: dict) -> list[str]:
        """Verify that strictly required parameters are not empty strings or None."""
        schema = self.tool_router.get_tool(tool_name) if self.tool_router else None
        if not schema or not schema.pydantic_model:
            return []
        
        missing = []
        for field_name, field_info in schema.pydantic_model.model_fields.items():
            if field_info.is_required() and (args.get(field_name) is None or args.get(field_name) == ""):
                missing.append(field_name)
        return missing

    def _execute_reasoning_step(self, step: TaskStep, step_outputs: dict, original_request: str) -> dict:
        """Execute an LLM reasoning node."""
        if self.reasoning:
            context_str = "\n".join([f"Step Output: {v}" for v in step_outputs.values()])
            prompt = (
                f"User Request: {original_request}\n"
                f"Context from executed steps:\n{context_str}\n\n"
                f"Task: {step.description}\n"
                "Synthesize a clear, accurate, and concise response for the user."
            )
            response = self.reasoning.generate_text(prompt)
            return {"success": True, "output": response}
        return {"success": True, "output": "Execution completed."}

    def _attempt_recovery(self, failed_step: TaskStep, args: dict, error_msg: str, step_outputs: dict) -> Optional[ToolExecutionResult]:
        """Attempt safe single retry or tool fallback."""
        tool_name = failed_step.tool_name
        
        # 1. Safe retry for read_file: try listing directory or finding close match
        if tool_name == "read_file":
            target_path = args.get("file_path", "")
            log.info(f"[Orchestrator] Attempting recovery for failed read_file('{target_path}')")
            list_res = self.tool_router.execute_tool("list_directory", {"path": "."}, interactive=False)
            if list_res.success and isinstance(list_res.output, str):
                base_target = target_path.split("/")[-1].split("\\")[-1].lower()
                base_stem = base_target.rsplit(".", 1)[0] if "." in base_target else base_target
                for line in list_res.output.split("\n"):
                    line_lower = line.lower()
                    if (base_target in line_lower or (base_stem and base_stem in line_lower)) and "." in line:
                        guessed_file = line.strip().split()[-1]
                        log.info(f"[Orchestrator] Recovered candidate file: {guessed_file}")
                        return self.tool_router.execute_tool("read_file", {"file_path": guessed_file}, interactive=False)

        # 2. Safe retry for web_search: simplify query
        if tool_name == "web_search":
            q = args.get("query", "")
            words = q.split()
            if len(words) > 3:
                simplified_q = " ".join(words[:3])
                log.info(f"[Orchestrator] Retrying web_search with simplified query: {simplified_q}")
                return self.tool_router.execute_tool("web_search", {"query": simplified_q}, interactive=False)

        return None

    def _generate_final_response(self, user_request: str, task: AssistantTask, step_outputs: dict) -> str:
        """Compose the final natural-language response."""
        if not step_outputs:
            session_id = getattr(task, "session_id", None)
            user_id = getattr(task, "user_id", None)
            if self.brain and hasattr(self.brain, "context") and hasattr(self.brain, "reasoning"):
                try:
                    import asyncio as _asyncio
                    try:
                        loop = _asyncio.get_event_loop()
                    except RuntimeError:
                        loop = _asyncio.new_event_loop()
                        _asyncio.set_event_loop(loop)
                    async def _enrich():
                        try:
                            return await self.brain.context.build_enriched_prompt(
                                user_request, session_id=session_id, user_id=user_id
                            )
                        except TypeError:
                            return await self.brain.context.build_enriched_prompt(user_request)

                    if loop.is_running():
                        enriched = _asyncio.run_coroutine_threadsafe(_enrich(), loop).result()
                    else:
                        enriched = loop.run_until_complete(_enrich())
                except Exception:
                    enriched = user_request
                raw_res = self.brain.reasoning.send_message(
                    enriched, raw_message=user_request, session_id=session_id, user_id=user_id
                )
                if hasattr(self.brain, "response"):
                    return self.brain.response.format_response(raw_res)
                return str(raw_res)
            elif self.reasoning:
                return self.reasoning.send_message(user_request, session_id=session_id, user_id=user_id)
            return "Task completed successfully, Sir."

        # If LLM reasoning available, synthesize final presentation
        if self.reasoning:
            outputs_summary = "\n".join([f"- {k}: {str(v)[:1500]}" for k, v in step_outputs.items()])
            prompt = (
                f"You are JARVIS, an AI personal assistant.\n"
                f"User asked: {user_request}\n"
                f"You executed the following task plan successfully:\n{outputs_summary}\n\n"
                "Respond to the user with a helpful, natural, and accurate summary of the results."
            )
            return self.reasoning.generate_text(prompt)

        return list(step_outputs.values())[-1]

    def _extract_candidates(self, tool_name: str, output: Any) -> list[str]:
        """Extract candidate items from tool outputs for referential follow-up."""
        candidates = []
        if tool_name == "list_directory" and isinstance(output, str):
            for line in output.split("\n"):
                clean = line.strip()
                if clean and not clean.startswith("Contents"):
                    candidates.append(clean)
        return candidates[:10]

    def _handle_memory_persistence(
        self,
        task: AssistantTask,
        result: str,
        execution_context: Optional[ExecutionContext] = None
    ) -> None:
        """
        Apply memory policy to persist only meaningful facts or preferences.
        Strictly honors store_memory=False to prevent writing to conversational or semantic memory.
        """
        store_allowed = True
        if execution_context is not None:
            store_allowed = execution_context.store_memory
        elif hasattr(task, "store_memory"):
            store_allowed = task.store_memory

        if not store_allowed:
            log.info(f"[Orchestrator] Memory persistence skipped for task {task.task_id} (store_memory=False).")
            return

        if not self.memory_manager:
            return

        tier, category = MemoryPolicy.classify_interaction(task.user_request)
        sess_id = execution_context.session_id if execution_context else getattr(task, "session_id", None)
        u_id = execution_context.user_id if execution_context else getattr(task, "user_id", None)
        if tier in (MemoryTier.USER_PREFERENCE, MemoryTier.LONG_TERM_KNOWLEDGE):
            self.memory_manager.store_exchange(task.user_request, str(result)[:500], session_id=sess_id, user_id=u_id)
            log.info(f"[Orchestrator] Persisted to long-term memory [{category}]: {task.user_request[:60]}")
        else:
            if hasattr(self.memory_manager._memory, "conversations"):
                self.memory_manager._memory.conversations.add_turn("user", task.user_request, session_id=sess_id, user_id=u_id)
                self.memory_manager._memory.conversations.add_turn("assistant", str(result)[:500], session_id=sess_id, user_id=u_id)
