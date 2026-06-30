"""
JARVIS — Base Agent
Abstract base class for all specialized agents in the multi-agent system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any
import uuid


class AgentRole(str, Enum):
    COMMANDER = "commander"
    PLANNER   = "planner"
    TOOL      = "tool"
    MEMORY    = "memory"
    SECURITY  = "security"


class MessagePriority(int, Enum):
    LOW      = 0
    NORMAL   = 1
    HIGH     = 2
    CRITICAL = 3


@dataclass
class AgentMessage:
    """Message passed between agents via the AgentBus."""
    sender:     str
    recipient:  str
    content:    str
    msg_type:   str = "request"          # request, response, event, error
    priority:   MessagePriority = MessagePriority.NORMAL
    metadata:   dict = field(default_factory=dict)
    msg_id:     str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reply_to:   Optional[str] = None     # msg_id of the message this replies to


@dataclass
class AgentResponse:
    """Standardized response from an agent."""
    success:    bool
    content:    str
    agent:      str
    metadata:   dict = field(default_factory=dict)
    error:      Optional[str] = None


class BaseAgent(ABC):
    """
    Abstract base class for JARVIS agents.
    Each agent is a specialized processor that handles specific types of work.
    """

    def __init__(self, name: str, role: AgentRole):
        self.name = name
        self.role = role
        self._active = True

    @abstractmethod
    def process(self, message: AgentMessage) -> AgentResponse:
        """
        Process an incoming message and return a response.
        This is the main entry point for agent work.
        """
        ...

    def handle_event(self, event: AgentMessage) -> None:
        """Handle a broadcast event (optional override)."""
        pass

    @property
    def is_active(self) -> bool:
        return self._active

    def status(self) -> dict:
        return {
            "name":   self.name,
            "role":   self.role.value,
            "active": self._active,
        }
