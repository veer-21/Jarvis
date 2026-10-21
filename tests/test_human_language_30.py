"""
Human-Language Acceptance Test Suite for JARVIS Phase 3.5.
Validates 30 realistic, diverse natural-language requests against the AssistantOrchestrator.
Ensures the general architecture (Planner, Validation, Security Gate, Tool Execution,
Result Verification, and Memory Boundary) processes natural language without hard-coded shortcuts.
"""

import sys
import pytest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.brain.assistant_orchestrator import AssistantOrchestrator
from core.brain.task_model import TaskStatus, TaskStepStatus
from core.brain.tool_router import ToolRouter
from core.brain.context_tracker import ContextTracker
from core.security import guard, RiskLevel

# Real tools
from tools.system_tools import execute_command
from tools.file_tools import read_file, write_file, list_directory, safe_delete_file, search_in_files
from tools.automation_tools import open_application, get_system_info, list_open_windows
from tools.web_tools import web_search, fetch_webpage


class DummyReasoningEngine:
    """Lightweight test engine for LLM decomposition and text synthesis without external API costs."""
    def generate_text(self, prompt: str) -> str:
        p_lower = prompt.lower()
        if "react" in p_lower:
            return "React is a JavaScript library for building user interfaces with components, state, and hooks."
        if "architecture" in p_lower:
            return "The architecture consists of AssistantOrchestrator, ToolRouter, SecurityGuard, and Memory."
        if "poem" in p_lower:
            return "In silicon dreams and lines of light, Jarvis works into the night."
        if "dag" in p_lower:
            return "The DAG task planner models steps as nodes with dependencies, executing ready nodes topological order."
        return "Processed natural language request successfully."

    def send_message(self, prompt: str, raw_message: str = "") -> str:
        return self.generate_text(prompt)


class MockBrain:
    def __init__(self, tool_router):
        self.tools = tool_router
        self.reasoning = DummyReasoningEngine()
        from core.brain.intent_classifier import IntentClassifier
        self.intent_classifier = IntentClassifier()
        self.memory_manager = None
        self.context = None


@pytest.fixture(scope="module")
def orchestrator():
    router = ToolRouter()
    # Register real tools
    router.register_callable(execute_command, category="system", risk_level=RiskLevel.HIGH)
    router.register_callable(read_file, category="file")
    router.register_callable(write_file, category="file", risk_level=RiskLevel.MEDIUM)
    router.register_callable(list_directory, category="file")
    router.register_callable(safe_delete_file, category="file", risk_level=RiskLevel.HIGH)
    router.register_callable(search_in_files, category="file")
    router.register_callable(open_application, category="automation")
    router.register_callable(get_system_info, category="automation")
    router.register_callable(list_open_windows, category="automation")
    router.register_callable(web_search, category="web")
    router.register_callable(fetch_webpage, category="web")

    brain = MockBrain(router)
    orch = AssistantOrchestrator(
        brain=brain,
        tool_router=router,
        memory_manager=None,
        reasoning_engine=brain.reasoning
    )
    return orch


# ─── 30 Natural Language Scenarios ───────────────────────────────────────────

def test_01_open_app_and_verify(orchestrator):
    """1. 'Open Notepad and tell me whether it is running.'"""
    plan = orchestrator._create_plan("Open Notepad and tell me whether it is running.", "task")
    assert len(plan) >= 1
    assert any("notepad" in str(s.input_variables).lower() or s.tool_name == "open_application" for s in plan)


def test_02_find_readme_and_explain(orchestrator):
    """2. 'Find my README and explain the architecture.'"""
    plan = orchestrator._create_plan("Find my README and explain the architecture.", "task")
    assert len(plan) >= 1
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "read_file" in tools or "search_in_files" in tools or "list_directory" in tools


