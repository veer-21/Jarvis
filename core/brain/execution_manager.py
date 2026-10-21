"""
JARVIS Brain — Execution Manager
Handles autonomous multi-step task execution using Dual-Routing paradigm.
"""

import json
import asyncio
from typing import Optional, AsyncIterator
from datetime import datetime, timezone
from core.logger import log, error_log

class PlanStep:
    """Represents a discrete step in an execution plan."""
    def __init__(self, step_number: int, description: str, tool_name: Optional[str] = None, params: Optional[dict] = None):
        self.step_number = step_number
        self.description = description
        self.tool_name = tool_name
        self.params = params or {}
        self.status = "pending"
        self.result = None

    def to_dict(self) -> dict:
        return {
            "step_number": self.step_number,
            "description": self.description,
            "tool_name": self.tool_name,
            "params": self.params,
            "status": self.status,
            "result": self.result,
        }

class ExecutionPlan:
    """Represents a planned series of steps to achieve a goal."""
    def __init__(self, goal: str, steps: Optional[list] = None):
        self.goal = goal
        self.steps = steps or []
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.status = "created"

    def add_step(self, step: PlanStep) -> None:
        self.steps.append(step)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "status": self.status,
            "created_at": self.created_at,
            "steps": [s.to_dict() if hasattr(s, "to_dict") else s for s in self.steps],
        }

class ExecutionEvent:
    """Represents a structured execution log/event for the OS agent terminal."""
    def __init__(self, event_type: str, step_index: int, data: dict):
        self.event_type = event_type
        self.step_index = step_index
        self.data = data
        self.timestamp = datetime.now(timezone.utc).isoformat()


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

    async def run_stream(self, task: str, verbose: bool = True) -> AsyncIterator[dict]:
        """
        Asynchronous execution pipeline yielding execution updates and output chunks.
        """
        if not self._brain:
            yield {"type": "stream_chunk", "chunk": "Error: Brain not attached."}
            return

        is_complex = self._is_complex_goal(task)
        route_str = "GoalExecutor" if is_complex else "ReasoningEngine"
        log.info(f"[ExecutionManager] Streaming Task '{task}' via {route_str}")

        try:
            if is_complex:
                # Stream the GoalExecutor steps
                async for event in self._goal_executor.process_goal_stream(task):
                    yield event
            else:
                # Simple action stream: broadcast initial step then stream tokens
                event = ExecutionEvent(
                    event_type="STARTING_STEP",
                    step_index=1,
                    data={"description": task, "type": "simple_action"}
                )
                from core.brain.streaming_manager import StreamingManager
                formatted_event = StreamingManager.format_execution_event(event)
                from api.ws_manager import ws_manager
                await ws_manager.broadcast(formatted_event)
                yield formatted_event

                async for chunk_dict in self._run_simple_action_first_stream(task):
                    yield chunk_dict

        except Exception as e:
            error_log.error(f"[ExecutionManager] Stream failure: {e}")
            yield {"type": "stream_chunk", "chunk": f"\n[Task Stream Error: {e}]"}

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

    async def _run_simple_action_first_stream(self, task: str) -> AsyncIterator[dict]:
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
        
        # Execute in executor thread to stream tokens asynchronously without blocking
        loop = asyncio.get_running_loop()
        def get_stream():
            return task_engine.stream_message(prompt, task_system_prompt, raw_message=prompt)
            
        gen = await loop.run_in_executor(None, get_stream)
        
        def get_next_token():
            try:
                return next(gen)
            except StopIteration:
                return None

        while True:
            chunk = await loop.run_in_executor(None, get_next_token)
            if chunk is None:
                break
            yield {"type": "stream_chunk", "chunk": chunk}

    def get_history(self) -> list[dict]:
        return list(self._execution_history)
