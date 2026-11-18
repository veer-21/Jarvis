"""
JARVIS Brain — Custom Tool Quarantine & Validation Pipeline
Guarantees that newly generated or loaded tools undergo rigorous multi-stage validation:
GENERATE → WRITE TO QUARANTINE → AST/SYNTAX VALIDATION → COMPILE → STATIC SAFETY CHECKS → TOOL CONTRACT VALIDATION → ONLY THEN REGISTER.
"""

import ast
import os
import re
import json
import shutil
import inspect
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any

from core.logger import log, error_log
from core.security import RiskLevel


# Explicit allowlist of modules permitted in generated tools (P0-4)
ALLOWED_MODULES = {
    "math",
    "datetime",
    "re",
    "json",
    "collections",
    "itertools",
    "string",
    "random",
    "typing",
    "pydantic",
}

# Permitted runtime built-ins for pure-computation tools (P0-1)
ALLOWED_BUILTINS = {
    # Types and constructors
    "abs", "all", "any", "bin", "bool", "bytes", "chr", "complex", "dict", "divmod",
    "enumerate", "filter", "float", "format", "frozenset", "hash", "hex", "int",
    "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next",
    "oct", "ord", "pow", "range", "repr", "reversed", "round", "set", "slice",
    "sorted", "str", "sum", "tuple", "zip",
    # Framework and schema types
    "jarvis_tool", "RiskLevel", "BaseModel", "Field",
    # Standard math/lookup exceptions
    "ArithmeticError", "AssertionError", "AttributeError", "Exception", "FloatingPointError",
    "IndexError", "KeyError", "LookupError", "OverflowError", "RuntimeError",
    "StopIteration", "TypeError", "ValueError", "ZeroDivisionError",
    # Constants
    "True", "False", "None"
}

# Forbidden runtime functions, builtins, and dangerous identifiers (P0-1)
FORBIDDEN_NAMES = {
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
    "__builtins__",
    "breakpoint",
    "input",
    "object",
    "type",
    "super",
    "memoryview",
    "bytearray",
    "id",
    "help",
    "exit",
    "quit",
}

# Dunder attributes and reflective patterns used for introspection escapes (P0-1)
# Names of dangerous modules that allowed modules expose as attributes (typing.sys, random._os).
_FORBIDDEN_MODULE_ATTRS = {
    "os", "sys", "subprocess", "shutil", "socket", "ctypes", "importlib", "builtins",
    "pickle", "marshal", "io", "pathlib", "signal", "threading", "multiprocessing",
    "system", "popen", "spawn", "modules", "environ",
}

FORBIDDEN_REFLECTIVE_PATTERNS = {
    "__class__",
    "__mro__",
    "__subclasses__",
    "__globals__",
    "__builtins__",
    "__getattribute__",
    "__getattr__",
    "__setattr__",
    "__delattr__",
    "__reduce__",
    "__reduce_ex__",
    "__dict__",
    "__bases__",
    "__base__",
    "__code__",
    "__closure__",
    "__init_subclass__",
    "__import__",
}

# Reflective formatting APIs in string.Formatter and related field-resolution functions (P0-1)
FORBIDDEN_FORMATTER_APIS = {
    "Formatter",
    "vformat",
    "get_field",
    "get_value",
    "format_field",
    "convert_field",
    "parse",
    "check_unused_args",
}


def _extract_assigned_targets(target_node: ast.AST) -> set[str]:
    """Helper to extract variable names from assignment targets."""
    names = set()
    if isinstance(target_node, ast.Name):
        names.add(target_node.id)
    elif isinstance(target_node, (ast.Tuple, ast.List)):
        for elt in target_node.elts:
            names.update(_extract_assigned_targets(elt))
    elif isinstance(target_node, ast.Starred):
        names.update(_extract_assigned_targets(target_node.value))
    return names


