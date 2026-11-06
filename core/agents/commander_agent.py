"""
JARVIS — Commander Agent
The top-level orchestrator that receives user input, classifies intent,
and routes to the appropriate specialist agent or brain module.
"""

from core.logger import log
from core.agents.base_agent import BaseAgent, AgentMessage, AgentResponse, AgentRole


class CommanderAgent(BaseAgent):
    """
    Commander Agent — the master orchestrator.
    Receives all user input and delegates to specialists.
    """

    # Intent classification keywords
    _TASK_KEYWORDS = [
        "search and", "find and", "create a", "write a", "build",
        "automate", "step by step", "plan", "execute", "deploy",
        "install", "set up", "configure", "download and",
    ]

    _COMMAND_KEYWORDS = [
        "open", "launch", "run", "execute", "start", "stop",
        "kill", "close", "shutdown", "restart", "press",
        "click", "type", "screenshot",
    ]

    _QUERY_KEYWORDS = [
        "what", "who", "how", "why", "when", "where", "which",
        "explain", "tell me", "show me", "weather", "news", "search for",
    ]

    def __init__(self, brain=None):
        super().__init__("commander", AgentRole.COMMANDER)
        self._brain = brain

    def set_brain(self, brain) -> None:
        """Attach the Brain for processing."""
        self._brain = brain

    def process(self, message: AgentMessage) -> AgentResponse:
        """
        Classify user intent and route to the appropriate handler.
        """
        user_input = message.content
        intent = self.classify_intent(user_input)

        log.info(f"Commander classified intent: {intent} for: {user_input[:60]}")

        if not self._brain:
            return AgentResponse(
                success=False,
                content="Brain not attached to Commander.",
                agent=self.name,
                error="No brain reference",
            )

        try:
            if user_input.lower().startswith("scaffold project "):
                project_name = user_input[17:].strip()
                if self._brain and self._brain.agent_bus:
                    req = AgentMessage(
                        sender=self.name,
                        recipient="operator",
                        content=user_input,
                        metadata={"command": "scaffold_project", "project_name": project_name}
                    )
                    res = self._brain.agent_bus.send_message(req)
                    return res if res else AgentResponse(False, "Operator not responding", self.name)
            
            # If caller only requested intent classification
            if message.metadata.get("classify_only", False):
                return AgentResponse(
                    success=True,
                    content=intent,
                    agent=self.name,
                    metadata={"intent": intent}
                )

            # Delegate to brain's authoritative orchestrator / processing pipeline
            if hasattr(self._brain, "process_input"):
                store_mem = message.metadata.get("store_memory", True)
                result = self._brain.process_input(user_input, store_memory=store_mem)
                return AgentResponse(
                    success=True,
                    content=str(result),
                    agent=self.name,
                    metadata={"intent": intent, "routed_via": "assistant_orchestrator"}
                )

            # Fallback if brain lacks process_input
            return AgentResponse(
                success=True,
                content=f"Intent: {intent}",
                agent=self.name,
                metadata={"intent": intent},
            )
        except Exception as e:
            return AgentResponse(
                success=False,
                content=f"Processing failed: {str(e)}",
                agent=self.name,
                error=str(e),
            )

    def classify_intent(self, text: str) -> str:
        """
        Classify user input into intent categories.

        Returns:
            One of: "task", "command", "query", "chat"
        """
        text_lower = text.lower().strip()

        # Multi-step task detection
        if any(kw in text_lower for kw in self._TASK_KEYWORDS):
            return "task"

        # Direct command
        first_word = text_lower.split()[0] if text_lower.split() else ""
        if first_word in [k.split()[0] for k in self._COMMAND_KEYWORDS]:
            return "command"

        # Information query
        if any(text_lower.startswith(kw) for kw in self._QUERY_KEYWORDS):
            return "query"

        # Default: conversational chat
        return "chat"
