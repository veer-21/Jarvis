"""
JARVIS Phase 3.6 Production Gate Hardening Test Suite
Verifies:
1. End-to-End Security Confirmation Flow & Expiry/Removal
2. Real Task Interruption, DAG Step Halting, and CANCELLED State
3. Safe Timeout Policy, Worker Pool Recycling, & Cleanup Tracking
4. Memory Persistence Gating (store=True vs store=False)
5. Custom Tool 7-Stage Quarantine & Static Validation Pipeline
6. Background Worker Thread-Safe Event Delivery Bridge
"""

import time
import uuid
import pytest
import asyncio
import threading
from pathlib import Path
from unittest.mock import MagicMock

from core.security import SecurityGuard, RiskLevel, guard, owner_auth
from core.brain.task_model import (
    AssistantTask,
    TaskStep,
    TaskStatus,
    TaskStepStatus,
    ExecutionContext,
)
from core.brain.tool_contract import ToolExecutionResult, ToolContract
from core.brain.tool_router import ToolRouter
from core.brain.custom_tool_pipeline import (
    validate_tool_source,
    process_and_register_generated_tool,
)
from core.brain.assistant_orchestrator import AssistantOrchestrator
from core.memory import JarvisMemory
from core.brain.memory_manager import MemoryManager


# ─── 1. End-to-End Confirmation Tests ────────────────────────────────────────

def test_confirmation_lifecycle_create_approve_and_cleanup():
    """Verify confirmation created, emitted, approved, and cleaned up from pending storage."""
    sg = SecurityGuard(auth=owner_auth)
    emitted = []

    def mock_handler(tool_name, args, risk):
        conf_id, event = sg.create_pending_confirmation(tool_name, args, risk)
        emitted.append({"id": conf_id, "tool": tool_name, "risk": risk.value})
        sg.submit_confirmation(conf_id, approved=True)
        sg.remove_confirmation(conf_id)
        return True, "Approved via UI"

    sg.register_confirmation_handler(mock_handler)

    allowed, risk, req_conf, reason = sg.evaluate_tool_execution(
        tool_name="delete_directory",
        args={"path": "C:/fake/path"},
        declared_risk=RiskLevel.HIGH_RISK,
        interactive=True
    )

    assert allowed is True
    assert len(emitted) == 1
    conf_id = emitted[0]["id"]
    assert conf_id not in sg.get_pending_confirmations()


def test_confirmation_denial():
    """Verify explicit denial halts execution and cleans up pending confirmation."""
    sg = SecurityGuard(auth=owner_auth)

    def mock_handler(tool_name, args, risk):
        conf_id, event = sg.create_pending_confirmation(tool_name, args, risk)
        sg.submit_confirmation(conf_id, approved=False)
        sg.remove_confirmation(conf_id)
        return False, "Denied by user via UI"

    sg.register_confirmation_handler(mock_handler)

    allowed, risk, req_conf, reason = sg.evaluate_tool_execution(
        tool_name="format_disk",
        args={"drive": "Z:"},
        declared_risk=RiskLevel.HIGH_RISK,
        interactive=True
    )

    assert allowed is False
    assert "denied" in reason.lower()
    assert len(sg.get_pending_confirmations()) == 0


def test_confirmation_session_authorization():
    """Verify that a confirmation bound to a session cannot be approved by an unauthorized session."""
    sg = SecurityGuard(auth=owner_auth)
    conf_id, event = sg.create_pending_confirmation(
        "reboot_system",
        {"force": True},
        RiskLevel.HIGH_RISK,
        session_id="authorized-session-123",
        user_id="authorized-user"
    )

    # Attacker authenticated as another user/session knowing confirmation_id cannot approve
    success_unauthorized = sg.submit_confirmation(
        conf_id,
        approved=True,
        session_id="attacker-session-456",
        user_id="attacker-user"
    )
    assert success_unauthorized is False
    assert not event.is_set()

    # Attacker attempting without session_id is also rejected
    assert sg.submit_confirmation(conf_id, approved=True, session_id=None, user_id="attacker-user") is False
    assert sg.submit_confirmation(conf_id, approved=True, session_id="authorized-session-123", user_id="attacker-user") is False

    # Legitimate authorized session and user succeeds
    success_authorized = sg.submit_confirmation(
        conf_id,
        approved=True,
        session_id="authorized-session-123",
        user_id="authorized-user"
    )
    assert success_authorized is True
    assert event.is_set()


def test_confirmation_expiry():
    """Verify expired confirmations are rejected and purged."""
    sg = SecurityGuard(auth=owner_auth)
    conf_id, event = sg.create_pending_confirmation(
        "delete_all",
        {"all": True},
        RiskLevel.HIGH_RISK,
        timeout_sec=0  # Expires immediately
    )
    time.sleep(0.01)

    # Submitting expired confirmation must fail
    res = sg.submit_confirmation(conf_id, approved=True)
    assert res is False

    # Pending list purges expired entries
    pending = sg.get_pending_confirmations()
    assert conf_id not in pending


# ─── 2. Real Task Interruption and Cancellation Tests ─────────────────────────

def test_task_real_interruption_and_dag_halting():
    """
    Start a multi-step task, trigger cancellation during step 1,
    verify step 2 never executes, and final task state is CANCELLED.
    """
    router = ToolRouter()
    step1_executed = threading.Event()
    step2_executed = threading.Event()

    def slow_step1():
        step1_executed.set()
        time.sleep(0.2)
        return "Step 1 done"

    def step2():
        step2_executed.set()
        return "Step 2 done"

    router.register_callable(slow_step1, name="slow_step1", category="custom")
    router.register_callable(step2, name="step2", category="custom")

    orchestrator = AssistantOrchestrator(tool_router=router)
    cancel_token = threading.Event()

    task = AssistantTask(
        user_request="Two step cancellation test",
        plan=[
            TaskStep(step_id="step_1", description="Step 1", capability="general", tool_name="slow_step1", input_variables={}, dependencies=[]),
            TaskStep(step_id="step_2", description="Step 2", capability="general", tool_name="step2", input_variables={}, dependencies=["step_1"]),
        ]
    )
    task._cancel_event = cancel_token

    # Launch cancellation in a separate thread once step 1 starts
    def trigger_cancel():
        step1_executed.wait(timeout=2.0)
        cancel_token.set()

    t = threading.Thread(target=trigger_cancel)
    t.start()

    res, _ = orchestrator._execute_plan_dag(task, "Two step cancellation test")
    t.join()

    assert step1_executed.is_set(), "Step 1 should have started"
    assert not step2_executed.is_set(), "Step 2 must NEVER execute after cancellation"
    assert task.status == TaskStatus.CANCELLED
    assert task.plan[1].status in (TaskStepStatus.CANCELLED, TaskStepStatus.SKIPPED)
    assert "cancelled" in res.lower()


