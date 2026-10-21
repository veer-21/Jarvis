"""
JARVIS — Operator Agent
Specialized deterministic agent for OS, filesystem, and browser manipulations.
No secondary LLM planning or tool choosing occurs here.
"""

import json
from core.agents.base_agent import BaseAgent, AgentRole, AgentMessage, AgentResponse
from core.agents.vision_abstraction import VisionScreenUnderstanding
from core.logger import log, error_log

class OperatorAgent(BaseAgent):
    """
    Deterministic execution layer with perceptual verification.
    Implements a Perception-Planning-Action loop for OS and desktop actions.
    """

    def __init__(self, tool_router, brain=None):
        super().__init__("operator", AgentRole.TOOL)
        self.tool_router = tool_router
        self._brain = brain
        self.vision = VisionScreenUnderstanding(brain=brain)
        log.info("OperatorAgent initialized with Perception-Planning-Action execution loop.")

    def process(self, message: AgentMessage) -> AgentResponse:
        """Process incoming execution requests with perception and state verification."""
        task_data = message.metadata.get("task")
        execution_context = message.metadata.get("execution_context", {})
        
        if not task_data:
            return AgentResponse(success=False, content="No task data provided.", agent=self.name)
            
        node_type = task_data.get("node_type", "action")
        task_id = task_data.get("id", "unknown")
        expected_state = task_data.get("expected_state")
        
        log.info(f"[OperatorAgent] Executing {node_type} Task {task_id}: {task_data.get('description')}")
        
        try:
            # 1. Resolve variables
            resolved_args = self._resolve_variables(task_data, execution_context)
            
            # 2. Execute based on node_type
            if node_type == "action":
                tool_name = task_data.get("tool_name")
                if not tool_name:
                    return AgentResponse(success=False, content="Missing tool_name for action node.", agent=self.name)
                
                # Check for target application focus requirement
                target_window = resolved_args.pop("target_window", None)
                if target_window:
                    from tools.automation_tools import focus_window
                    log.info(f"[OperatorAgent] Pre-action: Focusing window '{target_window}'")
                    focus_window(target_window)

                # Check if target element requires visual coordinate grounding
                element_desc = resolved_args.pop("target_element", None)
                if element_desc and tool_name == "click_mouse":
                    coords = self.vision.find_element(element_desc)
                    if coords:
                        resolved_args["x"] = coords["x"]
                        resolved_args["y"] = coords["y"]
                        log.info(f"[OperatorAgent] Grounded '{element_desc}' to coordinates ({coords['x']}, {coords['y']})")
                    else:
                        log.warning(f"[OperatorAgent] Could not visually ground element: '{element_desc}'")
                    
                result = self.tool_router.execute_tool(name=tool_name, args=resolved_args, interactive=True)
                
                if result["success"]:
                    # Post-action perceptual verification if requested
                    if expected_state:
                        verified = self.vision.verify_state(expected_state)
                        if not verified:
                            log.warning(f"[OperatorAgent] Task {task_id} completed action but failed perceptual verification for: {expected_state}")
                    return AgentResponse(success=True, content=str(result["result"]), agent=self.name)
                else:
                    return AgentResponse(success=False, content=str(result.get("error")), agent=self.name, error=str(result.get("error")))
            
            elif node_type == "reasoning":
                if not self._brain:
                    return AgentResponse(success=False, content="Brain required for reasoning nodes.", agent=self.name)
                
                # Direct inference call for data transformation
                prompt = (
                    f"Perform the following reasoning/transformation task.\n"
                    f"Task: {task_data.get('description')}\n"
                    f"Input Variables: {json.dumps(resolved_args, indent=2)}\n"
                    "Output strictly the final result. Do not include conversational filler."
                )
                try:
                    res = self._brain.reasoning._fallback_generate(prompt)
                    return AgentResponse(success=True, content=res, agent=self.name)
                except Exception as e:
                    return AgentResponse(success=False, content=str(e), agent=self.name, error=str(e))
                    
            else:
                return AgentResponse(success=False, content=f"Unknown node_type: {node_type}", agent=self.name)
                
        except Exception as e:
            return AgentResponse(
                success=False,
                content=str(e),
                agent=self.name,
                error=str(e)
            )

    def _resolve_variables(self, task: dict, execution_context: dict) -> dict:
        import re
        resolved_args = {}
        pattern = re.compile(r"\{\{([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\}\}")
        
        def interpolate(value):
            if isinstance(value, str):
                matches = pattern.findall(value)
                if not matches:
                    return value
                    
                # Exact match - Preserve underlying object type
                if len(matches) == 1 and value.strip() == f"{{{{{matches[0][0]}.{matches[0][1]}}}}}":
                    task_id, var_name = matches[0]
                    if task_id not in execution_context:
                        raise ValueError(f"Missing dependency context: task '{task_id}'")
                    if var_name not in execution_context[task_id]:
                        raise ValueError(f"Missing output variable: '{var_name}' from task '{task_id}'")
                    return execution_context[task_id][var_name]
                
                # String interpolation
                result_str = value
                for task_id, var_name in matches:
                    if task_id not in execution_context:
                        raise ValueError(f"Missing dependency context: task '{task_id}'")
                    if var_name not in execution_context[task_id]:
                        raise ValueError(f"Missing output variable: '{var_name}' from task '{task_id}'")
                    
                    replacement = str(execution_context[task_id][var_name])
                    result_str = result_str.replace(f"{{{{{task_id}.{var_name}}}}}", replacement)
                return result_str
                
            elif isinstance(value, dict):
                return {k: interpolate(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [interpolate(v) for v in value]
            return value

        input_vars = task.get("input_variables", {})
        for key, val in input_vars.items():
            resolved_args[key] = interpolate(val)
            
        return resolved_args
