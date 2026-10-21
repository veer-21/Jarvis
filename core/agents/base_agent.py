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
    user_id:    Optional[str] = None     # Verified authenticated owner identity (P0-1)
    session_id: Optional[str] = None     # Verified session identity (P0-1)
    system_authorized: bool = False      # Explicit trusted system-scope authorization (P0-1)

    def __post_init__(self):
        # 1. Identity safety: self.user_id is the canonical trusted identity attribute.
        # NEVER elevate identity from metadata["user_id"] if self.user_id is None.
        if self.user_id is not None:
            # Enforce consistency: synchronize metadata with trusted self.user_id
            self.metadata["user_id"] = self.user_id
        else:
            # If untrusted metadata contains user_id but self.user_id is None,
            # do NOT elevate. Remove metadata["user_id"] so downstream
            # components cannot be misled by untrusted metadata.
            if "user_id" in self.metadata:
                self.metadata.pop("user_id", None)

        if self.session_id is not None:
            self.metadata["session_id"] = self.session_id
        else:
            if "session_id" in self.metadata:
                self.metadata.pop("session_id", None)

        # 2. System authorization safety:
        # A plain metadata["allow_system_scope"] = True must NEVER grant system privileges.
        if not self.system_authorized:
            if "allow_system_scope" in self.metadata:
                self.metadata.pop("allow_system_scope", None)
        else:
            self.metadata["allow_system_scope"] = True


def create_system_message(
    sender: str,
    recipient: str,
    content: str,
    msg_type: str = "request",
    priority: MessagePriority = MessagePriority.NORMAL,
    metadata: Optional[dict] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> AgentMessage:
    """
    Factory for authorized internal system maintenance messages (P0-1).
    Only trusted internal kernel/subsystem code may invoke this.
    """
    meta = metadata.copy() if metadata else {}
    return AgentMessage(
        sender=sender,
        recipient=recipient,
        content=content,
        msg_type=msg_type,
        priority=priority,
        metadata=meta,
        user_id=user_id,
        session_id=session_id,
        system_authorized=True,
    )


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
