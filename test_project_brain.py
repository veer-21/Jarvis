"""Verification test for JARVIS Project Brain integration."""
import sys
import os
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class MockMemory:
    """Lightweight in-memory mock for testing MemoryAgent without filesystem ChromaDB overhead."""
    def __init__(self):
        self.memories = []

    def store_memory(self, content, category="knowledge", metadata=None):
        self.memories.append({"content": content, "category": category, "metadata": metadata or {}})
        return "mock_doc_id"

    def retrieve_memories(self, query, category=None, top_k=10):
        results = [m for m in self.memories if not category or m.get("category") == category]
        return results[:top_k]


def run_project_brain_tests():
    passed = 0
    failed = 0

    def test(name, condition):
        nonlocal passed, failed
        if condition:
            print(f"  [PASS] {name}")
            passed += 1
        else:
            print(f"  [FAIL] {name}")
            failed += 1

    print("=" * 55)
    print("  JARVIS — Project Brain Verification Test")
    print("=" * 55)

    temp_dir = Path("temp_test_brain")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    temp_dir_str = str(temp_dir.resolve())
    original_getcwd = os.getcwd
    os.getcwd = lambda: temp_dir_str

    try:
        # ─── Test 1: PromptComposer Dynamic Integration ───────────────────────────
        print("\n--- Test 1: PromptComposer Dynamic Injection ---")
        
        from core.prompts import PromptComposer
        pc = PromptComposer()
        
        # Composing without files
        prompt_before = pc.compose_for_chat(has_memory=True)
        test("Prompt composer compose runs without files", "[PROJECT BRAIN" not in prompt_before)
        
        # Create test brain files
        brain_folder = temp_dir / "brain"
        brain_folder.mkdir()
        
        master_memory_file = brain_folder / "master-memory.md"
        master_memory_file.write_text("# Test Master Memory\n- Core Decision: Use Test Framework", encoding="utf-8")
        
        architecture_file = brain_folder / "architecture.md"
        architecture_file.write_text("# Test Architecture\n- Core modules list", encoding="utf-8")
        
        # Re-compose with memory=True to trigger project brain loading
        pc._cache.clear()
        prompt_after = pc.compose(include_memory=True)
        
        test("Project Brain master memory injected", "[PROJECT BRAIN - MASTER MEMORY]" in prompt_after)
        test("Project Brain master memory content matches", "Core Decision: Use Test Framework" in prompt_after)
        test("Project Brain architecture injected", "[PROJECT BRAIN - ARCHITECTURE]" in prompt_after)
        test("Prompt limit handles the extra context", len(prompt_after) > len(prompt_before))

        # ─── Test 2: MemoryAgent Project Brain Update Action ─────────────────────
        print("\n--- Test 2: MemoryAgent update_project_brain ---")
        
        from core.agents.memory_agent import MemoryAgent
        from core.agents.base_agent import AgentMessage
        
        # Initialize Mock Memory & Agent
        memory = MockMemory()
        
        # Inject fake task memories
        memory.store_memory(
            "Task: Setup security groups\nResult: Decision: Enabled token validation. Problem: Connection failed due to wrong port. Fix: Used port 443.",
            category="task",
            metadata={"type": "task_result"}
        )
        
        agent = MemoryAgent(memory=memory)
        
        # Mock brain sender to return a structured update
        def mock_brain_send(prompt):
            return """
            {
              "decisions": "- Decision: Configured custom port for security routing",
              "patterns": "- Pattern: Standardize SSL handshakes",
              "mistakes": "- Problem: SSL handshake exception\\n  Cause: Port mismatch\\n  Fix: Ensure target port matches environment variables"
            }
            """
        agent.set_brain_sender(mock_brain_send)
        
        # Run action
        msg = AgentMessage(
            sender="test",
            recipient="memory",
            content="",
            metadata={"action": "update_project_brain"}
        )
        res = agent.process(msg)
        
        test("MemoryAgent updates processed successfully", res.success)
        
        # Verify files created in the mocked cwd
        dec_file = brain_folder / "decisions.md"
        pat_file = brain_folder / "patterns.md"
        mist_file = brain_folder / "mistakes.md"
        
        test("decisions.md updated", dec_file.exists())
        test("patterns.md updated", pat_file.exists())
        test("mistakes.md updated", mist_file.exists())
        
        if dec_file.exists():
            test("decisions.md has correct content", "Configured custom port for security routing" in dec_file.read_text(encoding="utf-8"))
        if mist_file.exists():
            test("mistakes.md has correct content", "SSL handshake exception" in mist_file.read_text(encoding="utf-8"))

    finally:
        # Cleanup and restore os.getcwd
        os.getcwd = original_getcwd
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

    print(f"\n{'=' * 55}")
    total = passed + failed
    if failed == 0:
        print(f"  ALL {passed} TESTS PASSED")
    else:
        print(f"  {passed}/{total} passed, {failed} FAILED")

    return passed, failed


def test_project_brain():
    passed, failed = run_project_brain_tests()
    assert failed == 0
    assert passed > 0


if __name__ == "__main__":
    passed, failed = run_project_brain_tests()
    if failed > 0:
        sys.exit(1)
