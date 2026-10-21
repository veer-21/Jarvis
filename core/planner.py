"""
JARVIS Backward Compatibility - Planner Adapter
Exposes JarvisPlanner pointing to the GoalExecutor and ExecutionManager.
"""

from typing import List, Optional
from core.brain.execution_manager import ExecutionManager, ExecutionPlan, PlanStep
from core.brain.goal_executor import GoalExecutor, GoalPlan, TaskNode

class JarvisPlanner:
    """
    Backward-compatible adapter for JarvisPlanner.
    Maps legacy plan requests to ExecutionPlan and GoalExecutor.
    """
    def __init__(self, brain=None):
        self.brain = brain
        self.execution_manager = ExecutionManager()
        if brain:
            self.execution_manager.set_brain(brain)

    def create_plan(self, goal: str) -> ExecutionPlan:
        plan = ExecutionPlan(goal=goal)
        step = PlanStep(step_number=1, description=f"Execute: {goal}")
        plan.add_step(step)
        return plan

    def execute_plan(self, plan: ExecutionPlan) -> str:
        return self.execution_manager.run(plan.goal)