def test_task_cancellation_idempotence():
    """Verify that multiple cancellation signals are completely idempotent."""
    task = AssistantTask(user_request="Test cancellation idempotence")
    assert task.status == TaskStatus.RECEIVED

    task.cancel("First cancel")
    assert task.status == TaskStatus.CANCELLED

    # Second cancel should not raise error and keep state CANCELLED
    task.cancel("Second cancel")
    assert task.status == TaskStatus.CANCELLED


# ─── 3. Safe Timeout Policy and Worker Isolation Tests ───────────────────────

def test_tool_safe_timeout_and_explicit_timed_out_state():
    """Verify that timing out sets status TIMED_OUT, timed_out=True, never success, and records cleanup."""
    router = ToolRouter()

    def slow_uncooperative_tool():
        time.sleep(0.5)
        return "Finished late"

    contract = ToolContract(
        name="slow_tool",
        description="A tool that takes too long",
        category="custom",
        callable=slow_uncooperative_tool,
        timeout_seconds=0.1
    )
    router.register_contract(contract)

    # Timeout after 0.1 seconds
    res = router.execute_tool("slow_tool", {}, interactive=False)

    assert res.success is False
    assert res.status == "TIMED_OUT"
    assert res.timed_out is True
    assert res.cleanup_succeeded is True
    assert "timed out" in str(res.error).lower()


def test_tool_cooperative_cancellation():
    """Verify cooperative tools receive cancellation token and stop safely."""
    router = ToolRouter()

    def cooperative_tool(cancellation_token=None):
        for _ in range(50):
            if cancellation_token and cancellation_token.is_set():
                return "Aborted cooperatively"
            time.sleep(0.01)
        return "Finished"

    router.register_callable(cooperative_tool, name="coop_tool", category="custom")

    cancel_token = threading.Event()
    cancel_token.set()

    res = router.execute_tool("coop_tool", {}, interactive=False, cancellation_token=cancel_token)
    assert res.status == "CANCELLED"
    assert res.success is False


def test_worker_pool_recycling_prevents_worker_corruption():
    """Verify that timing out recycles the worker pool so subsequent tools execute normally."""
    router = ToolRouter()

    def blocking_tool():
        time.sleep(0.5)
        return "Late"

    def fast_tool():
        return "Fast success"

    contract_slow = ToolContract(name="blocking_tool", description="Slow", category="custom", callable=blocking_tool, timeout_seconds=0.1)
    contract_fast = ToolContract(name="fast_tool", description="Fast", category="custom", callable=fast_tool, timeout_seconds=5)
    router.register_contract(contract_slow)
    router.register_contract(contract_fast)

    # First tool times out
    res1 = router.execute_tool("blocking_tool", {}, interactive=False)
    assert res1.status == "TIMED_OUT"

    # Subsequent tool executes cleanly in recycled worker pool without being blocked
    res2 = router.execute_tool("fast_tool", {}, interactive=False)
    assert res2.success is True
    assert res2.status == "COMPLETED"
    assert res2.output == "Fast success"


# ─── 4. Memory Persistence Store Policy Tests ────────────────────────────────

def test_memory_store_true_persists_interaction():
    """store=True writes the interaction to conversational memory."""
    mem = JarvisMemory()
    mem_mgr = MemoryManager(memory=mem)

    orchestrator = AssistantOrchestrator(memory_manager=mem_mgr)
    task = AssistantTask(user_request="Hello Jarvis, what is the plan today?", user_id="test_user")
    ctx = ExecutionContext(store_memory=True, user_id="test_user")

    orchestrator._handle_memory_persistence(task, "Today we focus on hardening.", execution_context=ctx)
    recent = mem.conversations.get_recent(2, user_id="test_user")
    assert len(recent) >= 2
    assert recent[-1]["content"] == "Today we focus on hardening."
    assert "plan today" in recent[-2]["content"]


def test_memory_store_false_leaves_conversational_memory_unchanged():
    """store=False strictly prevents interaction and task content from writing to memory."""
    mem = JarvisMemory()
    mem_mgr = MemoryManager(memory=mem)
    last_turn_before = mem.conversations.get_recent(1, user_id="test_user")
    initial_facts = mem._json_store.count(user_id="test_user")

    orchestrator = AssistantOrchestrator(memory_manager=mem_mgr)
    task = AssistantTask(user_request="Remember that my secret code is ALPHA-999", user_id="test_user")
    ctx = ExecutionContext(store_memory=False, user_id="test_user")

    orchestrator._handle_memory_persistence(task, "Acknowledged secret code.", execution_context=ctx)
    last_turn_after = mem.conversations.get_recent(1, user_id="test_user")
    assert last_turn_before == last_turn_after, "Conversational memory must remain unchanged when store=False"
    assert mem._json_store.count(user_id="test_user") == initial_facts, "Long-term facts must remain unchanged when store=False"


# ─── 5. Custom Tool Quarantine & Validation Pipeline Tests ───────────────────

def test_quarantine_rejects_syntax_error():
    """Verify syntax-broken tool source is rejected and quarantined."""
    broken_source = '''
def bad_syntax_tool():
    print("Unclosed string)
'''
    valid, reason, tree = validate_tool_source(broken_source)
    assert valid is False
    assert "syntax error" in reason.lower()

    router = ToolRouter()
    success, res_reason = process_and_register_generated_tool(broken_source, router)
    assert success is False
    assert "bad_syntax_tool" not in router._registry


def test_quarantine_rejects_dangerous_patterns():
    """Verify dangerous calls like os.system or __import__ are blocked by static checks."""
    dangerous_source = '''
import os

def malicious_tool():
    """Run malicious command."""
    os.system("echo hacked")
    return "done"
'''
    valid, reason, _ = validate_tool_source(dangerous_source)
    assert valid is False
    assert "security violation" in reason.lower() or "dangerous call" in reason.lower()


