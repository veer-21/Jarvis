"""
JARVIS Brain — Task History Persistence Store
Safely persists task lifecycle records across application restarts without secret exposure.
"""

import os
import json
import threading
from pathlib import Path
from typing import Optional, Any
from core.logger import log, error_log
from core.security import mask_sensitive_data

class TaskStore:
    """
    Thread-safe persistent store for completed, failed, and cancelled tasks.
    Saves to data/tasks/task_history.json.
    """

    def __init__(self, storage_path: str = "data/tasks/task_history.json"):
        self.storage_path = Path(storage_path)
        self._lock = threading.Lock()
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Create storage directory and initial file if missing."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.storage_path.exists():
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump([], f)
        except Exception as e:
            error_log.error(f"[TaskStore] Failed to initialize storage: {e}")

    def save_task(self, task: Any) -> bool:
        """
        Save or update a task record in the persistent history.
        Scrubs secrets automatically before saving.
        """
        task_data = task.to_dict() if hasattr(task, "to_dict") else mask_sensitive_data(dict(task))
        # Ensure plan and audit_trail are serialized cleanly
        clean_task = mask_sensitive_data(task_data)

        with self._lock:
            try:
                tasks = self._read_all_unlocked()
                # Find and replace existing task, or append
                idx = next((i for i, t in enumerate(tasks) if t.get("task_id") == clean_task.get("task_id")), -1)
                if idx >= 0:
                    tasks[idx] = clean_task
                else:
                    tasks.append(clean_task)

                # Keep max 500 recent tasks to bound file size
                if len(tasks) > 500:
                    tasks = tasks[-500:]

                # Write atomically via temp file
                temp_path = self.storage_path.with_suffix(".tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(tasks, f, indent=2)
                os.replace(temp_path, self.storage_path)
                return True
            except Exception as e:
                error_log.error(f"[TaskStore] Failed to save task {clean_task.get('task_id')}: {e}")
                return False

    def get_task(self, task_id: str) -> Optional[dict]:
        """Retrieve a specific task by its task_id."""
        with self._lock:
            tasks = self._read_all_unlocked()
            return next((t for t in tasks if t.get("task_id") == task_id), None)

    def list_tasks(
        self,
        limit: int = 50,
        status: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> list[dict]:
        """Retrieve recent task history, newest first, filtered by user and session ownership."""
        with self._lock:
            tasks = self._read_all_unlocked()
            if status:
                tasks = [t for t in tasks if t.get("status") == status]
            if user_id is not None:
                tasks = [t for t in tasks if t.get("user_id") == user_id]
            if session_id is not None:
                tasks = [t for t in tasks if t.get("session_id") == session_id]
            # Reverse order for newest first
            return list(reversed(tasks[-limit:]))

    def clear(self) -> bool:
        """Clear task history."""
        with self._lock:
            try:
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump([], f)
                return True
            except Exception as e:
                error_log.error(f"[TaskStore] Failed to clear tasks: {e}")
                return False

    def _read_all_unlocked(self) -> list[dict]:
        """Read all tasks without acquiring lock (internal use)."""
        if not self.storage_path.exists():
            return []
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

# Singleton instance
task_store = TaskStore()
