"""
JARVIS Brain — Execution Manager
Handles autonomous multi-step task execution using Dual-Routing paradigm.
"""

from typing import Optional
from datetime import datetime, timezone
from core.logger import log, error_log

class ExecutionManager:
    """
    Dual-Routing Execution Engine.
    Simple tasks route to the Action-First loop.
    Complex goals route to the GoalExecutor (DAG Planner).
    """

    def __init__(self):
        self._brain = None
        self._goal_executor = None
        self._execution_history = []
        log.info("ExecutionManager initialized.")

    def set_brain(self, brain) -> None:
        """Attach the full Brain reference."""
        self._brain = brain
        from core.brain.goal_executor import GoalExecutor
        self._goal_executor = GoalExecutor(brain=self._brain)

    def _is_complex_goal(self, task_text: str) -> bool:
        """Heuristic to route to GoalExecutor vs simple TaskEngine."""
        task_lower = task_text.lower().strip()
        
        # 1. Explicit Complex Intents
        complex_keywords = [
            "research", "compare", "organize", "build", "workflow", 
            "find all", "analyze", "summarize", "plan", "multiple", "series"
        ]
        if any(kw in task_lower for kw in complex_keywords):
            return True
            
        # 2. Explicit Simple Intents (Direct Commands)
        simple_keywords = [
            "open", "close", "launch", "run", "create folder", "create file", 
            "delete", "list", "show", "click", "type", "play", "pause"
        ]
        if any(task_lower.startswith(kw) for kw in simple_keywords):
            return False
            
        # 3. Fallback Heuristic
        return len(task_lower.split()) > 8

    def run(self, task: str, verbose: bool = True) -> str:
        if not self._brain:
            error_msg = "Brain not attached to ExecutionManager"
            error_log.error(error_msg)
            return error_msg

        is_complex = self._is_complex_goal(task)
        route_str = "GoalExecutor" if is_complex else "ReasoningEngine"
        
        log.info(f"Routing Task '{task}' via {route_str}")
        if verbose:
            print(f"\n🤖 JARVIS Executing Task: {task} (via {route_str})")

        try:
            if is_complex:
                final_report = self._goal_executor.process_goal(task)
            else:
                final_report = self._run_simple_action_first(task)
                
            self._execution_history.append({
                "task": task,
                "result": final_report[:500] if final_report else "",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            if verbose:
                print(f"\n✅ Task Complete. Result:\n{final_report}\n")
                
            return final_report

        except Exception as e:
            error_msg = f"Task Execution Failed: {str(e)}"
            error_log.error(error_msg)
            
            # Resilience fallback
            if is_complex:
                log.warning("GoalExecutor crashed. Falling back to simple reasoning engine.")
                return self._run_simple_action_first(task)
            
            return error_msg

    def _run_simple_action_first(self, task: str) -> str:
        prompt = (
            f"[AUTONOMOUS TASK MODE]\n"
            f"Goal: {task}\n\n"
            "Action-First Execution Rules:\n"
            "1. You MUST prioritize Execute -> Verify -> Respond.\n"
            "2. Select a tool to take action immediately. Do not talk without acting.\n"
            "3. If an action fails, analyze the error and try an alternative.\n"
            "4. Verify the results of your actions using tools.\n"
            "5. If the goal is achieved, output the final completion report.\n"
            "Now, begin execution."
        )
        from core.brain.reasoning_engine import ReasoningEngine
        task_engine = ReasoningEngine()
        
        task_system_prompt = self._brain._get_system_prompt(for_task=True)
        all_tools = self._brain.tools.get_all_callables()
        
        task_engine.create_chat_session(task_system_prompt, all_tools)
        return task_engine.send_message(prompt)

    def get_history(self) -> list[dict]:
        return list(self._execution_history)
