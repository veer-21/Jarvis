"""
JARVIS — Security Agent
Handles all security decisions: threat assessment, permission enforcement,
anomaly detection, and audit log analysis.
"""

from core.logger import log, audit_log
from core.security import guard, RiskLevel
from core.agents.base_agent import BaseAgent, AgentMessage, AgentResponse, AgentRole


class SecurityAgent(BaseAgent):
    """
    Security Agent — all security decisions go through here.
    Evaluates risks, enforces permissions, and monitors for anomalies.
    """

    # Rate limiting: max tool executions per minute
    MAX_TOOLS_PER_MINUTE = 30

    def __init__(self):
        super().__init__("security", AgentRole.SECURITY)
        self._execution_timestamps: list[float] = []

    def process(self, message: AgentMessage) -> AgentResponse:
        """
        Process a security check request.

        Message metadata should include:
            action: "check_command" | "check_tool" | "assess_risk"
            command: the command/tool to check
        """
        action = message.metadata.get("action", "assess_risk")

        if action == "check_command":
            command = message.metadata.get("command", message.content)
            allowed, reason = guard.check_command(command, interactive=False)
            return AgentResponse(
                success=allowed,
                content=reason,
                agent=self.name,
                metadata={"risk": guard.assess_command_risk(command).value},
            )

        elif action == "check_tool":
            tool_name = message.metadata.get("tool_name", "")
            risk_level = message.metadata.get("risk_level", RiskLevel.SAFE)
            return self._check_tool_permission(tool_name, risk_level)

        elif action == "assess_risk":
            command = message.content
            risk = guard.assess_command_risk(command)
            return AgentResponse(
                success=True,
                content=f"Risk level: {risk.value}",
                agent=self.name,
                metadata={"risk": risk.value},
            )

        return AgentResponse(
            success=False,
            content=f"Unknown security action: {action}",
            agent=self.name,
            error=f"Unknown action: {action}",
        )

    def _check_tool_permission(self, tool_name: str, risk_level: RiskLevel) -> AgentResponse:
        """Check if a tool execution should be allowed."""
        import time

        # Rate limiting
        now = time.time()
        self._execution_timestamps = [t for t in self._execution_timestamps if now - t < 60]
        if len(self._execution_timestamps) >= self.MAX_TOOLS_PER_MINUTE:
            return AgentResponse(
                success=False,
                content="Rate limit exceeded. Too many tool executions per minute.",
                agent=self.name,
                error="rate_limited",
            )

        self._execution_timestamps.append(now)

        # Auto-approve safe tools
        if risk_level in (RiskLevel.SAFE, RiskLevel.LOW):
            return AgentResponse(success=True, content="Approved", agent=self.name)

        # Medium risk: allow but log warning
        if risk_level == RiskLevel.MEDIUM:
            log.warning(f"Medium-risk tool execution: {tool_name}")
            return AgentResponse(
                success=True,
                content="Approved with warning",
                agent=self.name,
                metadata={"warning": True},
            )

        # High/Critical: block in non-interactive mode
        return AgentResponse(
            success=False,
            content=f"Tool '{tool_name}' blocked — risk level {risk_level.value} requires interactive confirmation.",
            agent=self.name,
            error="high_risk_blocked",
        )

    def handle_event(self, event: AgentMessage) -> None:
        """Monitor events for security anomalies."""
        if event.metadata.get("type") == "tool_executed":
            tool = event.metadata.get("tool_name", "unknown")
            audit_log.info({
                "event": "TOOL_EXECUTION_MONITORED",
                "tool": tool,
                "timestamp": event.timestamp,
            })
