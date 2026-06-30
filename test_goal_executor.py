import os
import asyncio
from core.brain.goal_executor import GoalExecutor, RiskLevel

# Create a dummy brain
class DummyBrain:
    pass

def test_goal_executor():
    print("Initializing Goal Executor...")
    executor = GoalExecutor(brain=DummyBrain())

    goals = [
        "open Chrome",
        "create folder",
        "organize Downloads",
        "research laptops under ₹100,000",
        "generate report"
    ]
    
    for goal in goals:
        try:
            print(f"\n--- Testing Goal: {goal} ---")
        except UnicodeEncodeError:
            print(f"\n--- Testing Goal: {goal.encode('ascii', 'ignore').decode()} ---")
        result = executor.process_goal(goal)
        print(f"\\n--- EXECUTION EVIDENCE FOR '{goal}' ---")
        print(f"Risk Level: {executor.active_plan.overall_risk.value if executor.active_plan else 'N/A'}")
        if executor.active_plan:
            print("Generated DAG:")
            for node in executor.active_plan.tasks:
                print(f"  [{node.id}] {node.description} (Tool: {node.tool_required})")
        print(f"Process Result: {result}\\n")
        
        if executor.active_plan and executor.active_plan.overall_risk in [RiskLevel.MEDIUM, RiskLevel.HIGH]:
            print("Approving plan automatically for testing...")
            executor.approve_plan(True)
            # wait a bit for thread to finish
            import time
            time.sleep(2)
            
if __name__ == "__main__":
    test_goal_executor()
