"""
JARVIS Brain — Central Orchestrator
Slim coordinator that delegates to specialized sub-engines.

This is the primary entry point for all AI operations. It wires together:
  - ReasoningEngine  (LLM communication)
  - ToolRouter       (tool registration & execution)
  - ContextManager   (prompt enrichment)
  - MemoryManager    (memory interface)
  - ExecutionManager  (task planning & execution)
  - ResponseGenerator (output formatting)
  - StreamingManager  (real-time streaming)
  - PromptComposer   (layered system prompts)
"""

from typing import Optional, Iterator, AsyncIterator, Any

from core.logger import log, error_log
from core.config import get_api_key, get_model_name
from core.prompts.composer import PromptComposer
from core.memory import JarvisMemory

from core.brain.reasoning_engine   import ReasoningEngine
from core.brain.tool_router        import ToolRouter
from core.brain.context_manager    import ContextManager
from core.brain.memory_manager     import MemoryManager
from core.brain.execution_manager  import ExecutionManager
from core.brain.response_generator import ResponseGenerator
from core.brain.streaming_manager  import StreamingManager
from core.brain.intent_classifier  import IntentClassifier

# Agent system
from core.agents.agent_bus        import AgentBus
from core.agents.commander_agent  import CommanderAgent
from core.agents.security_agent   import SecurityAgent
from core.agents.memory_agent     import MemoryAgent
from core.agents.operator_agent   import OperatorAgent
from core.agents.refiner_agent    import RefinerAgent

# ─── Tool Module Imports ──────────────────────────────────────────────────────
from tools.system_tools    import execute_command, schedule_task, list_scheduled_tasks
from tools.file_tools      import read_file, write_file, list_directory, safe_delete_file, get_file_info, search_in_files, graphify_query
from tools.web_tools       import web_search, fetch_webpage, get_weather, search_news
from tools.automation_tools import (
    open_application, take_screenshot, get_system_info, press_key, type_text,
    analyze_screen, click_mouse, move_mouse, scroll_mouse, list_open_windows, focus_window
)
from tools.browser_tools   import open_url, get_page_text, browser_screenshot, browser_click, browser_fill
from tools.everyday_tools  import (
    smart_organize_folder, undo_folder_organization, create_reminder_or_timer,
    list_and_manage_reminders, control_windows_setting, summarize_local_document,
    generate_daily_briefing
)
from tools.context_tools import get_active_window_context

from core.security import RiskLevel


