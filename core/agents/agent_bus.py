"""
JARVIS — Agent Communication Bus
Async message passing between agents with priority queuing and event broadcasting.
"""

from collections import defaultdict
from typing import Optional, Callable

from core.logger import log, error_log
from core.agents.base_agent import BaseAgent, AgentMessage, AgentResponse, MessagePriority


class AgentBus:
    """
    Central communication hub for the multi-agent system.
    Routes messages between agents and broadcasts events.
    """

    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}
        self._event_listeners: dict[str, list[Callable]] = defaultdict(list)
        self._message_log: list[dict] = []
        log.info("AgentBus initialized.")

    # ─── Agent Registration ───────────────────────────────────────────────────

    def register(self, agent: BaseAgent) -> None:
        """Register an agent with the bus."""
        self._agents[agent.name] = agent
        log.info(f"Agent registered: {agent.name} ({agent.role.value})")

    def unregister(self, name: str) -> None:
        """Remove an agent from the bus."""
        self._agents.pop(name, None)

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """Look up an agent by name."""
        return self._agents.get(name)

    # ─── Message Routing ──────────────────────────────────────────────────────

    def send(self, message: AgentMessage) -> AgentResponse:
        """
        Route a message to its recipient agent and return the response.

        Args:
            message: The message to deliver.

        Returns:
            AgentResponse from the recipient.
        """
        recipient = self._agents.get(message.recipient)
        if not recipient:
            error_msg = f"Agent '{message.recipient}' not found on bus"
            error_log.error(error_msg)
            return AgentResponse(
                success=False,
                content="",
                agent=message.recipient,
                error=error_msg,
            )

        # Log the message
        self._log_message(message)

        try:
            response = recipient.process(message)
            return response
        except Exception as e:
            error_msg = f"Agent '{message.recipient}' failed: {str(e)}"
            error_log.error(error_msg)
            return AgentResponse(
                success=False,
                content="",
                agent=message.recipient,
                error=error_msg,
            )

    def request(self, sender: str, recipient: str, content: str, **kwargs) -> AgentResponse:
        """
        Convenience method: create and send a message in one call.

        Args:
            sender:    Name of the sending agent.
            recipient: Name of the target agent.
            content:   Message content.
            **kwargs:  Additional AgentMessage fields.
        """
        msg = AgentMessage(
            sender=sender,
            recipient=recipient,
            content=content,
            **kwargs,
        )
        return self.send(msg)

    # ─── Event Broadcasting ───────────────────────────────────────────────────

    def broadcast(self, event: AgentMessage) -> None:
        """
        Broadcast an event to all registered agents.

        Args:
            event: The event message (msg_type should be "event").
        """
        event.msg_type = "event"
        for agent in self._agents.values():
            try:
                agent.handle_event(event)
            except Exception as e:
                error_log.error(f"Event handler failed for {agent.name}: {e}")

    def on_event(self, event_type: str, callback: Callable) -> None:
        """Register a callback for a specific event type."""
        self._event_listeners[event_type].append(callback)

    # ─── Logging ──────────────────────────────────────────────────────────────

    def _log_message(self, msg: AgentMessage) -> None:
        """Record a message in the bus log."""
        self._message_log.append({
            "id":        msg.msg_id,
            "sender":    msg.sender,
            "recipient": msg.recipient,
            "type":      msg.msg_type,
            "priority":  msg.priority.value,
            "timestamp": msg.timestamp,
            "content":   msg.content[:100],
        })
        # Keep log bounded
        if len(self._message_log) > 500:
            self._message_log = self._message_log[-500:]

    # ─── Introspection ────────────────────────────────────────────────────────

    def list_agents(self) -> list[dict]:
        """Return status of all registered agents."""
        return [a.status() for a in self._agents.values()]

    def get_message_log(self, n: int = 20) -> list[dict]:
        """Return recent message log entries."""
        return self._message_log[-n:]

    @property
    def agent_count(self) -> int:
        return len(self._agents)
