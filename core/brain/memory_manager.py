"""
JARVIS Brain — Memory Manager
Interface layer between the Brain and the JarvisMemory system.
Handles context-aware retrieval, working memory, and memory prioritization.
"""

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

    def clear_working(self) -> None:
        """Clear all working memory."""
        self._working_memory.clear()

    # ─── Context Retrieval ────────────────────────────────────────────────────

    def get_relevant_context(self, query: str, max_memories: int = 5) -> str:
        """
        Retrieve relevant memory context for the given query.

        Args:
            query:         The user's message to find relevant memories for.
            max_memories:  Maximum memories to include.

        Returns:
            Formatted memory context string, or empty string.
        """
        if not self._memory:
            return ""

        try:
            return self._memory.build_context_snippet(query, max_memories=max_memories)
        except Exception as e:
            error_log.error(f"Memory retrieval failed: {e}")
            return ""

    def get_recent_conversation_string(self, n: int = 6) -> str:
        """
        Get recent conversation turns as a formatted string.

        Args:
            n: Number of recent turns to include.

        Returns:
            Formatted conversation history string.
        """
        if not self._memory:
            return ""

        try:
            return self._memory.conversations.get_context_string(n=n)
        except Exception as e:
            error_log.error(f"Conversation retrieval failed: {e}")
            return ""

    # ─── Store ────────────────────────────────────────────────────────────────

    def store_exchange(self, user_input: str, response: str) -> None:
        """
        Store a conversation exchange in long-term memory.
        Only stores substantive exchanges to avoid memory pollution.

        Args:
            user_input: The user's message.
            response:   JARVIS's response.
        """
        if not self._memory:
            return

        try:
            self._memory.add_conversation_turn("user", user_input)
            self._memory.add_conversation_turn("assistant", response)
        except Exception as e:
            error_log.error(f"Memory store failed: {e}")

    def store_task_result(self, task: str, result: str) -> None:
        """Store a completed task and its result in task memory."""
        if not self._memory:
            return

        try:
            self._memory.store_memory(
                f"Task: {task}\nResult: {result[:500]}",
                category="task",
                metadata={"type": "task_result"},
            )
        except Exception as e:
            error_log.error(f"Task memory store failed: {e}")

    # ─── Introspection ────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return memory system statistics."""
        if not self._memory:
            return {"backend": "none", "long_term_memories": 0, "conversation_turns": 0}
        return self._memory.stats()

    def get_recent_conversation(self, n: int = 15) -> list[dict]:
        """Return recent conversation turns as a list of dicts."""
        if not self._memory:
            return []
        return self._memory.get_recent_conversation(n)
