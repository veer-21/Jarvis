"""
JARVIS Brain — Memory Manager
Interface layer between the Brain and the JarvisMemory system.
Handles context-aware retrieval, working memory, and memory prioritization.
"""

import asyncio
from typing import Optional

from core.logger import log, error_log


class MemoryManager:
    """
    Memory interface for the Brain.
    Wraps JarvisMemory with context-aware retrieval, working memory
    for current session state, and intelligent memory storage decisions.
    """

    def __init__(self, memory=None):
        """
        Args:
            memory: Optional JarvisMemory instance.
        """
        self._memory = memory
        self._working_memory: dict = {}  # Transient session state

    def set_memory(self, memory) -> None:
        """Attach or replace the memory system."""
        self._memory = memory
        log.info("Memory system attached to MemoryManager.")

    @property
    def is_active(self) -> bool:
        return self._memory is not None

    # ─── Working Memory (Session State) ───────────────────────────────────────

    def set_working(self, key: str, value) -> None:
        """Store a value in working memory (session-scoped, not persisted)."""
        self._working_memory[key] = value

    def get_working(self, key: str, default=None):
        """Retrieve from working memory."""
        return self._working_memory.get(key, default)

    def clear_working(self, session_id: Optional[str] = None) -> None:
        """Clear working memory, optionally scoped to a session."""
        if session_id:
            to_del = [k for k in self._working_memory if k.startswith(f"{session_id}:")]
            for k in to_del:
                self._working_memory.pop(k, None)
        else:
            self._working_memory.clear()

    # ─── Context Retrieval (Synchronous) ──────────────────────────────────────

    def get_relevant_context(
        self,
        query: str,
        max_memories: int = 5,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        allow_system_scope: bool = False,
    ) -> str:
        """
        Retrieve relevant memory context for the given query, filtered by user_id (Synchronous) (P0-1, P0-2, P1-5).
        Fails closed if user_id is missing and allow_system_scope is False.
        """
        if not self._memory:
            return ""
        if not user_id and not allow_system_scope:
            return ""

        try:
            return self._memory.build_context_snippet(
                query, max_memories=max_memories, user_id=user_id, session_id=session_id, allow_system_scope=allow_system_scope
            )
        except Exception as e:
            error_log.error(f"Memory retrieval failed: {e}")
            return ""

    def get_recent_conversation_string(self, n: int = 6, session_id: Optional[str] = None, user_id: Optional[str] = None, allow_system_scope: bool = False) -> str:
        """
        Get recent conversation turns as a formatted string (P1-2).
        Fails closed if user_id is missing without allow_system_scope.
        """
        if not self._memory:
            return ""
        if not user_id and not allow_system_scope:
            return ""

        try:
            return self._memory.conversations.get_context_string(n=n, session_id=session_id, user_id=user_id, allow_system_scope=allow_system_scope)
        except Exception as e:
            error_log.error(f"Conversation retrieval failed: {e}")
            return ""

    # ─── Context Retrieval (Asynchronous) ─────────────────────────────────────

    async def get_relevant_context_async(
        self,
        query: str,
        max_memories: int = 5,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        allow_system_scope: bool = False,
    ) -> str:
        """
        Asynchronously retrieve relevant memory context using thread executors, filtered by user_id (P0-1, P0-2, P1-5).
        Fails closed if user_id is missing and allow_system_scope is False.
        Ensures embedding generation never blocks the FastAPI loop.
        """
        if not self._memory:
            return ""
        if not user_id and not allow_system_scope:
            return ""

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, 
                self._memory.build_context_snippet, 
                query, 
                max_memories,
                user_id,
                session_id,
                allow_system_scope,
            )
        except Exception as e:
            error_log.error(f"Memory retrieval async failed: {e}")
            return ""

    # ─── Store (Synchronous) ──────────────────────────────────────────────────

    def store_exchange(self, user_input: str, response: str, session_id: Optional[str] = None, user_id: Optional[str] = None) -> None:
        """
        Store a conversation exchange in long-term memory.
        """
        if not self._memory:
            return

        try:
            self._memory.add_conversation_turn("user", user_input, session_id=session_id, user_id=user_id)
            self._memory.add_conversation_turn("assistant", response, session_id=session_id, user_id=user_id)
        except Exception as e:
            error_log.error(f"Memory store failed: {e}")

    def store_task_result(self, task: str, result: str, user_id: Optional[str] = None) -> None:
        """Store a completed task and its result in task memory scoped to owner."""
        if not self._memory:
            return

        try:
            self._memory.store_memory(
                f"Task: {task}\nResult: {result[:500]}",
                category="task",
                metadata={"type": "task_result"},
                user_id=user_id,
            )
        except Exception as e:
            error_log.error(f"Task memory store failed: {e}")

    # ─── Store (Asynchronous) ─────────────────────────────────────────────────

    async def store_exchange_async(self, user_input: str, response: str, session_id: Optional[str] = None, user_id: Optional[str] = None) -> None:
        """
        Asynchronously store a conversation exchange using thread executors.
        """
        if not self._memory:
            return

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, 
                self._memory.add_conversation_turn, 
                "user", 
                user_input,
                session_id,
                user_id
            )
            await loop.run_in_executor(
                None, 
                self._memory.add_conversation_turn, 
                "assistant", 
                response,
                session_id,
                user_id
            )
        except Exception as e:
            error_log.error(f"Memory store async failed: {e}")

    async def store_task_result_async(self, task: str, result: str, user_id: Optional[str] = None) -> None:
        """Asynchronously store a task result using thread executors."""
        if not self._memory:
            return

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._memory.store_memory,
                f"Task: {task}\nResult: {result[:500]}",
                "task",
                {"type": "task_result"},
                False,
                user_id,
            )
        except Exception as e:
            error_log.error(f"Task memory store async failed: {e}")

    # ─── Introspection ────────────────────────────────────────────────────────

    def stats(self, user_id: Optional[str] = None, allow_system_scope: bool = False) -> dict:
        """Return memory system statistics (P1-2)."""
        if not self._memory:
            return {"backend": "none", "long_term_memories": 0, "conversation_turns": 0, "episodes": 0}
        return self._memory.stats(user_id=user_id, allow_system_scope=allow_system_scope)

    def get_recent_conversation(self, n: int = 15, session_id: Optional[str] = None, user_id: Optional[str] = None, allow_system_scope: bool = False) -> list[dict]:
        """Return recent conversation turns as a list of dicts (P1-2). Fails closed without owner."""
        if not self._memory:
            return []
        if not user_id and not allow_system_scope:
            return []
        return self._memory.get_recent_conversation(n, session_id=session_id, user_id=user_id, allow_system_scope=allow_system_scope)

    def clear_conversation(self, session_id: Optional[str] = None, user_id: Optional[str] = None, allow_system_scope: bool = False) -> None:
        """Clear conversation turns scoped to session or user (P1-2)."""
        if self._memory and hasattr(self._memory, "conversations"):
            self._memory.conversations.clear(session_id=session_id, user_id=user_id, allow_system_scope=allow_system_scope)

    def clear_all(self, user_id: Optional[str] = None, allow_system_scope: bool = False) -> bool:
        """Clear all memory scoped to user or system authorized (P1-2)."""
        if self._memory and hasattr(self._memory, "clear_all"):
            return self._memory.clear_all(user_id=user_id, allow_system_scope=allow_system_scope)
        return False

    def delete_memory(
        self,
        memory_id: Optional[str] = None,
        query: Optional[str] = None,
        user_id: Optional[str] = None,
        allow_system_scope: bool = False,
    ) -> bool:
        """Delete a memory by id or query, enforcing ownership (P0-2, P1-5)."""
        if not self._memory or not hasattr(self._memory, "delete_memory"):
            return False
        if not user_id and not allow_system_scope:
            log.warning("MemoryManager: delete_memory rejected due to missing user_id.")
            return False
        return self._memory.delete_memory(
            memory_id=memory_id,
            query=query,
            user_id=user_id,
            allow_system_scope=allow_system_scope,
        )