def test_quarantine_registers_valid_tool():
    """Verify a syntactically valid and safe tool passes quarantine and registers."""
    valid_source = '''
def calculate_area(width: int, height: int) -> int:
    """Calculate the area of a rectangle.
    
    Args:
        width: Width of the rectangle.
        height: Height of the rectangle.
    """
    return width * height
'''
    router = ToolRouter()
    success, reason = process_and_register_generated_tool(valid_source, router)
    assert success is True
    assert "calculate_area" in router._registry

    def auto_approve(tool_name, args, risk):
        return True, "Approved in test"

    guard.register_confirmation_handler(auto_approve)

    res = router.execute_tool("calculate_area", {"width": 5, "height": 10}, interactive=True)
    assert res.success is True
    assert res.output == 50


# ─── 6. Background Worker Thread-Safe Event Delivery Bridge ──────────────────

def test_background_worker_safe_broadcast_delivery():
    """
    Verify safe_broadcast transmits events from worker threads to active WebSocket connections
    without relying on asyncio.get_event_loop() in worker threads.
    """
    async def _run():
        from api.ws_manager import ws_manager

        loop = asyncio.get_running_loop()
        ws_manager.set_main_loop(loop)

        received_messages = []

        mock_ws = MagicMock()
        async def mock_accept():
            pass
        async def mock_send_json(data):
            received_messages.append(data)

        mock_ws.accept = mock_accept
        mock_ws.send_json = mock_send_json

        await ws_manager.connect(mock_ws)

        def worker_dispatch():
            ws_manager.safe_broadcast({
                "type": "WORKER_EVENT",
                "source": "background_thread_1",
                "payload": "status_ok"
            })

        t = threading.Thread(target=worker_dispatch)
        t.start()
        t.join()

        await asyncio.sleep(0.05)
        ws_manager.disconnect(mock_ws)

        worker_events = [m for m in received_messages if m.get("type") == "WORKER_EVENT"]
        assert len(worker_events) == 1
        assert worker_events[0]["payload"] == "status_ok"

    asyncio.run(_run())


# ─── 7. Phase 3.6.1 Targeted Hardening Tests ──────────────────────────────────

def test_no_cross_session_cancel():
    """
    Verify cross-session cancellation safety:
    Cancelling session A cancels task A, but leaves session B running.
    Attempting to cancel an unknown session returns False and cancels nothing.
    """
    from api.ws_manager import WebSocketManager
    mgr = WebSocketManager()

    task_a = AssistantTask(user_request="Task A")
    task_b = AssistantTask(user_request="Task B")

    mgr.register_active_task("session-A", task_a)
    mgr.register_active_task("session-B", task_b)

    # Cancel unknown session
    res_unknown = mgr.cancel_active_task("unknown-session")
    assert res_unknown is False
    assert not task_a.is_cancelled
    assert not task_b.is_cancelled

    # Cancel session A
    res_a = mgr.cancel_active_task("session-A", reason="User cancel A")
    assert res_a is True
    assert task_a.is_cancelled
    assert task_a.status == TaskStatus.CANCELLED

    # Session B MUST still be running (not cancelled)
    assert not task_b.is_cancelled
    assert task_b.status == TaskStatus.RECEIVED


def test_session_affine_tool_blocks_concurrent_overlap():
    """
    Verify that session-affine tools (browser/desktop) block concurrent replacement/overlap
    on the SAME session if a previous operation is still active.
    """
    router = ToolRouter()

    block_event = threading.Event()
    def slow_browser_op(*args, **kwargs):
        block_event.wait(timeout=2.0)
        return "Browser finished"

    contract = ToolContract(
        name="open_url",
        description="Browser op",
        category="browser",
        callable=slow_browser_op,
        timeout_seconds=0.1
    )
    router.register_contract(contract)

    from core.brain.task_model import current_execution_context
    token_sess1 = current_execution_context.set(ExecutionContext(session_id="session-1"))

    # Execute first call - it will time out because block_event is not set
    res1 = router.execute_tool("open_url", {"url": "https://example.com"}, interactive=False)
    assert res1.status == "TIMED_OUT"
    assert res1.timed_out is True

    # Now while slow_browser_op is STILL in the thread pool running,
    # attempting a second call on the SAME session MUST be BLOCKED!
    res2 = router.execute_tool("open_url", {"url": "https://example.com"}, interactive=False)
    assert res2.status == "BLOCKED"
    assert res2.success is False
    assert "still active" in res2.error

    current_execution_context.reset(token_sess1)
    block_event.set()


def test_tool_success_semantics_error_vs_verified():
    """
    Verifies:
    - Web fetch failure (returns error string) -> success=False, status='FAILED'
    - Browser navigation failure (returns error string) -> success=False, status='FAILED'
    - App launch verification failure (app does not exist) -> success=False, status='FAILED'
    - Web fetch success (valid content) -> success=True, status='COMPLETED'
    - Value-based success (custom tool returning 0, False, empty list) -> success=True, status='COMPLETED'
    """
    router = ToolRouter()

    # 1. Web fetch failure
    def mock_fetch_failure(url: str):
        return "Error fetching webpage: HTTP 404 Not Found"
    router.register_callable(mock_fetch_failure, name="fetch_webpage", category="web")
    res_web_fail = router.execute_tool("fetch_webpage", {"url": "https://bad.example.com"}, interactive=False)
    assert res_web_fail.success is False
    assert res_web_fail.status == "FAILED"
    assert "error" in res_web_fail.error.lower() or "error fetching webpage" in str(res_web_fail.output).lower()

    # 2. Browser navigation failure
    def mock_browser_fail(url: str):
        return "Error opening URL 'bad://url': Invalid URL"
    router.register_callable(mock_browser_fail, name="open_url", category="browser")
    res_b_fail = router.execute_tool("open_url", {"url": "bad://url"}, interactive=False)
    assert res_b_fail.success is False
    assert res_b_fail.status == "FAILED"
    assert "browser operation failed" in res_b_fail.error.lower() or "error opening url" in str(res_b_fail.output).lower()

    # 3. App launch verification failure
    def mock_launch_nonexistent(app_name: str):
        return f"Launched '{app_name}' successfully."
    router.register_callable(mock_launch_nonexistent, name="open_application", category="automation")
    res_app_fail = router.execute_tool("open_application", {"app_name": "totally_nonexistent_process_xyz123"}, interactive=False)
    assert res_app_fail.success is False
    assert res_app_fail.status == "FAILED"
    assert "no active process" in res_app_fail.error.lower() or "failed verification" in res_app_fail.error.lower() or "not found" in res_app_fail.error.lower()

    # 4. Web fetch success
    def mock_fetch_success(url: str):
        return "This is a legitimate webpage content with sufficient text length to verify successfully."
    router.register_callable(mock_fetch_success, name="fetch_webpage_ok", category="web")
    res_web_ok = router.execute_tool("fetch_webpage_ok", {"url": "https://good.example.com"}, interactive=False)
    assert res_web_ok.success is True
    assert res_web_ok.status == "COMPLETED"

    # 5. Value-based success (0, False, empty list)
    def calc_zero():
        return 0
    def return_false():
        return False
    def return_empty_list():
        return []
    router.register_callable(calc_zero, name="calc_zero", category="custom")
    router.register_callable(return_false, name="return_false", category="custom")
    router.register_callable(return_empty_list, name="return_empty_list", category="custom")

    assert router.execute_tool("calc_zero", {}, interactive=False).success is True
    assert router.execute_tool("return_false", {}, interactive=False).success is True
    assert router.execute_tool("return_empty_list", {}, interactive=False).success is True


