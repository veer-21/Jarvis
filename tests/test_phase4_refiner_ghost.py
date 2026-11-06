"""
Test Suite: Phase 4 — The Ghost Operator & Refiner 2.0 + Declarative Tool Decorators
Covers:
  - Declarative @jarvis_tool decorator and ToolSchema binding
  - ToolRouter.register_decorated_tools() and auto-discovery
  - The Ghost Operator Win32 message dispatch (click, text, list windows)
  - Refiner 2.0 AST safety validation and quarantine isolation
  - Dry-run synthetic test execution
  - Closed-loop autonomous promotion and hot-reloading into ToolRouter
  - ResultVerifier deterministic Level 2/Level 3 checks
  - Brain integration for ghost and refiner categories
"""

import os
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.security import RiskLevel
from core.brain.tool_router import jarvis_tool, ToolSchema, ToolRouter
from core.brain.custom_tool_pipeline import (
    validate_ast_safety,
    validate_tool_source,
    dry_run_synthetic_execution,
    process_and_register_generated_tool,
)
from tools.ghost_operator import (
    ghost_list_targetable_windows,
    ghost_click_window,
    ghost_send_text,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_CHAR,
)
from core.agents.refiner_agent import RefinerAgent, refiner_synthesize_custom_tool
from core.brain.verifier import ResultVerifier, VerificationLevel
from core.agents.base_agent import AgentMessage


