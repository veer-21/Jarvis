"""
JARVIS — Dynamic Prompt Composer
Assembles system prompts from modular layers based on the current context.
Replaces the monolithic system_prompt.py with intelligent, context-aware composition.
"""

from typing import Optional

from core.prompts.core_prompt import CORE_PROMPT
from core.prompts.safety_prompt import SAFETY_PROMPT
from core.prompts.planner_prompt import PLANNER_PROMPT
from core.prompts.memory_prompt import MEMORY_PROMPT
from core.prompts.ui_prompt import UI_PROMPT
from core.prompts.tool_prompt import build_tool_prompt


class PromptComposer:
    """
    Dynamically assembles system prompts from focused layers.
    Only includes layers relevant to the current request context,
    keeping the prompt concise and avoiding response dilution.
    """

    # Maximum total prompt length (characters) to avoid token budget issues
    # Increased to 30000 to allow Project Brain documentation context injection
    MAX_PROMPT_CHARS = 30000

    def __init__(self):
        self._cache: dict[str, str] = {}

    def compose(
        self,
        *,
        include_tools: bool = True,
        include_planner: bool = False,
        include_memory: bool = False,
        include_ui: bool = False,
        tool_categories: Optional[dict[str, list[str]]] = None,
    ) -> str:
        """
        Compose a system prompt from relevant layers.

        Args:
            include_tools:    Include tool usage instructions.
            include_planner:  Include planning/task execution instructions.
            include_memory:   Include memory awareness instructions.
            include_ui:       Include UI response formatting.
            tool_categories:  Dict of tool categories for dynamic tool prompt.

        Returns:
            Assembled system prompt string.
        """
        # Build cache key from flags
        cache_key = f"t{include_tools}p{include_planner}m{include_memory}u{include_ui}"

        if cache_key in self._cache and not tool_categories:
            return self._cache[cache_key]

        layers = []

        # Always include core identity and safety
        layers.append(CORE_PROMPT)
        layers.append(SAFETY_PROMPT)
        
        # Inject current system time and location context
        from datetime import datetime
        now = datetime.now()
        time_context = f"[SYSTEM CONTEXT]\nCurrent Date/Time: {now.strftime('%A, %B %d, %Y - %I:%M %p')}\n"
        layers.append(time_context)

        # Conditional layers
        if include_tools and tool_categories:
            tool_text = build_tool_prompt(tool_categories)
            if tool_text:
                layers.append(tool_text)

        if include_planner:
            layers.append(PLANNER_PROMPT)

        if include_memory:
            layers.append(MEMORY_PROMPT)
            
            # Check for Project Brain context in active repository
            import os
            from pathlib import Path
            project_brain_dir = Path(os.getcwd()) / "brain"
            if project_brain_dir.exists() and project_brain_dir.is_dir():
                pb_layers = []
                files_to_load = [
                    ("master-memory.md", "[PROJECT BRAIN - MASTER MEMORY]"),
                    ("architecture.md", "[PROJECT BRAIN - ARCHITECTURE]"),
                    ("patterns.md", "[PROJECT BRAIN - IMPORTANT PATTERNS]"),
                    ("decisions.md", "[PROJECT BRAIN - DESIGN DECISIONS]"),
                ]
                for filename, header in files_to_load:
                    file_path = project_brain_dir / filename
                    if file_path.exists() and file_path.is_file():
                        try:
                            # Read file content safely
                            content = file_path.read_text(encoding="utf-8").strip()
                            if content:
                                pb_layers.append(f"{header}\n{content}")
                        except Exception as e:
                            pass
                if pb_layers:
                    layers.append("PROJECT BRAIN PERSISTENT MEMORY CONTEXT:\n\n" + "\n\n".join(pb_layers))

        if include_ui:
            layers.append(UI_PROMPT)

        assembled = "\n\n---\n\n".join(layers)

        # Truncate if too long (safety measure)
        if len(assembled) > self.MAX_PROMPT_CHARS:
            assembled = assembled[:self.MAX_PROMPT_CHARS] + "\n[...prompt truncated]"

        # Cache composed prompt (only if no dynamic tool list)
        if not tool_categories:
            self._cache[cache_key] = assembled

        return assembled

    def compose_for_chat(self, tool_categories: Optional[dict] = None, has_memory: bool = False) -> str:
        """Convenience: compose prompt for normal chat interaction."""
        return self.compose(
            include_tools=True,
            include_memory=has_memory,
            tool_categories=tool_categories,
        )

    def compose_for_task(self, tool_categories: Optional[dict] = None) -> str:
        """Convenience: compose prompt for autonomous task execution."""
        return self.compose(
            include_tools=True,
            include_planner=True,
            include_memory=True,
            tool_categories=tool_categories,
        )

    def compose_for_api(self, tool_categories: Optional[dict] = None, has_memory: bool = False) -> str:
        """Convenience: compose prompt for API/UI responses."""
        return self.compose(
            include_tools=True,
            include_memory=has_memory,
            include_ui=True,
            tool_categories=tool_categories,
        )

    def clear_cache(self) -> None:
        """Clear the prompt cache (e.g., after tools change)."""
        self._cache.clear()