def test_custom_tool_security_ast_rejects_forbidden_patterns(tmp_path):
    """
    P0-4 Strict AST Allowlist Validation:
    Verify AST rejects at minimum:
    open(".env"), import os, pathlib, subprocess, ctypes, socket, urllib, requests,
    importlib, pickle, sys, shutil, getattr, globals, locals, vars, __builtins__,
    importlib.import_module, getattr(os, "system"), __builtins__["eval"].
    Verify rejected tools are NEVER registered into live ToolRouter.
    Verify valid pure-computation tool passes and registers.
    """
    forbidden_snippets = [
        ("open_env", "def read_env():\n    '''read env'''\n    return open('.env').read()"),
        ("import_os", "import os\ndef get_dir():\n    '''dir'''\n    return os.listdir('.')"),
        ("import_pathlib", "import pathlib\ndef p_read():\n    '''path'''\n    return pathlib.Path('.').name"),
        ("import_subprocess", "import subprocess\ndef run_cmd():\n    '''cmd'''\n    return subprocess.run(['ls'])"),
        ("import_ctypes", "import ctypes\ndef mem_hack():\n    '''hack'''\n    return ctypes.CDLL(None)"),
        ("import_socket", "import socket\ndef net_call():\n    '''net'''\n    return socket.socket()"),
        ("import_urllib", "import urllib.request\ndef fetch():\n    '''fetch'''\n    return urllib.request.urlopen('http://x')"),
        ("import_requests", "import requests\ndef get_site():\n    '''site'''\n    return requests.get('http://x')"),
        ("import_importlib", "import importlib\ndef dyn_imp():\n    '''imp'''\n    return importlib.import_module('os')"),
        ("import_pickle", "import pickle\ndef unpick(b):\n    '''pickle'''\n    return pickle.loads(b)"),
        ("import_sys", "import sys\ndef get_sys():\n    '''sys'''\n    return sys.modules"),
        ("import_shutil", "import shutil\ndef wipe_dir():\n    '''wipe'''\n    return shutil.rmtree('/tmp')"),
        ("getattr_call", "def get_attr(obj):\n    '''attr'''\n    return getattr(obj, 'secret')"),
        ("globals_call", "def get_glob():\n    '''glob'''\n    return globals()"),
        ("locals_call", "def get_loc():\n    '''loc'''\n    return locals()"),
        ("vars_call", "def get_vars(obj):\n    '''vars'''\n    return vars(obj)"),
        ("builtins_ref", "def get_bi():\n    '''bi'''\n    return __builtins__"),
        ("import_module_dynamic", "def dyn_call():\n    '''dyn'''\n    import importlib\n    return importlib.import_module('math')"),
        ("getattr_os_system", "def hack_sys():\n    '''sys'''\n    return getattr(os, 'system')('echo 1')"),
        ("subclasses_escape", "def escape():\n    '''escape'''\n    return object.__subclasses__()"),
        ("reflection_getattribute_class", 'def probe():\n    """Probe."""\n    return object.__getattribute__((), "__class__")'),
        ("reflection_getattribute_mro", 'def probe():\n    """Probe."""\n    x = object.__getattribute__((), "__class__")\n    return object.__getattribute__(x, "__mro__")'),
        ("reflection_format_string_class", 'def probe():\n    """Probe."""\n    return "{0.__class__}".format(())'),
        ("reflection_concatenation_exact", 'def probe():\n    """Probe."""\n    fmt = "{0." + "__" + "class__}"\n    return fmt.format(())'),
        ("reflection_concatenation_chained", 'def probe():\n    """Probe."""\n    a = "{0."\n    b = "__"\n    c = "class__}"\n    fmt = a + b + c\n    return fmt.format(())'),
        ("reflection_concatenation_join", 'def probe():\n    """Probe."""\n    fmt = "".join(["{0.", "__", "class__}"])\n    return fmt.format(())'),
        ("reflection_format_mro_concat", 'def probe():\n    """Probe."""\n    return ("{" + "0.__mro__}").format(())'),
        ("reflection_variable_join_exact", 'def probe():\n    """Probe."""\n    parts = ["{0.", "__", "class__}"]\n    fmt = "".join(parts)\n    return fmt.format(())'),
        ("reflection_variable_join_tuple", 'def probe():\n    """Probe."""\n    parts = ("{0.", "__", "mro__}")\n    fmt = "".join(parts)\n    return fmt.format(())'),
        ("reflection_variable_sep_join", 'def probe():\n    """Probe."""\n    sep = ""\n    parts = ["{0.", "__class__}"]\n    fmt = sep.join(parts)\n    return fmt.format(())'),
        ("reflection_dynamic_format_unvalidated", 'def probe(user_fmt):\n    """Probe."""\n    return user_fmt.format(())'),
        ("direct_dunder_class", 'def probe():\n    """Probe."""\n    return ().__class__'),
    ]

    custom_dir = tmp_path / "custom"
    quarantine_dir = tmp_path / "quarantine"
    custom_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    router = ToolRouter()
    initial_count = router.tool_count

    for name, code in forbidden_snippets:
        valid, reason, _ = validate_tool_source(code)
        assert not valid, f"Code with {name} must be rejected by AST validation"
        assert "security violation" in reason.lower() or "forbidden" in reason.lower() or "not in the allowed" in reason.lower()

        # Full quarantine pipeline must reject and not register
        ok, res_msg = process_and_register_generated_tool(code, router, custom_dir=custom_dir, quarantine_dir=quarantine_dir)
        assert not ok, f"Tool with {name} must fail quarantine pipeline"
        assert router.tool_count == initial_count, f"Rejected tool {name} must NEVER be registered"

    # Valid pure-computation tool passes and registers
    safe_code = '''import math

def calculate_hypotenuse(a: float, b: float) -> float:
    """Calculates hypotenuse of a right-angled triangle using Pythagorean theorem."""
    return math.hypot(a, b)
'''
    valid, _, meta = validate_tool_source(safe_code)
    assert valid is True
    assert meta["function_name"] == "calculate_hypotenuse"

    # Successfully registers into ToolRouter
    ok, report = process_and_register_generated_tool(safe_code, router, custom_dir=custom_dir, quarantine_dir=quarantine_dir)
    assert ok is True
    assert router.tool_count == initial_count + 1
    tool_schema = router.get_tool("calculate_hypotenuse")
    assert tool_schema is not None
    tool_schema.risk_level = RiskLevel.SAFE
    res = router.execute_tool("calculate_hypotenuse", {"a": 3.0, "b": 4.0}, interactive=False)
    assert res.success is True
    assert res.output == 5.0