def _evaluate_constant_expr(node: ast.AST, env: dict[str, Any]) -> Optional[Any]:
    """
    Recursively evaluate constant expressions: strings, ints, floats, lists, tuples,
    binary additions (strings, lists, tuples), joined strings, list/tuple joins,
    and variable lookups from the constant environment.
    """
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.Name):
        return env.get(node.id)
    elif isinstance(node, ast.List):
        elts = [_evaluate_constant_expr(elt, env) for elt in node.elts]
        if all(e is not None for e in elts):
            return elts
    elif isinstance(node, ast.Tuple):
        elts = [_evaluate_constant_expr(elt, env) for elt in node.elts]
        if all(e is not None for e in elts):
            return tuple(elts)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left_val = _evaluate_constant_expr(node.left, env)
        right_val = _evaluate_constant_expr(node.right, env)
        if isinstance(left_val, str) and isinstance(right_val, str):
            return left_val + right_val
        elif isinstance(left_val, list) and isinstance(right_val, list):
            return left_val + right_val
        elif isinstance(left_val, tuple) and isinstance(right_val, tuple):
            return left_val + right_val
    elif isinstance(node, ast.JoinedStr):
        parts = []
        for elt in node.values:
            val = _evaluate_constant_expr(elt, env)
            if val is not None:
                parts.append(str(val))
            else:
                return None
        return "".join(parts)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join":
        joiner = _evaluate_constant_expr(node.func.value, env)
        if isinstance(joiner, str) and node.args:
            parts_val = _evaluate_constant_expr(node.args[0], env)
            if isinstance(parts_val, (list, tuple)):
                if all(isinstance(p, str) for p in parts_val):
                    return joiner.join(parts_val)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn_id = node.func.id
        if fn_id == "chr" and node.args:
            arg_val = _evaluate_constant_expr(node.args[0], env)
            if isinstance(arg_val, int) and 0 <= arg_val <= 0x10ffff:
                return chr(arg_val)
        elif fn_id == "ord" and node.args:
            arg_val = _evaluate_constant_expr(node.args[0], env)
            if isinstance(arg_val, str) and len(arg_val) == 1:
                return ord(arg_val)
        elif fn_id == "str" and node.args:
            arg_val = _evaluate_constant_expr(node.args[0], env)
            if arg_val is not None:
                return str(arg_val)
        elif fn_id in ("list", "tuple") and node.args:
            arg_val = _evaluate_constant_expr(node.args[0], env)
            if isinstance(arg_val, (list, tuple)):
                return list(arg_val) if fn_id == "list" else tuple(arg_val)
        elif fn_id == "map" and len(node.args) >= 2:
            target_fn = node.args[0].id if isinstance(node.args[0], ast.Name) else None
            seq_val = _evaluate_constant_expr(node.args[1], env)
            if target_fn == "chr" and isinstance(seq_val, (list, tuple)):
                chars = []
                for item in seq_val:
                    if isinstance(item, int) and 0 <= item <= 0x10ffff:
                        chars.append(chr(item))
                    else:
                        return None
                return chars
            elif target_fn == "ord" and isinstance(seq_val, (list, tuple)):
                ords = []
                for item in seq_val:
                    if isinstance(item, str) and len(item) == 1:
                        ords.append(ord(item))
                    else:
                        return None
                return ords
            elif target_fn == "str" and isinstance(seq_val, (list, tuple)):
                return [str(item) for item in seq_val]
    elif isinstance(node, ast.ListComp) and len(node.generators) == 1:
        gen = node.generators[0]
        if isinstance(gen.target, ast.Name) and not gen.ifs:
            iter_val = _evaluate_constant_expr(gen.iter, env)
            if isinstance(iter_val, (list, tuple)):
                res = []
                for item in iter_val:
                    sub_env = dict(env)
                    sub_env[gen.target.id] = item
                    elt_val = _evaluate_constant_expr(node.elt, sub_env)
                    if elt_val is None:
                        return None
                    res.append(elt_val)
                return res
    return None


def _evaluate_constant_str(node: ast.AST, env: dict[str, Any]) -> Optional[str]:
    """Helper that returns a string result from _evaluate_constant_expr, or None."""
    val = _evaluate_constant_expr(node, env)
    return val if isinstance(val, str) else None


