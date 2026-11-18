import sys
import os
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.brain.brain import Brain
from core.brain.execution_manager import ExecutionManager
from core.logger import log

def test_goal(manager: ExecutionManager, goal: str):
    print(f"\n{'='*60}")
    print(f" TESTING GOAL: {goal}")
    print(f"{'='*60}")
    
    # Simulate execution
    # Since some tools might block or prompt for approval, we should mock the approval in GoalExecutor
    # Wait, GoalExecutor pauses via approval_event if Risk is HIGH or MEDIUM.
    # We must patch approve_plan to automatically approve for this headless test.
    
    executor = manager._goal_executor
    original_preview = executor.preview_plan
    
    def auto_approve_preview():
        print(f"    [TEST] Auto-approving {executor.active_plan.overall_risk.value} risk plan.")
        executor.approve_plan(True)
        # Wait for execution to finish
        while not hasattr(executor, 'test_done') or not executor.test_done:
            import time
            time.sleep(0.5)
        return "Execution Finished via Auto-Approve"

    executor.preview_plan = auto_approve_preview
    
    # We also need to set test_done flag when execute finishes
    original_execute = executor.execute
    def execute_with_flag():
        res = original_execute()
        executor.test_done = True
        return res
    executor.execute = execute_with_flag
    
    # Same for guard check in tool_router for HIGH risk tools
    from core.security import guard
    original_check = guard.check_command
    def auto_approve_guard(cmd, interactive):
        print(f"    [TEST] Auto-approving guard check for: {cmd}")
        return True, "Auto-approved for test"
    guard.check_command = auto_approve_guard
    
    result = manager.run(goal, verbose=True)
    print(f"\nFINAL RESULT for '{goal}':\n{result}")
    
    # Reset
    executor.preview_plan = original_preview
    executor.execute = original_execute
    guard.check_command = original_check
    executor.test_done = False

def main():
    print("Initializing Brain and Execution Manager...")
    brain = Brain()
    manager = ExecutionManager()
    manager.set_brain(brain)
    
    goals = [
        "Open Chrome",
        "Create folder named Test Folder on Desktop",
        "Organize Downloads folder",
        "Research laptops under 100000 INR and save report"
    ]
    
    for goal in goals:
        test_goal(manager, goal)

if __name__ == "__main__":
    main()