def test_execution_context_lifecycle_isolation():
    """
    P1-7 Context Lifecycle:
    Ensure current_execution_context is set during execution,
    and reliably reset in finally blocks across sync, async, and error scenarios.
    """
    from core.brain.task_model import current_execution_context, ExecutionContext
    from core.brain.assistant_orchestrator import AssistantOrchestrator

    orch = AssistantOrchestrator()
    assert current_execution_context.get() is None

    # Test sync execution
    ctx = ExecutionContext(session_id="test_sess_lifecycle", user_id="test_user")
    orch.process("Hello world", context=ctx)
    # Context must be reset back to None
    assert current_execution_context.get() is None

    # Test async streaming execution
    import asyncio
    async def _test_stream():
        ctx_stream = ExecutionContext(session_id="test_stream_lifecycle", user_id="test_user")
        async for _ in orch.process_stream("Hello stream", context=ctx_stream):
            pass
        assert current_execution_context.get() is None

    asyncio.run(_test_stream())
    assert current_execution_context.get() is None


def test_task_status_truth_mappings():
    """
    P0-6 & P1-6 Task Status Truth:
    Derive the response from actual AssistantTask status:
    COMPLETED -> completed=true, status="success"
    CANCELLED -> false, "cancelled"
    FAILED -> false, "failed"
    WAITING_FOR_INPUT -> false, "waiting_for_input"
    WAITING_FOR_CONFIRMATION -> false, "waiting_for_confirmation"
    TIMED_OUT -> false, "timed_out"
    Unknown or non-terminal states must NEVER default to success.
    """
    from core.brain.task_model import TaskStatus, map_task_status_to_api

    # 1. Authoritative truth mappings
    assert map_task_status_to_api(TaskStatus.COMPLETED) == (True, "success")
    assert map_task_status_to_api(TaskStatus.CANCELLED) == (False, "cancelled")
    assert map_task_status_to_api(TaskStatus.FAILED) == (False, "failed")
    assert map_task_status_to_api(TaskStatus.WAITING_FOR_INPUT) == (False, "waiting_for_input")
    assert map_task_status_to_api(TaskStatus.WAITING_FOR_CONFIRMATION) == (False, "waiting_for_confirmation")
    assert map_task_status_to_api(TaskStatus.TIMED_OUT) == (False, "timed_out")

    # 2. Cancellation flag override
    assert map_task_status_to_api(TaskStatus.COMPLETED, is_cancelled=True) == (False, "cancelled")
    assert map_task_status_to_api(TaskStatus.EXECUTING, is_cancelled=True) == (False, "cancelled")

    # 3. Non-terminal and missing states must NEVER default to success
    assert map_task_status_to_api(TaskStatus.PLANNING) == (False, "failed")
    assert map_task_status_to_api(TaskStatus.EXECUTING) == (False, "failed")
    assert map_task_status_to_api(TaskStatus.RECEIVED) == (False, "failed")
    assert map_task_status_to_api(None) == (False, "failed")


def test_multiple_active_tasks_independence():
    """
    P1-8 Multiple Active Tasks:
    Sessions A and B both running keep independent state;
    cancelling A never changes or affects B.
    """
    from api.ws_manager import WebSocketManager
    from core.brain.task_model import AssistantTask, TaskStatus

    mgr = WebSocketManager()
    task_a = AssistantTask(user_request="Task A Session")
    task_b = AssistantTask(user_request="Task B Session")

    mgr.register_active_task("session_alpha", task_a, task_id="task_alpha", user_id="user_alpha")
    mgr.register_active_task("session_beta", task_b, task_id="task_beta", user_id="user_beta")

    assert mgr.get_active_task("session_alpha") == task_a
    assert mgr.get_active_task("session_beta") == task_b
    assert not task_a.is_cancelled
    assert not task_b.is_cancelled

    # Cancel session alpha
    cancelled = mgr.cancel_active_task("session_alpha", reason="User cancel alpha")
    assert cancelled is True
    assert task_a.is_cancelled
    assert task_a.status == TaskStatus.CANCELLED

    # Session beta must remain uncancelled and healthy
    assert not task_b.is_cancelled
    assert task_b.status == TaskStatus.RECEIVED
    assert mgr.get_active_task("session_beta") == task_b


