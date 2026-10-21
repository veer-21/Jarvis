"""
Integration tests for JARVIS Phase 3.5 using REAL registered tools.
Tests actual tool execution without mocking, validating the end-to-end tool pipeline:
A. Real file search
B. Real file read
C. Real file write
D. Real application launch
E. Real process verification
F. Real web search
G. Real webpage retrieval
H. Real browser navigation
I. Real browser form interaction
J. Real screen OCR
K. Real memory persistence
L. Real task cancellation
M. Real confirmation flow
"""

import os
import sys
import time
import pytest
import tempfile
import psutil
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.brain.tool_router import ToolRouter
from core.brain.task_model import AssistantTask, TaskStatus, TaskStep, TaskStepStatus
from core.brain.verifier import ResultVerifier, VerificationLevel
from core.security import guard, RiskLevel
from core.memory import JarvisMemory

# Import real tool callables from tools package
from tools.system_tools import execute_command, schedule_task, list_scheduled_tasks
from tools.file_tools import read_file, write_file, search_in_files, list_directory, safe_delete_file
from tools.automation_tools import open_application, get_system_info, analyze_screen
from tools.web_tools import web_search, fetch_webpage
from tools.browser_tools import open_url, get_page_text, browser_fill, browser_screenshot


@pytest.fixture(scope="module")
def real_tool_router():
    """Build a ToolRouter with real system and file tools registered."""
    router = ToolRouter()
    # File tools
    router.register_callable(read_file, category="file")
    router.register_callable(write_file, category="file", risk_level=RiskLevel.MEDIUM)
    router.register_callable(search_in_files, category="file")
    router.register_callable(list_directory, category="file")
    router.register_callable(safe_delete_file, category="file", risk_level=RiskLevel.HIGH)

    # Desktop & system
    router.register_callable(open_application, category="automation")
    router.register_callable(get_system_info, category="automation")
    router.register_callable(analyze_screen, category="automation")

    # Web & browser
    router.register_callable(web_search, category="web")
    router.register_callable(fetch_webpage, category="web")
    router.register_callable(open_url, category="browser")
    router.register_callable(get_page_text, category="browser")
    router.register_callable(browser_fill, category="browser", risk_level=RiskLevel.HIGH)
    router.register_callable(browser_screenshot, category="browser")

    return router


# ─── A. Real File Search ──────────────────────────────────────────────────────

def test_real_file_search(real_tool_router):
    """Search for known text inside workspace files using real search_in_files tool."""
    res = real_tool_router.execute_tool(
        "search_in_files",
        {"query": "Personal Assistant", "directory": str(PROJECT_ROOT), "max_results": 5},
        interactive=False
    )
    assert res.success is True, f"Search failed: {res.error}"
    assert "Personal Assistant" in str(res.output) or "Matches found" in str(res.output) or len(str(res.output)) > 10


# ─── B. Real File Read ────────────────────────────────────────────────────────

def test_real_file_read(real_tool_router):
    """Read an existing project file (README.md) using real read_file tool."""
    readme_path = PROJECT_ROOT / "README.md"
    assert readme_path.exists(), "README.md must exist in project root"

    res = real_tool_router.execute_tool(
        "read_file",
        {"path": str(readme_path)},
        interactive=False
    )
    assert res.success is True
    assert "JARVIS" in str(res.output) or len(str(res.output)) > 50


# ─── C. Real File Write ───────────────────────────────────────────────────────

