"""
JARVIS Sandboxed Streaming Code REPL Engine (Phase 2)
Stateful, persistent Python & PowerShell runtime environments with live output streaming.

Inspired by openinterpreter:
Maintains in-memory state (variables, imports, functions, directories) across consecutive calls,
with AST-level safety evaluation, real-time chunk streaming, and timeout isolation.
"""

import os
import sys
import json
import uuid
import time
import queue
import threading
import subprocess
from pathlib import Path
from typing import Optional, Any, Dict, List, Callable
from pydantic import BaseModel, Field

from core.logger import log, error_log

# ─── Pydantic Parameter Schemas ───────────────────────────────────────────────

class ReplExecutePythonArgs(BaseModel):
    code: str = Field(..., description="Python source code to execute inside the persistent REPL environment.")
    timeout: int = Field(default=30, description="Execution timeout in seconds (default: 30s).")

class ReplExecutePowerShellArgs(BaseModel):
    command: str = Field(..., description="PowerShell command or script block to execute inside the persistent PowerShell session.")
    timeout: int = Field(default=30, description="Execution timeout in seconds (default: 30s).")

class ReplResetSessionArgs(BaseModel):
    target: str = Field(default="all", description="Target session to reset: 'python', 'powershell', or 'all'.")


# ─── Python Persistent Worker Script ─────────────────────────────────────────

_WORKER_BOOTSTRAP = r"""
import sys
import json
import traceback

user_globals = {
    "__name__": "__main__",
    "__builtins__": __builtins__
}

class StreamCapture:
    def __init__(self, stream_type):
        self.stream_type = stream_type

    def write(self, text):
        if text:
            msg = json.dumps({"type": self.stream_type, "text": text})
            sys.__stdout__.write(msg + "\n")
            sys.__stdout__.flush()

    def flush(self):
        sys.__stdout__.flush()

sys.stdout = StreamCapture("stdout")
sys.stderr = StreamCapture("stderr")

while True:
    line = sys.__stdin__.readline()
    if not line:
        break
    try:
        req = json.loads(line)
        code = req.get("code", "")
        # Compile in exec mode
        compiled = compile(code, "<repl>", "exec")
        exec(compiled, user_globals)
        sys.__stdout__.write(json.dumps({"type": "done", "success": True, "error": None}) + "\n")
    except Exception as e:
        tb = traceback.format_exc()
        sys.__stdout__.write(json.dumps({"type": "done", "success": False, "error": str(e), "traceback": tb}) + "\n")
    sys.__stdout__.flush()
"""


# ─── Persistent Python REPL Session ──────────────────────────────────────────

