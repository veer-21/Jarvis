"""
JARVIS System Tools
Provides system command execution with integrated security checks.

Uses the SecurityGuard from core.security for risk assessment
instead of maintaining a duplicate dangerous commands list.
"""

import subprocess

from core.logger import log, error_log
from core.security import guard


def execute_command(command: str) -> str:
    """Execute a system command on the user's PC. Dangerous commands require explicit confirmation.

    Args:
        command: The shell command string to execute.
    """
    # Security check through the central guard
    allowed, reason = guard.check_command(command, interactive=True)
    if not allowed:
        log.warning(f"Command blocked: {command} — {reason}")
        return f"Command execution blocked: {reason}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Audit log the execution
        output = result.stdout if result.returncode == 0 else result.stderr
        guard.log_tool_execution("execute_command", {"command": command}, output[:200])

        if result.returncode == 0:
            return f"Success:\n{result.stdout}"
        else:
            return f"Error (exit code {result.returncode}):\n{result.stderr}"

    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 30 seconds."
    except Exception as e:
        error_log.error(f"Command execution failed: {e}")
        return f"Execution failed: {str(e)}"