def test_orchestrator_task_registry_lifecycle_and_cross_session_isolation():
    """
    P0-2 Task Registry Lifecycle:
    - a completed task leaves no stale registry entries
    - a failed task leaves no stale active entry
    - cancelling a task in Session A does not change Session B
    - Session B issuing 'stop' without owning an active task cannot cancel Session A
    - early returns and exceptions do not leave unintended active-task references
    """
    from core.brain.assistant_orchestrator import AssistantOrchestrator
    from core.brain.task_model import ExecutionContext, AssistantTask, TaskStatus, current_execution_context
    from core.brain.tool_router import ToolRouter

    orch = AssistantOrchestrator()

    # 1. Completed task leaves zero stale registry entries
    ctx1 = ExecutionContext(session_id="sess_complete", request_id="req_complete")
    orch.process("what time is it", context=ctx1)
    tok1 = current_execution_context.set(ctx1)
    try:
        assert orch.active_task is None
        assert "req_complete" not in orch._request_active_tasks
        assert "sess_complete" not in orch._session_active_tasks
    finally:
        current_execution_context.reset(tok1)

    # 2. Failed plan validation task leaves zero stale active entries
    class FailingValidationOrch(AssistantOrchestrator):
        def _create_plan(self, *args, **kwargs):
            from core.brain.task_model import TaskStep
            # Empty invalid tool step to trigger plan validation failure
            return [TaskStep(step_id="bad", description="bad step", tool_name="nonexistent_xyz_tool")]

    failing_orch = FailingValidationOrch()
    failing_orch.tool_router = ToolRouter()
    ctx_fail = ExecutionContext(session_id="sess_fail", request_id="req_fail")
    res_fail = failing_orch.process("do bad thing", context=ctx_fail)
    assert "could not form a safe execution plan" in res_fail
    tok_f = current_execution_context.set(ctx_fail)
    try:
        assert failing_orch.active_task is None
        assert "req_fail" not in failing_orch._request_active_tasks
        assert "sess_fail" not in failing_orch._session_active_tasks
    finally:
        current_execution_context.reset(tok_f)

    # 3. Cancelling a task in Session A does not change Session B
    task_a = AssistantTask(user_request="Task A", status=TaskStatus.EXECUTING)
    task_b = AssistantTask(user_request="Task B", status=TaskStatus.EXECUTING)
    ctx_a = ExecutionContext(session_id="session_A", request_id="req_A")
    ctx_b = ExecutionContext(session_id="session_B", request_id="req_B")

    orch._register_active_task(task_a, ctx_a)
    orch._register_active_task(task_b, ctx_b)

    # Verify lookups
    tok_a = current_execution_context.set(ctx_a)
    try:
        assert orch.active_task == task_a
    finally:
        current_execution_context.reset(tok_a)

    tok_b = current_execution_context.set(ctx_b)
    try:
        assert orch.active_task == task_b
    finally:
        current_execution_context.reset(tok_b)

    # Cancel task in Session A
    tok_a = current_execution_context.set(ctx_a)
    try:
        cancel_reply = orch.process("stop", context=ctx_a)
        assert "stopped the active task" in cancel_reply
        assert task_a.status == TaskStatus.CANCELLED
        assert orch.active_task is None
    finally:
        current_execution_context.reset(tok_a)

    # Session B task MUST be untouched and still active
    tok_b = current_execution_context.set(ctx_b)
    try:
        assert not task_b.is_cancelled
        assert task_b.status == TaskStatus.EXECUTING
        assert orch.active_task == task_b
    finally:
        current_execution_context.reset(tok_b)

    # 4. Session B issuing 'stop' without owning an active task cannot cancel Session A
    orch_cross = AssistantOrchestrator()
    task_live_a = AssistantTask(user_request="Running Live Task A", status=TaskStatus.EXECUTING)
    ctx_live_a = ExecutionContext(session_id="sess_live_a", request_id="req_live_a")
    ctx_empty_b = ExecutionContext(session_id="sess_empty_b", request_id="req_empty_b")

    orch_cross._register_active_task(task_live_a, ctx_live_a)

    # Session B says stop
    tok_eb = current_execution_context.set(ctx_empty_b)
    try:
        reply_b = orch_cross.process("stop", context=ctx_empty_b)
        assert reply_b == "There is no active task running, Sir."
    finally:
        current_execution_context.reset(tok_eb)

    # Session A task is STILL executing and active
    tok_la = current_execution_context.set(ctx_live_a)
    try:
        assert orch_cross.active_task == task_live_a
        assert task_live_a.status == TaskStatus.EXECUTING
        assert not task_live_a.is_cancelled
    finally:
        current_execution_context.reset(tok_la)

    # 5. Exception in execution unregisters active task
    class CrashingOrch(AssistantOrchestrator):
        def _execute_plan_dag(self, *args, **kwargs):
            raise ValueError("Crashing inside DAG loop")

    crash_orch = CrashingOrch()
    ctx_crash = ExecutionContext(session_id="sess_crash", request_id="req_crash")
    try:
        crash_orch.process("open notepad", context=ctx_crash)
    except ValueError:
        pass

    tok_c = current_execution_context.set(ctx_crash)
    try:
        assert crash_orch.active_task is None
        assert "req_crash" not in crash_orch._request_active_tasks
        assert "sess_crash" not in crash_orch._session_active_tasks
    finally:
        current_execution_context.reset(tok_c)


# ─── 8. Phase 3.6.4 Identity-Safe Task Registry Tests (P1-6) ──────────────────

def test_p1_6_active_task_setter_explicit_context_no_task_never_falls_back():
    """
    P1-6: active_task.setter with explicit session/request context but no matching task
    must be a no-op and NEVER unregister or touch the global fallback task.
    """
    from core.brain.assistant_orchestrator import AssistantOrchestrator
    from core.brain.task_model import ExecutionContext, AssistantTask, current_execution_context

    orch = AssistantOrchestrator()
    fallback_task = AssistantTask(user_request="Fallback CLI task")
    orch._fallback_active_task = fallback_task

    # Context with explicit session/request but no registered task
    empty_ctx = ExecutionContext(session_id="sess_empty_unknown", request_id="req_empty_unknown")
    tok = current_execution_context.set(empty_ctx)
    try:
        # Setting active_task to None in this empty context must NOT clear the global fallback task!
        orch.active_task = None
        assert orch._fallback_active_task is fallback_task, "Explicit context with no task must never wipe global fallback"
    finally:
        current_execution_context.reset(tok)


def test_p1_6_identity_safe_task_unregister_concurrent_same_session():
    """
    P1-6: In the same session, task A unregistering must not remove task B's registry entry.
    """
    from core.brain.assistant_orchestrator import AssistantOrchestrator
    from core.brain.task_model import ExecutionContext, AssistantTask, current_execution_context
    from api.ws_manager import WebSocketManager

    orch = AssistantOrchestrator()
    ws_mgr = WebSocketManager()

    task_a = AssistantTask(task_id="task_A", session_id="shared_sess", request_id="req_A", user_request="Task A")
    task_b = AssistantTask(task_id="task_B", session_id="shared_sess", request_id="req_B", user_request="Task B")

    ctx_a = ExecutionContext(task_id="task_A", session_id="shared_sess", request_id="req_A")
    ctx_b = ExecutionContext(task_id="task_B", session_id="shared_sess", request_id="req_B")

    # Register task A, then task B in same session
    orch._register_active_task(task_a, ctx_a)
    ws_mgr.register_active_task("shared_sess", task_a, task_id="task_A")

    orch._register_active_task(task_b, ctx_b)
    ws_mgr.register_active_task("shared_sess", task_b, task_id="task_B")

    # Orchestrator session active task points to task_b now
    assert orch._session_active_tasks["shared_sess"] is task_b
    assert orch._request_active_tasks["req_A"] is task_a
    assert orch._request_active_tasks["req_B"] is task_b

    # Now task A unregisters (completes)
    orch._unregister_active_task(task_a)
    ws_mgr.unregister_active_task("task_A", task_obj=task_a)

    # Task A's request mapping is removed
    assert "req_A" not in orch._request_active_tasks
    assert "task_A" not in orch._active_tasks

    # BUT Task B's mappings must REMAIN intact!
    assert orch._request_active_tasks["req_B"] is task_b
    assert orch._active_tasks["task_B"] is task_b
    assert orch._session_active_tasks["shared_sess"] is task_b
    assert ws_mgr.get_active_task("shared_sess") is task_b
    assert ws_mgr.get_active_task("task_B") is task_b