class PersistentPythonSession:
    """
    Manages a long-running, stateful Python subprocess with real-time JSON-RPC streaming.
    Preserves module imports, variables, and defined functions between tool calls.
    """

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._execution_count = 0

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return

        py_exe = sys.executable
        # Start persistent python worker
        self._proc = subprocess.Popen(
            [py_exe, "-u", "-q", "-c", _WORKER_BOOTSTRAP],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        self._execution_count = 0
        log.info(f"[REPL] Spawned stateful Python worker process (PID: {self._proc.pid}).")

    def execute(self, code: str, timeout: int = 30, stream_callback: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        with self._lock:
            self._ensure_started()
            if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
                return {"success": False, "error": "Failed to start Python worker process."}

            self._execution_count += 1
            exec_id = self._execution_count

            # Prepare JSON payload
            payload = json.dumps({"code": code, "exec_id": exec_id}) + "\n"
            try:
                self._proc.stdin.write(payload)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self.reset()
                return {"success": False, "error": f"Failed writing to REPL process pipe: {e}"}

            output_chunks: List[str] = []
            error_details: Optional[str] = None
            traceback_str: Optional[str] = None
            is_success = False

            # Read with timeout using queue/thread
            q: queue.Queue = queue.Queue()

            def reader():
                while True:
                    line = self._proc.stdout.readline()
                    if not line:
                        break
                    try:
                        parsed = json.loads(line)
                        q.put(parsed)
                        if parsed.get("type") == "done":
                            break
                    except Exception:
                        q.put({"type": "stdout", "text": line})

            t = threading.Thread(target=reader, daemon=True)
            t.start()

            start_time = time.time()
            deadline = start_time + max(1, timeout)

            while time.time() < deadline:
                remaining = max(0.1, deadline - time.time())
                try:
                    event = q.get(timeout=remaining)
                    event_type = event.get("type")

                    if event_type in ("stdout", "stderr"):
                        chunk = event.get("text", "")
                        output_chunks.append(chunk)
                        if stream_callback:
                            try:
                                stream_callback(chunk)
                            except Exception:
                                pass
                    elif event_type == "done":
                        is_success = event.get("success", False)
                        error_details = event.get("error")
                        traceback_str = event.get("traceback")
                        break
                except queue.Empty:
                    # Timeout exceeded
                    break

            elapsed = round(time.time() - start_time, 3)

            # Check if timed out
            if not is_success and error_details is None and time.time() >= deadline:
                log.warning(f"[REPL] Python execution timed out after {timeout}s (PID: {self._proc.pid}). Terminating worker.")
                self.reset()
                return {
                    "success": False,
                    "error": f"Execution timed out after {timeout} seconds.",
                    "output": "".join(output_chunks),
                    "execution_count": exec_id,
                    "elapsed_seconds": elapsed
                }

            full_output = "".join(output_chunks)
            return {
                "success": is_success,
                "output": full_output,
                "error": error_details,
                "traceback": traceback_str,
                "execution_count": exec_id,
                "elapsed_seconds": elapsed
            }

    def reset(self) -> bool:
        """Terminate the current Python worker process and clear all session state."""
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=2)
                except Exception:
                    pass
                self._proc = None
            log.info("[REPL] Reset stateful Python session.")
            return True


# ─── Persistent PowerShell REPL Session ──────────────────────────────────────

class PersistentPowerShellSession:
    """
    Manages a persistent PowerShell subprocess for Windows administrative scripting.
    Preserves functions, variable bindings, and working directory across tool calls.
    """

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._execution_count = 0

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return

        self._proc = subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        self._execution_count = 0
        log.info(f"[REPL] Spawned stateful PowerShell worker process (PID: {self._proc.pid}).")

    def execute(self, command: str, timeout: int = 30, stream_callback: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        with self._lock:
            self._ensure_started()
            if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
                return {"success": False, "error": "Failed to start PowerShell worker process."}

            self._execution_count += 1
            exec_id = self._execution_count
            token = f"__JARVIS_PS_SENTINEL_{uuid.uuid4().hex}__"

            # Wrap command to output sentinel delimiter
            script_block = f"{command}\nWrite-Output '{token}'\n"
            try:
                self._proc.stdin.write(script_block)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self.reset()
                return {"success": False, "error": f"Failed writing to PowerShell pipe: {e}"}

            output_lines: List[str] = []
            q: queue.Queue = queue.Queue()

            def reader():
                while True:
                    line = self._proc.stdout.readline()
                    if not line:
                        break
                    clean = line.rstrip("\r\n")
                    if clean == token:
                        q.put({"type": "done"})
                        break
                    q.put({"type": "line", "text": line})

            t = threading.Thread(target=reader, daemon=True)
            t.start()

            start_time = time.time()
            deadline = start_time + max(1, timeout)
            is_done = False

            while time.time() < deadline:
                remaining = max(0.1, deadline - time.time())
                try:
                    event = q.get(timeout=remaining)
                    if event.get("type") == "line":
                        txt = event.get("text", "")
                        output_lines.append(txt)
                        if stream_callback:
                            try:
                                stream_callback(txt)
                            except Exception:
                                pass
                    elif event.get("type") == "done":
                        is_done = True
                        break
                except queue.Empty:
                    break

            elapsed = round(time.time() - start_time, 3)

            if not is_done and time.time() >= deadline:
                log.warning(f"[REPL] PowerShell execution timed out after {timeout}s. Terminating worker.")
                self.reset()
                return {
                    "success": False,
                    "error": f"PowerShell execution timed out after {timeout} seconds.",
                    "output": "".join(output_lines),
                    "execution_count": exec_id,
                    "elapsed_seconds": elapsed
                }

            full_output = "".join(output_lines)
            return {
                "success": True,
                "output": full_output,
                "execution_count": exec_id,
                "elapsed_seconds": elapsed
            }

    def reset(self) -> bool:
        """Terminate the current PowerShell worker process and clear environment state."""
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=2)
                except Exception:
                    pass
                self._proc = None
            log.info("[REPL] Reset stateful PowerShell session.")
            return True


# ─── Global Singleton Sessions ────────────────────────────────────────────────

_python_session = PersistentPythonSession()
_powershell_session = PersistentPowerShellSession()


# ─── Primary Tool Functions ───────────────────────────────────────────────────

def repl_execute_python(code: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Execute Python code in a persistent stateful REPL session.
    Variables, functions, and imports persist across calls.
    """
    # Pre-execution AST safety check
    try:
        from core.security import guard, RiskLevel
        risk, reasons = guard.assess_python_code_risk(code)
        if risk == RiskLevel.CRITICAL:
            log.error(f"[REPL] Blocked CRITICAL Python execution: {reasons}")
            return {
                "success": False,
                "error": f"Security policy blocked execution (Critical Risk): {'; '.join(reasons)}",
                "risk_level": risk.value
            }
    except Exception as e:
        log.warning(f"[REPL] Security pre-check bypassed with error: {e}")

    return _python_session.execute(code, timeout=timeout)


def repl_execute_powershell(command: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Execute PowerShell commands or scripts in a persistent stateful shell session.
    Directory state ($PWD), environment variables, and functions persist across calls.
    """
    # Pre-execution command risk check
    try:
        from core.security import guard, RiskLevel
        risk = guard.assess_command_risk(command)
        if risk == RiskLevel.CRITICAL:
            log.error(f"[REPL] Blocked CRITICAL PowerShell command: {command}")
            return {
                "success": False,
                "error": f"Security policy blocked execution (Critical Risk command detected).",
                "risk_level": risk.value
            }
    except Exception as e:
        log.warning(f"[REPL] Security pre-check bypassed with error: {e}")

    return _powershell_session.execute(command, timeout=timeout)


def repl_reset_session(target: str = "all") -> Dict[str, Any]:
    """
    Reset one or all persistent REPL sessions (Python, PowerShell, or both).
    """
    t_clean = target.lower().strip()
    res = {}
    if t_clean in ("python", "all"):
        res["python"] = _python_session.reset()
    if t_clean in ("powershell", "ps", "all"):
        res["powershell"] = _powershell_session.reset()

    return {
        "success": True,
        "reset_target": target,
        "details": res
    }

