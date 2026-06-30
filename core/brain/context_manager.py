"""
JARVIS Brain — Context Manager
Builds enriched prompts by assembling memory context, conversation history,
and relevant state into the user message before sending to the LLM.
"""

from typing import Optional

from core.logger import log, error_log


class ContextManager:
    """
    Responsible for building the enriched prompt that goes to the LLM.
    Injects memory context, recent conversation, and active task state
    into the user's message as structured prefixes.
    """

    def __init__(self, memory_manager=None):
        """
        Args:
            memory_manager: Optional MemoryManager instance for context retrieval.
        """
        self._memory_manager = memory_manager
        self._active_task_context: Optional[str] = None

    def set_memory_manager(self, memory_manager) -> None:
        """Attach or replace the memory manager."""
        self._memory_manager = memory_manager

    def set_active_task(self, task_context: Optional[str]) -> None:
        """
        Set the active task context (for multi-step task execution).
        Set to None when no task is active.
        """
        self._active_task_context = task_context

    def build_enriched_prompt(self, user_input: str) -> str:
        """
        Enrich the user's message with relevant context.

        Injects:
        1. Relevant memory snippets (semantic search)
        2. Recent conversation turns
        3. Active task context (if executing a plan)

        Args:
            user_input: The raw user message.

        Returns:
            Enriched prompt string with context prefixes.
        """
        prefix_parts = []

        # 1. Memory context
        if self._memory_manager:
            try:
                memory_snippet = self._memory_manager.get_relevant_context(user_input)
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

        Args:
            task:              Overall task description.
            step_description:  Current step to execute.
            step_index:        Step number (0-indexed).
            previous_results:  Results from prior successful steps.

        Returns:
            Formatted step execution prompt.
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
