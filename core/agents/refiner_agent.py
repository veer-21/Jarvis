"""
JARVIS Refiner Agent
Analyzes recent memory to detect repetitive multi-step tasks and writes
custom Python tools to automate them instantly.
"""

import os
from typing import Optional
from core.logger import log, error_log
from core.agents.base_agent import BaseAgent, AgentMessage, AgentResponse, AgentRole

class RefinerAgent(BaseAgent):
    """
    Self-Improving workflow agent.
    Scans memory for complex tasks and uses the LLM to generate optimized Python tools.
    """

    def __init__(self, brain=None):
        super().__init__(name="refiner", role=AgentRole.TOOL)
        self.brain = brain
        self.custom_tools_dir = os.path.join("tools", "custom")

    def process(self, message: AgentMessage) -> AgentResponse:
        """
        Process an optimization request scoped to the authenticated caller owner (P0-1, P0-4).
        """
        if not self.brain or not self.brain.memory_manager:
            return AgentResponse(success=False, content="Memory manager is offline.", agent="refiner")

        user_id = message.user_id
        is_system = getattr(message, "system_authorized", False)
        if not user_id and not is_system:
            return AgentResponse(
                success=False,
                content="Workflow optimization requires a verified user owner identity.",
                agent="refiner",
                error="UNAUTHORIZED_MISSING_OWNER"
            )

        try:
            return self._optimize_workflows(user_id=user_id, allow_system_scope=is_system)
        except Exception as e:
            error_log.error(f"RefinerAgent failed: {e}")
            return AgentResponse(success=False, content=f"Optimization failed: {e}", agent="refiner")

    def _optimize_workflows(self, user_id: Optional[str] = None, allow_system_scope: bool = False) -> AgentResponse:
        log.info(f"RefinerAgent started workflow optimization cycle for user={user_id} (allow_system_scope={allow_system_scope}).")
        
        # 1. Fetch recent tasks from memory scoped to owner
        db = self.brain.memory_manager._memory
        if not db:
            return AgentResponse(success=False, content="ChromaDB offline.", agent="refiner")
            
        # We search for "Task executed" or "Task" in memory to find recent workflows for this owner
        results = db.retrieve_memories("Task executed", top_k=10, category="task", user_id=user_id, allow_system_scope=allow_system_scope)
        if not results:
            results = db.retrieve_memories("Task", top_k=10, category="task", user_id=user_id, allow_system_scope=allow_system_scope)
        if not results:
            return AgentResponse(success=True, content="No recent complex tasks found to optimize.", agent="refiner")
            
        # 2. Extract task patterns
        # For a simple local implementation, we'll ask the LLM to review the logs and generate code.
        log_text = "\n".join([f"- {r['content']}" for r in results])
        
        prompt = f"""
You are the JARVIS Refiner Agent. Your goal is to write a single Python function that automates a repetitive calculation, data parsing, or text processing task found in the user's recent execution history.

Recent Task History:
{log_text}

Security and Implementation Constraints:
1. ONLY use allowed standard modules: math, datetime, re, json, collections, itertools, string, random, typing.
2. DO NOT use os, pathlib, subprocess, requests, httpx, ctypes, socket, or any filesystem/network/process libraries.
3. DO NOT use open(), eval(), exec(), compile(), __import__(), object, type, or reflection builtins.
4. DO NOT use any dunder attributes, reflection, or introspection (e.g. __getattribute__, __setattr__, __class__, __subclasses__, __mro__, __globals__, __dict__).
5. The function must have a clear docstring and type annotations.
6. Output ONLY the raw Python code. Do not include markdown blocks like ```python. Do not include explanations.

Example Output:
def format_meeting_notes(raw_notes: str) -> dict:
    \"\"\"Parses raw notes and extracts timestamps and action items.\"\"\"
    import re
    import datetime
    return {{"summary": raw_notes[:100], "processed_at": str(datetime.datetime.now())}}
"""
        
        # 3. Use reasoning engine to generate code
        generated_code = self.brain.reasoning.send_message(prompt)
        generated_code = generated_code.replace("```python", "").replace("```", "").strip()
        
        if not generated_code or "def " not in generated_code:
            return AgentResponse(success=True, content="No clear automation pattern detected.", agent="refiner")
            
        # 4. Extract function name to use as filename
        import re
        match = re.search(r"def\s+([a-zA-Z0-9_]+)\s*\(", generated_code)
        if not match:
            return AgentResponse(success=True, content="Generated code lacked a valid function name.", agent="refiner")
            
        func_name = match.group(1)
        
        # 5. Route through custom tool quarantine validation pipeline
        from pathlib import Path
        from core.brain.custom_tool_pipeline import process_and_register_generated_tool
        custom_dir = Path(self.custom_tools_dir)
        quarantine_dir = custom_dir / "_quarantine"
        
        success, report = process_and_register_generated_tool(
            source_code=generated_code,
            tool_router=self.brain.tools,
            custom_dir=custom_dir,
            quarantine_dir=quarantine_dir
        )

        if not success:
            return AgentResponse(
                success=False,
                content=f"Generated tool '{func_name}' failed validation and was quarantined: {report}",
                agent="refiner"
            )

        log.info(f"RefinerAgent successfully generated and validated new tool: {func_name}")
        return AgentResponse(
            success=True, 
            content=f"Successfully analyzed memory and validated new tool: {func_name}.py. {report}",
            agent="refiner"
        )

