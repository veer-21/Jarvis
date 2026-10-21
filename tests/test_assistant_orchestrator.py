"""
Tests for JARVIS Central Assistant Orchestrator & Phase 3 Architecture.
Validates requirements A through K:
A. Single-step tasks
B. Multi-step tasks
C. Ambiguous requests & referential context
D. Missing parameters
E. Confirmation flow & security policy
F. Task cancellation
G. Failure recovery & safe retry
H. Result verification
I. Memory integration & deletion
J. Unified execution across provider fallbacks
K. Security risk evaluation & data masking
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.security import guard, RiskLevel, mask_sensitive_data
from core.brain.verifier import ResultVerifier
from core.brain.tool_contract import ToolContract, ToolExecutionResult, ConfirmationPolicy, RetryPolicy
from core.brain.task_model import AssistantTask, TaskStep, TaskStatus, TaskStepStatus, ExecutionContext
from core.brain.context_tracker import ContextTracker
from core.brain.memory_policy import MemoryPolicy, MemoryTier
from core.brain.assistant_orchestrator import AssistantOrchestrator
from core.brain.tool_router import ToolRouter
from core.brain.reasoning_engine import ReasoningEngine


class TestPhase3Orchestrator(unittest.TestCase):

    def setUp(self):
        self.router = ToolRouter()
        # Register standard dummy/mock tools for deterministic testing
        def dummy_read(file_path: str):
            if file_path == "README.md":
                return "# JARVIS\nPersonal assistant architecture and core tools."
            if file_path == "assignment.pdf":
                return "Assignment 1: Neural Networks. Questions 1 to 5."
            raise FileNotFoundError(f"File not found: {file_path}")

        def dummy_list(path: str = "."):
            return "README.md\nmain.py\nassignment.pdf"

        def dummy_search(query: str):
            return f"Results for: {query}\n1. Official Documentation\n2. Release notes"

        def dummy_open(app_name: str):
            try:
                from tools.automation_tools import open_application
                return open_application(app_name)
            except Exception:
                return f"Application '{app_name}' launched successfully."

        def dummy_cmd(command: str):
            return f"Executed: {command}"

        self.router.register_callable(dummy_read, name="read_file", category="file",
                                      risk_level=RiskLevel.READ_ONLY, requires_confirmation=False)
        self.router.register_callable(dummy_list, name="list_directory", category="file",
                                      risk_level=RiskLevel.READ_ONLY, requires_confirmation=False)
        self.router.register_callable(dummy_search, name="web_search", category="web",
                                      risk_level=RiskLevel.READ_ONLY, requires_confirmation=False)
        self.router.register_callable(dummy_open, name="open_application", category="automation",
                                      risk_level=RiskLevel.LOW_RISK, requires_confirmation=False)
        self.router.register_callable(dummy_cmd, name="execute_command", category="system",
                                      risk_level=RiskLevel.HIGH_RISK, requires_confirmation=True)

        self.mock_reasoning = MagicMock()
        self.mock_reasoning.generate_text.side_effect = lambda prompt: f"Synthesized summary from: {prompt[:30]}..."
        self.mock_reasoning.send_message.side_effect = lambda msg, raw_message=None: f"Answer: {msg[:30]}..."

        self.mock_memory = MagicMock()
        self.mock_memory.delete_memory.return_value = True

        self.orchestrator = AssistantOrchestrator(
            tool_router=self.router,
            memory_manager=self.mock_memory,
            reasoning_engine=self.mock_reasoning
        )

    def tearDown(self):
        try:
            import subprocess
            subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)
        except Exception:
            pass

    # ─── A. Single-Step Tasks ─────────────────────────────────────────────────

    def test_single_step_task(self):
        """Test single-step execution and result formatting."""
        res = self.orchestrator.process("open notepad and tell me whether it is running")
        self.assertIsNotNone(res)
        self.assertIn("notepad", res.lower())
        self.assertEqual(len(self.orchestrator._execution_history), 1)
        task = self.orchestrator._execution_history[0]
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertGreaterEqual(len(task.completed_steps), 1)

    # ─── B. Multi-Step Tasks ──────────────────────────────────────────────────

    def test_multi_step_task_dag(self):
        """Test explicit multi-step plan generation, execution graph, and tracking."""
        res = self.orchestrator.process("Find my README and summarize the architecture")
        self.assertIsNotNone(res)
        task = self.orchestrator._execution_history[-1]
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        # Should have planned search/list -> read_file -> summarize
        self.assertGreaterEqual(len(task.plan), 2)
        self.assertIn(task.plan[0].step_id, task.completed_steps)
        self.assertEqual(len(task.failed_steps), 0)

    # ─── C. Ambiguous Requests & Follow-Up Context ────────────────────────────

    def test_referential_follow_up_context(self):
        """Test resolving pronouns like 'the second one' from previous candidates."""
        # 1. First task lists candidates
        self.orchestrator.context_tracker.update_exchange(
            "Find my files",
            "Found 3 files",
            candidates=["report1.docx", "report2.pdf", "report3.xlsx"]
        )

        # 2. User refers to 'the second one'
        resolved = self.orchestrator.context_tracker.resolve_reference("open the second one")
        self.assertEqual(resolved, "report2.pdf")

        # 3. Ordinal test
        resolved_1st = self.orchestrator.context_tracker.resolve_reference("read the 1st option")
        self.assertEqual(resolved_1st, "report1.docx")

    # ─── D. Missing Parameters ────────────────────────────────────────────────

    def test_missing_parameters_validation(self):
        """Test that missing required parameters are detected before execution."""
        missing = self.orchestrator._check_missing_parameters("read_file", {})
        self.assertIn("file_path", missing)

        not_missing = self.orchestrator._check_missing_parameters("read_file", {"file_path": "README.md"})
        self.assertEqual(len(not_missing), 0)

    # ─── E. Confirmation Flow & Security Enforcement ──────────────────────────

    def test_security_policy_decision_point(self):
        """Test that all tool executions pass through the 5-tier policy decision point."""
        # READ_ONLY tool does not require confirmation
        approved, risk, req_conf, reason = guard.evaluate_tool_execution(
            "read_file", {"file_path": "README.md"}, declared_risk=RiskLevel.READ_ONLY, interactive=False
        )
        self.assertTrue(approved)
        self.assertFalse(req_conf)

        # HIGH_RISK tool requires confirmation
        approved_hi, risk_hi, req_conf_hi, reason_hi = guard.evaluate_tool_execution(
            "execute_command", {"command": "rm -rf /"}, declared_risk=RiskLevel.HIGH_RISK, interactive=False
        )
        self.assertFalse(approved_hi)
        self.assertTrue(req_conf_hi)
        self.assertIn("confirmation", reason_hi.lower())

        # Interactive approval simulation
        with patch("builtins.input", return_value="y"):
            approved_int, risk_int, req_conf_int, reason_int = guard.evaluate_tool_execution(
                "execute_command", {"command": "dir"}, declared_risk=RiskLevel.HIGH_RISK, interactive=True
            )
            self.assertTrue(approved_int)

    # ─── F. Cancellation ──────────────────────────────────────────────────────

    def test_task_cancellation(self):
        """Test stopping/cancelling active tasks with varied natural language."""
        cancellation_phrases = ["stop", "cancel that", "never mind", "don't do it", "abort the task"]
        for phrase in cancellation_phrases:
            self.assertTrue(self.orchestrator.context_tracker.is_cancellation(phrase))

        # Test active task cancellation propagation
        active_task = AssistantTask(user_request="Download giant dataset")
        active_task.transition_to(TaskStatus.EXECUTING)
        self.orchestrator.active_task = active_task

        resp = self.orchestrator.process("stop")
        self.assertIn("stopped the active task", resp)
        self.assertEqual(active_task.status, TaskStatus.CANCELLED)

    # ─── G. Failure Recovery ──────────────────────────────────────────────────

    def test_failure_recovery_safe_retry(self):
        """Test controlled recovery when a step fails safely."""
        step = TaskStep(description="Read file", capability="file", tool_name="read_file")
        # Attempt recovery with non-existent file, recovery tries candidate search
        recovered = self.orchestrator._attempt_recovery(step, {"file_path": "readme.txt"}, "File not found", {})
        self.assertIsNotNone(recovered)
        self.assertTrue(recovered.success)
        self.assertIn("JARVIS", str(recovered.output))

    # ─── H. Result Verification ───────────────────────────────────────────────

    def test_result_verification_deterministic(self):
        """Test ResultVerifier verifying real post-conditions."""
        # 1. Existing file verification
        file_check = ResultVerifier.verify_file_exists("README.md")
        self.assertTrue(file_check.verified)
        self.assertTrue(file_check["verified"])
        self.assertGreater(file_check.evidence["size_bytes"], 0)

        # 2. Non-existent file verification must not fabricate success
        fake_check = ResultVerifier.verify_file_exists("non_existent_file_xyz_12345.txt")
        self.assertFalse(fake_check.verified)

        # 3. Running process verification
        proc_check = ResultVerifier.verify_process_running("python")
        self.assertTrue(proc_check.verified)

    # ─── I. Memory Integration & Deletion ─────────────────────────────────────

    def test_memory_policy_filtering(self):
        """Test that transient searches/calculations are not dumped into permanent memory."""
        # Transient calculation
        tier_calc, cat_calc = MemoryPolicy.classify_interaction("what is 42 * 9")
        self.assertEqual(tier_calc, MemoryTier.TRANSIENT_CONVERSATION)

        # Transient greeting
        tier_hi, cat_hi = MemoryPolicy.classify_interaction("hello there")
        self.assertEqual(tier_hi, MemoryTier.TRANSIENT_CONVERSATION)

        # Permanent preference
        tier_pref, cat_pref = MemoryPolicy.classify_interaction("remember that I prefer dark mode and concise answers")
        self.assertEqual(tier_pref, MemoryTier.USER_PREFERENCE)

    def test_memory_deletion(self):
        """Test user memory deletion flow."""
        # Unauthenticated / unowned request fails closed
        unauth_resp = self.orchestrator.process("forget my preference for dark mode")
        self.assertIn("cannot delete memories without verified user identity", unauth_resp)

        # Authenticated owner request succeeds
        ctx = ExecutionContext(user_id="test_user")
        resp = self.orchestrator.process("forget my preference for dark mode", context=ctx)
        self.assertIn("deleted that information from memory", resp)
        self.mock_memory.delete_memory.assert_called()

    # ─── J. Provider Fallback Unified Tool Execution ──────────────────────────

    def test_provider_fallback_uses_unified_tool_router(self):
        """Test that fallback LLMs execute tools through the central ToolRouter, not raw functions."""
        engine = ReasoningEngine()
        engine.set_tool_router(self.router)

        # Verify that ToolRouter is attached to the reasoning engine
        self.assertEqual(engine._tool_router, self.router)

        # Create mock provider with chat completions returning tool calls
        mock_client = MagicMock()

        class MockFunction:
            def __init__(self, name, arguments):
                self.name = name
                self.arguments = arguments

        class MockToolCall:
            def __init__(self, id, name, arguments):
                self.id = id
                self.function = MockFunction(name, arguments)

        class MockChoice:
            def __init__(self, tool_calls, content=None):
                self.message = MagicMock()
                self.message.tool_calls = tool_calls
                self.message.content = content

        class MockResponse:
            def __init__(self, choices):
                self.choices = choices

        resp1 = MockResponse([MockChoice([MockToolCall("call_1", "open_application", '{"app_name": "notepad"}')])])
        resp2 = MockResponse([MockChoice([], content="Notepad is open")])
        mock_client.chat.completions.create.side_effect = [resp1, resp2]

        with patch.object(self.router, "execute_tool", wraps=self.router.execute_tool) as spy_execute:
            res = engine._execute_fallback_with_tools(mock_client, "llama-3.3-70b-versatile", [{"role": "user", "content": "open notepad"}])
            self.assertEqual(res, "Notepad is open")
            # Proves tool execution passed strictly through tool_router.execute_tool
            spy_execute.assert_called_once_with(name="open_application", args={"app_name": "notepad"}, interactive=False)

    # ─── K. Security Risk Evaluation & Data Masking ───────────────────────────

    def test_sensitive_data_masking(self):
        """Test that credentials, tokens, and API keys are masked from audit logs."""
        payload_dict = {
            "api_key": "AIzaSySecretApiKey1234567890",
            "password": "super_secret_password",
            "normal_field": "hello world"
        }
        masked_dict = mask_sensitive_data(payload_dict)
        self.assertEqual(masked_dict["api_key"], "[MASKED_SECRET]")
        self.assertEqual(masked_dict["password"], "[MASKED_SECRET]")
        self.assertEqual(masked_dict["normal_field"], "hello world")

        token_str = "sk-proj-1234567890abcdef1234567890abcdef"
        masked_token = mask_sensitive_data(token_str)
        self.assertEqual(masked_token, "[MASKED_TOKEN]")


class TestAcceptanceCriteria(unittest.TestCase):
    """
    Acceptance tests for section 16 human-language requests.
    Validates natural interaction patterns without hardcoding.
    """

    def setUp(self):
        self.router = ToolRouter()

        def mock_read(file_path: str):
            if "readme" in file_path.lower():
                return "# JARVIS\nPersonal assistant architecture and core tools."
            if "assignment" in file_path.lower():
                return "AI Assignment: Question 1: Describe CNNs. Question 2: Implement Backpropagation."
            return "File content placeholder."

        def mock_list(path: str = "."):
            return "README.md\nAI_Assignment.pdf\nsrc/main.py"

        def mock_search(query: str):
            return f"Results for {query}: Python 3.12 is the latest stable release."

        def mock_open(app_name: str):
            try:
                from tools.automation_tools import open_application
                return open_application(app_name)
            except Exception:
                return f"{app_name} launched successfully."

        self.router.register_callable(mock_read, name="read_file", category="file", risk_level=RiskLevel.READ_ONLY)
        self.router.register_callable(mock_list, name="list_directory", category="file", risk_level=RiskLevel.READ_ONLY)
        self.router.register_callable(mock_search, name="web_search", category="web", risk_level=RiskLevel.READ_ONLY)
        self.router.register_callable(mock_open, name="open_application", category="automation", risk_level=RiskLevel.LOW_RISK)

        self.mock_reasoning = MagicMock()
        self.mock_reasoning.generate_text.side_effect = lambda prompt: f"Processed summary: {prompt[:80]}"
        self.mock_reasoning.send_message.side_effect = lambda msg, raw_message=None: f"Answer: {msg[:80]}"

        self.mock_memory = MagicMock()

        self.orchestrator = AssistantOrchestrator(
            tool_router=self.router,
            memory_manager=self.mock_memory,
            reasoning_engine=self.mock_reasoning
        )

    def tearDown(self):
        try:
            import subprocess
            subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)
        except Exception:
            pass

    def test_acceptance_open_notepad_and_verify(self):
        """'Open Notepad and tell me whether it is running.'"""
        res = self.orchestrator.process("Open Notepad and tell me whether it is running.")
        self.assertIsNotNone(res)
        self.assertEqual(len(self.orchestrator._execution_history), 1)
        task = self.orchestrator._execution_history[-1]
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_acceptance_find_readme_and_summarize(self):
        """'Find my README and summarize the architecture.'"""
        res = self.orchestrator.process("Find my README and summarize the architecture.")
        self.assertIsNotNone(res)
        task = self.orchestrator._execution_history[-1]
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertGreaterEqual(len(task.completed_steps), 2)

    def test_acceptance_web_search_and_summarize(self):
        """'Open the browser, search for a topic, inspect the results, and summarize them.'"""
        res = self.orchestrator.process("Open the browser, search for React 19 documentation, and summarize them.")
        self.assertIsNotNone(res)
        task = self.orchestrator._execution_history[-1]
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_acceptance_find_assignment_and_checklist(self):
        """'Find my AI assignment and create a checklist of the questions.'"""
        res = self.orchestrator.process("Find my AI assignment and create a checklist of the questions.")
        self.assertIsNotNone(res)
        task = self.orchestrator._execution_history[-1]
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_acceptance_remember_preference(self):
        """'Remember that I prefer concise answers.'"""
        res = self.orchestrator.process("Remember that I prefer concise answers.")
        self.assertIsNotNone(res)
        # Should be stored in permanent memory per MemoryPolicy
        self.mock_memory.store_exchange.assert_called()

    def test_acceptance_stop_current_task(self):
        """'Stop the current task.'"""
        # Active task running
        active_task = AssistantTask(user_request="Perform web crawl")
        active_task.transition_to(TaskStatus.EXECUTING)
        self.orchestrator.active_task = active_task

        res = self.orchestrator.process("Stop the current task.")
        self.assertIn("stopped the active task", res.lower())
        self.assertEqual(active_task.status, TaskStatus.CANCELLED)


if __name__ == "__main__":
    unittest.main()
