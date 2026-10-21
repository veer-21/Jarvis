"""
JARVIS Proactive System Daemon
Continuously runs in the background to monitor system health, detect anomalies,
and deliver proactive notifications or briefings without waiting for user commands.
"""

import time
import threading
from datetime import datetime
from typing import Callable, Optional
from core.logger import log, error_log

class ProactiveDaemon:
    """
    Background worker that runs routine system diagnostic checks and proactive actions.
    """

    def __init__(
        self,
        notify_fn: Optional[Callable[[str], None]] = None,
        health_interval_seconds: int = 180,    # Check system vitals every 3 mins
        briefing_interval_seconds: int = 3600, # Check briefing status every hour
    ):
        self.notify_fn = notify_fn
        self.health_interval = health_interval_seconds
        self.briefing_interval = briefing_interval_seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Thresholds
        self.cpu_threshold = 90.0
        self.ram_threshold = 92.0
        self.disk_threshold = 95.0

        # State tracking to avoid spamming alerts
        self._last_alert_time: dict[str, float] = {}
        self._last_briefing_date: Optional[str] = None

        # Scheduled jobs list: list of dicts {id, task_desc, run_at_timestamp, executed}
        self._scheduled_jobs: list[dict] = []
        self._job_lock = threading.Lock()

    def schedule_job(self, task_description: str, delay_seconds: float) -> str:
        """Schedule an autonomous task to be executed after delay_seconds."""
        import uuid
        job_id = str(uuid.uuid4())[:8]
        run_at = time.time() + delay_seconds
        scheduled_time_str = datetime.fromtimestamp(run_at).strftime("%Y-%m-%d %H:%M:%S")

        with self._job_lock:
            self._scheduled_jobs.append({
                "id": job_id,
                "task": task_description,
                "run_at": run_at,
                "scheduled_time_str": scheduled_time_str,
                "executed": False,
            })
        log.info(f"[ProactiveDaemon] Scheduled job {job_id} ('{task_description}') at {scheduled_time_str}")
        return f"Job '{job_id}' scheduled for {scheduled_time_str} (in {delay_seconds:.0f}s)."

    def list_scheduled_jobs(self) -> list[dict]:
        """Return all pending scheduled jobs."""
        with self._job_lock:
            return [j for j in self._scheduled_jobs if not j["executed"]]

    def start(self) -> None:
        """Start the proactive background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="JarvisProactiveDaemon")
        self._thread.start()
        log.info("ProactiveDaemon started in background.")

    def stop(self) -> None:
        """Stop the proactive background daemon thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        log.info("ProactiveDaemon stopped.")

    def _run_loop(self) -> None:
        """Main background loop."""
        last_health_check = 0.0
        last_briefing_check = 0.0

        while self._running:
            now = time.time()

            # 1. Check scheduled jobs
            self._check_scheduled_jobs(now)

            # 2. Health monitoring
            if now - last_health_check >= self.health_interval:
                try:
                    self._check_system_health()
                except Exception as e:
                    error_log.error(f"[ProactiveDaemon] Health check error: {e}")
                last_health_check = now

            # 3. Briefing / Scheduled check
            if now - last_briefing_check >= self.briefing_interval:
                try:
                    self._check_daily_briefing()
                except Exception as e:
                    error_log.error(f"[ProactiveDaemon] Briefing check error: {e}")
                last_briefing_check = now

            time.sleep(2.0)

    def _check_scheduled_jobs(self, current_time: float) -> None:
        """Execute any jobs whose time has arrived."""
        due_jobs = []
        with self._job_lock:
            for job in self._scheduled_jobs:
                if not job["executed"] and current_time >= job["run_at"]:
                    job["executed"] = True
                    due_jobs.append(job)

        for job in due_jobs:
            task_desc = job["task"]
            self._alert(f"Executing scheduled task: '{task_desc}'")
            try:
                # Run the task through the brain if available
                from core.brain.brain import Brain
                from tools.automation_tools import prevent_windows_sleep
                import threading
                def _execute():
                    # 1. Prevent Windows from sleeping during the task
                    prevent_windows_sleep(True)
                    start_time = datetime.now()
                    try:
                        brain = Brain()
                        result = brain.execute_task(task_desc)
                        self._alert(f"Scheduled task '{task_desc}' finished: {result[:120]}")
                        
                        # 2. Write Unattended Activity Audit Trail
                        from pathlib import Path
                        log_dir = Path(__file__).parent.parent / "logs"
                        log_dir.mkdir(parents=True, exist_ok=True)
                        unattended_file = log_dir / "unattended_activity.md"
                        
                        duration = (datetime.now() - start_time).total_seconds()
                        entry = (
                            f"\n## 📋 Scheduled Task Report — {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"- **Goal:** {task_desc}\n"
                            f"- **Duration:** {duration:.1f} seconds\n"
                            f"- **Status:** Completed Successfully ✅\n"
                            f"- **Summary:**\n```\n{result[:1000]}\n```\n"
                            f"{'─'*50}\n"
                        )
                        with open(unattended_file, "a", encoding="utf-8") as f:
                            f.write(entry)
                    except Exception as e:
                        error_log.error(f"Scheduled job execution failed: {e}")
                    finally:
                        prevent_windows_sleep(False)

                threading.Thread(target=_execute, daemon=True).start()
            except Exception as e:
                error_log.error(f"Failed to launch scheduled task: {e}")

    def _check_system_health(self) -> None:
        """Inspect CPU, RAM, and Disk for critical load."""
        try:
            import psutil
        except ImportError:
            return

        now = time.time()
        cooldown = 900  # 15 min cooldown per metric alert

        # CPU Check
        cpu_pct = psutil.cpu_percent(interval=None)
        if cpu_pct > self.cpu_threshold:
            if now - self._last_alert_time.get("cpu", 0) > cooldown:
                self._alert(f"Warning: Sustained CPU usage is critically high at {cpu_pct}%.")
                self._last_alert_time["cpu"] = now

        # RAM Check
        ram = psutil.virtual_memory()
        if ram.percent > self.ram_threshold:
            if now - self._last_alert_time.get("ram", 0) > cooldown:
                self._alert(f"Warning: System memory load is high at {ram.percent}% ({ram.used / 1e9:.1f} GB used).")
                self._last_alert_time["ram"] = now

        # Disk Check
        disk = psutil.disk_usage("C:\\")
        if disk.percent > self.disk_threshold:
            if now - self._last_alert_time.get("disk", 0) > cooldown:
                self._alert(f"Caution: Primary drive C: is almost full ({disk.percent}% used).")
                self._last_alert_time["disk"] = now

    def _check_daily_briefing(self) -> None:
        """Deliver a brief morning status report between 8 AM and 11 AM once per day."""
        current_hour = datetime.now().hour
        today = datetime.now().strftime("%Y-%m-%d")

        if 8 <= current_hour <= 11 and self._last_briefing_date != today:
            self._last_briefing_date = today
            briefing = self.generate_briefing()
            self._alert(briefing)

    def generate_briefing(self) -> str:
        """Generate a concise proactive system overview."""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage("C:\\").percent
            date_str = datetime.now().strftime("%A, %B %d")
            return f"Good morning, sir. Today is {date_str}. All JARVIS core systems are operating normally. CPU is at {cpu}%, RAM at {ram}%, and Disk at {disk}%."
        except Exception:
            return "Good morning, sir. All JARVIS core subsystems are online and operational."

    def _alert(self, message: str) -> None:
        """Dispatch notification to console, voice, or registered callback."""
        log.info(f"[ProactiveDaemon Notification]: {message}")
        if self.notify_fn:
            try:
                self.notify_fn(message)
            except Exception as e:
                error_log.error(f"[ProactiveDaemon] Failed to dispatch notification: {e}")
        else:
            print(f"\n[JARVIS Proactive Alert] 🔔 {message}\n")