def _check_string_for_reflective_violations(val: str) -> Optional[str]:
    """
    Checks a string value (literal, folded, or format string) for forbidden reflective patterns.
    Returns error reason string if violation is detected, None if safe.
    """
    for pattern in FORBIDDEN_REFLECTIVE_PATTERNS:
        if pattern in val:
            return f"Security violation: reflective dunder pattern '{pattern}' detected in string expression."
    if re.search(r"__\w+__", val):
        return f"Security violation: dunder reflection pattern detected in string expression: '{val[:40]}'."
    # Format-field reflection access, e.g. {0.__class__}, {x.__mro__}, {.__globals__}
    if re.search(r"\{[^{}]*__\w+__[^{}]*\}", val):
        return f"Security violation: format-string dunder field access detected: '{val[:40]}'."
    # Format-field forbidden identifier access, e.g. {0.open}, {0.eval}
    for forbidden in FORBIDDEN_NAMES:
        if re.search(rf"\{{[^{{}}]*\b{re.escape(forbidden)}\b[^{{}}]*\}}", val):
            return f"Security violation: forbidden identifier '{forbidden}' detected in format-string field: '{val[:40]}'."
    return None


def validate_tool_source(source_code: str, filename: str = "<custom_tool>") -> tuple[bool, Optional[str], Optional[dict]]:
    """
    Multi-stage static validation of Python tool source code using strict AST analysis.
    AST validation is a static safety filter and contract gate, NOT an OS runtime sandbox.
    ALLOWED_BUILTINS and ALLOWED_MODULES are enforced strictly at static AST analysis time;
    the runtime loader executes via standard importlib without isolated builtins at runtime.

    Stages:
    1. AST / Syntax parsing
    2. Bytecode compilation check
    3. Static AST safety checks (strict module allowlist, forbidden runtime behaviors, escape vectors)
    4. Tool contract validation (public function exists, docstring present, valid signature)

    Returns:
        (is_valid: bool, error_reason: Optional[str], metadata: Optional[dict])
    """
    if not source_code or not source_code.strip():
        return False, "Tool source code is empty.", None

    # ── Stage 1: AST / Syntax Validation ──
    try:
        tree = ast.parse(source_code, filename=filename)
    except SyntaxError as syn_err:
        reason = f"Syntax error: {syn_err.msg} at line {syn_err.lineno}:{syn_err.offset}"
        return False, reason, None
    except Exception as e:
        return False, f"AST parsing failed: {str(e)}", None

    # ── Stage 2: Compilation Check ──
    try:
        compile(source_code, filename, "exec")
    except Exception as comp_err:
        return False, f"Bytecode compilation failed: {str(comp_err)}", None

    # ── Collect Docstrings to exclude legitimate documentation from string reflection checks ──
    docstring_nodes = set()
    mod_doc = ast.get_docstring(tree)
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant):
        docstring_nodes.add(id(tree.body[0].value))

    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.body and isinstance(item.body[0], ast.Expr) and isinstance(item.body[0].value, ast.Constant):
                docstring_nodes.add(id(item.body[0].value))

    # ── Collect Local Symbols (Parameters, local variables, imported aliases, function names) ──
    local_symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local_symbols.add(node.name)
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                local_symbols.add(arg.arg)
            if node.args.vararg:
                local_symbols.add(node.args.vararg.arg)
            if node.args.kwarg:
                local_symbols.add(node.args.kwarg.arg)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                local_symbols.update(_extract_assigned_targets(target))
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            if hasattr(node, "target"):
                local_symbols.update(_extract_assigned_targets(node.target))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            local_symbols.update(_extract_assigned_targets(node.target))
        elif isinstance(node, ast.comprehension):
            local_symbols.update(_extract_assigned_targets(node.target))
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                local_symbols.add(node.name)
        elif isinstance(node, ast.NamedExpr):
            local_symbols.update(_extract_assigned_targets(node.target))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_symbols.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local_symbols.add(alias.asname or alias.name)

    # ── Collect Constant Variable Assignments for Data-Flow Aware Constant Folding ──
    const_env: dict[str, Any] = {}
    for _ in range(5):  # Iterate to fixed point for chained constant assignments
        added = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        val = _evaluate_constant_expr(node.value, const_env)
                        if val is not None and const_env.get(target.id) != val:
                            const_env[target.id] = val
                            added = True
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value:
                    val = _evaluate_constant_expr(node.value, const_env)
                    if val is not None and const_env.get(node.target.id) != val:
                        const_env[node.target.id] = val
                        added = True
        if not added:
            break

    # ── Stage 3: Strict Static AST Safety Gate ──
    for node in ast.walk(tree):
        # 1. Strict Import Allowlist (ast.Import)
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod_root = alias.name.split('.')[0]
                if mod_root not in ALLOWED_MODULES:
                    return False, f"Security violation: module '{alias.name}' is not in the allowed import list ({sorted(ALLOWED_MODULES)}).", None

        # 2. Strict ImportFrom Allowlist (ast.ImportFrom)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                return False, "Security violation: relative imports are not permitted in custom tools.", None
            if not node.module:
                return False, "Security violation: import without module name is not permitted.", None
            mod_root = node.module.split('.')[0]
            if mod_root not in ALLOWED_MODULES:
                if node.module == "core.brain.tool_router":
                    for alias in node.names:
                        if alias.name not in ("jarvis_tool", "ToolSchema"):
                            return False, f"Security violation: forbidden import '{alias.name}' from '{node.module}'.", None
                elif node.module == "core.security":
                    for alias in node.names:
                        if alias.name not in ("RiskLevel",):
                            return False, f"Security violation: forbidden import '{alias.name}' from '{node.module}'.", None
                else:
                    return False, f"Security violation: module '{node.module}' is not in the allowed import list ({sorted(ALLOWED_MODULES)}).", None
            else:
                for alias in node.names:
                    if alias.name in FORBIDDEN_NAMES or alias.name in FORBIDDEN_FORMATTER_APIS or alias.name.startswith("__"):
                        return False, f"Security violation: forbidden import of '{alias.name}' detected.", None

        # 3. Forbidden Function Calls (ast.Call)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_NAMES or node.func.id in FORBIDDEN_FORMATTER_APIS or node.func.id.startswith("__"):
                    return False, f"Security violation: forbidden call '{node.func.id}()' detected.", None
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in FORBIDDEN_NAMES or node.func.attr in FORBIDDEN_FORMATTER_APIS or node.func.attr.startswith("__"):
                    return False, f"Security violation: forbidden call '{node.func.attr}()' detected.", None

        # 4. Comprehensive Dunder Attribute Access & Reflection (ast.Attribute)
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_NAMES or node.attr in FORBIDDEN_FORMATTER_APIS:
                return False, f"Security violation: forbidden attribute or reflective formatting API '{node.attr}' detected.", None
            if node.attr.startswith("__") or node.attr.endswith("__"):
                return False, f"Security violation: dunder attribute access '{node.attr}' is prohibited.", None
            # Allowed modules re-export dangerous ones through private or module-named
            # attributes (random._os, typing.sys, json.decoder.re ...). Tool code never needs
            # private attributes, nor to reach a module through another module's attributes.
            if node.attr.startswith("_"):
                return False, f"Security violation: forbidden private attribute access '{node.attr}' is prohibited.", None
            if node.attr in _FORBIDDEN_MODULE_ATTRS:
                return False, f"Security violation: forbidden access to module '{node.attr}' through an attribute is prohibited.", None

        # 5. Identifier & Runtime Name References (ast.Name)
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                return False, f"Security violation: dunder identifier '{node.id}' is prohibited.", None
            if node.id in FORBIDDEN_NAMES or node.id in FORBIDDEN_FORMATTER_APIS:
                return False, f"Security violation: forbidden reference to '{node.id}' detected.", None
            if isinstance(node.ctx, ast.Load):
                if (
                    node.id not in local_symbols
                    and node.id not in ALLOWED_BUILTINS
                    and node.id not in ALLOWED_MODULES
                ):
                    return False, f"Security violation: identifier '{node.id}' is not in the permitted built-ins, allowed modules, or local scope.", None

        # 6. String-Based Reflection, Introspection & Reconstructed Format Access
        evaluated_str = _evaluate_constant_str(node, const_env)
        if evaluated_str is not None and id(node) not in docstring_nodes:
            violation_reason = _check_string_for_reflective_violations(evaluated_str)
            if violation_reason:
                return False, violation_reason, None

        # 7. Format Calls (e.g. fmt.format(...), fmt.format_map(...), format(x, ...), string.Formatter)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in ("vformat", "get_field", "get_value", "format_field", "convert_field"):
                    return False, f"Security violation: reflective formatting API '{node.func.attr}()' is prohibited in custom tools.", None
                if node.func.attr in ("format", "format_map"):
                    fmt_caller = _evaluate_constant_str(node.func.value, const_env)
                    if fmt_caller is not None:
                        violation_reason = _check_string_for_reflective_violations(fmt_caller)
                        if violation_reason:
                            return False, violation_reason, None
                    else:
                        return False, f"Security violation: .{node.func.attr}() called on dynamic or unvalidated format string.", None
            elif isinstance(node.func, ast.Name) and node.func.id == "format" and node.args:
                if len(node.args) >= 2:
                    fmt_arg = _evaluate_constant_str(node.args[1], const_env)
                    if fmt_arg is not None:
                        violation_reason = _check_string_for_reflective_violations(fmt_arg)
                        if violation_reason:
                            return False, violation_reason, None
                    else:
                        return False, "Security violation: format() called with dynamic or unvalidated format spec.", None

    # ── Stage 4: Tool Contract Validation ──
    # Must have at least one top-level function that is not private
    public_functions = []
    for item in tree.body:
        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
            public_functions.append(item)

    if not public_functions:
        return False, "Tool contract violation: No public top-level function definition found.", None

    primary_fn = public_functions[0]
    docstring = ast.get_docstring(primary_fn)
    if not docstring or not docstring.strip():
        return False, f"Tool contract violation: Function '{primary_fn.name}' lacks a descriptive docstring.", None

    # Validate function arguments
    args = primary_fn.args
    param_names = [arg.arg for arg in args.args]
    if len(param_names) == 0 and (args.vararg or args.kwarg) and not docstring:
        return False, f"Tool contract violation: Function '{primary_fn.name}' has invalid signature.", None

    metadata = {
        "function_name": primary_fn.name,
        "docstring": docstring.strip(),
        "parameters": param_names,
        "all_public_functions": [fn.name for fn in public_functions],
    }

    return True, None, metadata