class TestPhase4RefinerGhostSuite:

    # ─── 1. Declarative @jarvis_tool Decorator Tests ─────────────────────────

    def test_jarvis_tool_decorator_attaches_schema_and_metadata(self):
        """Verify @jarvis_tool creates and binds ToolSchema with inferred and explicit attributes."""
        @jarvis_tool(
            name="custom_math_tool",
            category="math",
            risk_level=RiskLevel.LOW_RISK,
            requires_binaries=["calc.exe"],
            timeout_seconds=45
        )
        def custom_math_tool(x: int, y: int = 10) -> int:
            """Multiplies x by y."""
            return x * y

        assert hasattr(custom_math_tool, "__jarvis_tool__")
        assert custom_math_tool.__jarvis_tool__ is True
        assert hasattr(custom_math_tool, "__jarvis_tool_schema__")

        schema: ToolSchema = custom_math_tool.__jarvis_tool_schema__
        assert isinstance(schema, ToolSchema)
        assert schema.name == "custom_math_tool"
        assert schema.category == "math"
        assert schema.risk_level == RiskLevel.LOW_RISK
        assert schema.requires_binaries == ["calc.exe"]
        assert schema.timeout_seconds == 45
        assert "Multiplies x by y" in schema.description
        assert schema.pydantic_model is not None

    def test_jarvis_tool_decorator_supports_alternate_aliases(self):
        """Verify @jarvis_tool supports 'risk' and 'requires' alias arguments."""
        @jarvis_tool(risk=RiskLevel.HIGH_RISK, requires=["notepad.exe"])
        def launch_notepad(path: str) -> bool:
            """Launches notepad."""
            return True

        schema = launch_notepad.__jarvis_tool_schema__
        assert schema.risk_level == RiskLevel.HIGH_RISK
        assert schema.requires_confirmation is True
        assert schema.requires_binaries == ["notepad.exe"]
        assert schema.name == "launch_notepad"

    def test_tool_router_register_decorated_tool_single(self):
        """Verify ToolRouter registers a single decorated callable directly."""
        router = ToolRouter()

        @jarvis_tool(name="ping_service", category="network", risk_level=RiskLevel.READ_ONLY)
        def ping_service(host: str) -> str:
            """Pings a host."""
            return f"pong from {host}"

        schema = router.register_decorated_tool(ping_service)
        assert schema is not None
        assert router.get_tool("ping_service") is not None
        assert "network" in router.get_categories()

        res = router.execute_tool("ping_service", {"host": "127.0.0.1"}, interactive=False)
        assert res.success is True
        assert "pong from 127.0.0.1" in res.output

    def test_tool_router_register_decorated_tools_from_module(self):
        """Verify ToolRouter scans and registers multiple @jarvis_tool functions from an object/module."""
        router = ToolRouter()

        class DummyModule:
            @staticmethod
            @jarvis_tool(name="fn_alpha", category="alpha")
            def fn_alpha():
                """Alpha tool."""
                return "alpha"

            @staticmethod
            @jarvis_tool(name="fn_beta", category="beta")
            def fn_beta():
                """Beta tool."""
                return "beta"

            @staticmethod
            def plain_helper():
                return "plain"

        count = router.register_decorated_tools(DummyModule)
        assert count == 2
        assert router.get_tool("fn_alpha") is not None
        assert router.get_tool("fn_beta") is not None
        assert router.get_tool("plain_helper") is None

    # ─── 2. The Ghost Operator Win32 Messaging Tests ─────────────────────────

    def test_ghost_list_targetable_windows_structure(self):
        """Verify ghost_list_targetable_windows returns well-formed window listings."""
        res = ghost_list_targetable_windows()
        assert isinstance(res, dict)
        assert res.get("success") is True
        assert res.get("action") == "ghost_list_targetable_windows"
        assert isinstance(res.get("windows"), list)
        assert isinstance(res.get("count"), int)
        assert res.get("count") == len(res.get("windows"))

    def test_ghost_click_window_handles_missing_window(self):
        """Verify ghost_click_window returns an error when window does not exist."""
        res = ghost_click_window(window_title="__NON_EXISTENT_GHOST_TARGET_12345__")
        assert res.get("success") is False
        assert "not found" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()

    @patch("tools.ghost_operator.HAS_PYWIN32", True)
    @patch("tools.ghost_operator.win32gui")
    def test_ghost_click_window_dispatches_post_message(self, mock_win32gui):
        """Verify ghost_click_window posts WM_LBUTTONDOWN and WM_LBUTTONUP with packed coordinates."""
        mock_win32gui.IsWindow.return_value = True
        mock_win32gui.GetWindowText.return_value = "Mock Target Window"

        res = ghost_click_window(hwnd=99999, x=150, y=300, button="left")
        assert res.get("success") is True
        assert res.get("hwnd") == 99999
        assert res.get("x") == 150
        assert res.get("y") == 300

        # Verify PostMessage calls
        calls = mock_win32gui.PostMessage.call_args_list
        assert len(calls) == 2
        # Check first call (down) and second call (up)
        down_call = calls[0]
        up_call = calls[1]
        assert down_call[0][0] == 99999
        assert down_call[0][1] == WM_LBUTTONDOWN
        assert up_call[0][0] == 99999
        assert up_call[0][1] == WM_LBUTTONUP

        expected_lparam = ((300 & 0xFFFF) << 16) | (150 & 0xFFFF)
        assert down_call[0][3] == expected_lparam
        assert up_call[0][3] == expected_lparam

    def test_ghost_send_text_handles_missing_window(self):
        """Verify ghost_send_text returns an error when target window is missing."""
        res = ghost_send_text(window_title="__NON_EXISTENT_GHOST_TARGET_12345__", text="Hello")
        assert res.get("success") is False
        assert "not found" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()

    @patch("tools.ghost_operator.HAS_PYWIN32", True)
    @patch("tools.ghost_operator.win32gui")
    def test_ghost_send_text_dispatches_wm_char_messages(self, mock_win32gui):
        """Verify ghost_send_text posts WM_CHAR for each character without mouse/focus hijack."""
        mock_win32gui.IsWindow.return_value = True
        mock_win32gui.GetWindowText.return_value = "Mock Target Editor"
        mock_win32gui.EnumChildWindows.return_value = None

        test_payload = "JARVIS_TEST"
        res = ghost_send_text(hwnd=88888, text=test_payload)
        assert res.get("success") is True
        assert res.get("text_length") == len(test_payload)

        calls = mock_win32gui.PostMessage.call_args_list
        assert len(calls) == len(test_payload)
        for i, char in enumerate(test_payload):
            assert calls[i][0][0] == 88888
            assert calls[i][0][1] == WM_CHAR
            assert calls[i][0][2] == ord(char)

    # ─── 3. Refiner 2.0 AST Security and Dry-Run Tests ────────────────────────

    def test_refiner_ast_validation_allows_safe_decorated_tool(self):
        """Verify validate_ast_safety accepts clean tool code with @jarvis_tool decoration."""
        code = '''from core.brain.tool_router import jarvis_tool
from core.security import RiskLevel
import math

@jarvis_tool(name="calc_sphere_volume", category="math", risk_level=RiskLevel.LOW_RISK)
def calc_sphere_volume(radius: float) -> float:
    """Calculates sphere volume from radius."""
    return (4.0 / 3.0) * math.pi * (radius ** 3)
'''
        is_valid, reason, meta = validate_ast_safety(code)
        assert is_valid is True
        assert reason is None
        assert meta["function_name"] == "calc_sphere_volume"

    def test_refiner_ast_validation_blocks_forbidden_imports_and_calls(self):
        """Verify validate_ast_safety rejects unauthorized imports and forbidden reflective operations."""
        forbidden_snippets = [
            ("import os", "import os\ndef bad_tool():\n    '''bad'''\n    return os.listdir('.')\n"),
            ("subprocess", "import subprocess\ndef bad_tool():\n    '''bad'''\n    return subprocess.run(['cmd'])\n"),
            ("open", "def bad_tool():\n    '''bad'''\n    with open('data.txt') as f:\n        return f.read()\n"),
            ("eval", "def bad_tool(code: str):\n    '''bad'''\n    return eval(code)\n"),
            ("__class__", "def bad_tool():\n    '''bad'''\n    return ''.__class__.__mro__\n"),
        ]

        for name, code in forbidden_snippets:
            is_valid, reason, _ = validate_ast_safety(code)
            assert is_valid is False, f"Snippet with '{name}' should have been rejected."
            assert "security violation" in reason.lower() or "forbidden" in reason.lower() or "not in the allowed" in reason.lower()

    def test_refiner_dry_run_synthetic_execution_success(self):
        """Verify dry_run_synthetic_execution runs safe code and returns output without exception."""
        code = '''import math

def calculate_diagonal(w: float, h: float) -> float:
    """Calculates diagonal length using Pythagorean theorem."""
    return math.hypot(w, h)
'''
        ok, msg, res = dry_run_synthetic_execution(code, function_name="calculate_diagonal", synthetic_args={"w": 3.0, "h": 4.0})
        assert ok is True
        assert "succeeded" in msg.lower()
        assert res == 5.0

    def test_refiner_dry_run_synthetic_execution_catches_runtime_crash(self):
        """Verify dry_run_synthetic_execution catches runtime errors during the quarantine phase."""
        code = '''def broken_math_tool(x: int) -> int:
    """Intentionally crashes at runtime."""
    return 100 // 0
'''
        ok, msg, res = dry_run_synthetic_execution(code, function_name="broken_math_tool")
        assert ok is False
        assert "ZeroDivisionError" in msg

    # ─── 4. Refiner 2.0 Autonomous Promotion & Hot-Reloading ─────────────────

    def test_refiner_closed_loop_promotion_and_hot_reloading(self, tmp_path):
        """Verify the full pipeline: AST audit -> dry-run -> promote to custom/ -> hot-reload into ToolRouter."""
        router = ToolRouter()
        custom_dir = tmp_path / "custom"
        quarantine_dir = tmp_path / "_quarantine"

        tool_code = '''from core.brain.tool_router import jarvis_tool
from core.security import RiskLevel
import math

@jarvis_tool(name="calc_kinetic_energy", category="physics", risk_level=RiskLevel.LOW_RISK)
def calc_kinetic_energy(mass: float, velocity: float) -> float:
    """Computes kinetic energy: 0.5 * m * v^2."""
    return 0.5 * mass * (velocity ** 2)
'''

        ok, report = process_and_register_generated_tool(
            source_code=tool_code,
            tool_router=router,
            custom_dir=custom_dir,
            quarantine_dir=quarantine_dir
        )

        assert ok is True
        assert "calc_kinetic_energy" in router._registry
        assert (custom_dir / "calc_kinetic_energy.py").exists()
        assert not (quarantine_dir / "quarantine_*").exists()

        # Execute through router without restart
        res = router.execute_tool("calc_kinetic_energy", {"mass": 10.0, "velocity": 2.0}, interactive=False)
        assert res.success is True
        assert res.output == 20.0

    def test_refiner_synthesize_custom_tool_callable(self, tmp_path):
        """Verify refiner_synthesize_custom_tool function completes synthesis and hot-reload."""
        router = ToolRouter()
        mock_brain = MagicMock()
        mock_brain.tools = router

        tool_code = '''from core.brain.tool_router import jarvis_tool
from core.security import RiskLevel

@jarvis_tool(name="format_currency", category="finance", risk_level=RiskLevel.LOW_RISK)
def format_currency(amount: float) -> str:
    """Formats amount into USD string."""
    return f"${amount:,.2f}"
'''

        with patch("core.agents.refiner_agent.Path") as mock_path:
            # Let Path("tools") / "custom" point to tmp_path
            mock_path.return_value = tmp_path
            res = refiner_synthesize_custom_tool(
                task_description="Format amounts as currency",
                source_code=tool_code,
                function_name="format_currency",
                brain=mock_brain
            )

        assert res.get("success") is True
        assert res.get("tool_name") == "format_currency"
        assert res.get("hot_reloaded") is True

    def test_refiner_agent_message_dispatch(self, tmp_path):
        """Verify RefinerAgent handles synthesize_tool AgentMessage."""
        mock_brain = MagicMock()
        mock_brain.tools = ToolRouter()
        agent = RefinerAgent(brain=mock_brain)
        agent.custom_tools_dir = str(tmp_path / "custom")

        msg = AgentMessage(
            sender="user",
            recipient="refiner",
            user_id="test_owner",
            system_authorized=True,
            content="Reverse a string payload",
            metadata={
                "action": "synthesize_tool",
                "source_code": '''from core.brain.tool_router import jarvis_tool
from core.security import RiskLevel

@jarvis_tool(name="reverse_text_helper", category="custom", risk_level=RiskLevel.LOW_RISK)
def reverse_text_helper(text: str = "sample") -> str:
    """Reverses text."""
    return text[::-1]
''',
                "function_name": "reverse_text_helper"
            }
        )

        resp = agent.process(msg)
        assert resp.success is True
        assert "reverse_text_helper" in resp.content or resp.metadata.get("tool_name") == "reverse_text_helper"

    # ─── 5. ResultVerifier Deterministic Post-Condition Tests ────────────────

    def test_result_verifier_levels_for_phase4_tools(self):
        """Verify ResultVerifier TOOL_LEVEL_REGISTRY registers all Phase 4 tools at Level 2/3."""
        assert ResultVerifier.get_tool_verification_level("ghost_list_targetable_windows") == VerificationLevel.LEVEL_2
        assert ResultVerifier.get_tool_verification_level("ghost_click_window") == VerificationLevel.LEVEL_3
        assert ResultVerifier.get_tool_verification_level("ghost_send_text") == VerificationLevel.LEVEL_3
        assert ResultVerifier.get_tool_verification_level("refiner_synthesize_custom_tool") == VerificationLevel.LEVEL_3

    def test_result_verifier_verify_ghost_tools(self):
        """Verify ResultVerifier.verify_tool_result() validates ghost operations deterministically."""
        # ghost_list_targetable_windows
        v_list = ResultVerifier.verify_tool_result(
            "ghost_list_targetable_windows",
            {},
            {"success": True, "count": 3, "windows": [{"hwnd": 1}, {"hwnd": 2}, {"hwnd": 3}]}
        )
        assert v_list.verified is True
        assert v_list.level == VerificationLevel.LEVEL_2
        assert v_list.evidence.get("windows_count") == 3

        # ghost_click_window
        v_click = ResultVerifier.verify_tool_result(
            "ghost_click_window",
            {"window_title": "Notepad", "x": 100, "y": 200},
            {"success": True, "hwnd": 12345, "window_title": "Notepad", "x": 100, "y": 200, "button": "left"}
        )
        assert v_click.verified is True
        assert v_click.level == VerificationLevel.LEVEL_3
        assert v_click.evidence.get("hwnd") == 12345

        # ghost_send_text
        v_text = ResultVerifier.verify_tool_result(
            "ghost_send_text",
            {"window_title": "Notepad", "text": "Hello world"},
            {"success": True, "hwnd": 12345, "window_title": "Notepad", "text_length": 11}
        )
        assert v_text.verified is True
        assert v_text.level == VerificationLevel.LEVEL_3

        # Error path
        v_err = ResultVerifier.verify_tool_result(
            "ghost_click_window",
            {"window_title": "Missing"},
            {"success": False, "error": "Window not found"}
        )
        assert v_err.verified is False

    def test_result_verifier_verify_refiner_synthesize_tool(self):
        """Verify ResultVerifier validates refiner_synthesize_custom_tool at Level 3."""
        v_refiner = ResultVerifier.verify_tool_result(
            "refiner_synthesize_custom_tool",
            {"task_description": "Calculate area"},
            {"success": True, "tool_name": "calc_area", "promoted_path": "tools/custom/calc_area.py", "hot_reloaded": True}
        )
        assert v_refiner.verified is True
        assert v_refiner.level == VerificationLevel.LEVEL_3
        assert v_refiner.evidence.get("tool_name") == "calc_area"

    # ─── 6. Full Brain Registry Discovery Tests ──────────────────────────────

    def test_phase4_tools_registered_in_brain(self):
        """Verify Brain initializes with ghost and refiner tools registered in appropriate categories."""
        from tools import get_tool_registry, get_tool_categories

        registry = get_tool_registry()
        categories = get_tool_categories()

        # Ghost operator tools
        assert "ghost_list_targetable_windows" in registry
        assert "ghost_click_window" in registry
        assert "ghost_send_text" in registry
        assert "ghost" in categories
        assert "ghost_click_window" in categories["ghost"]

        # Refiner tools
        assert "refiner_synthesize_custom_tool" in registry
        assert "refiner" in categories
        assert "refiner_synthesize_custom_tool" in categories["refiner"]
