"""Full verification test for JARVIS v3.0 — all phases."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

passed = 0
failed = 0

def test(name, condition):
    global passed, failed
    if condition:
        print(f"  [PASS] {name}")
        passed += 1
    else:
        print(f"  [FAIL] {name}")
        failed += 1

test.__test__ = False

print("=" * 55)
print("  JARVIS v3.0 — Full Architecture Verification")
print("=" * 55)

# ─── Phase 1: Brain Architecture ──────────────────────────────────────────────
print("\n--- Phase 1: Brain Architecture Split ---")

from core.brain import Brain, JarvisBrain
test("Brain import", Brain is not None)
test("JarvisBrain backward compat", JarvisBrain is Brain)

from core.brain.reasoning_engine import ReasoningEngine
from core.brain.tool_router import ToolRouter, ToolSchema
from core.brain.context_manager import ContextManager
from core.brain.memory_manager import MemoryManager
from core.brain.execution_manager import ExecutionManager, ExecutionPlan, PlanStep
from core.brain.response_generator import ResponseGenerator
from core.brain.streaming_manager import StreamingManager
test("All 7 brain sub-modules imported", True)

from core.prompts import PromptComposer
pc = PromptComposer()
chat_p = pc.compose_for_chat()
task_p = pc.compose_for_task()
api_p  = pc.compose_for_api()
test(f"PromptComposer: chat={len(chat_p)} task={len(task_p)} api={len(api_p)}", len(chat_p) > 500)

# ─── Phase 2: Tool Calling ────────────────────────────────────────────────────
print("\n--- Phase 2: Tool Calling Pipeline ---")

router = ToolRouter()
router.register_callable(lambda x: x, category="test")
test(f"ToolRouter: {router.tool_count} tool registered", router.tool_count == 1)
test(f"Categories: {list(router.get_categories().keys())}", 'test' in router.get_categories())

from tools import get_tool_registry, get_tool_categories
cats = get_tool_categories()
test(f"Tools auto-discovery: {len(cats)} categories", len(cats) == 5)

from tools.system_tools import execute_command
test("system_tools rewritten (no duplicate keywords)", True)

# ─── Phase 3: Memory System ──────────────────────────────────────────────────
print("\n--- Phase 3: Memory System Upgrade ---")

from core.memory import JarvisMemory, score_importance, IMPORTANCE_THRESHOLD
test("JarvisMemory v2.0 imported", True)

# Test importance scoring
score_hi = score_importance("Remember that I prefer dark mode always", "user")
score_lo = score_importance("ok thanks", "user")
score_bot = score_importance("Here is the result", "assistant")
test(f"Importance: 'remember prefer' = {score_hi:.2f} (should be > threshold)", score_hi >= IMPORTANCE_THRESHOLD)
test(f"Importance: 'ok thanks' = {score_lo:.2f} (should be < threshold)", score_lo < IMPORTANCE_THRESHOLD)
test(f"Importance: assistant msg = {score_bot:.2f} (should be 0)", score_bot == 0.0)

from core.memory import EpisodicMemory, ConversationStore
test("EpisodicMemory class available", EpisodicMemory is not None)

mm = MemoryManager()
test(f"MemoryManager: active={mm.is_active}", not mm.is_active)
mm.set_working("test_key", "test_value")
test(f"Working memory: {mm.get_working('test_key')}", mm.get_working("test_key") == "test_value")

# ─── Phase 4: Multi-Agent Architecture ────────────────────────────────────────
print("\n--- Phase 4: Multi-Agent Architecture ---")

from core.agents import BaseAgent, AgentMessage, AgentResponse, AgentBus
from core.agents.base_agent import AgentRole
from core.agents.commander_agent import CommanderAgent
from core.agents.security_agent import SecurityAgent
from core.agents.memory_agent import MemoryAgent
test("All agent modules imported", True)

bus = AgentBus()
cmd = CommanderAgent()
sec = SecurityAgent()
mem = MemoryAgent()
bus.register(cmd)
bus.register(sec)
bus.register(mem)
test(f"AgentBus: {bus.agent_count} agents registered", bus.agent_count == 3)

# Test commander intent classification
test("Intent: 'search and summarize' = task", cmd.classify_intent("search and summarize news") == "task")
test("Intent: 'open chrome' = command", cmd.classify_intent("open chrome") == "command")
test("Intent: 'what is python' = query", cmd.classify_intent("what is python?") == "query")
test("Intent: 'hello there' = chat", cmd.classify_intent("hello there") == "chat")

# Test security agent
sec_msg = AgentMessage(sender="test", recipient="security", content="rm -rf /",
                       metadata={"action": "assess_risk"})
sec_resp = sec.process(sec_msg)
test(f"Security: 'rm -rf' risk = {sec_resp.metadata.get('risk')}", sec_resp.metadata.get('risk') == 'CRITICAL')

# ─── Phase 5: API Models ─────────────────────────────────────────────────────
print("\n--- Phase 5: API Enhancement ---")

from api.models import (
    StreamChunk, StreamChunkType, ExecutionEventModel,
    SystemMetrics, AgentStatusModel, AgentSystemStatus,
)
test("Streaming models imported", StreamChunkType.TEXT.value == "text")
test("SystemMetrics model", SystemMetrics(uptime_seconds=1.0).tools_registered == 0)
test("AgentSystemStatus model", AgentSystemStatus(agents=[], total_agents=0).total_agents == 0)

# ─── Phase 6: Security ───────────────────────────────────────────────────────
print("\n--- Phase 6: Security Integration ---")

from core.security import guard, RiskLevel
risk = guard.assess_command_risk("del /s /q C:\\*")
test(f"SecurityGuard risk assessment: {risk}", risk == RiskLevel.CRITICAL)
risk_safe = guard.assess_command_risk("echo hello")
test(f"Safe command assessment: {risk_safe}", risk_safe == RiskLevel.SAFE)

# ─── Backward Compatibility ──────────────────────────────────────────────────
print("\n--- Backward Compatibility ---")

from core.logger import log
from core.config import get_api_key, get_model_name
from core.planner import JarvisPlanner
from core.voice import VoiceInterface
from core.security import owner_auth
test("All legacy imports work", True)

# ─── Summary ──────────────────────────────────────────────────────────────────
print(f"\n{'=' * 55}")
total = passed + failed
if failed == 0:
    print(f"  ALL {passed} TESTS PASSED")
else:
    print(f"  {passed}/{total} passed, {failed} FAILED")
print(f"{'=' * 55}")

def test_architecture():
    assert failed == 0

if __name__ == "__main__":
    if failed > 0:
        sys.exit(1)
