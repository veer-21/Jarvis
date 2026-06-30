"""
JARVIS Brain — Tool Router
Structured tool calling hub with schemas, permission checks,
execution validation, and dynamic tool discovery.
"""

from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from enum import Enum

from core.logger import log, error_log
from core.security import guard, RiskLevel


# ─── Tool Schema ──────────────────────────────────────────────────────────────

@dataclass
class ToolSchema:
    """Structured metadata for a registered tool."""
    name:                 str
    description:          str
    callable:             Callable
    category:             str = "general"
    risk_level:           RiskLevel = RiskLevel.SAFE
    requires_confirmation: bool = False
    timeout_seconds:      int = 30
    retry_allowed:        bool = True
    parameters:           dict = field(default_factory=dict)
    pydantic_model:       Any = None


class ToolRouter:
    """
    Central tool calling hub.
    Manages tool registration, routing, permission enforcement,
    and execution validation.
    """

    def __init__(self):
        self._registry: dict[str, ToolSchema] = {}
        self._categories: dict[str, list[str]] = {}
        log.info("ToolRouter initialized.")

    # ─── Registration ─────────────────────────────────────────────────────────

    def register(self, schema: ToolSchema) -> None:
        """Register a tool with its schema."""
        self._registry[schema.name] = schema

        # Track categories
        cat = schema.category
        if cat not in self._categories:
            self._categories[cat] = []
        if schema.name not in self._categories[cat]:
            self._categories[cat].append(schema.name)

        log.debug(f"Tool registered: {schema.name} [{cat}]")

    def register_callable(
        self,
        func: Callable,
        category: str = "general",
        risk_level: RiskLevel = RiskLevel.SAFE,
        requires_confirmation: bool = False,
        timeout_seconds: int = 30,
    ) -> None:
        """
        Register a plain callable as a tool, auto-extracting name and docstring.

        Args:
            func:                  The tool function.
            category:              Tool category for grouping.
            risk_level:            Security risk level.
            requires_confirmation: Whether to require user confirmation.
            timeout_seconds:       Execution timeout.
        """
        schema = ToolSchema(
            name=func.__name__,
            description=(func.__doc__ or "").strip().split("\n")[0],
            callable=func,
            category=category,
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
            timeout_seconds=timeout_seconds,
        )
        
        # Generate Pydantic Model dynamically
        import inspect
        from pydantic import create_model
        fields = {}
        sig = inspect.signature(func)
        for name, param in sig.parameters.items():
            param_type = param.annotation if param.annotation != inspect.Parameter.empty else Any
            default_val = param.default if param.default != inspect.Parameter.empty else ...
            fields[name] = (param_type, default_val)
        
        try:
            schema.pydantic_model = create_model(f"{func.__name__}Model", **fields)
        except Exception as e:
            log.warning(f"Could not generate Pydantic model for {func.__name__}: {e}")

        self.register(schema)

    def register_tools_from_module(self, module, category: str, risk_overrides: Optional[dict] = None) -> int:
        """
        Auto-register all public functions from a tool module.

        Args:
            module:         The module to scan for tool functions.
            category:       Category to assign to all tools from this module.
            risk_overrides: Optional dict of {function_name: RiskLevel} overrides.

        Returns:
            Number of tools registered.
        """
        count = 0
        overrides = risk_overrides or {}

        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name)
            if callable(attr) and hasattr(attr, "__name__"):
                # Skip classes, constants, etc.
                if isinstance(attr, type):
                    continue
                risk = overrides.get(attr_name, RiskLevel.SAFE)
                self.register_callable(
                    func=attr,
                    category=category,
                    risk_level=risk,
                    requires_confirmation=(risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)),
                )
                count += 1

        log.info(f"Registered {count} tools from module category: {category}")
        return count

    def load_custom_tools(self, custom_tools_dir: str = "tools/custom") -> int:
        """Dynamically load and register python scripts from tools/custom/"""
        import os
        import importlib.util
        from pathlib import Path
        
        custom_dir = Path(custom_tools_dir)
        if not custom_dir.exists():
            return 0
            
        count = 0
        for py_file in custom_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
                
            module_name = f"custom_tools_{py_file.stem}"
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec and spec.loader:
                try:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    # Custom tools default to HIGH risk since they are auto-generated
                    overrides = {}
                    for attr_name in dir(module):
                        if not attr_name.startswith("_"):
                            overrides[attr_name] = RiskLevel.HIGH
                    count += self.register_tools_from_module(module, category="custom", risk_overrides=overrides)
                except Exception as e:
                    error_log.error(f"Failed to load custom tool {py_file.name}: {e}")
                    
        if count > 0:
            log.info(f"Loaded {count} auto-generated tools from {custom_tools_dir}")
        return count

    # ─── Discovery ────────────────────────────────────────────────────────────

    def get_tool(self, name: str) -> Optional[ToolSchema]:
        """Look up a tool by name."""
        return self._registry.get(name)

    def get_all_callables(self, categories: Optional[list[str]] = None) -> list[Callable]:
        """Return registered tool callables wrapped to use execute_tool, optionally filtered by category."""
        import inspect
        import functools
        
        callables = []
        for schema in self._registry.values():
            if categories and schema.category not in categories:
                continue
            def make_wrapper(s):
                original = s.callable
                sig = inspect.signature(original)
                
                @functools.wraps(original)
                def wrapper(*args, **kwargs):
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    res = self.execute_tool(s.name, bound.arguments, interactive=False)
                    if res["success"]:
                        return str(res["result"])
                    else:
                        return f"Action Failed: {res.get('error', 'Unknown Error')}"
                return wrapper
                
            callables.append(make_wrapper(schema))
        return callables

    def get_categories(self) -> dict[str, list[str]]:
        """Return tool categories mapping for prompt composition."""
        return dict(self._categories)

    @property
    def tool_count(self) -> int:
        return len(self._registry)

    # ─── Execution ────────────────────────────────────────────────────────────

    def execute_tool(
        self,
        name: str,
        args: dict,
        interactive: bool = True,
    ) -> dict[str, Any]:
        """
        Execute a tool with permission checks and audit logging.

        Args:
            name:        Tool name to execute.
            args:        Arguments to pass to the tool.
            interactive: Whether user confirmation is available.

        Returns:
            Dict with keys: success, result, error
        """
        schema = self._registry.get(name)
        if not schema:
            return {"success": False, "result": None, "error": f"Tool '{name}' not found in registry."}

        # Validate arguments using Pydantic
        if schema.pydantic_model:
            from pydantic import ValidationError
            try:
                validated = schema.pydantic_model(**args)
                args = validated.model_dump()
            except ValidationError as e:
                return {"success": False, "result": None, "error": f"Validation Error: {e.errors()}"}

        # Permission check for risky tools
        if schema.risk_level not in (RiskLevel.SAFE, RiskLevel.LOW):
            # For system commands, use the security guard
            command_str = args.get("command", str(args))
            allowed, reason = guard.check_command(command_str, interactive=interactive)
            if not allowed:
                log.warning(f"Tool '{name}' blocked: {reason}")
                return {"success": False, "result": None, "error": f"Blocked: {reason}"}

        # Emit WebSocket event
        try:
            import asyncio
            from api.ws_manager import ws_manager
            
            async def _emit():
                await ws_manager.send_execution_event(name, str(args)[:200])
                
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_emit())
            else:
                asyncio.run(_emit())
        except Exception:
            pass

        # Execute
        try:
            result = schema.callable(**args)
            result_summary = str(result)[:200]

            # Audit log
            guard.log_tool_execution(name, args, result_summary)
            log.info(f"Tool executed: {name} → {result_summary[:80]}")

            return {"success": True, "result": result, "error": None}

        except Exception as e:
            error_msg = f"Tool '{name}' failed: {str(e)}"
            error_log.error(error_msg)
            return {"success": False, "result": None, "error": error_msg}

    def execute_tool_safe(self, name: str, args: dict) -> str:
        """
        Execute a tool and return result as string. Safe wrapper for LLM tool calls.

        Args:
            name: Tool name.
            args: Tool arguments.

        Returns:
            String result or error message.
        """
        result = self.execute_tool(name, args)
        if result["success"]:
            return str(result["result"])
        return f"Error: {result['error']}"

    # ─── Introspection ────────────────────────────────────────────────────────

    def list_tools(self) -> list[dict]:
        """Return a summary list of all registered tools."""
        return [
            {
                "name":     s.name,
                "category": s.category,
                "risk":     s.risk_level.value,
                "description": s.description,
            }
            for s in self._registry.values()
        ]