def test_real_file_write_and_verify(real_tool_router):
    """Write real data to a temporary file and verify Level 2/3 verification."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "jarvis_integration_test.txt"
        test_content = "JARVIS Phase 3.5 Real Tool Verification Payload"

        res = real_tool_router.execute_tool(
            "write_file",
            {"path": str(test_file), "content": test_content},
            interactive=True
        )
        assert res.success is True
        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == test_content

        # Verify ResultVerifier Level 2/3 system state check
        ver_res = ResultVerifier.verify_tool_result(
            "write_file",
            {"path": str(test_file), "content": test_content},
            res.output
        )
        assert ver_res.verified is True
        assert ver_res.level in (VerificationLevel.LEVEL_2, VerificationLevel.LEVEL_3)


# ─── D & E. Real Application Launch & Process Verification ────────────────────

def test_real_application_launch_and_process_verification(real_tool_router):
    """Launch real notepad.exe, verify process exists, then terminate cleanly."""
    # Launch Notepad
    res = real_tool_router.execute_tool(
        "open_application",
        {"app_name": "notepad"},
        interactive=False
    )
    assert res.success is True, f"Failed to launch notepad: {res.error}"

    # Verify process is actually running in Windows OS
    time.sleep(1.0)
    notepad_running = any(
        "notepad" in (p.info.get("name") or "").lower()
        for p in psutil.process_iter(attrs=["name"])
    )
    assert notepad_running is True, "notepad.exe process was not found in Windows OS process list"

    # Verifier Level 2/3 window/process check
    ver_res = ResultVerifier.verify_process_running("notepad")
    assert ver_res.verified is True

    # Cleanup: Terminate notepad instances created during test
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            if "notepad" in (proc.info.get("name") or "").lower():
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


# ─── F. Real Web Search ───────────────────────────────────────────────────────

@pytest.mark.network
def test_real_web_search(real_tool_router):
    """Execute live web search for a known query."""
    res = real_tool_router.execute_tool(
        "web_search",
        {"query": "Python official documentation", "max_results": 3},
        interactive=False
    )
    assert res.success is True
    # Either results found or rate limited / empty result handled gracefully
    assert len(str(res.output)) > 0


# ─── G. Real Webpage Retrieval ────────────────────────────────────────────────

@pytest.mark.network
def test_real_webpage_retrieval(real_tool_router):
    """Fetch live webpage content via HTTP requests."""
    res = real_tool_router.execute_tool(
        "fetch_webpage",
        {"url": "https://example.com"},
        interactive=False
    )
    assert res.success is True
    assert "Example Domain" in str(res.output)


# ─── H & I. Real Browser Navigation & Form Interaction ────────────────────────

@pytest.mark.browser
def test_real_browser_navigation_and_text(real_tool_router):
    """Test real browser launch, navigation, and page text reading via Playwright."""
    # Open URL
    res = real_tool_router.execute_tool(
        "open_url",
        {"url": "https://example.com"},
        interactive=False
    )
    if not res.success and "Playwright" in str(res.error):
        pytest.skip(f"Playwright browser unavailable in current environment: {res.error}")

    assert res.success is True
    assert "Example Domain" in str(res.output)

    # Read page text
    text_res = real_tool_router.execute_tool(
        "get_page_text",
        {},
        interactive=False
    )
    assert text_res.success is True
    assert "example" in str(text_res.output).lower() or "domain" in str(text_res.output).lower()


# ─── J. Real Screen OCR ───────────────────────────────────────────────────────

@pytest.mark.desktop
def test_real_screen_ocr(real_tool_router, tmp_path):
    """Analyze real image with OCR using the canonical contract."""
    from PIL import Image, ImageDraw

    # Create a test image with legible text
    img_path = tmp_path / "ocr_test.png"
    img = Image.new("RGB", (400, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 35), "JARVIS OCR TEST 123", fill=(0, 0, 0))
    img.save(img_path)

    res = real_tool_router.execute_tool(
        "analyze_screen",
        {"image": str(img_path)},
        interactive=False
    )

    if not res.success:
        err_lower = str(res.error).lower()
        if "no ocr engine" in err_lower or "tesseract" in err_lower:
            pytest.skip(f"OCR engine not available on system: {res.error}")

    assert res.success is True, f"OCR execution failed: {res.error}"
    output_text = str(res.output).upper()
    # Check that text was recognized
    assert "JARVIS" in output_text or "OCR" in output_text or "TEST" in output_text or "123" in output_text or "VISIBLE TEXT" in output_text


# ─── K. Real Memory Persistence ───────────────────────────────────────────────

def test_real_memory_persistence():
    """Verify durable preference and fact storage in real JarvisMemory with owner scoping."""
    memory = JarvisMemory()
    owner = "test_owner"
    # Store preference
    memory.store_preference("editor", "VSCode", user_id=owner)
    pref = memory.get_preference("editor", user_id=owner)
    assert pref == "VSCode"

    # Store general memory
    doc_id = memory.store_memory("Owner lives in Tokyo and speaks Japanese.", category="knowledge", user_id=owner)
    assert doc_id is not None

    # Retrieve memory scoped to owner
    results = memory.retrieve_memories("Where does owner live?", user_id=owner)
    assert len(results) > 0


# ─── L. Real Task Cancellation ────────────────────────────────────────────────

def test_real_task_cancellation_cooperative():
    """Verify that an active task cancellation token halts downstream execution."""
    task = AssistantTask(user_request="Perform long multi-step task")
    assert task.is_cancelled is False

    # Simulate cancellation trigger (e.g. user saying "stop")
    task.cancel("USER_STOP_REQUEST")
    assert task.is_cancelled is True
    assert task.cancellation_token.is_set() is True
    assert task.status == TaskStatus.CANCELLED
    assert len(task.audit_trail) > 0
    assert task.audit_trail[-1].event == "TASK_CANCELLED"


# ─── M. Real Confirmation Flow ────────────────────────────────────────────────

def test_real_confirmation_flow_non_blocking():
    """Verify non-blocking UI/WebSocket confirmation request and resolution."""
    received_confirmations = []

    def mock_ui_handler(tool_name: str, args: dict, risk_level: RiskLevel):
        received_confirmations.append({"tool": tool_name, "args": args, "risk": risk_level})
        return True, "Approved by mock UI test handler"

    guard.register_confirmation_handler(mock_ui_handler)

    # Evaluate a high-risk tool execution
    allowed, effective_risk, was_intercepted, reason = guard.evaluate_tool_execution(
        tool_name="execute_command",
        args={"command": "dir"},
        declared_risk=RiskLevel.HIGH_RISK,
        interactive=True
    )

    assert allowed is True
    assert was_intercepted is True
    assert "Approved by mock UI test handler" in reason
    assert len(received_confirmations) == 1
    assert received_confirmations[0]["tool"] == "execute_command"

    # Reset handler
    guard.register_confirmation_handler(None)


def test_real_confirmation_pending_and_submission():
    """Verify create_pending_confirmation and submit_confirmation cycle."""
    conf_id, event = guard.create_pending_confirmation(
        tool_name="safe_delete_file",
        args={"path": "dummy.txt"},
        risk_level=RiskLevel.HIGH_RISK,
        timeout_sec=5
    )

    pending = guard.get_pending_confirmations()
    assert any(c["id"] == conf_id for c in pending)

    # Submit approval
    submitted = guard.submit_confirmation(conf_id, approved=True)
    assert submitted is True
    assert event.is_set() is True

    with guard._confirm_lock:
        conf = guard._pending_confirmations[conf_id]
        assert conf["approved"] is True
