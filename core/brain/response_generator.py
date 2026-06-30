"""
JARVIS Brain — Response Generator
Post-processes LLM output: formats responses, adds execution summaries,
and prepares final user-facing text.
"""

from typing import Optional

from core.logger import log


class ResponseGenerator:
    """
    Post-processes the raw LLM response into clean, user-facing output.
    Handles formatting, execution summaries, and response cleanup.
    """

    def __init__(self):
        log.info("ResponseGenerator initialized.")

    def format_response(self, raw_response: str, execution_summary: Optional[str] = None) -> str:
        """
        Format the raw LLM response for user presentation.

        Args:
            raw_response:      The raw text from the LLM.
            execution_summary: Optional execution report to append.

        Returns:
            Cleaned, formatted response string.
        """
        response = raw_response.strip()

        # Remove any internal reasoning markers
        response = self._strip_internal_markers(response)

        # Append execution summary if provided
        if execution_summary:
            response = f"{response}\n\n{execution_summary}"

        return response

    def format_tool_result(self, tool_name: str, success: bool, result: str) -> str:
        """
        Format a tool execution result for display.

        Args:
            tool_name: Name of the executed tool.
            success:   Whether execution succeeded.
            result:    The tool's output.

        Returns:
            Formatted result string.
        """
        status = "✅ Success" if success else "❌ Failed"
        return f"[Tool: {tool_name}] {status}\n{result}"

    def format_error(self, error_message: str) -> str:
        """Format an error message for user display."""
        return f"I encountered an issue: {error_message}\nPlease let me know if you'd like me to try a different approach."

    def _strip_internal_markers(self, text: str) -> str:
        """Remove internal reasoning/planning markers from the response."""
        # Strip common internal markers
        markers = [
            "[INTERNAL]", "[REASONING]", "[PLANNING]",
            "[THINKING]", "[DEBUG]",
        ]
        for marker in markers:
            text = text.replace(marker, "")

        return text.strip()

    def summarize_multi_step(self, task: str, steps_completed: int, steps_total: int, results: list[str]) -> str:
        """
        Create a human-readable summary of a multi-step execution.

        Args:
            task:            The original task description.
            steps_completed: Number of steps that succeeded.
            steps_total:     Total number of steps.
            results:         List of step result strings.

        Returns:
            Formatted summary string.
        """
        lines = [
            f"Task completed: {task}",
            f"Steps: {steps_completed}/{steps_total} succeeded",
        ]

        if results:
            lines.append("\nKey results:")
            for i, r in enumerate(results, 1):
                if r:
                    lines.append(f"  {i}. {r[:150]}")

        return "\n".join(lines)