def validate_ast_safety(source_code: str, filename: str = "<custom_tool>") -> tuple[bool, Optional[str], Optional[dict]]:
    """
    AST Security Audit for synthesized tools.
    Verifies that the code contains no forbidden calls, unauthorized imports, or reflection exploits.
    """
    return validate_tool_source(source_code, filename=filename)


def dry_run_synthetic_execution(
    source_code: str,
    function_name: Optional[str] = None,
    synthetic_args: Optional[dict[str, Any]] = None,
    timeout_seconds: float = 5.0,
) -> tuple[bool, str, Any]:
    """
    Dry-run synthetic test execution of custom tool code inside an isolated namespace.
    Compiles code, instantiates callable, and tests execution with synthetic parameters.
    """
    # 1. Pre-execution AST safety check
    is_valid, reason, meta = validate_ast_safety(source_code, filename="<dry_run>")
    if not is_valid:
        return False, f"AST safety check failed: {reason}", None

    fn_name = function_name or (meta.get("function_name") if meta else None)
    if not fn_name:
        match = re.search(r"def\s+([a-zA-Z0-9_]+)\s*\(", source_code)
        fn_name = match.group(1) if match else None

    if not fn_name:
        return False, "Could not determine target function name for dry-run.", None

    # 2. Compile (cheap syntax check in-process; nothing is executed here)
    try:
        compile(source_code, "<dry_run>", "exec")
    except Exception as comp_err:
        return False, f"Dry-run compilation error: {comp_err}", None

    # 3. Execute in a separate, isolated interpreter with a hard timeout.
    #    LLM-written code must never run inside the JARVIS process: an infinite loop would hang
    #    it and any validator bypass would get full access to its memory and credentials.
    payload = json.dumps({
        "source": source_code,
        "fn_name": fn_name,
        "synthetic_args": synthetic_args or {},
        "allowed_builtins": sorted(ALLOWED_BUILTINS),
        "allowed_modules": sorted(ALLOWED_MODULES),
    })
    import sys
    import subprocess
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _DRY_RUN_CHILD],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return False, f"Dry-run timed out after {timeout_seconds:g}s (possible infinite loop).", None
    except Exception as spawn_err:
        return False, f"Dry-run sandbox could not start: {spawn_err}", None

    try:
        report = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except Exception:
        detail = (proc.stderr or proc.stdout or "no output").strip()[-300:]
        return False, f"Dry-run sandbox produced no result: {detail}", None

    if not report.get("ok"):
        return False, report.get("msg", "Dry-run failed."), None
    if "result_json" in report:
        return True, "Dry-run execution succeeded.", json.loads(report["result_json"])
    return True, "Dry-run execution succeeded.", report.get("result_repr")