def test_p1_6_identity_safe_task_unregister_different_sessions():
    """
    P1-6: Two concurrent tasks in different sessions: unregistering task A in Session 1
    cannot remove task B in Session 2.
    """
    from core.brain.assistant_orchestrator import AssistantOrchestrator
    from core.brain.task_model import ExecutionContext, AssistantTask
    from api.ws_manager import WebSocketManager

    orch = AssistantOrchestrator()
    ws_mgr = WebSocketManager()

    task_1 = AssistantTask(task_id="task_1", session_id="sess_1", request_id="req_1", user_request="Task 1")
    task_2 = AssistantTask(task_id="task_2", session_id="sess_2", request_id="req_2", user_request="Task 2")

    ctx_1 = ExecutionContext(task_id="task_1", session_id="sess_1", request_id="req_1")
    ctx_2 = ExecutionContext(task_id="task_2", session_id="sess_2", request_id="req_2")

    orch._register_active_task(task_1, ctx_1)
    orch._register_active_task(task_2, ctx_2)
    ws_mgr.register_active_task("sess_1", task_1, task_id="task_1")
    ws_mgr.register_active_task("sess_2", task_2, task_id="task_2")

    # Unregister task 1
    orch._unregister_active_task(task_1)
    ws_mgr.unregister_active_task("task_1", task_obj=task_1)

    # Session 1 is cleaned up
    assert "sess_1" not in orch._session_active_tasks
    assert "req_1" not in orch._request_active_tasks
    assert "task_1" not in orch._active_tasks

    # Session 2 is completely intact
    assert orch._session_active_tasks["sess_2"] is task_2
    assert orch._request_active_tasks["req_2"] is task_2
    assert orch._active_tasks["task_2"] is task_2
    assert ws_mgr.get_active_task("sess_2") is task_2


def test_p1_6_lifecycle_cleanup_completion_failure_cancellation():
    """
    P1-6: Verify that completion, failure, and cancellation all safely purge
    their own task registry entries without leaving leaks.
    """
    from core.brain.assistant_orchestrator import AssistantOrchestrator
    from core.brain.task_model import ExecutionContext, AssistantTask, TaskStatus, current_execution_context

    orch = AssistantOrchestrator()

    # 1. Completion cleanup
    task_comp = AssistantTask(task_id="t_comp", session_id="s_comp", request_id="r_comp", user_request="Comp")
    ctx_comp = ExecutionContext(task_id="t_comp", session_id="s_comp", request_id="r_comp")
    orch._register_active_task(task_comp, ctx_comp)
    task_comp.transition_to(TaskStatus.COMPLETED)
    orch._unregister_active_task(task_comp)
    assert "t_comp" not in orch._active_tasks
    assert "s_comp" not in orch._session_active_tasks
    assert "r_comp" not in orch._request_active_tasks

    # 2. Failure cleanup
    task_fail = AssistantTask(task_id="t_fail", session_id="s_fail", request_id="r_fail", user_request="Fail")
    ctx_fail = ExecutionContext(task_id="t_fail", session_id="s_fail", request_id="r_fail")
    orch._register_active_task(task_fail, ctx_fail)
    task_fail.transition_to(TaskStatus.FAILED)
    orch._unregister_active_task(task_fail)
    assert "t_fail" not in orch._active_tasks
    assert "s_fail" not in orch._session_active_tasks
    assert "r_fail" not in orch._request_active_tasks

    # 3. Cancellation cleanup
    task_cancel = AssistantTask(task_id="t_cancel", session_id="s_cancel", request_id="r_cancel", user_request="Cancel")
    ctx_cancel = ExecutionContext(task_id="t_cancel", session_id="s_cancel", request_id="r_cancel")
    orch._register_active_task(task_cancel, ctx_cancel)
    task_cancel.cancel("User cancel")
    orch._unregister_active_task(task_cancel)
    assert "t_cancel" not in orch._active_tasks
    assert "s_cancel" not in orch._session_active_tasks
    assert "r_cancel" not in orch._request_active_tasks


# ─── P0-1: format_map() Reflection Bypass Regression Tests ────────────────────

def test_custom_tool_security_ast_rejects_reflection_format_map_chr_map_exact():
    """
    P0-1 Regression: The exact dynamic format_map chr/map reflection probe must be rejected.
    def probe():
        fmt = "".join(map(chr, [123, 120, 46, 95, 95, 99, 108, 97, 115, 115, 95, 95, 125]))
        return fmt.format_map({"x": ()})
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code = '''def probe():
    """Probe function."""
    fmt = "".join(map(chr, [
        123, 120, 46, 95, 95, 99, 108,
        97, 115, 115, 95, 95, 125
    ]))
    return fmt.format_map({"x": ()})
'''
    valid, reason, _ = validate_tool_source(code)
    assert not valid
    assert "reflective" in reason.lower() or "dunder" in reason.lower() or "format_map" in reason.lower()


def test_custom_tool_security_ast_rejects_reflection_format_map_constant_dunder():
    """
    P0-1 Regression: Constant format_map with dunder field access must be rejected.
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code = '''def probe():
    """Probe constant format_map."""
    return "{x.__class__}".format_map({"x": ()})
'''
    valid, reason, _ = validate_tool_source(code)
    assert not valid
    assert "reflective" in reason.lower() or "dunder" in reason.lower()


def test_custom_tool_security_ast_rejects_reflection_format_map_variable_dunder():
    """
    P0-1 Regression: Variable-based format_map with dunder field access must be rejected.
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code = '''def probe():
    """Probe variable format_map."""
    fmt = "{x." + "__class__" + "}"
    return fmt.format_map({"x": ()})
'''
    valid, reason, _ = validate_tool_source(code)
    assert not valid
    assert "reflective" in reason.lower() or "dunder" in reason.lower()


def test_custom_tool_security_ast_rejects_reflection_format_map_dynamic_unvalidated():
    """
    P0-1 Regression: format_map called on dynamic or unvalidated format string must fail closed.
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code = '''def probe(f: str):
    """Probe dynamic format_map."""
    return f.format_map({"x": 1})
'''
    valid, reason, _ = validate_tool_source(code)
    assert not valid
    assert "format_map" in reason.lower() and "unvalidated" in reason.lower()


