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

from typing import Optional, Iterator

from core.logger import log, error_log
from core.config import get_api_key, get_model_name
from core.prompts.composer import PromptComposer

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
from tools.system_tools    import execute_command
from tools.file_tools      import read_file, write_file, list_directory, safe_delete_file, get_file_info, search_in_files
from tools.web_tools       import web_search, fetch_webpage, get_weather, search_news
from tools.automation_tools import open_application, take_screenshot, get_system_info, press_key, type_text
from tools.browser_tools   import open_url, get_page_text, browser_screenshot, browser_click, browser_fill

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

        # ── Sub-engines ──────────────────────────────────────────────────────
        self.reasoning       = ReasoningEngine(api_key=api_key, model_name=model_name)
        self.tools           = ToolRouter()
        self.memory_manager  = MemoryManager(memory=memory)
        self.context         = ContextManager(memory_manager=self.memory_manager)
        self.execution       = ExecutionManager()
        self.response        = ResponseGenerator()
        self.streaming       = StreamingManager()
        self.prompts         = PromptComposer()
        self.intent_classifier = IntentClassifier()

        # ── Wire internal connections ────────────────────────────────────────
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

        # ── Register tools & create session ──────────────────────────────────
        self._register_all_tools()
        self._create_session()

        log.info(f"Brain online. {self.tools.tool_count} tools registered across "
                 f"{len(self.tools.get_categories())} categories. "
                 f"{self.agent_bus.agent_count} agents active.")

    # ─── Tool Registration ────────────────────────────────────────────────────

    def _register_all_tools(self) -> None:
        """Register all tool functions with the ToolRouter."""
        # System tools (higher risk)
        self.tools.register_callable(execute_command, category="system",
                                     risk_level=RiskLevel.HIGH, requires_confirmation=True)

        # File tools
        for fn in [read_file, list_directory, get_file_info, search_in_files]:
            self.tools.register_callable(fn, category="file")
        self.tools.register_callable(write_file, category="file",
                                     risk_level=RiskLevel.MEDIUM, requires_confirmation=True)
        self.tools.register_callable(safe_delete_file, category="file",
                                     risk_level=RiskLevel.HIGH, requires_confirmation=True)

        # Web tools
        for fn in [web_search, fetch_webpage, get_weather, search_news]:
            self.tools.register_callable(fn, category="web")

        # Desktop automation
        for fn in [open_application, take_screenshot, get_system_info]:
            self.tools.register_callable(fn, category="automation")
        for fn in [press_key, type_text]:
            self.tools.register_callable(fn, category="automation",
                                         risk_level=RiskLevel.HIGH, requires_confirmation=True)

        # Browser automation
        for fn in [open_url, get_page_text, browser_screenshot]:
            self.tools.register_callable(fn, category="browser")
        for fn in [browser_click, browser_fill]:
            self.tools.register_callable(fn, category="browser",
                                         risk_level=RiskLevel.HIGH, requires_confirmation=True)

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
            # Only provide 'web' tools to the general chat to prevent hallucinated system automation
            tool_callables = self.tools.get_all_callables(categories=["web"])
            
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

    def process_input(self, user_input: str, store_memory: bool = True) -> str:
        """
        Process user input end-to-end:
        0. Try local intent classification (zero-latency fast path)
        1. Route through CommanderAgent
        2. Enrich with memory context
        3. Send to LLM
        4. Format response
        5. Store in memory

        Args:
            user_input:   The user's raw message.
            store_memory: Whether to save this exchange.

        Returns:
            JARVIS's text response.
        """
        import time as _time
        t_start = _time.perf_counter()

        # ── 0. Fast Path: Local intent classification ────────────────────────
        local_match = self.intent_classifier.classify(user_input)
        if local_match:
            tool_name, tool_args = local_match

            # Check for built-in local functions (time, date, etc.)
            from core.brain.intent_classifier import IntentClassifier
            local_result = IntentClassifier.execute_local(tool_name, tool_args)
            if local_result is not None:
                t_total = (_time.perf_counter() - t_start) * 1000
                log.info(f"[PERF] Local built-in: {t_total:.0f}ms total")
                if store_memory:
                    self.memory_manager.store_exchange(user_input, local_result)
                return local_result

            # Execute via ToolRouter
            t_exec = _time.perf_counter()
            result = self.tools.execute_tool(tool_name, tool_args, interactive=False)
            t_exec_ms = (_time.perf_counter() - t_exec) * 1000

            if result["success"]:
                response = str(result["result"])
            else:
                response = f"Command failed: {result.get('error', 'Unknown error')}"

            t_total = (_time.perf_counter() - t_start) * 1000
            log.info(
                f"[PERF] Local command: exec={t_exec_ms:.0f}ms total={t_total:.0f}ms "
                f"| {tool_name}({tool_args})"
            )

            if store_memory:
                self.memory_manager.store_exchange(user_input, response)
            return response

        # ── 1. Route through CommanderAgent ──────────────────────────────────
        from core.agents.base_agent import AgentMessage
        cmd_msg = AgentMessage(sender="user", recipient="commander", content=user_input)
        cmd_res = self._commander.process(cmd_msg)
        
        if cmd_res.success:
            response = cmd_res.content
            if store_memory:
                self.memory_manager.store_exchange(user_input, response)
            return response
            
        intent = cmd_res.metadata.get("intent", "chat")
        if intent == "task":
            result = self.execute_task(user_input)
            if store_memory:
                self.memory_manager.store_exchange(user_input, result)
            return result

        # ── 2. Build enriched prompt ─────────────────────────────────────────
        enriched = self.context.build_enriched_prompt(user_input)

        # ── 3. Send to LLM ──────────────────────────────────────────────────
        t_llm = _time.perf_counter()
        raw_response = self.reasoning.send_message(enriched, raw_message=user_input)
        t_llm_ms = (_time.perf_counter() - t_llm) * 1000

        # ── 4. Format response ──────────────────────────────────────────────
        response = self.response.format_response(raw_response)

        t_total = (_time.perf_counter() - t_start) * 1000
        log.info(f"[PERF] LLM route: llm={t_llm_ms:.0f}ms total={t_total:.0f}ms")

        # ── 5. Store in memory ──────────────────────────────────────────────
        if store_memory:
            self.memory_manager.store_exchange(user_input, response)

        return response

    # ─── Streaming ────────────────────────────────────────────────────────────

    def process_input_stream(self, user_input: str) -> Iterator[str]:
        """
        Stream the response token-by-token.

        Args:
            user_input: The user's message.

        Yields:
            String chunks of the response.
        """
        import time as _time
        t_start = _time.perf_counter()

        # ── 0. Fast Path: Local intent classification ────────────────────────
        local_match = self.intent_classifier.classify(user_input)
        if local_match:
            tool_name, tool_args = local_match

            # Check for built-in local functions (time, date, etc.)
            from core.brain.intent_classifier import IntentClassifier
            local_result = IntentClassifier.execute_local(tool_name, tool_args)
            if local_result is not None:
                t_total = (_time.perf_counter() - t_start) * 1000
                log.info(f"[PERF] Local built-in (stream): {t_total:.0f}ms total")
                if self.memory_manager.is_active:
                    self.memory_manager.store_exchange(user_input, local_result)
                yield local_result
                return

            # Execute via ToolRouter
            result = self.tools.execute_tool(tool_name, tool_args, interactive=False)
            if result["success"]:
                response = str(result["result"])
            else:
                response = f"Command failed: {result.get('error', 'Unknown error')}"

            t_total = (_time.perf_counter() - t_start) * 1000
            log.info(f"[PERF] Local command (stream): {t_total:.0f}ms total | {tool_name}")

            if self.memory_manager.is_active:
                self.memory_manager.store_exchange(user_input, response)
            yield response
            return

        # ── 1. Route through CommanderAgent ──────────────────────────────────
        from core.agents.base_agent import AgentMessage
        cmd_msg = AgentMessage(sender="user", recipient="commander", content=user_input)
        cmd_res = self._commander.process(cmd_msg)
        
        if cmd_res.success:
            response = cmd_res.content
            if self.memory_manager.is_active:
                self.memory_manager.store_exchange(user_input, response)
            yield response
            return
            
        intent = cmd_res.metadata.get("intent", "chat")
        if intent == "task":
            # Streams don't fully support tasks yet, so just yield the result
            result = self.execute_task(user_input)
            if self.memory_manager.is_active:
                self.memory_manager.store_exchange(user_input, result)
            yield result
            return

        enriched = self.context.build_enriched_prompt(user_input)
        system_prompt = self._get_system_prompt()

        yield from self.streaming.stream_response(user_input, enriched, system_prompt)

    # ─── Task Execution ───────────────────────────────────────────────────────

    def execute_task(self, task: str) -> str:
        """
        Execute a complex multi-step task autonomously.

        Args:
            task: Natural language task description.

        Returns:
            Formatted execution report.
        """
        log.info(f"Executing task via ExecutionManager: {task}")
        result = self.execution.run(task, verbose=True)

        # Store task result in memory
        self.memory_manager.store_task_result(task, result)

        return result

    # ─── Model Management ─────────────────────────────────────────────────────

    def switch_model(self, model_name: str) -> str:
        """Switch to a different LLM model."""
        system_prompt = self._get_system_prompt()
        tools = self.tools.get_all_callables()
        return self.reasoning.switch_model(model_name, system_prompt, tools)

    def reset_chat(self) -> str:
        """Reset the chat session."""
        system_prompt = self._get_system_prompt()
        tools = self.tools.get_all_callables()
        if self._memory:
            self._memory.conversations.clear()
        if self.memory_manager:
            self.memory_manager.clear_working()
        return self.reasoning.reset_session(system_prompt, tools)

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
