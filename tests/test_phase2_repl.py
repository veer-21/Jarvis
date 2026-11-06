"""
JARVIS Phase 2 Test Suite: Sandboxed Streaming Code REPL Engine
Verifies:
1. Python persistent REPL statefulness (variables, functions, classes persist across calls).
2. Python error resilience (exceptions caught, session does not crash).
3. AST-level security pre-execution gating (blocks ctypes, system wipes, dangerous imports).
4. PowerShell persistent session (variables, directory changes, environment).
5. Session reset lifecycle.
6. ResultVerifier Level 2 post-condition verification.
7. ToolRouter registration, session affinity, and Brain integration.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.repl_tools import (
    repl_execute_python,
    repl_execute_powershell,
    repl_reset_session,
    ReplExecutePythonArgs,
    ReplExecutePowerShellArgs,
    ReplResetSessionArgs
)
from core.brain.verifier import ResultVerifier, VerificationLevel
from core.brain.tool_router import ToolRouter
from tools import get_tool_registry, get_tool_categories


class TestPhase2ReplSuite:

    @classmethod
    def setup_class(cls):
        # Reset any prior active sessions
        repl_reset_session("all")

    @classmethod
    def teardown_class(cls):
        # Clean teardown
        repl_reset_session("all")

    # ─── 1. Python Persistent REPL Tests ──────────────────────────────────────

    def test_python_repl_args_validation(self):
        args = ReplExecutePythonArgs(code="print('Hello')", timeout=15)
        assert args.code == "print('Hello')"
        assert args.timeout == 15

    def test_python_repl_variable_persistence(self):
        # Cell 1: Assign variable
        res1 = repl_execute_python("jarvis_test_val = 42\nprint(f'SET:{jarvis_test_val}')")
        assert res1["success"] is True
        assert "SET:42" in res1["output"]

        # Cell 2: Access and modify variable in next cell
        res2 = repl_execute_python("jarvis_test_val += 58\nprint(f'UPDATED:{jarvis_test_val}')")
        assert res2["success"] is True
        assert "UPDATED:100" in res2["output"]

    def test_python_repl_function_and_class_persistence(self):
        # Define function and class
        def_code = """
class Calculator:
    def __init__(self, factor):
        self.factor = factor
    def multiply(self, x):
        return self.factor * x

def greet(name):
    return f"Welcome, {name}!"
"""
        res_def = repl_execute_python(def_code)
        assert res_def["success"] is True

        # Use function and class in subsequent cell
        use_code = """
calc = Calculator(10)
print(calc.multiply(5))
print(greet('Commander'))
"""
        res_use = repl_execute_python(use_code)
        assert res_use["success"] is True
        assert "50" in res_use["output"]
        assert "Welcome, Commander!" in res_use["output"]

    def test_python_repl_error_resilience(self):
        # Trigger runtime exception
        err_res = repl_execute_python("1 / 0")
        assert err_res["success"] is False
        assert "division by zero" in str(err_res.get("error", ""))
        assert err_res.get("traceback") is not None

        # Verify session is still alive and retains prior state
        recover_res = repl_execute_python("print(f'RECOVERED:{jarvis_test_val}')")
        assert recover_res["success"] is True
        assert "RECOVERED:100" in recover_res["output"]

    # ─── 2. Security AST Pre-Execution Gating ─────────────────────────────────

    def test_python_repl_ast_security_blocks_ctypes(self):
        # ctypes import should be flagged as CRITICAL and blocked before execution
        malicious_code = "import ctypes\nctypes.windll.kernel32.ExitProcess(0)"
        res = repl_execute_python(malicious_code)
        assert res["success"] is False
        assert "Security policy blocked" in res["error"]
        assert "ctypes" in res["error"]

    def test_python_repl_ast_security_blocks_critical_calls(self):
        # os.system should be flagged as CRITICAL and blocked
        call_code = "import os\nos.system('calc.exe')"
        res = repl_execute_python(call_code)
        assert res["success"] is False
        assert "Security policy blocked" in res["error"]

    # ─── 3. PowerShell Persistent REPL Tests ──────────────────────────────────

    def test_powershell_repl_args_validation(self):
        args = ReplExecutePowerShellArgs(command="Get-Date", timeout=20)
        assert args.command == "Get-Date"
        assert args.timeout == 20

    def test_powershell_repl_variable_persistence(self):
        # Step 1: Assign PowerShell variable
        res1 = repl_execute_powershell("$myVar = 'JARVIS_PS_ACTIVE'")
        assert res1["success"] is True

        # Step 2: Read PowerShell variable in subsequent command
        res2 = repl_execute_powershell("Write-Output \"VAL:$myVar\"")
        assert res2["success"] is True
        assert "VAL:JARVIS_PS_ACTIVE" in res2["output"]

    def test_powershell_repl_stateful_math(self):
        res1 = repl_execute_powershell("$num = 25; Write-Output ($num * 4)")
        assert res1["success"] is True
        assert "100" in res1["output"]

        res2 = repl_execute_powershell("Write-Output ($num + 75)")
        assert res2["success"] is True
        assert "100" in res2["output"]

    # ─── 4. Session Reset Lifecycle ───────────────────────────────────────────

    def test_repl_session_reset(self):
        # Set variable
        repl_execute_python("temp_token_123 = 'active'")
        res_before = repl_execute_python("print(temp_token_123)")
        assert "active" in res_before["output"]

        # Reset session
        reset_res = repl_reset_session("python")
        assert reset_res["success"] is True
        assert reset_res["details"]["python"] is True

        # Verify variable no longer exists in fresh session
        res_after = repl_execute_python("print(temp_token_123)")
        assert res_after["success"] is False
        assert "name 'temp_token_123' is not defined" in str(res_after.get("error", ""))

    # ─── 5. ResultVerifier Integration ────────────────────────────────────────

    def test_result_verifier_for_repl_tools(self):
        # REPL execution verification (Level 2)
        raw_res = {
            "success": True,
            "output": "Result is 42\n",
            "execution_count": 5,
            "elapsed_seconds": 0.04
        }
        v_res = ResultVerifier.verify_tool_result("repl_execute_python", {"code": "print(42)"}, raw_res)
        assert v_res.verified is True
        assert v_res.level == VerificationLevel.LEVEL_2
        assert v_res.evidence["output_length"] == len(raw_res["output"])

        # REPL reset verification (Level 1)
        raw_reset = {"success": True, "reset_target": "all", "details": {"python": True, "powershell": True}}
        v_reset = ResultVerifier.verify_tool_result("repl_reset_session", {}, raw_reset)
        assert v_reset.verified is True
        assert v_reset.level == VerificationLevel.LEVEL_1

    # ─── 6. Tool Registry & Router Integration ────────────────────────────────

    def test_tool_registry_and_categories_discovery(self):
        registry = get_tool_registry()
        categories = get_tool_categories()

        assert "repl_execute_python" in registry
        assert "repl_execute_powershell" in registry
        assert "repl_reset_session" in registry
        assert "repl" in categories
        assert "repl_execute_python" in categories["repl"]

    def test_tool_router_session_affinity(self):
        router = ToolRouter()
        schema_repl = MagicMock(category="repl")
        schema_other = MagicMock(category="random")

        assert router._is_session_affine("repl_execute_python", schema_repl) is True
        assert router._is_session_affine("repl_execute_powershell", schema_repl) is True
        assert router._is_session_affine("other_task", schema_other) is False

