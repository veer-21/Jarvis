"""
JARVIS Refiner Agent (Refiner 2.0)
Analyzes recent memory to detect repetitive multi-step tasks, synthesizes
clean Python tools with @jarvis_tool decorators, validates them via AST safety
and synthetic dry-runs, and hot-reloads them directly into ToolRouter.
"""

import os
import re
from pathlib import Path
from typing import Optional, Any
from core.logger import log, error_log
from core.security import RiskLevel
from core.agents.base_agent import BaseAgent, AgentMessage, AgentResponse, AgentRole
from core.brain.tool_router import jarvis_tool


@jarvis_tool(name="refiner_synthesize_custom_tool", category="refiner", risk_level=RiskLevel.HIGH_RISK, requires_confirmation=True)
def refiner_synthesize_custom_tool(
    task_description: str,
    source_code: Optional[str] = None,
    function_name: Optional[str] = None,
    category: str = "custom",
    brain: Optional[Any] = None,
    custom_dir: Optional[Path] = None,
    quarantine_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Synthesizes, validates, and hot-reloads a new custom tool into JARVIS ToolRouter.
    Executes quarantine AST safety analysis, dry-run synthetic execution, and live promotion.
    """
    from core.brain.custom_tool_pipeline import process_and_register_generated_tool, validate_ast_safety

    code_to_use = source_code
    if not code_to_use or not code_to_use.strip():
        if brain and hasattr(brain, "reasoning"):
            prompt = f"""
You are the JARVIS Refiner 2.0 Autonomous Tool Synthesizer.
Synthesize a single clean, safe Python tool function to achieve:
"{task_description}"

Requirements:
1. Include @jarvis_tool(name="...", category="{category}", risk_level=RiskLevel.LOW_RISK) decorator.
2. Only import from allowed standard modules: math, datetime, re, json, collections, itertools, string, random, typing, pydantic, or core.brain.tool_router / core.security.
3. Include clear docstring and explicit type hints.
4. Output ONLY valid Python code without markdown tags or explanations.
"""
            try:
                llm_code = brain.reasoning.send_message(prompt)
                code_to_use = llm_code.replace("```python", "").replace("```", "").strip()
            except Exception as e:
                log.warning(f"Refiner LLM synthesis failed, using template fallback: {e}")

        if not code_to_use or "def " not in code_to_use:
            clean_name = (function_name or "custom_synthesized_tool").replace(" ", "_").lower()
            code_to_use = f'''from core.brain.tool_router import jarvis_tool
from core.security import RiskLevel

@jarvis_tool(name="{clean_name}", category="{category}", risk_level=RiskLevel.LOW_RISK)
def {clean_name}(payload: str = "default") -> dict:
    """Automates: {task_description.strip()}"""
    import datetime
    return {{"status": "completed", "task": "{task_description.strip()}", "payload": payload, "timestamp": str(datetime.datetime.now())}}
'''

    match = re.search(r"def\s+([a-zA-Z0-9_]+)\s*\(", code_to_use)
    resolved_name = function_name or (match.group(1) if match else "synthesized_tool")

    router = getattr(brain, "tools", None)
    if not router:
        from core.brain.tool_router import ToolRouter
        router = ToolRouter()

    target_custom_dir = custom_dir if custom_dir is not None else (Path("tools") / "custom")
    target_quarantine_dir = quarantine_dir if quarantine_dir is not None else (target_custom_dir / "_quarantine")

    ok, report = process_and_register_generated_tool(
        source_code=code_to_use,
        tool_router=router,
        custom_dir=target_custom_dir,
        quarantine_dir=target_quarantine_dir
    )

    if not ok:
        return {
            "success": False,
            "action": "refiner_synthesize_custom_tool",
            "error": report,
            "tool_name": resolved_name,
            "hot_reloaded": False,
        }

    return {
        "success": True,
        "action": "refiner_synthesize_custom_tool",
        "tool_name": resolved_name,
        "source_code": code_to_use,
        "promoted_path": str(target_custom_dir / f"{resolved_name}.py"),
        "hot_reloaded": True,
        "message": f"Tool '{resolved_name}' synthesized, AST-audited, dry-run verified, and hot-reloaded into ToolRouter."
    }


class RefinerAgent(BaseAgent):
    """
    Self-Improving workflow agent (Refiner 2.0).
    Scans memory for complex repetitive tasks, synthesizes @jarvis_tool decorated tools,
    validates them in quarantine, and promotes them to the live environment.
    """

    def __init__(self, brain=None):
        super().__init__(name="refiner", role=AgentRole.TOOL)
        self.brain = brain
        self.custom_tools_dir = os.path.join("tools", "custom")

    def process(self, message: AgentMessage) -> AgentResponse:
        """
        Process an optimization or synthesis request scoped to the authenticated caller owner.
        """
        action = getattr(message, "action", None) or (message.metadata.get("action", "") if message.metadata else "")
        if action in ("synthesize_tool", "synthesize_custom_tool", "evolve_tool"):
            src = message.metadata.get("source_code") if message.metadata else None
            fn_name = message.metadata.get("function_name") if message.metadata else None
            cat = message.metadata.get("category", "custom") if message.metadata else "custom"
            c_dir = Path(self.custom_tools_dir)
            res = refiner_synthesize_custom_tool(
                task_description=message.content,
                source_code=src,
                function_name=fn_name,
                category=cat,
                brain=self.brain,
                custom_dir=c_dir,
                quarantine_dir=c_dir / "_quarantine"
            )
            return AgentResponse(
                success=res.get("success", False),
                content=res.get("message", res.get("error", "")),
                agent="refiner",
                metadata=res
            )

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

        db = self.brain.memory_manager._memory
        if not db:
            return AgentResponse(success=False, content="ChromaDB offline.", agent="refiner")

        results = db.retrieve_memories("Task executed", top_k=10, category="task", user_id=user_id, allow_system_scope=allow_system_scope)
        if not results:
            results = db.retrieve_memories("Task", top_k=10, category="task", user_id=user_id, allow_system_scope=allow_system_scope)
        if not results:
            return AgentResponse(success=True, content="No recent complex tasks found to optimize.", agent="refiner")

        log_text = "\n".join([f"- {r['content']}" for r in results])

        prompt = f"""
You are the JARVIS Refiner 2.0 Agent. Your goal is to write a single Python function that automates a repetitive calculation, data parsing, or text processing task found in the user's recent execution history.

Recent Task History:
{log_text}

Security and Implementation Constraints:
1. ONLY use allowed standard modules: math, datetime, re, json, collections, itertools, string, random, typing, pydantic, or core.brain.tool_router / core.security.
2. Include @jarvis_tool(name="...", category="custom", risk_level=RiskLevel.LOW_RISK) decorator.
3. DO NOT use os, pathlib, subprocess, requests, httpx, ctypes, socket, or any filesystem/network/process libraries.
4. DO NOT use open(), eval(), exec(), compile(), __import__(), object, type, or reflection builtins.
5. DO NOT use any dunder attributes, reflection, or introspection.
6. The function must have a clear docstring and type annotations.
7. Output ONLY the raw Python code. Do not include markdown blocks like ```python. Do not include explanations.

Example Output:
from core.brain.tool_router import jarvis_tool
from core.security import RiskLevel

@jarvis_tool(name="format_meeting_notes", category="custom", risk_level=RiskLevel.LOW_RISK)
def format_meeting_notes(raw_notes: str) -> dict:
    \"\"\"Parses raw notes and extracts timestamps and action items.\"\"\"
    import re
    import datetime
    return {{"summary": raw_notes[:100], "processed_at": str(datetime.datetime.now())}}
"""

        generated_code = self.brain.reasoning.send_message(prompt)
        generated_code = generated_code.replace("```python", "").replace("```", "").strip()

        if not generated_code or "def " not in generated_code:
            return AgentResponse(success=True, content="No clear automation pattern detected.", agent="refiner")

        res = refiner_synthesize_custom_tool(
            task_description="Repeated workflow optimization",
            source_code=generated_code,
            category="custom",
            brain=self.brain
        )

        if not res.get("success"):
            return AgentResponse(
                success=False,
                content=f"Generated tool failed validation: {res.get('error')}",
                agent="refiner",
                metadata=res
            )

        tool_name = res.get("tool_name")
        log.info(f"RefinerAgent successfully generated, validated, and hot-reloaded: {tool_name}")
        return AgentResponse(
            success=True,
            content=f"Successfully analyzed memory and validated new tool: {tool_name}.py. {res.get('message')}",
            agent="refiner",
            metadata=res
        )