def test_custom_tool_security_ast_allows_safe_format_map_pure_computation():
    """
    P0-1: Safe formatting without reflection must be accepted and execute cleanly.
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code = '''def greet_user(first_name: str, last_name: str) -> str:
    """Safely format a greeting message without reflection."""
    template = "Hello, {first_name} {last_name}!"
    return template.format_map({"first_name": first_name, "last_name": last_name})
'''
    valid, reason, meta = validate_tool_source(code)
    assert valid, f"Expected valid, got error: {reason}"
    assert meta["function_name"] == "greet_user"


def test_quarantine_rejects_format_map_reflection_never_registered(tmp_path):
    """
    P0-1: Rejected format_map reflection probe must be quarantined and never registered in ToolRouter.
    """
    from core.brain.custom_tool_pipeline import process_and_register_generated_tool
    from core.brain.tool_router import ToolRouter

    router = ToolRouter()
    code = '''def malicious_format_map_tool():
    """Attempts format_map reflection escape."""
    fmt = "".join(map(chr, [123, 120, 46, 95, 95, 99, 108, 97, 115, 115, 95, 95, 125]))
    return fmt.format_map({"x": ()})
'''
    custom_dir = tmp_path / "custom"
    quarantine_dir = tmp_path / "quarantine"

    success, msg = process_and_register_generated_tool(
        code,
        router,
        custom_dir=custom_dir,
        quarantine_dir=quarantine_dir
    )
    assert not success
    assert "Quarantined" in msg
    assert "malicious_format_map_tool" not in router._registry
    assert not (custom_dir / "malicious_format_map_tool.py").exists()


# ─── P0-1 (Phase 3.6.7): string.Formatter Reflection API Closure Tests ─────────

def test_custom_tool_security_ast_rejects_exact_vformat_probe():
    """
    P0-1 Regression: The exact string.Formatter().vformat probe must be rejected.
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code = '''import string

def probe(fmt: str) -> str:
    """Probe dynamic formatting."""
    return string.Formatter().vformat(fmt, (), {"x": ()})
'''
    valid, reason, _ = validate_tool_source(code)
    assert not valid
    assert "vformat" in reason.lower() or "formatter" in reason.lower() or "forbidden" in reason.lower()


def test_custom_tool_security_ast_rejects_exact_get_field_probe():
    """
    P0-1 Regression: The exact string.Formatter().get_field probe must be rejected.
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code = '''import string

def probe(fmt: str):
    """Probe field access."""
    formatter = string.Formatter()
    return formatter.get_field(fmt, (), {})[0]
'''
    valid, reason, _ = validate_tool_source(code)
    assert not valid
    assert "formatter" in reason.lower() or "get_field" in reason.lower() or "forbidden" in reason.lower()


def test_custom_tool_security_ast_rejects_formatter_dynamic_field_names():
    """
    P0-1 Regression: Dynamic field names on Formatter methods must be rejected.
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code = '''import string

def probe(obj, field_name: str):
    """Probe dynamic field name resolution."""
    f = string.Formatter()
    return f.get_value(field_name, (obj,), {})
'''
    valid, reason, _ = validate_tool_source(code)
    assert not valid
    assert "formatter" in reason.lower() or "get_value" in reason.lower() or "forbidden" in reason.lower()


def test_custom_tool_security_ast_rejects_constant_dunder_format_fields():
    """
    P0-1 Regression: Constant format string with dunder access must be rejected.
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code = '''def probe():
    """Probe dunder format field."""
    return "{0.__class__.__base__}".format(1)
'''
    valid, reason, _ = validate_tool_source(code)
    assert not valid
    assert "reflective" in reason.lower() or "dunder" in reason.lower()


def test_custom_tool_security_ast_rejects_variable_constructed_format_strings():
    """
    P0-1 Regression: Variable-constructed format strings attempting reflection must be rejected.
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code = '''def probe():
    """Probe variable-constructed format string."""
    prefix = "{x."
    dunder = "__globals__"
    suffix = "}"
    fmt = prefix + dunder + suffix
    return fmt.format_map({"x": ()})
'''
    valid, reason, _ = validate_tool_source(code)
    assert not valid
    assert "reflective" in reason.lower() or "dunder" in reason.lower()


def test_custom_tool_security_ast_rejects_dynamic_imports_and_direct_dunder_access():
    """
    P0-1 Regression: Dynamic imports and direct dunder access must be rejected.
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code1 = '''def probe():
    """Probe dynamic import."""
    return __import__("os").system("whoami")
'''
    valid1, reason1, _ = validate_tool_source(code1)
    assert not valid1
    assert "forbidden" in reason1.lower() or "dunder" in reason1.lower()

    code2 = '''def probe():
    """Probe direct dunder access."""
    return ().__class__
'''
    valid2, reason2, _ = validate_tool_source(code2)
    assert not valid2
    assert "dunder" in reason2.lower()


def test_custom_tool_security_ast_allows_safe_literal_formatting():
    """
    P0-1: Safe literal formatting without reflection must be accepted.
    """
    from core.brain.custom_tool_pipeline import validate_tool_source

    code = '''def format_report(name: str, count: int) -> str:
    """Format report cleanly."""
    return "User {} has {} items".format(name, count)
'''
    valid, reason, meta = validate_tool_source(code)
    assert valid, f"Expected valid, got error: {reason}"
    assert meta["function_name"] == "format_report"


def test_quarantine_rejects_formatter_vformat_never_registered(tmp_path):
    """
    P0-1: Rejected vformat tool is quarantined and never enters live ToolRouter registry.
    """
    from core.brain.custom_tool_pipeline import process_and_register_generated_tool
    from core.brain.tool_router import ToolRouter

    router = ToolRouter()
    code = '''import string

def malicious_vformat_tool(fmt: str) -> str:
    """Probe vformat reflection."""
    return string.Formatter().vformat(fmt, (), {"x": ()})
'''
    custom_dir = tmp_path / "custom"
    quarantine_dir = tmp_path / "quarantine"

    success, msg = process_and_register_generated_tool(
        code,
        router,
        custom_dir=custom_dir,
        quarantine_dir=quarantine_dir
    )
    assert not success
    assert "Quarantined" in msg
    assert "malicious_vformat_tool" not in router._registry
    assert not (custom_dir / "malicious_vformat_tool.py").exists()




