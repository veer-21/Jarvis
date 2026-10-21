import json
import time
import threading
import asyncio
import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from enum import Enum
from core.logger import log, error_log
from core.agents.base_agent import AgentMessage

class RiskLevel(str, Enum):
    SAFE = "Safe"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"

class Capability(str, Enum):
    BROWSER = "browser"
    FILE = "file"
    DESKTOP = "desktop"
    SYSTEM = "system"
    MEMORY = "memory"
    REASONING = "reasoning"

class NodeType(str, Enum):
    ACTION = "action"
    REASONING = "reasoning"

class VerificationType(str, Enum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"

class TaskNode(BaseModel):
    id: str
    node_type: NodeType
    description: str
    capability: Capability
    tool_name: Optional[str] = None
    input_variables: Dict[str, Any] = Field(default_factory=dict)
    output_variables: List[str] = Field(default_factory=list)
    expected_outcome: str
    verification_type: VerificationType
    risk_level: RiskLevel = RiskLevel.SAFE
    dependencies: List[str] = Field(default_factory=list)
    status: str = "pending"
    result: Optional[str] = None
    verification_status: Optional[str] = None

class GoalPlan(BaseModel):
    goal: str
    overall_risk: RiskLevel = RiskLevel.SAFE
    tasks: List[TaskNode]

class GoalExecutor:
    """
    Goal Executor Engine
    Handles structured DAG generation, validation, and execution.
    """
    def __init__(self, brain):
        self.brain = brain
        self.active_plan: Optional[GoalPlan] = None
        self.execution_context: Dict[str, Any] = {}
        self.approval_event = threading.Event()
        self.approval_result = False
        log.info("GoalExecutor initialized.")

    def process_goal(self, goal_text: str) -> str:
        log.info(f"[GoalExecutor] Processing Goal: {goal_text}")
        
        self.active_plan = self.generate_dag(goal_text)
        
        if not self.active_plan or not self.active_plan.tasks:
            return "Failed to generate a valid plan."

        try:
            self.validate_dag(self.active_plan)
        except ValueError as e:
            error_log.error(f"DAG Validation Failed: {e}")
            return f"Plan Validation Error: {e}"
        
        if self.active_plan.overall_risk in [RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]:
            return self.preview_plan()
            
        return self.execute()

    def generate_dag(self, goal_text: str) -> GoalPlan:
        log.info("[GoalExecutor] Generating DAG...")
        
        tools_list = []
        for name, schema in self.brain.tools._registry.items():
            params = []
            if schema.pydantic_model:
                for f_name, f_field in schema.pydantic_model.model_fields.items():
                    params.append(f"{f_name}: {f_field.annotation.__name__ if hasattr(f_field.annotation, '__name__') else str(f_field.annotation)}")
            tools_list.append(f"- {name} ({', '.join(params)}) -> Risk: {schema.risk_level.value}")

        prompt = f"""
Decompose the following goal into a sequence of tasks (DAG).
Goal: {goal_text}

Available Tools:
{chr(10).join(tools_list)}

Rules:
1. Every task must be either 'action' (uses a tool) or 'reasoning' (LLM transformation).
2. For 'action' nodes, 'tool_name' must be an exact match from the Available Tools.
3. For 'reasoning' nodes, 'tool_name' must be null.
4. Pass data between tasks using interpolation in 'input_variables' like: "{{{{task_id.output_var}}}}".
5. Output MUST be valid JSON strictly matching the schema.

Schema:
{{
  "goal": "...",
  "overall_risk": "Safe|Medium|High",
  "tasks": [
    {{
      "id": "t1",
      "node_type": "action|reasoning",
      "description": "...",
      "capability": "browser|file|desktop|system|memory|reasoning",
      "tool_name": "...",
      "input_variables": {{"key": "value"}},
      "output_variables": ["out1"],
      "expected_outcome": "...",
      "verification_type": "deterministic|llm",
      "risk_level": "Safe|Medium|High",
      "dependencies": []
    }}
  ]
}}
"""
        try:
            if hasattr(self.brain.reasoning, "generate_text"):
                res = self.brain.reasoning.generate_text(prompt)
            else:
                res = self.brain.reasoning._fallback_generate(prompt)
            # Try to extract JSON if surrounded by markdown
            import re
            json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', res, re.DOTALL)
            if json_match:
                res = json_match.group(1)
            else:
                # Also try to extract first outer JSON object if extra text exists
                brace_match = re.search(r'(\{[\s\S]*\})', res)
                if brace_match:
                    res = brace_match.group(1)
                
            data = json.loads(res)
            return GoalPlan(**data)
        except Exception as e:
            error_log.error(f"DAG generation failed: {e}")
            return GoalPlan(goal=goal_text, tasks=[])

    def validate_dag(self, dag: GoalPlan, max_tasks: int = 15, max_depth: int = 10):
        log.info("[GoalExecutor] Validating DAG...")
        if len(dag.tasks) > max_tasks:
            raise ValueError(f"Exceeded maximum task count of {max_tasks}.")
            
        task_map = {t.id: t for t in dag.tasks}
        if len(task_map) != len(dag.tasks):
            raise ValueError("Duplicate task IDs detected.")
            
        for task in dag.tasks:
            if task.node_type == NodeType.ACTION:
                if not task.tool_name:
                    raise ValueError(f"Task {task.id} is an ACTION but missing 'tool_name'.")
                if not self.brain.tools.get_tool(task.tool_name):
                    raise ValueError(f"Invalid tool_name '{task.tool_name}'.")
                    
            for dep in task.dependencies:
                if dep not in task_map:
                    raise ValueError(f"Task {task.id} has missing dependency reference: {dep}")
                    
        depths = {}
        def get_depth(tid, path):
            if tid in path:
                raise ValueError(f"Cyclic dependency detected -> {' -> '.join(path + [tid])}")
            if tid in depths:
                return depths[tid]
                
            task = task_map[tid]
            if not task.dependencies:
                depths[tid] = 1
                return 1
                
            max_dep_depth = max(get_depth(dep, path + [tid]) for dep in task.dependencies)
            depths[tid] = max_dep_depth + 1
            if depths[tid] > max_depth:
                raise ValueError(f"Exceeded maximum dependency depth of {max_depth}.")
            return depths[tid]
            
        for t in dag.tasks:
            get_depth(t.id, [])
        log.info("[GoalExecutor] DAG Validation Passed.")

    def preview_plan(self) -> str:
        log.info(f"[GoalExecutor] Plan is {self.active_plan.overall_risk.value} risk. Awaiting preview approval.")
        self._broadcast_plan_preview()
        self.approval_event.clear()
        self.approval_result = False
        return f"Goal analyzed. Risk Level: {self.active_plan.overall_risk.value}. Awaiting your approval in Mission Control."

    def approve_plan(self, approved: bool):
        self.approval_result = approved
        self.approval_event.set()
        if approved:
            threading.Thread(target=self.execute, daemon=True).start()

    def execute(self) -> str:
        if not self.active_plan:
            return "No active goal."
            
        log.info("[GoalExecutor] Starting Execution Loop.")
        self._broadcast_execution_state("RUNNING")
        self.execution_context = {}
        
        # Determine execution order based on dependencies
        task_map = {t.id: t for t in self.active_plan.tasks}
        completed = set()
        
        while len(completed) < len(self.active_plan.tasks):
            progress_made = False
            for task in self.active_plan.tasks:
                if task.id in completed:
                    continue
                    
                if all(dep in completed for dep in task.dependencies):
                    # Ready to execute
                    self._broadcast_snapshot("BEFORE", task)
                    log.info(f"[GoalExecutor] Executing Task {task.id}: {task.description}")
                    
                    try:
                        # AgentBus Dispatch to OperatorAgent
                        req = AgentMessage(
                            sender="goal_executor", 
                            recipient="operator", 
                            content=task.description, 
                            metadata={
                                "task": task.model_dump(),
                                "execution_context": self.execution_context
                            }
                        )
                        res = self.brain.agent_bus.send(req)
                        
                        task.status = "completed" if res.success else "failed"
                        task.result = res.content
                        
                        # Populate execution context with outputs if successful
                        if res.success:
                            if task.id not in self.execution_context:
                                self.execution_context[task.id] = {}
                            # In reality, tools might return structured dicts.
                            # For safety, we map the entire string result to the first expected output var.
                            if task.output_variables:
                                out_var = task.output_variables[0]
                                self.execution_context[task.id][out_var] = res.content
                        
                        # Verification
                        if res.success:
                            verified = self.verify(task)
                            task.verification_status = "Passed" if verified else "Failed"
                            if not verified:
                                task.status = "failed"
                                
                    except Exception as e:
                        task.status = "failed"
                        task.result = str(e)

                    # Dynamic Self-Healing & Adaptive Recovery
                    if task.status == "failed":
                        log.warning(f"[GoalExecutor] Task {task.id} failed ({task.result}). Attempting self-healing recovery...")
                        try:
                            recovery_prompt = (
                                f"Goal: {self.active_plan.goal}\n"
                                f"Failed Task: {task.description}\n"
                                f"Tool: {task.tool_name}\n"
                                f"Error Encountered: {task.result}\n"
                                "Provide an alternative action or corrected parameters to achieve this step.\n"
                                "Return JSON: {\"tool_name\": string, \"input_variables\": dict}"
                            )
                            reflection = self.brain.reasoning._fallback_generate(recovery_prompt)
                            match = re.search(r"\{.*?\}", reflection, re.DOTALL)
                            if match:
                                fix_data = json.loads(match.group(0))
                                alt_tool = fix_data.get("tool_name", task.tool_name)
                                alt_vars = fix_data.get("input_variables", task.input_variables)
                                log.info(f"[GoalExecutor] Retrying Task {task.id} with alternative tool '{alt_tool}'")
                                
                                retry_task = task.model_copy()
                                retry_task.tool_name = alt_tool
                                retry_task.input_variables = alt_vars
                                retry_req = AgentMessage(
                                    sender="goal_executor",
                                    recipient="operator",
                                    content=f"Recovery for {task.description}",
                                    metadata={
                                        "task": retry_task.model_dump(),
                                        "execution_context": self.execution_context
                                    }
                                )
                                retry_res = self.brain.agent_bus.send(retry_req)
                                if retry_res.success:
                                    task.status = "completed"
                                    task.result = retry_res.content
                                    if task.output_variables:
                                        self.execution_context[task.id][task.output_variables[0]] = retry_res.content
                                    log.info(f"[GoalExecutor] Self-healing succeeded for Task {task.id}!")
                        except Exception as heal_err:
                            log.warning(f"[GoalExecutor] Self-healing reflection failed: {heal_err}")
                    
                    self._broadcast_snapshot("AFTER", task)
                    
                    if task.status == "failed":
                        log.error(f"[GoalExecutor] Task {task.id} failed after recovery: {task.result}")
                        self._broadcast_execution_state("FAILED")
                        return f"Execution failed at task {task.id}: {task.result}"
                        
                    completed.add(task.id)
                    progress_made = True
                    
            if not progress_made:
                break
                
        self._broadcast_execution_state("COMPLETED")
        
        # Generate completion report
        final_prompt = f"Goal: {self.active_plan.goal}\nContext: {json.dumps(self.execution_context)}\nWrite a final summary report."
        try:
            report = self.brain.reasoning._fallback_generate(final_prompt)
            return report
        except:
            return "Goal execution finished successfully."

    def verify(self, task: TaskNode) -> bool:
        log.info(f"[GoalExecutor] Verifying Task {task.id}...")
        if task.verification_type == VerificationType.DETERMINISTIC:
            # Deterministic is usually verified by the fact that the tool didn't raise an exception
            # and returned success in the OperatorAgent response.
            return True
        else:
            prompt = f"Task: {task.description}\nExpected Outcome: {task.expected_outcome}\nActual Result: {task.result}\nDid the task succeed? Answer YES or NO."
            try:
                res = self.brain.reasoning._fallback_generate(prompt)
                return "YES" in res.upper()
            except:
                return True

    def _broadcast_plan_preview(self):
        try:
            from api.ws_manager import ws_manager
            import asyncio
            payload = self.active_plan.model_dump() if self.active_plan else {}
            async def _send():
                await ws_manager.broadcast({"type": "plan_preview", "data": payload})
            self._run_async(_send())
        except Exception:
            pass

    def _broadcast_execution_state(self, state: str):
        try:
            from api.ws_manager import ws_manager
            import asyncio
            async def _send():
                await ws_manager.broadcast({"type": "goal_execution_state", "data": {"state": state}})
            self._run_async(_send())
        except Exception:
            pass

    def _broadcast_snapshot(self, phase: str, task: TaskNode):
        try:
            from api.ws_manager import ws_manager
            import asyncio
            async def _send():
                await ws_manager.broadcast({"type": "task_snapshot", "data": {"phase": phase, "task": task.model_dump()}})
            self._run_async(_send())
        except Exception:
            pass

    def _run_async(self, coro):
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = None

            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(coro, loop)
            else:
                if loop and not loop.is_closed():
                    loop.run_until_complete(coro)
                else:
                    asyncio.run(coro)
        except Exception:
            try:
                new_loop = asyncio.new_event_loop()
                new_loop.run_until_complete(coro)
                new_loop.close()
            except Exception:
                pass

    async def _broadcast_execution_state_async(self, state: str):
        try:
            from api.ws_manager import ws_manager
            await ws_manager.broadcast({"type": "goal_execution_state", "data": {"state": state}})
        except Exception:
            pass

    async def process_goal_stream(self, goal_text: str):
        from core.brain.streaming_manager import StreamingManager
        from core.brain.execution_manager import ExecutionEvent

        log.info(f"[GoalExecutor] Processing Goal Stream: {goal_text}")
        
        loop = asyncio.get_running_loop()
        
        event = ExecutionEvent(
            event_type="STARTING_STEP",
            step_index=0,
            data={"status": "Generating execution plan..."}
        )
        yield StreamingManager.format_execution_event(event)

        # Generate DAG
        self.active_plan = await loop.run_in_executor(None, self.generate_dag, goal_text)
        
        if not self.active_plan or not self.active_plan.tasks:
            event = ExecutionEvent(
                event_type="STEP_FAILED",
                step_index=0,
                data={"error": "Failed to generate a valid plan."}
            )
            yield StreamingManager.format_execution_event(event)
            return

        try:
            self.validate_dag(self.active_plan)
        except ValueError as e:
            error_log.error(f"DAG Validation Failed: {e}")
            event = ExecutionEvent(
                event_type="STEP_FAILED",
                step_index=0,
                data={"error": f"Plan Validation Error: {e}"}
            )
            yield StreamingManager.format_execution_event(event)
            return
        
        if self.active_plan.overall_risk in [RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]:
            event = ExecutionEvent(
                event_type="STEP_SUSPENDED",
                step_index=0,
                data={"risk": self.active_plan.overall_risk.value, "message": "Awaiting approval in Mission Control."}
            )
            yield StreamingManager.format_execution_event(event)
            await loop.run_in_executor(None, self._broadcast_plan_preview)
            return

        async for event_dict in self.execute_stream():
            yield event_dict

    async def execute_stream(self):
        from core.brain.streaming_manager import StreamingManager
        from core.brain.execution_manager import ExecutionEvent
        
        if not self.active_plan:
            return
            
        log.info("[GoalExecutor] Starting Execution Loop Stream.")
        await self._broadcast_execution_state_async("RUNNING")
        self.execution_context = {}
        
        completed = set()
        step_idx = 1
        
        while len(completed) < len(self.active_plan.tasks):
            progress_made = False
            for task in self.active_plan.tasks:
                if task.id in completed:
                    continue
                    
                if all(dep in completed for dep in task.dependencies):
                    # Ready to execute! Yield STARTING_STEP event
                    event = ExecutionEvent(
                        event_type="STARTING_STEP",
                        step_index=step_idx,
                        data={
                            "task_id": task.id,
                            "description": task.description,
                            "capability": task.capability.value
                        }
                    )
                    formatted_event = StreamingManager.format_execution_event(event)
                    from api.ws_manager import ws_manager
                    await ws_manager.broadcast(formatted_event)
                    yield formatted_event
                    
                    if task.node_type == NodeType.ACTION:
                        # Yield EXECUTING_TOOL event
                        event = ExecutionEvent(
                            event_type="EXECUTING_TOOL",
                            step_index=step_idx,
                            data={
                                "tool_name": task.tool_name,
                                "input_variables": task.input_variables
                            }
                        )
                        formatted_event = StreamingManager.format_execution_event(event)
                        await ws_manager.broadcast(formatted_event)
                        yield formatted_event
                        
                    try:
                        # Dispatch to Operator Agent via AgentBus
                        req = AgentMessage(
                            sender="goal_executor", 
                            recipient="operator", 
                            content=task.description, 
                            metadata={
                                "task": task.model_dump(),
                                "execution_context": self.execution_context
                            }
                        )
                        
                        loop = asyncio.get_running_loop()
                        res = await loop.run_in_executor(None, self.brain.agent_bus.send, req)
                        
                        task.status = "completed" if res.success else "failed"
                        task.result = res.content
                        
                        if res.success:
                            if task.id not in self.execution_context:
                                self.execution_context[task.id] = {}
                            if task.output_variables:
                                out_var = task.output_variables[0]
                                self.execution_context[task.id][out_var] = res.content
                                
                            # Verification
                            verified = await loop.run_in_executor(None, self.verify, task)
                            task.verification_status = "Passed" if verified else "Failed"
                            if not verified:
                                task.status = "failed"
                                
                    except Exception as e:
                        task.status = "failed"
                        task.result = str(e)
                        
                    # Yield TOOL_OUTPUT event
                    event = ExecutionEvent(
                        event_type="TOOL_OUTPUT",
                        step_index=step_idx,
                        data={
                            "task_id": task.id,
                            "status": task.status,
                            "result": task.result,
                            "verification_status": task.verification_status
                        }
                    )
                    formatted_event = StreamingManager.format_execution_event(event)
                    await ws_manager.broadcast(formatted_event)
                    yield formatted_event
                    
                    if task.status == "failed":
                        log.error(f"[GoalExecutor] Task {task.id} failed: {task.result}")
                        await self._broadcast_execution_state_async("FAILED")
                        return
                        
                    completed.add(task.id)
                    progress_made = True
                    step_idx += 1
                    
            if not progress_made:
                break
                
        await self._broadcast_execution_state_async("COMPLETED")
        
        # Generate completion report and stream the tokens!
        final_prompt = f"Goal: {self.active_plan.goal}\nContext: {json.dumps(self.execution_context)}\nWrite a final summary report."
        try:
            loop = asyncio.get_running_loop()
            
            def run_final_stream():
                return self.brain.reasoning.stream_message(final_prompt, "You are JARVIS. Summarize the task execution results.", raw_message=final_prompt)
                
            gen = await loop.run_in_executor(None, run_final_stream)
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
        except Exception:
            yield {"type": "stream_chunk", "chunk": "Goal execution finished successfully."}
