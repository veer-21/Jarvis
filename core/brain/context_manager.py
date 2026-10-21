"""
JARVIS Brain — Context Manager
Builds enriched prompts by assembling memory context, conversation history,
and relevant state into the user message before sending to the LLM.
"""

import threading
import asyncio
from typing import Optional, Dict, Any
from core.logger import log, error_log


class ContextManager:
    """
    Responsible for building the enriched prompt that goes to the LLM.
    Injects memory context, recent conversation, and active task state
    into the user's message as structured prefixes.
    Supports thread-safe pre-fetching of context to bring critical path RAG latency to zero.
    """

    def __init__(self, memory_manager=None):
        """
        Args:
            memory_manager: Optional MemoryManager instance for context retrieval.
        """
        self._memory_manager = memory_manager
        self._active_task_context: Optional[str] = None
        
        # Thread-safe sliding window memory cache keyed by (user_id, session_id)
        self._prefetched_contexts: Dict[str, str] = {}
        self._prefetch_lock = threading.Lock()

    @property
    def _prefetched_context(self) -> Optional[str]:
        """Backward-compatible access to default prefetch context."""
        with self._prefetch_lock:
            return self._prefetched_contexts.get("default:default")

    @_prefetched_context.setter
    def _prefetched_context(self, value: Optional[str]) -> None:
        with self._prefetch_lock:
            if value is None:
                self._prefetched_contexts.pop("default:default", None)
            else:
                self._prefetched_contexts["default:default"] = value

    def _make_key(self, session_id: Optional[str] = None, user_id: Optional[str] = None) -> str:
        sid = session_id or "default"
        uid = user_id or "default"
        return f"{uid}:{sid}"

    def set_memory_manager(self, memory_manager) -> None:
        """Attach or replace the memory manager."""
        self._memory_manager = memory_manager

    def set_active_task(self, task_context: Optional[str]) -> None:
        """
        Set the active task context (for multi-step task execution).
        Set to None when no task is active.
        """
        self._active_task_context = task_context

    def clear_prefetch(self, session_id: Optional[str] = None, user_id: Optional[str] = None) -> None:
        """Clear prefetched context for a specific session or globally."""
        with self._prefetch_lock:
            if session_id is None and user_id is None:
                self._prefetched_contexts.clear()
            else:
                key = self._make_key(session_id, user_id)
                self._prefetched_contexts.pop(key, None)
                if session_id and not user_id:
                    to_remove = [k for k in self._prefetched_contexts if k.endswith(f":{session_id}")]
                    for k in to_remove:
                        self._prefetched_contexts.pop(k, None)

    def start_prefetch(self, query: str, session_id: Optional[str] = None, user_id: Optional[str] = None) -> None:
        """
        Proactively pre-fetch context in a background worker thread.
        This warms up the local embedding models and vector database search
        while the user is still speaking or typing.
        Prefetch is strictly isolated by authenticated session and user (P0-4).
        """
        if not self._memory_manager:
            return

        # Skip pre-fetching for extremely short queries
        if len(query.strip()) < 3:
            return

        key = self._make_key(session_id, user_id)

        def _worker():
            try:
                log.debug(f"[ContextManager] Background pre-fetch starting for [{key}]: '{query[:40]}'")
                context = self._memory_manager.get_relevant_context(query, user_id=user_id, session_id=session_id)
                with self._prefetch_lock:
                    self._prefetched_contexts[key] = context
                log.info(f"[ContextManager] Context pre-fetched for [{key}]: {len(context)} chars.")
            except Exception as e:
                error_log.error(f"Background pre-fetch failed for [{key}]: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    async def build_enriched_prompt(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        context: Optional[Any] = None,
    ) -> str:
        """
        Enrich the user's message with relevant context.
        Uses pre-fetched context from background thread for the calling session if available,
        otherwise falls back to asynchronous retrieval.
        Context prefetch is strictly isolated per session and user (P0-2, P0-4).

        Injects:
        1. Relevant memory snippets (semantic search scoped to user_id)
        2. Active task context (if executing a plan)

        Args:
            user_input: The raw user message.
            session_id: Authenticated session identifier.
            user_id:    Authenticated user identifier.
            context:    Optional ExecutionContext instance.

        Returns:
            Enriched prompt string with context prefixes.
        """
        prefix_parts = []

        if context is not None:
            if not session_id:
                session_id = getattr(context, "session_id", None)
            if not user_id:
                user_id = getattr(context, "user_id", None)

        key = self._make_key(session_id, user_id)

        # 1. Memory context
        if self._memory_manager:
            try:
                memory_snippet = None
                with self._prefetch_lock:
                    if key in self._prefetched_contexts:
                        memory_snippet = self._prefetched_contexts.pop(key, None)  # Consume cache strictly for this session

                if memory_snippet is None:
                    # Cache miss fallback: retrieve asynchronously without blocking main thread
                    memory_snippet = await self._memory_manager.get_relevant_context_async(
                        user_input, user_id=user_id, session_id=session_id
                    )

                if memory_snippet:
                    prefix_parts.append(memory_snippet)
            except Exception as e:
                error_log.error(f"Memory context retrieval failed: {e}")

        # 2. Active task context
        if self._active_task_context:
            prefix_parts.append(f"[ACTIVE TASK CONTEXT]\n{self._active_task_context}")

        # Assemble
        if prefix_parts:
            prefix = "\n\n".join(prefix_parts)
            return f"{prefix}\n\n[CURRENT USER MESSAGE]\n{user_input}"

        return user_input

    def build_task_step_prompt(
        self,
        task: str,
        step_description: str,
        step_index: int,
        previous_results: list[str],
    ) -> str:
        """
        Build a prompt for executing a single step of a multi-step plan.
        """
        context = ""
        if previous_results:
            context_lines = [
                f"Step {i+1} result: {r}"
                for i, r in enumerate(previous_results)
            ]
            context = "Previous steps completed:\n" + "\n".join(context_lines) + "\n"

        return (
            f"You are executing step {step_index+1} of a plan.\n"
            f"Overall task: {task}\n"
            f"{context}\n"
            f"Current step: {step_description}\n\n"
            "Execute this step now. Be concise. Use tools if needed."
        )
