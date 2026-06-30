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
        Process an optimization request.
        """
        if not self.brain or not self.brain.memory_manager:
            return AgentResponse(success=False, content="Memory manager is offline.", agent="refiner")

        try:
            return self._optimize_workflows()
        except Exception as e:
            error_log.error(f"RefinerAgent failed: {e}")
            return AgentResponse(success=False, content=f"Optimization failed: {e}", agent="refiner")

    def _optimize_workflows(self) -> AgentResponse:
        log.info("RefinerAgent started workflow optimization cycle.")
        
        # 1. Fetch recent tasks from memory
        db = self.brain.memory_manager._memory
        if not db:
            return AgentResponse(success=False, content="ChromaDB offline.", agent="refiner")
            
        # We search for "Task executed" in memory to find recent workflows
        results = db.retrieve_memories("Task executed", top_k=10)
        if not results:
            return AgentResponse(success=True, content="No recent complex tasks found to optimize.", agent="refiner")
            
        # 2. Extract task patterns
        # For a simple local implementation, we'll ask the LLM to review the logs and generate code.
        log_text = "\n".join([f"- {r['content']}" for r in results])
        
        prompt = f"""
You are the JARVIS Refiner Agent. Your goal is to write a single Python function that automates a repetitive task found in the user's recent execution history.

Recent Task History:
{log_text}

Instructions:
1. Identify if there is a common multi-step task the user performs.
2. If there is, write a complete Python function that automates this workflow using standard libraries (os, subprocess, requests, etc).
3. The function must have a clear docstring.
4. Output ONLY the raw Python code. Do not include markdown blocks like ```python. Do not include explanations.

Example Output:
def fetch_daily_briefing():
    \"\"\"Fetches the top news and current weather.\"\"\"
    import requests
    # ... implementation
    return "Briefing complete."
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
        filepath = os.path.join(self.custom_tools_dir, f"{func_name}.py")
        
        # 5. Save the new tool!
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(generated_code)
            
        log.info(f"RefinerAgent successfully generated new tool: {func_name}")
        
        # 6. Dynamically reload tools in the active router
        count = self.brain.tools.load_custom_tools(self.custom_tools_dir)
        
        return AgentResponse(
            success=True, 
            content=f"Successfully analyzed memory and generated 1 new tool: {func_name}.py. Registered {count} total custom tools.",
            agent="refiner"
        )