# Runs in a fresh `python -I` child. Only allowlisted modules can be imported, builtins are
# restricted, and framework names (jarvis_tool, RiskLevel, ...) are inert stand-ins.
_DRY_RUN_CHILD = r"""
import sys, json, inspect, builtins

def _emit(obj):
    sys.stdout.write(chr(10) + json.dumps(obj))
    sys.stdout.flush()

req = json.loads(sys.stdin.read())
allowed_modules = set(req["allowed_modules"])
_real_import = builtins.__import__

FRAMEWORK_STUBS = ("core", "core.brain", "core.brain.tool_router", "core.security")

def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name in FRAMEWORK_STUBS:
        return sys.modules[name] if fromlist else sys.modules["core"]
    if level != 0 or name.split(".")[0] not in allowed_modules:
        raise ImportError(f"import of '{name}' is not allowed in custom tools")
    return _real_import(name, globals, locals, fromlist, level)

safe_builtins = {b: getattr(builtins, b) for b in req["allowed_builtins"] if hasattr(builtins, b)}
safe_builtins["__import__"] = _restricted_import
safe_builtins["__build_class__"] = builtins.__build_class__

class RiskLevel:
    READ_ONLY = SAFE = "READ_ONLY"
    LOW_RISK = LOW = "LOW_RISK"
    MODERATE_RISK = MEDIUM = "MODERATE_RISK"
    HIGH_RISK = HIGH = "HIGH_RISK"
    CRITICAL = CRITICAL_RISK = "CRITICAL"

def jarvis_tool(*args, **kwargs):
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]
    return lambda fn: fn

import types
for _mod_name in FRAMEWORK_STUBS:
    sys.modules[_mod_name] = types.ModuleType(_mod_name)
sys.modules["core"].brain = sys.modules["core.brain"]
sys.modules["core"].security = sys.modules["core.security"]
sys.modules["core.brain"].tool_router = sys.modules["core.brain.tool_router"]
sys.modules["core.brain.tool_router"].jarvis_tool = jarvis_tool
sys.modules["core.brain.tool_router"].ToolSchema = object
sys.modules["core.security"].RiskLevel = RiskLevel

ns = {"__builtins__": safe_builtins, "__name__": "custom_tool_dry_run",
      "jarvis_tool": jarvis_tool, "RiskLevel": RiskLevel, "ToolSchema": object}
for mod in ("math", "datetime", "re", "json", "collections", "itertools", "string", "random", "typing"):
    ns[mod] = _real_import(mod)
try:
    import pydantic
    ns["pydantic"] = pydantic
    ns["BaseModel"] = pydantic.BaseModel
    ns["Field"] = pydantic.Field
except ImportError:
    pass

try:
    exec(compile(req["source"], "<dry_run>", "exec"), ns)
except Exception as e:
    _emit({"ok": False, "msg": f"Dry-run module execution failed: {e}"}); sys.exit(0)

fn = ns.get(req["fn_name"])
if not fn or not callable(fn):
    _emit({"ok": False, "msg": f"Callable function '{req['fn_name']}' not found after execution."}); sys.exit(0)

defaults = {int: 1, "int": 1, float: 1.0, "float": 1.0, bool: True, "bool": True,
            list: [], "list": [], dict: {}, "dict": {}, str: "sample", "str": "sample"}
try:
    call_args = {}
    for p_name, param in inspect.signature(fn).parameters.items():
        if param.default is not inspect.Parameter.empty:
            continue
        call_args[p_name] = defaults.get(param.annotation, 1)
    call_args.update(req.get("synthetic_args") or {})
    result = fn(**call_args)
except Exception as e:
    _emit({"ok": False, "msg": f"Dry-run invocation failed: {type(e).__name__}: {e}"}); sys.exit(0)

try:
    _emit({"ok": True, "result_json": json.dumps(result)})
except Exception:
    _emit({"ok": True, "result_repr": repr(result)})
"""


