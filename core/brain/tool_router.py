"""
JARVIS Brain — Tool Router
Structured tool calling hub with schemas, permission checks,
execution validation, and dynamic tool discovery.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from enum import Enum

from core.logger import log, error_log
from core.security import guard, RiskLevel
from core.brain.tool_contract import ToolContract, ToolExecutionResult, ConfirmationPolicy, RetryPolicy
from core.brain.verifier import ResultVerifier


# ─── Tool Schema ──────────────────────────────────────────────────────────────

@dataclass
class ToolSchema:
    """Structured metadata for a registered tool."""
    name:                 str
    description:          str
    callable:             Callable
    category:             str = "general"
    risk_level:           RiskLevel = RiskLevel.READ_ONLY
    requires_confirmation: bool = False
    confirmation_policy:  ConfirmationPolicy = ConfirmationPolicy.NEVER
    timeout_seconds:      int = 30
    retry_allowed:        bool = True
    retry_policy:         RetryPolicy = RetryPolicy.RETRY_ONCE
    reversible:           bool = False
    parameters:           dict = field(default_factory=dict)
    pydantic_model:       Any = None


class ToolRouter:
    """
    Central tool calling hub.
    Manages tool registration, routing, permission enforcement,
    and execution validation.
    """

    def __init__(self):
        import concurrent.futures
        self._registry: dict[str, ToolSchema] = {}
        self._categories: dict[str, list[str]] = {}
        self._worker_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="jarvis_tool_worker")
        self._session_affine_running: dict[str, Any] = {}
        log.info("ToolRouter initialized.")

    def _is_session_affine(self, name: str, schema: Optional[ToolSchema]) -> bool:
        """Identify if a tool requires single-threaded affinity (Playwright / COM / Win32)."""
        if not schema:
            return False
        cat = getattr(schema, "category", "").lower()
        if cat in ("browser", "desktop", "automation"):
            return True
        return any(k in name.lower() for k in ("browser", "window", "mouse", "keyboard", "screenshot", "screen"))

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

    def register_contract(self, contract: Any) -> None:
        """Register a ToolContract canonical declaration."""
        self.register(contract)

    def register_callable(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: str = "general",
        risk_level: RiskLevel = RiskLevel.SAFE,
        requires_confirmation: bool = False,
        timeout_seconds: int = 30,
    ) -> None:
        """
        Register a plain callable as a tool, auto-extracting name and docstring.

        Args:
            func:                  The tool function.
            name:                  Optional tool name override.
            description:           Optional description override.
            category:              Tool category for grouping.
            risk_level:            Security risk level.
            requires_confirmation: Whether to require user confirmation.
            timeout_seconds:       Execution timeout.
        """
        tool_name = name or getattr(func, "__name__", "custom_tool")
        tool_desc = description or (func.__doc__ or "").strip().split("\n")[0]
        schema = ToolSchema(
            name=tool_name,
            description=tool_desc,
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
        """Dynamically load and register python scripts from tools/custom/ after multi-stage validation."""
        import os
        import importlib.util
        from pathlib import Path
        from core.brain.custom_tool_pipeline import validate_tool_source
        
        custom_dir = Path(custom_tools_dir)
        if not custom_dir.exists():
            return 0
            
        quarantine_dir = custom_dir / "_quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        count = 0

        for py_file in custom_dir.glob("*.py"):
            if py_file.name == "__init__.py" or py_file.parent.name == "_quarantine":
                continue

            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    source_code = f.read()
            except Exception as read_err:
                error_log.error(f"Cannot read custom tool file {py_file.name}: {read_err}")
                continue

            # Run validation pipeline
            is_valid, reason, _ = validate_tool_source(source_code, filename=str(py_file))
            if not is_valid:
                error_log.error(f"Rejecting custom tool {py_file.name} due to contract failure: {reason}. Quarantining.")
                # Move to quarantine
                quarantined_dest = quarantine_dir / f"quarantined_{py_file.name}"
                try:
                    import shutil
                    shutil.move(str(py_file), str(quarantined_dest))
                except Exception as move_err:
                    error_log.error(f"Failed to move rejected file {py_file.name} to quarantine: {move_err}")
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
                    error_log.error(f"Failed to load validated custom tool {py_file.name}: {e}")
                    
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
        cancellation_token: Optional[Any] = None,
    ) -> ToolExecutionResult:
        """
        Authoritative single execution pathway for ALL tools.
        Enforces schema validation, single security policy gate, interactive confirmation,
        perceptual/deterministic post-condition verification, and structured audit trails.

        Args:
            name:               Tool name to execute.
            args:               Arguments to pass to the tool.
            interactive:        Whether user confirmation is available.
            cancellation_token: Optional threading.Event to abort execution.

        Returns:
            ToolExecutionResult with success, output, evidence, error, verified, reversible.
        """
        t_start = time.perf_counter()

        if cancellation_token and hasattr(cancellation_token, "is_set") and cancellation_token.is_set():
            return ToolExecutionResult(
                success=False,
                status="CANCELLED",
                output=None,
                error="Tool execution cancelled by user directive."
            )

        schema = self._registry.get(name)
        if not schema:
            return ToolExecutionResult(
                success=False,
                status="FAILED",
                output=None,
                error=f"Tool '{name}' not found in registry."
            )

        # 1. Validate arguments using Pydantic
        if schema.pydantic_model:
            from pydantic import ValidationError
            try:
                validated = schema.pydantic_model(**args)
                args = validated.model_dump()
            except ValidationError as e:
                return ToolExecutionResult(
                    success=False,
                    status="FAILED",
                    output=None,
                    error=f"Validation Error: {e.errors()}"
                )

        # 2. Single Policy Decision Point
        allowed, eff_risk, req_confirm, reason = guard.evaluate_tool_execution(
            tool_name=name,
            args=args,
            declared_risk=schema.risk_level,
            interactive=interactive
        )
        if not allowed:
            log.warning(f"Tool '{name}' blocked: {reason}")
            return ToolExecutionResult(
                success=False,
                status="BLOCKED",
                output=None,
                error=f"Blocked: {reason}",
                evidence={"risk_level": eff_risk.value, "reason": reason}
            )

        # Check session affinity for GUI / Browser tools to prevent concurrent overlap
        from core.brain.task_model import current_execution_context
        ctx = current_execution_context.get()
        session_id = ctx.session_id if ctx and ctx.session_id else "default"

        is_affine = self._is_session_affine(name, schema)
        affine_key = f"{session_id}:{schema.category}" if is_affine else None

        if is_affine and affine_key:
            active_fut = self._session_affine_running.get(affine_key)
            if active_fut is not None and not active_fut.done():
                return ToolExecutionResult(
                    success=False,
                    status="BLOCKED",
                    timed_out=False,
                    cleanup_succeeded=False,
                    output=None,
                    error=f"Session-affine operation '{name}' blocked: a previous operation on session '{session_id}' is still active."
                )

        # 3. Thread-safe WebSocket execution event delivery
        try:
            from api.ws_manager import ws_manager
            from core.brain.task_model import current_execution_context
            exec_ctx = current_execution_context.get()
            event_payload = {
                "type": "execution_event",
                "event_type": "tool_executing",
                "tool": name,
                "args": str(args)[:200]
            }
            if exec_ctx and exec_ctx.session_id:
                ws_manager.safe_send_to_session(exec_ctx.session_id, event_payload)
            else:
                log.debug(f"Skipping private tool execution broadcast for '{name}'; no authenticated owning session.")
        except Exception as emit_err:
            log.debug(f"Could not emit tool execution event: {emit_err}")

        # 4. Execute tool with timeout enforcement and cooperative deadlines
        import concurrent.futures
        import inspect
        timeout_sec = schema.timeout_seconds if hasattr(schema, "timeout_seconds") and schema.timeout_seconds else 30

        # Inspect if tool supports cooperative cancellation or deadline
        sig = inspect.signature(schema.callable)
        call_kwargs = dict(args)
        if "cancellation_token" in sig.parameters and "cancellation_token" not in call_kwargs:
            call_kwargs["cancellation_token"] = cancellation_token
        if "deadline" in sig.parameters and "deadline" not in call_kwargs:
            call_kwargs["deadline"] = time.time() + timeout_sec

        try:
            future = self._worker_pool.submit(schema.callable, **call_kwargs)
            if is_affine and affine_key:
                self._session_affine_running[affine_key] = future

            try:
                result = future.result(timeout=timeout_sec)
            except concurrent.futures.TimeoutError:
                elapsed_ms = (time.perf_counter() - t_start) * 1000.0
                error_msg = f"Tool '{name}' execution timed out after {timeout_sec}s."
                error_log.error(error_msg)
                
                # Signal cooperative cancellation if available
                if cancellation_token and hasattr(cancellation_token, "set"):
                    cancellation_token.set()

                # Clean up session resources to prevent worker corruption
                cleanup_ok = True
                if schema.category == "browser" or "browser" in name:
                    try:
                        from tools.browser_tools import close_browser
                        close_browser()
                    except Exception as b_err:
                        error_log.warning(f"Browser cleanup after timeout encountered error: {b_err}")
                        cleanup_ok = False

                # We preserve the worker pool without shutdown(wait=False).
                # Session-affine operations block overlap until the background thread completes or terminates.
                return ToolExecutionResult(
                    success=False,
                    status="TIMED_OUT",
                    timed_out=True,
                    cleanup_succeeded=cleanup_ok,
                    output=None,
                    error=error_msg,
                    execution_time_ms=elapsed_ms
                )

            if cancellation_token and hasattr(cancellation_token, "is_set") and cancellation_token.is_set():
                return ToolExecutionResult(
                    success=False,
                    status="CANCELLED",
                    output=None,
                    error="Tool execution cancelled by user directive."
                )

            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            result_summary = str(result)[:200]

            # 5. Deterministic post-condition verification
            ver_res = ResultVerifier.verify_tool_result(name, args, result)

            # Audit log with secret masking
            guard.log_tool_execution(name, args, result_summary)
            log.info(f"Tool executed: {name} [{elapsed_ms:.1f}ms, verified={ver_res.verified}, level={ver_res.level.value}] → {result_summary[:80]}")

            is_error_str = isinstance(result, str) and (
                result.startswith("Error") or
                result.startswith("Failed") or
                "process not found" in result.lower() or
                "error fetching webpage" in result.lower() or
                "error navigating" in result.lower()
            )

            # If post-conditions were unverified or tool returned error, fail execution
            if not ver_res.verified or is_error_str:
                err_detail = ver_res.details if (ver_res.details and not ver_res.verified) else (str(result) if is_error_str else f"Tool '{name}' failed verification.")
                return ToolExecutionResult(
                    success=False,
                    status="FAILED",
                    timed_out=False,
                    output=result,
                    evidence=ver_res.evidence,
                    verified=ver_res.verified,
                    reversible=getattr(schema, "reversible", False),
                    execution_time_ms=elapsed_ms,
                    error=err_detail
                )

            return ToolExecutionResult(
                success=True,
                status="COMPLETED",
                timed_out=False,
                output=result,
                evidence=ver_res.evidence,
                verified=ver_res.verified,
                reversible=getattr(schema, "reversible", False),
                execution_time_ms=elapsed_ms,
                error=None
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            error_msg = f"Tool '{name}' failed: {str(e)}"
            error_log.error(error_msg)
            return ToolExecutionResult(
                success=False,
                status="FAILED",
                timed_out=False,
                output=None,
                error=error_msg,
                execution_time_ms=elapsed_ms
            )

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