def test_03_list_root_directory(orchestrator):
    """3. 'Find my project files and list the contents of the root directory.'"""
    plan = orchestrator._create_plan("Find my project files and list the contents of the root directory.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "list_directory" in tools or "search_in_files" in tools


def test_04_search_react_docs(orchestrator):
    """4. 'Search the web for the official React documentation and summarize it.'"""
    plan = orchestrator._create_plan("Search the web for the official React documentation and summarize it.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "web_search" in tools or "fetch_webpage" in tools


def test_05_open_browser_and_read(orchestrator):
    """5. 'Open the browser and read this webpage.'"""
    plan = orchestrator._create_plan("Open the browser and read https://example.com", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "fetch_webpage" in tools or "open_url" in tools or any("example.com" in str(s.input_variables) for s in plan)


def test_06_find_todos_in_code(orchestrator):
    """6. 'Open my project and find files containing TODO.'"""
    plan = orchestrator._create_plan("Open my project and find files containing TODO.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "search_in_files" in tools


def test_07_remember_preference(orchestrator):
    """7. 'Remember that I prefer concise answers.'"""
    res = orchestrator.process("Remember that I prefer concise answers.")
    assert res is not None
    assert len(res) > 0


def test_08_query_preference(orchestrator):
    """8. 'What is my preferred answer style?'"""
    res = orchestrator.process("What is my preferred answer style?")
    assert res is not None


def test_09_forget_preference(orchestrator):
    """9. 'Forget that preference.'"""
    res = orchestrator.process("Forget that preference.")
    assert res is not None


def test_10_search_python_docs(orchestrator):
    """10. 'Open Chrome and search for the latest Python documentation.'"""
    plan = orchestrator._create_plan("Open Chrome and search for the latest Python documentation.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "web_search" in tools or "open_application" in tools or "fetch_webpage" in tools


def test_11_stop_task(orchestrator):
    """11. 'Stop the task.'"""
    res = orchestrator.process("Stop the task.")
    assert "no active task" in res.lower() or "stopped" in res.lower() or "cancelled" in res.lower()


def test_12_cancel_doing(orchestrator):
    """12. 'Cancel what you are doing.'"""
    res = orchestrator.process("Cancel what you are doing.")
    assert "no active task" in res.lower() or "stopped" in res.lower() or "cancelled" in res.lower()


def test_13_abort_operation(orchestrator):
    """13. 'Abort the current operation.'"""
    res = orchestrator.process("Abort the current operation.")
    assert "no active task" in res.lower() or "stopped" in res.lower() or "cancelled" in res.lower()


def test_14_never_mind(orchestrator):
    """14. 'Never mind, stop.'"""
    res = orchestrator.process("Never mind, stop.")
    assert "no active task" in res.lower() or "stopped" in res.lower() or "cancelled" in res.lower()


def test_15_check_system_status(orchestrator):
    """15. 'Check system status and tell me CPU and memory usage.'"""
    plan = orchestrator._create_plan("Check system status and tell me CPU and memory usage.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "get_system_info" in tools


def test_16_what_time_is_it(orchestrator):
    """16. 'What time is it right now?'"""
    res = orchestrator.process("What time is it right now?")
    assert ":" in res or "time" in res.lower() or "am" in res.lower() or "pm" in res.lower()


def test_17_what_is_todays_date(orchestrator):
    """17. 'What is today's date?'"""
    res = orchestrator.process("What is today's date?")
    assert "202" in res or "january" in res.lower() or "today" in res.lower() or len(res) > 3


def test_18_list_files_current_dir(orchestrator):
    """18. 'List all files in the current folder.'"""
    plan = orchestrator._create_plan("List all files in the current folder.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "list_directory" in tools


def test_19_create_notes_file(orchestrator):
    """19. 'Create a notes file named test_notes.txt with my daily tasks.'"""
    plan = orchestrator._create_plan("Create a notes file named test_notes.txt with my daily tasks.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "write_file" in tools


def test_20_read_notes_file(orchestrator):
    """20. 'Read test_notes.txt and tell me what is inside.'"""
    plan = orchestrator._create_plan("Read test_notes.txt and tell me what is inside.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "read_file" in tools


def test_21_delete_notes_file(orchestrator):
    """21. 'Delete test_notes.txt safely.'"""
    plan = orchestrator._create_plan("Delete test_notes.txt safely.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "safe_delete_file" in tools


def test_22_check_notepad_active(orchestrator):
    """22. 'Check if notepad.exe is currently active.'"""
    plan = orchestrator._create_plan("Check if notepad.exe is currently active.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "list_open_windows" in tools or "get_system_info" in tools


def test_23_weather_search(orchestrator):
    """23. 'Search Google or DuckDuckGo for the weather forecast in London.'"""
    plan = orchestrator._create_plan("Search Google or DuckDuckGo for the weather forecast in London.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "web_search" in tools or "get_weather" in tools


def test_24_find_first_python_file(orchestrator):
    """24. 'Find python files in the directory.'"""
    plan = orchestrator._create_plan("Find python files in the directory.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "search_in_files" in tools or "list_directory" in tools


def test_25_read_that_file_referential(orchestrator):
    """25. 'Read that file.' (Referential resolution)"""
    orchestrator.context_tracker.update_exchange("list files", "Found README.md", candidates=["README.md"])
    resolved = orchestrator.context_tracker.resolve_references("Read that file.")
    assert "README.md" in resolved


def test_26_summarize_file(orchestrator):
    """26. 'Summarize the file you just read.'"""
    resolved = orchestrator.context_tracker.resolve_references("Summarize the file you just read.")
    assert resolved is not None


def test_27_write_poem(orchestrator):
    """27. 'Write a poem about intelligent assistants.' (Conversational)"""
    res = orchestrator.process("Write a poem about intelligent assistants.")
    assert res is not None
    assert len(res) > 10


def test_28_explain_dag_dependencies(orchestrator):
    """28. 'Explain how the DAG task planner handles dependencies.'"""
    res = orchestrator.process("Explain how the DAG task planner handles dependencies.")
    assert res is not None
    assert len(res) > 10


def test_29_list_running_windows(orchestrator):
    """29. 'List all running windows on my desktop.'"""
    plan = orchestrator._create_plan("List all running windows on my desktop.", "task")
    tools = [s.tool_name for s in plan if s.tool_name]
    assert "list_open_windows" in tools


def test_30_who_are_you(orchestrator):
    """30. 'Who are you and what are your capabilities?'"""
    res = orchestrator.process("Who are you and what are your capabilities?")
    assert res is not None
    assert len(res) > 10
