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


def schedule_task(task_description: str, delay_minutes: float = 60.0) -> str:
    """
    Schedule an autonomous task to run in the background after a specified delay in minutes.

    Args:
        task_description: The goal or prompt for JARVIS to execute (e.g., 'Take a screenshot and summarize system vitals').
        delay_minutes: How many minutes from now to run the task (e.g. 5, 60, 300 for 5 hours).
    """
    try:
        from core.daemon import ProactiveDaemon
        # Singleton/default scheduler instance helper
        delay_seconds = float(delay_minutes) * 60.0
        from core.daemon_instance import get_daemon
        daemon = get_daemon()
        return daemon.schedule_job(task_description, delay_seconds)
    except Exception as e:
        return f"Failed to schedule task: {str(e)}"


def list_scheduled_tasks() -> str:
    """
    List all pending scheduled autonomous tasks.
    """
    try:
        from core.daemon_instance import get_daemon
        daemon = get_daemon()
        jobs = daemon.list_scheduled_jobs()
        if not jobs:
            return "No scheduled tasks pending."
        lines = [f"- [{j['id']}] '{j['task']}' scheduled for {j['scheduled_time_str']}" for j in jobs]
        return "Pending Scheduled Tasks:\n" + "\n".join(lines)
    except Exception as e:
        return f"Failed to list scheduled tasks: {str(e)}"