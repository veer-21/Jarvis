"""
Tests for Phase 0 Baseline Remediation
Verifies:
1. AgentBus broadcast() event listener dispatch and send_message() alias
2. VisionScreenUnderstanding verify_state() returning False on keyword mismatch
3. OperatorAgent controlled retry on safe tool failure and perceptual verification metadata
4. CommanderAgent proper routing and execution delegation
5. ResultVerifier verify_task_objective() Level 4 verification
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch
from core.agents.base_agent import BaseAgent, AgentRole, AgentMessage, AgentResponse
from core.agents.agent_bus import AgentBus
from core.agents.vision_abstraction import VisionScreenUnderstanding
from core.agents.operator_agent import OperatorAgent
from core.agents.commander_agent import CommanderAgent
from core.brain.verifier import ResultVerifier, VerificationLevel


class DummyAgent(BaseAgent):
    def __init__(self, name: str):
        super().__init__(name, AgentRole.TOOL)
        self.received_events = []
        self.processed_messages = []

    def process(self, message: AgentMessage) -> AgentResponse:
        self.processed_messages.append(message)
        return AgentResponse(success=True, content=f"Echo: {message.content}", agent=self.name)

    def handle_event(self, event: AgentMessage) -> None:
        self.received_events.append(event)


class TestPhase0Remediation:

    # ─── 1. AgentBus Remediation Tests ─────────────────────────────────────────

    def test_agent_bus_event_listeners_and_alias(self):
        bus = AgentBus()
        agent = DummyAgent("test_tool")
        bus.register(agent)

        # Verify send_message alias exists and works
        msg = AgentMessage(sender="user", recipient="test_tool", content="ping")
        resp = bus.send_message(msg)
        assert resp.success is True
        assert resp.content == "Echo: ping"

        # Verify on_event listener dispatching
        received_custom = []
        received_wildcard = []
        bus.on_event("tool_executed", lambda ev: received_custom.append(ev))
        bus.on_event("*", lambda ev: received_wildcard.append(ev))

        event = AgentMessage(
            sender="operator",
            recipient="*",
            content="Tool execution finished",
            metadata={"type": "tool_executed", "tool_name": "read_file"}
        )
        bus.broadcast(event)

        # Verify both the registered agent and the registered listener callbacks received the event
        assert len(agent.received_events) == 1
        assert len(received_custom) == 1
        assert received_custom[0].metadata["tool_name"] == "read_file"
        assert len(received_wildcard) == 1

    # ─── 2. Vision verify_state Bug Fix Tests ───────────────────────────────────

    def test_vision_verify_state_pass_and_fail(self):
        vision = VisionScreenUnderstanding()

        # Mock analyze_screen to return specific OCR text
        with patch("tools.automation_tools.analyze_screen", return_value="Welcome to Notepad Document 1"):
            # Should PASS: 3 out of 3 words match (100% >= 60%)
            assert vision.verify_state("Welcome to Notepad") is True

            # Should PASS: 2 out of 3 words match (66.7% >= 60%)
            assert vision.verify_state("Notepad Document Editor") is True

            # Should FAIL: 0 out of 2 words match (0% < 60%)
            assert vision.verify_state("Calculator Error") is False

            # Should FAIL: 1 out of 3 words match (33.3% < 60%)
            assert vision.verify_state("Calculator Scientific Mode") is False

            # Empty expected state passes heuristic
            assert vision.verify_state("") is True

    # ─── 3. OperatorAgent Controlled Retry Tests ───────────────────────────────

    def test_operator_retry_on_safe_tool(self):
        mock_router = MagicMock()
        operator = OperatorAgent(tool_router=mock_router)

        # Mock first execution fails, second retry succeeds
        fail_res = {"success": False, "error": "Disk busy, retry later"}
        success_res = {"success": True, "result": "file contents here"}
        mock_router.execute_tool.side_effect = [fail_res, success_res]

        task_data = {
            "id": "task_1",
            "node_type": "action",
            "tool_name": "read_file",
            "input_variables": {"path": "test.txt"}
        }
        msg = AgentMessage(
            sender="commander",
            recipient="operator",
            content="read file",
            metadata={"task": task_data}
        )

        resp = operator.process(msg)
        assert resp.success is True
        assert resp.content == "file contents here"
        assert mock_router.execute_tool.call_count == 2

    def test_operator_no_retry_on_destructive_tool(self):
        mock_router = MagicMock()
        operator = OperatorAgent(tool_router=mock_router)

        # Destructive or non-idempotent tool should NOT retry on failure
        fail_res = {"success": False, "error": "Permission denied"}
        mock_router.execute_tool.return_value = fail_res

        task_data = {
            "id": "task_2",
            "node_type": "action",
            "tool_name": "execute_command",
            "input_variables": {"command": "rmdir /s /q temp"}
        }
        msg = AgentMessage(
            sender="commander",
            recipient="operator",
            content="delete temp",
            metadata={"task": task_data}
        )

        resp = operator.process(msg)
        assert resp.success is False
        assert mock_router.execute_tool.call_count == 1

    # ─── 4. CommanderAgent Routing Tests ───────────────────────────────────────

    def test_commander_delegation_to_brain(self):
        mock_brain = MagicMock()
        mock_brain.process_input.return_value = "The current time is 3:30 PM."
        commander = CommanderAgent(brain=mock_brain)

        # Classify only request
        msg_classify = AgentMessage(
            sender="user",
            recipient="commander",
            content="what time is it",
            metadata={"classify_only": True}
        )
        resp_classify = commander.process(msg_classify)
        assert resp_classify.success is True
        assert resp_classify.content == "query"

        # Full execution delegation
        msg_exec = AgentMessage(
            sender="user",
            recipient="commander",
            content="what time is it"
        )
        resp_exec = commander.process(msg_exec)
        assert resp_exec.success is True
        assert resp_exec.content == "The current time is 3:30 PM."
        assert resp_exec.metadata["routed_via"] == "assistant_orchestrator"
        mock_brain.process_input.assert_called_once_with("what time is it", store_memory=True)

    # ─── 5. ResultVerifier Level 4 Task Objective Tests ────────────────────────

    def test_result_verifier_level_4(self):
        # All completed steps
        steps_ok = [
            {"step_id": "step_1", "status": "COMPLETED", "error": None},
            {"step_id": "step_2", "status": "COMPLETED", "error": None},
        ]
        res_ok = ResultVerifier.verify_task_objective(steps_ok, expected_outcome="Data retrieved and summarized")
        assert res_ok.verified is True
        assert res_ok.level == VerificationLevel.LEVEL_4
        assert "Level 4 Objective Met" in res_ok.details

        # Incomplete steps
        steps_incomplete = [
            {"step_id": "step_1", "status": "COMPLETED", "error": None},
            {"step_id": "step_2", "status": "FAILED", "error": "Connection timeout"},
        ]
        res_fail = ResultVerifier.verify_task_objective(steps_incomplete)
        assert res_fail.verified is False
        assert res_fail.level == VerificationLevel.LEVEL_4
        assert "Task objective not met" in res_fail.details