class Brain:
    """
    Central JARVIS Brain — the slim orchestrator.

    Coordinates all sub-engines without containing business logic itself.
    Each sub-engine is independently testable and replaceable.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        memory=None,
        planner=None,
    ):
        log.info("Initializing JARVIS Brain (v3.0 — modular architecture)...")
        if memory is None:
            memory = JarvisMemory()

        # ── Sub-engines ──────────────────────────────────────────────────────
        self.memory_manager  = MemoryManager(memory=memory)
        self.reasoning       = ReasoningEngine(api_key=api_key, model_name=model_name)
        self.tools           = ToolRouter()
        self.context         = ContextManager(memory_manager=self.memory_manager)
        self.execution       = ExecutionManager()
        self.response        = ResponseGenerator()
        self.streaming       = StreamingManager()
        self.prompts         = PromptComposer()
        self.intent_classifier = IntentClassifier()

        # ── Wire internal connections ────────────────────────────────────────
        self.reasoning.set_tool_router(self.tools)
        self.streaming.set_reasoning_engine(self.reasoning)
        self.streaming.set_memory_manager(self.memory_manager)
        self.execution.set_brain(self)

        # ── Legacy planner support ───────────────────────────────────────────
        self._planner = None

        # ── Agent System (v3.0) ──────────────────────────────────────────────
        self.agent_bus = AgentBus()
        self._commander = CommanderAgent(brain=self)
        self._security_agent = SecurityAgent()
        self._memory_agent = MemoryAgent(memory=memory)
        self._memory_agent.set_brain_sender(self.reasoning.send_message)
        self._operator = OperatorAgent(tool_router=self.tools, brain=self)
        self._refiner = RefinerAgent(brain=self)
        self.agent_bus.register(self._commander)
        self.agent_bus.register(self._security_agent)
        self.agent_bus.register(self._memory_agent)
        self.agent_bus.register(self._operator)
        self.agent_bus.register(self._refiner)

        # ── Assistant Orchestrator (Personal Assistant v3.5) ────────────────
        from core.brain.assistant_orchestrator import AssistantOrchestrator
        self.orchestrator = AssistantOrchestrator(brain=self)

        # ── Register tools & create session ──────────────────────────────────
        self._register_all_tools()
        self._create_session()

        # Ensure memory manager and preference cache are warm before reporting online
        if self.memory_manager.is_active:
            import time as _time
            log.info("Waiting for memory system and preference caches to warm up...")
            t_wait_start = _time.perf_counter()
            while hasattr(self.memory_manager._memory, "is_warm") and not self.memory_manager._memory.is_warm:
                if _time.perf_counter() - t_wait_start > 5.0:
                    log.warning("Memory system warm-up timed out. Proceeding online anyway.")
                    break
                _time.sleep(0.05)

        log.info(f"Brain online. {self.tools.tool_count} tools registered across "
                 f"{len(self.tools.get_categories())} categories. "
                 f"{self.agent_bus.agent_count} agents active.")

    # ─── Tool Registration ────────────────────────────────────────────────────

    def _register_all_tools(self) -> None:
        """Register all tool functions with the ToolRouter."""
        # System tools (higher risk)
        self.tools.register_callable(execute_command, category="system",
                                     risk_level=RiskLevel.HIGH, requires_confirmation=True)
        self.tools.register_callable(schedule_task, category="system")
        self.tools.register_callable(list_scheduled_tasks, category="system")

        # File tools
        for fn in [read_file, list_directory, get_file_info, search_in_files, graphify_query]:
            self.tools.register_callable(fn, category="file")
        self.tools.register_callable(write_file, category="file",
                                     risk_level=RiskLevel.MEDIUM, requires_confirmation=True)
        self.tools.register_callable(safe_delete_file, category="file",
                                     risk_level=RiskLevel.HIGH, requires_confirmation=True)

        # Web tools
        for fn in [web_search, fetch_webpage, get_weather, search_news]:
            self.tools.register_callable(fn, category="web")

        # Desktop automation
        for fn in [open_application, take_screenshot, get_system_info, analyze_screen, list_open_windows, focus_window]:
            self.tools.register_callable(fn, category="automation")
        for fn in [press_key, type_text, click_mouse, move_mouse, scroll_mouse]:
            self.tools.register_callable(fn, category="automation",
                                         risk_level=RiskLevel.HIGH, requires_confirmation=True)

        # Browser automation
        for fn in [open_url, get_page_text, browser_screenshot]:
            self.tools.register_callable(fn, category="browser")
        for fn in [browser_click, browser_fill]:
            self.tools.register_callable(fn, category="browser",
                                         risk_level=RiskLevel.HIGH, requires_confirmation=True)

        # Everyday Consumer tools (Phase 4.1)
        self.tools.register_callable(smart_organize_folder, category="everyday",
                                     risk_level=RiskLevel.MODERATE_RISK, requires_confirmation=False)
        self.tools.register_callable(undo_folder_organization, category="everyday",
                                     risk_level=RiskLevel.MODERATE_RISK, requires_confirmation=False)
        self.tools.register_callable(create_reminder_or_timer, category="everyday",
                                     risk_level=RiskLevel.LOW_RISK, requires_confirmation=False)
        self.tools.register_callable(list_and_manage_reminders, category="everyday",
                                     risk_level=RiskLevel.READ_ONLY, requires_confirmation=False)
        self.tools.register_callable(control_windows_setting, category="everyday",
                                     risk_level=RiskLevel.LOW_RISK, requires_confirmation=False)
        self.tools.register_callable(summarize_local_document, category="everyday",
                                     risk_level=RiskLevel.READ_ONLY, requires_confirmation=False)
        self.tools.register_callable(generate_daily_briefing, category="everyday",
                                     risk_level=RiskLevel.READ_ONLY, requires_confirmation=False)
        self.tools.register_callable(get_active_window_context, category="everyday",
                                     risk_level=RiskLevel.READ_ONLY, requires_confirmation=False)

        # Load Auto-Generated Custom Tools
        self.tools.load_custom_tools()

    # ─── Session Management ───────────────────────────────────────────────────

    def _create_session(self) -> None:
        """Create the LLM chat session with composed prompt and safe conversational tools."""
        system_prompt = self.prompts.compose_for_chat(
            tool_categories=self.tools.get_categories(),
            has_memory=self.memory_manager.is_active,
        )
        
        import os
        is_offline = os.getenv("JARVIS_OFFLINE") == "1"
        
        if is_offline:
            # Offline mode with a 3B model (llama3.2) is extremely slow and hallucination-prone when given complex tools.
            # We provide NO tools for general chat so it runs incredibly fast and accurately on local hardware.
            # (Tasks will still use tools via the Action-First ExecutionManager if requested).
            tool_callables = []
        else:
            # Provide safe informational & inspection tools to general chat
            tool_callables = self.tools.get_all_callables(categories=["web", "system", "file", "browser", "everyday"])
            # Include safe system inspection tools
            safe_auto = [
                self.tools.get_tool("get_system_info"),
                self.tools.get_tool("take_screenshot"),
                self.tools.get_tool("analyze_screen"),
                self.tools.get_tool("list_open_windows")
            ]
            for st in safe_auto:
                if st and st.callable not in tool_callables:
                    tool_callables.append(st.callable)
            
        self.reasoning.create_chat_session(system_prompt, tool_callables)

    def _get_system_prompt(self, for_task: bool = False, for_api: bool = False) -> str:
        """Get the appropriate composed system prompt."""
        cats = self.tools.get_categories()
        has_mem = self.memory_manager.is_active

        if for_task:
            return self.prompts.compose_for_task(tool_categories=cats)
        elif for_api:
            return self.prompts.compose_for_api(tool_categories=cats, has_memory=has_mem)
        else:
            return self.prompts.compose_for_chat(tool_categories=cats, has_memory=has_mem)

    # ─── Core Processing ──────────────────────────────────────────────────────

    def process_input(
        self,
        user_input: str,
        store_memory: bool = True,
        context: Optional[Any] = None
    ) -> str:
        """
        Process user input end-to-end through the Central Assistant Orchestrator.

        Args:
            user_input:   The user's raw message.
            store_memory: Controls whether this interaction is persisted to memory.
            context:      Optional ExecutionContext instance.

        Returns:
            JARVIS's text response.
        """
        from core.brain.task_model import ExecutionContext
        ctx = context if context is not None else ExecutionContext(store_memory=store_memory)
        return self.orchestrator.process(user_input, context=ctx)

    # ─── Streaming ────────────────────────────────────────────────────────────

    async def process_input_stream(
        self,
        user_input: str,
        interrupt_event = None,
        context: Optional[Any] = None
    ) -> AsyncIterator[str]:
        """
        Stream the response token-by-token through the Central Assistant Orchestrator.
        Guarantees that streaming is strictly a presentation mode, not a separate execution architecture.

        Args:
            user_input:      The user's message.
            interrupt_event: Optional event to monitor for barge-in interruption.
            context:         Optional ExecutionContext instance.

        Yields:
            String chunks of the response.
        """
        from core.brain.task_model import ExecutionContext
        if context is not None:
            ctx = context
            if interrupt_event is not None and ctx.cancellation_token is None:
                ctx.cancellation_token = interrupt_event
        else:
            ctx = ExecutionContext(store_memory=True, cancellation_token=interrupt_event)
        async for chunk in self.orchestrator.process_stream(user_input, interrupt_event=interrupt_event, context=ctx):
            yield chunk

    # ─── Task Execution ───────────────────────────────────────────────────────

    def execute_task(
        self,
        task: str,
        store_memory: bool = True,
        context: Optional[Any] = None
    ) -> str:
        """
        Execute a complex multi-step task autonomously via AssistantOrchestrator.

        Args:
            task:         Natural language task description.
            store_memory: Controls whether task outcome is stored in memory.
            context:      Optional ExecutionContext instance.

        Returns:
            Formatted execution report.
        """
        log.info(f"Executing task via AssistantOrchestrator: {task}")
        from core.brain.task_model import ExecutionContext
        ctx = context if context is not None else ExecutionContext(store_memory=store_memory)
        # AssistantOrchestrator is the authoritative engine and owns memory policy enforcement.
        # Brain does not duplicate memory persistence.
        result = self.orchestrator.process(task, context=ctx)
        return result

    # ─── Model Management ─────────────────────────────────────────────────────

    def switch_model(self, model_name: str) -> str:
        """Switch to a different LLM model."""
        system_prompt = self._get_system_prompt()
        tools = self.tools.get_all_callables()
        return self.reasoning.switch_model(model_name, system_prompt, tools)

    def reset_chat(self, session_id: Optional[str] = None, user_id: Optional[str] = None) -> str:
        """Reset the chat session strictly scoped to session_id and user_id (P0-3, P0-4)."""
        system_prompt = self._get_system_prompt()
        tools = self.tools.get_all_callables()
        if self._memory:
            self._memory.conversations.clear(session_id=session_id, user_id=user_id)
        if self.memory_manager:
            self.memory_manager.clear_working(session_id=session_id)
        if hasattr(self.context, "clear_prefetch"):
            self.context.clear_prefetch(session_id=session_id, user_id=user_id)
        return self.reasoning.reset_session(system_prompt, tools, session_id=session_id, user_id=user_id)

    # ─── Backward Compatibility ───────────────────────────────────────────────

    def set_memory(self, memory) -> None:
        """Attach a JarvisMemory instance."""
        self.memory_manager.set_memory(memory)
        self.context.set_memory_manager(self.memory_manager)
        log.info("Memory system attached to Brain.")

    @property
    def model_name(self) -> str:
        """Public model name (backward compat)."""
        return self.reasoning.model_name

    @property
    def _model_name(self) -> str:
        """Backward compat alias used by api/server.py."""
        return self.reasoning.model_name

    @property
    def _memory(self):
        """Backward compat alias for memory access."""
        return self.memory_manager._memory if self.memory_manager else None

    # ─── Introspection ────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return comprehensive brain status."""
        return {
            "model":          self.reasoning.model_name,
            "tools_count":    self.tools.tool_count,
            "memory_active":  self.memory_manager.is_active,
            "planner_active": self._planner is not None or True,  # ExecutionManager always available
            "tool_categories": list(self.tools.get_categories().keys()),
        }