DEFAULT_CUSTOM_DIR = Path(__file__).resolve().parent.parent.parent / "tools" / "custom"
# Single quarantine location used by the pipeline, ToolRouter.load_custom_tools and the Refiner.
QUARANTINE_DIRNAME = "_quarantine"
DEFAULT_QUARANTINE_DIR = DEFAULT_CUSTOM_DIR / QUARANTINE_DIRNAME


def resolve_tool_dir(requested: Optional[Any], default: Path) -> Path:
    """
    Resolve a custom-tool / quarantine directory, refusing locations outside the project's
    tools/custom tree (or the system temp dir, used by tests). These paths can arrive as
    LLM-supplied tool arguments, and writing generated code anywhere else (e.g. a Startup
    folder) would be a persistence vector.
    """
    import tempfile
    if requested is None:
        return default
    candidate = Path(requested).resolve()
    allowed_roots = [DEFAULT_CUSTOM_DIR.resolve(), Path(tempfile.gettempdir()).resolve()]
    for root in allowed_roots:
        if candidate == root or root in candidate.parents:
            return candidate
    raise ValueError(f"Refusing to write generated tools outside tools/custom: {candidate}")


def process_and_register_generated_tool(
    source_code: str,
    tool_router: Any,
    custom_dir: Path = DEFAULT_CUSTOM_DIR,
    quarantine_dir: Path = DEFAULT_QUARANTINE_DIR
) -> tuple[bool, str]:
    """
    Executes the full quarantine, validation, dry-run, and registration pipeline for generated tools:
    GENERATE → WRITE TO QUARANTINE → AST/SYNTAX VALIDATION → COMPILE → STATIC SAFETY CHECKS → DRY-RUN → ONLY THEN REGISTER.
    """
    try:
        custom_dir = resolve_tool_dir(custom_dir, DEFAULT_CUSTOM_DIR)
        quarantine_dir = resolve_tool_dir(quarantine_dir, custom_dir / QUARANTINE_DIRNAME)
    except ValueError as path_err:
        error_log.error(f"[CustomToolPipeline] {path_err}")
        return False, str(path_err)
    custom_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    timestamp =datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    match = re.search(r"def\s+([a-zA-Z0-9_]+)\s*\(", source_code)
    func_name = match.group(1) if match else f"unknown_tool_{timestamp}"

    # 1. Write to Quarantine
    quarantine_file = quarantine_dir / f"quarantine_{timestamp}_{func_name}.py.quarantine"
    with open(quarantine_file, "w", encoding="utf-8") as f:
        f.write(source_code)

    # 2-4. Run Multi-Stage AST Validation
    is_valid, reason, metadata = validate_ast_safety(source_code, filename=str(quarantine_file))
    if not is_valid:
        error_log.error(f"[CustomToolPipeline] Tool '{func_name}' rejected during quarantine validation: {reason}")
        rejection_meta = {
            "function_name": func_name,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "file": quarantine_file.name
        }
        meta_path = quarantine_dir / f"quarantine_{timestamp}_{func_name}.rejection.json"
        with open(meta_path, "w", encoding="utf-8") as mf:
            json.dump(rejection_meta, mf, indent=2)

        return False, f"Quarantined: {reason}"

    # Stage 5: Dry-Run Synthetic Test Execution
    dry_ok, dry_msg, _ = dry_run_synthetic_execution(source_code, function_name=func_name)
    if not dry_ok:
        error_log.error(f"[CustomToolPipeline] Tool '{func_name}' rejected during synthetic dry-run: {dry_msg}")
        rejection_meta = {
            "function_name": func_name,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "reason": f"Synthetic dry-run failed: {dry_msg}",
            "file": quarantine_file.name
        }
        meta_path = quarantine_dir / f"quarantine_{timestamp}_{func_name}.rejection.json"
        with open(meta_path, "w", encoding="utf-8") as mf:
            json.dump(rejection_meta, mf, indent=2)

        return False, f"Quarantined: Synthetic dry-run failed: {dry_msg}"

    # 6. Promoted from Quarantine to Registered Custom Directory
    target_file = custom_dir / f"{func_name}.py"
    with open(target_file, "w", encoding="utf-8") as tf:
        tf.write(source_code)

    # Clean up pending quarantine file on successful promotion
    try:
        quarantine_file.unlink(missing_ok=True)
    except Exception:
        pass

    # 7. Dynamically load and hot-reload into live ToolRouter
    loaded = tool_router.load_custom_tools(str(custom_dir))
    log.info(f"[CustomToolPipeline] Successfully validated and promoted '{func_name}.py' to live ToolRouter.")
    return True, f"Successfully validated and registered '{func_name}' ({loaded} custom tools online)."
