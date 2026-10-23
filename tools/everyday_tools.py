"""
JARVIS Everyday Tools Suite (Phase 4.1)
Consumer-friendly tools for everyday Windows users:
- smart_organize_folder: Automated smart downloads/desktop decluttering with undo
- undo_folder_organization: 1-click restore from undo manifest
- create_reminder_or_timer: Persistent reminders with Windows Toast & WebSocket triggers
- list_and_manage_reminders: List, cancel, or clear active timers and reminders
- control_windows_setting: Friendly OS controls (volume, task manager, settings, recycle bin)
- summarize_local_document: PDF, Word docx, CSV, TXT, MD document extraction
- generate_daily_briefing: Unified morning/daily briefing combining time, weather, reminders & system health
"""

import os
import re
import sys
import time
import json
import uuid
import shutil
import psutil
import zipfile
import threading
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field

from core.logger import log, error_log, audit_log
from core.security import mask_sensitive_data

# ─── Pydantic Parameter Schemas ───────────────────────────────────────────────

class SmartOrganizeFolderArgs(BaseModel):
    directory_path: str = Field(..., description="Target directory to organize (e.g. 'Downloads', 'Desktop', or absolute path)")
    dry_run: bool = Field(default=False, description="If True, returns planned moves without moving any files")

class UndoFolderOrganizationArgs(BaseModel):
    directory_path: str = Field(..., description="Directory containing undo_manifest.json to restore files from")

class CreateReminderOrTimerArgs(BaseModel):
    title: str = Field(..., description="Short title or label for the reminder / timer")
    trigger_in_seconds: int = Field(..., description="Number of seconds from now when the reminder should trigger (e.g. 600 for 10 minutes)")
    message: str = Field(default="", description="Detailed reminder notification message")

class ListAndManageRemindersArgs(BaseModel):
    action: str = Field(default="list", description="Action to perform: 'list', 'cancel', or 'clear'")
    reminder_id: Optional[str] = Field(default=None, description="Reminder ID to cancel (required when action='cancel')")

class ControlWindowsSettingArgs(BaseModel):
    setting: str = Field(..., description="Windows setting/action: 'volume_up', 'volume_down', 'mute_toggle', 'open_task_manager', 'open_settings', 'empty_recycle_bin', 'lock_workstation', 'clipboard_get', 'clipboard_set'")
    value: Optional[str] = Field(default=None, description="Optional value (used for clipboard_set or specific volume targets)")

class SummarizeLocalDocumentArgs(BaseModel):
    file_path: str = Field(..., description="Path to local .pdf, .docx, .txt, .md, or .csv document")
    focus_query: Optional[str] = Field(default=None, description="Optional question or topic to focus the extraction on")

class GenerateDailyBriefingArgs(BaseModel):
    city: str = Field(default="auto", description="City for weather lookup (default: 'auto' or user home city)")

class ManagePersonalNotesAndTodosArgs(BaseModel):
    action: str = Field(default="list", description="Action to perform: 'add', 'list', 'complete', or 'delete'")
    content: Optional[str] = Field(default=None, description="Content/text of the to-do item or note")
    item_id: Optional[str] = Field(default=None, description="Item ID to complete or delete")
    category: str = Field(default="todo", description="Category: 'todo' or 'note'")

class SmartClipboardAssistantArgs(BaseModel):
    action: str = Field(default="read", description="Action to perform: 'read', 'write', or 'history'")
    text_to_copy: Optional[str] = Field(default=None, description="Text to copy to clipboard when action='write'")

class ReadAndSummarizeWebpageArgs(BaseModel):
    url: str = Field(..., description="Webpage or article URL to read and summarize")
    focus_question: Optional[str] = Field(default=None, description="Optional question or focus topic for the extraction")

class ComposeAndLaunchMessageArgs(BaseModel):
    recipient: str = Field(default="", description="Recipient email address or name")
    subject: str = Field(default="", description="Subject line of the email or message")
    body: str = Field(default="", description="Draft body text of the message")
    channel: str = Field(default="clipboard", description="Channel: 'clipboard', 'gmail', 'mailto', or 'email'")
    open_client: bool = Field(default=False, description="Whether to launch web or OS mail client")


# ─── Global State & Persistence Paths ─────────────────────────────────────────

REMINDERS_FILE = Path(r"D:\Jarvis\data\tasks\reminders.json")
PERSONAL_TODOS_FILE = Path(r"D:\Jarvis\data\tasks\personal_todos.json")
_active_timer_threads: Dict[str, threading.Timer] = {}
_reminders_lock = threading.Lock()
_todos_lock = threading.Lock()
_CLIPBOARD_HISTORY: List[Dict[str, Any]] = []
_clipboard_lock = threading.Lock()

CATEGORY_EXTENSIONS: Dict[str, set[str]] = {
    "Documents": {".pdf", ".docx", ".doc", ".txt", ".rtf", ".pptx", ".ppt", ".xlsx", ".xls", ".csv", ".odt", ".epub"},
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff", ".psd"},
    "Installers_Archives": {".exe", ".msi", ".zip", ".rar", ".7z", ".tar", ".gz", ".iso", ".dmg", ".pkg", ".setup"},
    "Media": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".webm"},
    "Code_Data": {".py", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml", ".sql", ".sh", ".bat", ".xml", ".ipynb"},
}


def _resolve_user_directory(dir_name_or_path: str) -> Path:
    """Resolve standard friendly user folder names like 'Downloads', 'Desktop', 'Documents'."""
    raw = dir_name_or_path.strip().strip('"').strip("'")
    user_home = Path.home()
    standard_map = {
        "downloads": user_home / "Downloads",
        "desktop": user_home / "Desktop",
        "documents": user_home / "Documents",
        "pictures": user_home / "Pictures",
        "music": user_home / "Music",
        "videos": user_home / "Videos",
    }
    low = raw.lower()
    if low in standard_map:
        return standard_map[low]
    # Expand environment variables and user tilde
    expanded = os.path.expandvars(os.path.expanduser(raw))
    p = Path(expanded)
    if not p.is_absolute():
        p = Path(r"D:\Jarvis") / p
    return p


# ─── Tool 1: smart_organize_folder ───────────────────────────────────────────

def smart_organize_folder(directory_path: str, dry_run: bool = False) -> Dict[str, Any]:
    """
    Safely organizes cluttered folders (such as Downloads or Desktop) into categorized subfolders.
    Never overwrites existing files (auto-increments collisions).
    Writes an undo_manifest.json inside the target folder for 1-click rollback.
    """
    target_dir = _resolve_user_directory(directory_path)
    if not target_dir.exists() or not target_dir.is_dir():
        return {
            "success": False,
            "error": f"Target directory does not exist or is not a directory: {target_dir}",
            "directory": str(target_dir),
        }

    manifest_file = target_dir / "undo_manifest.json"
    planned_moves = []
    category_counts: Dict[str, int] = {cat: 0 for cat in CATEGORY_EXTENSIONS}
    category_counts["Other"] = 0

    try:
        entries = list(target_dir.iterdir())
    except Exception as e:
        return {"success": False, "error": f"Failed to list directory: {e}", "directory": str(target_dir)}

    for item in entries:
        # Skip subfolders, hidden files, and undo manifest itself
        if item.is_dir() or item.name.startswith(".") or item.name == "undo_manifest.json":
            continue

        ext = item.suffix.lower()
        matched_cat = "Other"
        for cat, ext_set in CATEGORY_EXTENSIONS.items():
            if ext in ext_set:
                matched_cat = cat
                break

        dest_folder = target_dir / matched_cat
        stem = item.stem
        candidate_name = item.name
        counter = 1

        # Determine non-colliding destination path
        dest_path = dest_folder / candidate_name
        while dest_path.exists():
            candidate_name = f"{stem} ({counter}){ext}"
            dest_path = dest_folder / candidate_name
            counter += 1

        planned_moves.append({
            "original_name": item.name,
            "original_path": str(item.resolve()),
            "new_path": str(dest_path.resolve()),
            "category": matched_cat,
        })
        category_counts[matched_cat] += 1

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "directory": str(target_dir),
            "total_files_identified": len(planned_moves),
            "category_summary": category_counts,
            "moves": planned_moves,
            "message": f"Dry run complete. {len(planned_moves)} files would be organized."
        }

    # Execute moves safely
    executed_moves = []
    try:
        for move in planned_moves:
            src = Path(move["original_path"])
            dst = Path(move["new_path"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            executed_moves.append(move)

        # Write undo manifest
        manifest_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_directory": str(target_dir),
            "total_organized": len(executed_moves),
            "moves": executed_moves,
        }
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_payload, f, indent=2)

        return {
            "success": True,
            "dry_run": False,
            "directory": str(target_dir),
            "total_organized": len(executed_moves),
            "category_summary": category_counts,
            "undo_manifest": str(manifest_file),
            "message": f"Successfully organized {len(executed_moves)} files into categorized folders."
        }
    except Exception as e:
        error_log.error(f"Error during smart_organize_folder: {e}")
        return {
            "success": False,
            "error": f"Failed during organization: {e}",
            "partial_moves": len(executed_moves),
            "directory": str(target_dir)
        }


# ─── Tool 2: undo_folder_organization ─────────────────────────────────────────

def undo_folder_organization(directory_path: str) -> Dict[str, Any]:
    """
    Reads undo_manifest.json from the target directory and restores every file
    to its exact original path, cleaning up newly empty categorization folders.
    """
    target_dir = _resolve_user_directory(directory_path)
    manifest_file = target_dir / "undo_manifest.json"

    if not manifest_file.exists():
        return {
            "success": False,
            "error": f"No undo_manifest.json found in {target_dir}. Cannot undo organization.",
            "directory": str(target_dir)
        }

    try:
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        return {"success": False, "error": f"Failed to read undo manifest: {e}"}

    moves = manifest.get("moves", [])
    restored_count = 0
    errors = []

    # Process in reverse order
    for move in reversed(moves):
        curr_path = Path(move["new_path"])
        orig_path = Path(move["original_path"])

        if not curr_path.exists():
            continue

        try:
            orig_path.parent.mkdir(parents=True, exist_ok=True)
            # If original path already exists, find non-colliding name
            target_dest = orig_path
            if target_dest.exists() and target_dest.resolve() != curr_path.resolve():
                counter = 1
                stem = orig_path.stem
                ext = orig_path.suffix
                while target_dest.exists():
                    target_dest = orig_path.parent / f"{stem}_restored_{counter}{ext}"
                    counter += 1
            shutil.move(str(curr_path), str(target_dest))
            restored_count += 1
        except Exception as e:
            errors.append(f"Could not restore {curr_path.name}: {e}")

    # Clean up empty category folders
    for cat in list(CATEGORY_EXTENSIONS.keys()) + ["Other"]:
        cat_dir = target_dir / cat
        if cat_dir.exists() and cat_dir.is_dir():
            try:
                if not any(cat_dir.iterdir()):
                    cat_dir.rmdir()
            except Exception:
                pass

    # Remove manifest on success
    try:
        manifest_file.unlink()
    except Exception:
        pass

    return {
        "success": True,
        "directory": str(target_dir),
        "files_restored": restored_count,
        "errors": errors,
        "message": f"Successfully restored {restored_count} files to original positions."
    }


# ─── Tool 3: create_reminder_or_timer ────────────────────────────────────────

def _load_reminders() -> List[Dict[str, Any]]:
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not REMINDERS_FILE.exists():
        return []
    try:
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_reminders(reminders: List[Dict[str, Any]]) -> None:
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(reminders, f, indent=2)


def _trigger_reminder_action(reminder_id: str, title: str, message: str) -> None:
    """Fires native toast notification, WebSocket broadcast, and marks reminder triggered."""
    log.info(f"Reminder triggered: [{reminder_id}] {title} - {message}")
    with _reminders_lock:
        reminders = _load_reminders()
        for r in reminders:
            if r.get("reminder_id") == reminder_id:
                r["status"] = "triggered"
                r["triggered_at_actual"] = datetime.now(timezone.utc).isoformat()
                break
        _save_reminders(reminders)
        _active_timer_threads.pop(reminder_id, None)

    # 1. Windows Notification (PowerShell BurntToast / Toast fallback)
    def notify_worker():
        try:
            ps_script = """
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName("text")
            $textNodes.Item(0).AppendChild($template.CreateTextNode($env:JARVIS_REM_TITLE)) > $null
            $textNodes.Item(1).AppendChild($template.CreateTextNode($env:JARVIS_REM_MSG)) > $null
            $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("JARVIS")
            $notification = [Windows.UI.Notifications.ToastNotification]::new($template)
            $notifier.Show($notification)
            """
            env = os.environ.copy()
            env["JARVIS_REM_TITLE"] = str(title)
            env["JARVIS_REM_MSG"] = str(message)
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], env=env, capture_output=True, timeout=5)
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, message or title, f"JARVIS Reminder: {title}", 0x40 | 0x10000)
            except Exception:
                pass

    threading.Thread(target=notify_worker, daemon=True).start()

    # 2. WebSocket event broadcast
    try:
        from api.ws_manager import ws_manager
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(ws_manager.broadcast_event("reminder_triggered", {
                "reminder_id": reminder_id,
                "title": title,
                "message": message,
            }))
    except Exception:
        pass


def create_reminder_or_timer(title: str, trigger_in_seconds: int, message: str = "") -> Dict[str, Any]:
    """
    Schedules a local reminder or countdown timer.
    Persists to data/tasks/reminders.json and triggers a Windows notification and UI event when due.
    """
    reminder_id = f"rem_{uuid.uuid4().hex[:8]}"
    now_epoch = time.time()
    trigger_epoch = now_epoch + max(1, trigger_in_seconds)
    trigger_iso = datetime.fromtimestamp(trigger_epoch, timezone.utc).isoformat()
    msg_body = message.strip() or title.strip()

    record = {
        "reminder_id": reminder_id,
        "title": title.strip(),
        "message": msg_body,
        "duration_seconds": trigger_in_seconds,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trigger_epoch": trigger_epoch,
        "trigger_at": trigger_iso,
        "status": "pending",
    }

    with _reminders_lock:
        reminders = _load_reminders()
        reminders.append(record)
        _save_reminders(reminders)

        # Schedule timer
        t = threading.Timer(trigger_in_seconds, _trigger_reminder_action, args=[reminder_id, title.strip(), msg_body])
        t.daemon = True
        t.start()
        _active_timer_threads[reminder_id] = t

    return {
        "success": True,
        "reminder_id": reminder_id,
        "title": title.strip(),
        "message": msg_body,
        "trigger_in_seconds": trigger_in_seconds,
        "trigger_at": trigger_iso,
        "status": "pending",
    }


# ─── Tool 4: list_and_manage_reminders ────────────────────────────────────────

def list_and_manage_reminders(action: str = "list", reminder_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Lists active and historical reminders/timers, or cancels a scheduled reminder by ID.
    """
    act = action.strip().lower()
    with _reminders_lock:
        reminders = _load_reminders()

        if act == "list":
            active = [r for r in reminders if r.get("status") == "pending"]
            recent = [r for r in reminders if r.get("status") != "pending"][-10:]
            return {
                "success": True,
                "action": "list",
                "active_count": len(active),
                "pending_count": len(active),
                "active_reminders": active,
                "recent_history": recent,
            }

        elif act == "cancel":
            if not reminder_id:
                return {"success": False, "error": "reminder_id is required to cancel a reminder."}

            found = False
            for r in reminders:
                if r.get("reminder_id") == reminder_id:
                    r["status"] = "cancelled"
                    found = True
                    break

            if reminder_id in _active_timer_threads:
                timer = _active_timer_threads.pop(reminder_id)
                timer.cancel()

            if found:
                _save_reminders(reminders)
                return {"success": True, "action": "cancel", "reminder_id": reminder_id, "message": "Reminder cancelled successfully."}
            else:
                return {"success": False, "error": f"Reminder ID '{reminder_id}' not found."}

        elif act == "clear":
            cleaned = [r for r in reminders if r.get("status") == "pending"]
            cleared_count = len(reminders) - len(cleaned)
            _save_reminders(cleaned)
            return {"success": True, "action": "clear", "cleared_count": cleared_count}

        else:
            return {"success": False, "error": f"Unknown action '{action}'. Valid actions are 'list', 'cancel', 'clear'."}


def restore_pending_reminders_on_startup() -> Dict[str, int]:
    """
    Scans reminders.json on system boot/startup and recovers pending reminders:
    - Overdue or immediate (remaining <= 1s): triggered in a background thread after a 2-second grace delay.
    - Future timers (remaining > 1s): re-scheduled as daemon threading.Timer and registered in _active_timer_threads.
    Returns:
        dict: {"restored_count": count, "triggered_overdue_count": overdue_count}
    """
    restored_count = 0
    triggered_overdue_count = 0
    delayed_threads = []

    with _reminders_lock:
        reminders = _load_reminders()
        now = time.time()
        for r in reminders:
            if r.get("status") != "pending":
                continue

            reminder_id = r.get("reminder_id")
            if not reminder_id:
                continue

            title = r.get("title", "Reminder")
            message = r.get("message") or title
            try:
                trigger_epoch = float(r.get("trigger_epoch", 0))
            except (ValueError, TypeError):
                trigger_epoch = 0.0

            remaining = trigger_epoch - now

            if remaining <= 1:
                # Trigger immediately in background thread after 2-second grace delay
                def _delayed_overdue_trigger(rid=reminder_id, t=title, m=message):
                    time.sleep(2.0)
                    _trigger_reminder_action(rid, t, m)

                th = threading.Thread(target=_delayed_overdue_trigger, daemon=True)
                delayed_threads.append(th)
                triggered_overdue_count += 1
            else:
                if reminder_id not in _active_timer_threads:
                    timer = threading.Timer(remaining, _trigger_reminder_action, args=[reminder_id, title, message])
                    timer.daemon = True
                    timer.start()
                    _active_timer_threads[reminder_id] = timer
                    restored_count += 1

    for th in delayed_threads:
        th.start()

    log.info(f"Reminder restoration on boot: restored {restored_count} future timers, queued {triggered_overdue_count} overdue triggers.")
    return {
        "restored_count": restored_count,
        "triggered_overdue_count": triggered_overdue_count
    }


# ─── Tool 5: control_windows_setting ──────────────────────────────────────────

def control_windows_setting(setting: str, value: Optional[str] = None) -> Dict[str, Any]:
    """
    Controls standard everyday Windows features and settings:
    volume_up, volume_down, mute_toggle, open_task_manager, open_settings,
    empty_recycle_bin (HIGH_RISK), lock_workstation (MODERATE_RISK), clipboard_get, clipboard_set.
    """
    st = setting.strip().lower()

    if st in ("volume_up", "vol_up"):
        try:
            import ctypes
            # VK_VOLUME_UP = 0xAF
            for _ in range(3):
                ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
            return {"success": True, "setting": "volume_up", "action": "Increased master volume."}
        except Exception as e:
            return {"success": False, "error": f"Failed to change volume: {e}"}

    elif st in ("volume_down", "vol_down"):
        try:
            import ctypes
            # VK_VOLUME_DOWN = 0xAE
            for _ in range(3):
                ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
            return {"success": True, "setting": "volume_down", "action": "Decreased master volume."}
        except Exception as e:
            return {"success": False, "error": f"Failed to change volume: {e}"}

    elif st in ("mute_toggle", "mute", "unmute"):
        try:
            import ctypes
            # VK_VOLUME_MUTE = 0xAD
            ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
            return {"success": True, "setting": "mute_toggle", "action": "Toggled master volume mute."}
        except Exception as e:
            return {"success": False, "error": f"Failed to toggle mute: {e}"}

    elif st in ("open_task_manager", "task_manager", "taskmgr"):
        try:
            subprocess.Popen(["taskmgr.exe"])
            return {"success": True, "setting": "open_task_manager", "action": "Launched Windows Task Manager."}
        except Exception as e:
            return {"success": False, "error": f"Failed to open Task Manager: {e}"}

    elif st in ("open_settings", "settings"):
        try:
            subprocess.Popen(["cmd", "/c", "start", "ms-settings:"])
            return {"success": True, "setting": "open_settings", "action": "Opened Windows Settings app."}
        except Exception as e:
            return {"success": False, "error": f"Failed to open Windows Settings: {e}"}

    elif st in ("empty_recycle_bin", "clear_recycle_bin"):
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return {"success": True, "setting": "empty_recycle_bin", "action": "Emptied Windows Recycle Bin."}
        except Exception as e:
            return {"success": False, "error": f"Failed to empty Recycle Bin: {e}"}

    elif st in ("lock_workstation", "lock_pc", "lock_screen"):
        try:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            return {"success": True, "setting": "lock_workstation", "action": "Locked Windows Workstation."}
        except Exception as e:
            return {"success": False, "error": f"Failed to lock workstation: {e}"}

    elif st in ("clipboard_get", "get_clipboard"):
        try:
            import pyperclip
            content = pyperclip.paste()
            return {
                "success": True,
                "setting": "clipboard_get",
                "content_preview": content[:200] if content else "",
                "character_count": len(content),
                "content": content
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to read clipboard: {e}"}

    elif st in ("clipboard_set", "set_clipboard"):
        if value is None:
            return {"success": False, "error": "value is required for clipboard_set."}
        try:
            import pyperclip
            pyperclip.copy(str(value))
            return {"success": True, "setting": "clipboard_set", "action": "Copied text to Windows Clipboard."}
        except Exception as e:
            return {"success": False, "error": f"Failed to set clipboard: {e}"}

    else:
        return {
            "success": False,
            "error": f"Unknown setting '{setting}'. Supported settings: volume_up, volume_down, mute_toggle, open_task_manager, open_settings, empty_recycle_bin, lock_workstation, clipboard_get, clipboard_set."
        }


# ─── Tool 6: summarize_local_document ────────────────────────────────────────

def _extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from PDF using pypdf with fallback."""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        text_parts = []
        for i, page in enumerate(reader.pages):
            txt = page.extract_text() or ""
            if txt.strip():
                text_parts.append(f"--- Page {i+1} ---\n{txt}")
        return "\n\n".join(text_parts)
    except Exception as e:
        log.warning(f"pypdf extraction failed on {pdf_path}: {e}")
        return f"[PDF text extraction error: {e}]"


def _extract_text_from_docx(docx_path: Path) -> str:
    """Extract text from DOCX using python-docx with zip/XML fallback."""
    try:
        import docx
        doc = docx.Document(str(docx_path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        log.warning(f"python-docx failed, falling back to zip/xml extraction: {e}")
        try:
            with zipfile.ZipFile(str(docx_path), "r") as z:
                xml_content = z.read("word/document.xml")
                root = ET.fromstring(xml_content)
                texts = [elem.text for elem in root.iter() if elem.tag.endswith("t") and elem.text]
                return "".join(texts)
        except Exception as zerr:
            return f"[DOCX text extraction error: {zerr}]"


def summarize_local_document(file_path: str, focus_query: Optional[str] = None) -> Dict[str, Any]:
    """
    Extracts text from local .pdf, .docx, .txt, .md, or .csv documents on the PC
    and prepares clean structured content for LLM summarization.
    """
    raw_path = file_path.strip().strip('"').strip("'")
    target_path = Path(os.path.expandvars(os.path.expanduser(raw_path)))

    # If relative, check common user locations
    if not target_path.exists():
        for base in [Path(r"D:\Jarvis"), Path.home() / "Desktop", Path.home() / "Downloads", Path.home() / "Documents"]:
            cand = base / raw_path
            if cand.exists() and cand.is_file():
                target_path = cand
                break

    if not target_path.exists() or not target_path.is_file():
        return {
            "success": False,
            "error": f"File not found: {raw_path}. Checked common locations (Desktop, Downloads, Documents).",
            "file_path": str(target_path)
        }

    ext = target_path.suffix.lower()
    extracted_text = ""

    try:
        if ext == ".pdf":
            extracted_text = _extract_text_from_pdf(target_path)
        elif ext in (".docx", ".doc"):
            extracted_text = _extract_text_from_docx(target_path)
        elif ext in (".txt", ".md", ".json", ".log"):
            with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                extracted_text = f.read()
        elif ext == ".csv":
            import csv
            rows = []
            with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if i > 50:  # cap preview rows for speed
                        rows.append(f"... and {i} more rows")
                        break
                    rows.append(" | ".join(row))
            extracted_text = "\n".join(rows)
        else:
            with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                extracted_text = f.read(50000)

        word_count = len(extracted_text.split())
        char_count = len(extracted_text)

        # Cap length at 12,000 characters for token safety while keeping the core content
        capped_text = extracted_text[:12000]
        if len(extracted_text) > 12000:
            capped_text += f"\n\n[Note: Document truncated at 12,000 chars of {char_count} total characters.]"

        return {
            "success": True,
            "filename": target_path.name,
            "file_path": str(target_path.resolve()),
            "extension": ext,
            "character_count": char_count,
            "word_count": word_count,
            "focus_query": focus_query,
            "extracted_text": capped_text,
            "message": f"Successfully extracted {word_count} words from {target_path.name}."
        }
    except Exception as e:
        error_log.error(f"Failed to extract document {target_path}: {e}")
        return {"success": False, "error": f"Extraction failed: {e}", "file_path": str(target_path)}


# ─── Tool 7: generate_daily_briefing ─────────────────────────────────────────

def generate_daily_briefing(city: str = "auto") -> Dict[str, Any]:
    """
    Generates a unified daily/morning briefing combining local date/time,
    real-time system health metrics, scheduled reminders, and live weather.
    """
    now = datetime.now()
    dt_str = now.strftime("%A, %B %d, %Y at %I:%M %p")

    # Read user preferences if available
    user_name = "Sir"
    resolved_city = city
    prefs_file = Path(r"D:\Jarvis\data\user_preferences.json")
    if prefs_file.exists():
        try:
            with open(prefs_file, "r", encoding="utf-8") as f:
                prefs_data = json.load(f)
                if prefs_data.get("user_name"):
                    user_name = prefs_data["user_name"].strip()
                if prefs_data.get("preferred_city") and city in ("auto", "local"):
                    resolved_city = prefs_data["preferred_city"].strip()
        except Exception:
            pass

    # 1. System Health
    cpu_pct = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")

    system_health = {
        "cpu_percent": cpu_pct,
        "ram_percent": ram.percent,
        "ram_used_gb": round((ram.total - ram.available) / (1024**3), 1),
        "ram_total_gb": round(ram.total / (1024**3), 1),
        "disk_free_gb": round(disk.free / (1024**3), 1),
        "status": "Healthy" if cpu_pct < 85 and ram.percent < 85 else "High Load",
    }

    # 2. Pending Reminders
    reminders = _load_reminders()
    pending = [r for r in reminders if r.get("status") == "pending"]

    # 2b. Pending To-Dos
    todos = _load_todos()
    pending_todos = [t for t in todos if t.get("category") == "todo" and t.get("status") == "pending"]

    # 3. Weather
    weather_summary = "Weather information unavailable."
    try:
        from tools.web_tools import get_weather
        weather_res = get_weather(resolved_city if resolved_city not in ("auto", "local") else "local")
        if weather_res and isinstance(weather_res, str):
            weather_summary = weather_res[:300]
    except Exception:
        pass

    # Build human-readable markdown briefing
    reminders_bullets = ""
    if pending:
        for r in pending[:5]:
            reminders_bullets += f"- **{r.get('title')}**: due at {r.get('trigger_at', 'soon')}\n"
    else:
        reminders_bullets = "- No pending reminders scheduled.\n"

    todos_bullets = ""
    if pending_todos:
        for t in pending_todos[:5]:
            todos_bullets += f"- [ ] **{t.get('content')}** (ID: {t.get('item_id')})\n"
    else:
        todos_bullets = "- No pending to-do items.\n"

    briefing_md = f"""# 🌅 Good Day, {user_name}! Here is your Daily Briefing

📅 **Date & Time**: {dt_str}
🌡️ **Weather**: {weather_summary}

💻 **System Status ({system_health['status']})**:
- CPU: {system_health['cpu_percent']}%
- Memory: {system_health['ram_percent']}% ({system_health['ram_used_gb']} GB / {system_health['ram_total_gb']} GB)
- Free Disk: {system_health['disk_free_gb']} GB on Drive C:

⏰ **Today's Reminders & Tasks**:
{reminders_bullets}
📋 **Pending To-Do Items**:
{todos_bullets}
All core systems are operational and standing by for your commands.
"""

    return {
        "success": True,
        "user_name": user_name,
        "city": resolved_city,
        "datetime": dt_str,
        "system_health": system_health,
        "weather": weather_summary,
        "pending_reminders_count": len(pending),
        "pending_reminders": pending,
        "pending_todos_count": len(pending_todos),
        "pending_todos": pending_todos,
        "briefing_markdown": briefing_md,
    }


# ─── Tool 8: manage_personal_notes_and_todos ──────────────────────────────────

def _load_todos() -> List[Dict[str, Any]]:
    PERSONAL_TODOS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not PERSONAL_TODOS_FILE.exists():
        return []
    try:
        with open(PERSONAL_TODOS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_todos(todos: List[Dict[str, Any]]) -> None:
    PERSONAL_TODOS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PERSONAL_TODOS_FILE, "w", encoding="utf-8") as f:
        json.dump(todos, f, indent=2)


def manage_personal_notes_and_todos(
    action: str = "list",
    content: Optional[str] = None,
    title: Optional[str] = None,
    notes: Optional[str] = None,
    item_id: Optional[str] = None,
    category: str = "todo",
    due_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Persists and manages a personal To-Do list and Quick Notes store in data/tasks/personal_todos.json.
    Actions:
      - 'add': Adds a new note or to-do.
      - 'list': Lists all active to-dos and notes.
      - 'complete': Marks a to-do item completed by item_id or content substring match.
      - 'delete': Removes an item by item_id or content substring match.
    """
    act = (action or "list").strip().lower()
    cat_in = (category or "todo").strip().lower()
    cat = "note" if cat_in in ("note", "notes", "quicknote") else "todo"

    with _todos_lock:
        items = _load_todos()

        if act == "add":
            item_text = (content or title or "").strip()
            if not item_text:
                return {"success": False, "error": "content or title is required when adding a to-do or note."}
            new_id = f"todo_{uuid.uuid4().hex[:8]}" if cat == "todo" else f"note_{uuid.uuid4().hex[:8]}"
            record = {
                "item_id": new_id,
                "title": (title or item_text).strip(),
                "content": item_text,
                "notes": str(notes).strip() if notes else "",
                "category": cat,
                "due_date": due_date,
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": None
            }
            items.append(record)
            _save_todos(items)
            return {
                "success": True,
                "action": "add",
                "item_id": new_id,
                "category": cat,
                "title": record["title"],
                "content": item_text,
                "status": "pending",
                "message": f"Added {cat} [{new_id}]: '{item_text}'"
            }

        elif act == "list":
            pending_todos = [i for i in items if i.get("category") == "todo" and i.get("status") == "pending"]
            completed_todos = [i for i in items if i.get("category") == "todo" and i.get("status") == "completed"]
            notes_list = [i for i in items if i.get("category") == "note"]
            return {
                "success": True,
                "action": "list",
                "total_items": len(items),
                "pending_todos_count": len(pending_todos),
                "pending_todos": pending_todos,
                "completed_todos": completed_todos,
                "notes": notes_list,
                "items": items,
            }

        elif act == "complete":
            search_key = (item_id or content or title or "").strip().lower()
            target = None
            for item in items:
                if item_id and item.get("item_id") == item_id:
                    target = item
                    break
                combined = f"{item.get('item_id', '')} {item.get('title', '')} {item.get('content', '')}".lower()
                if search_key and search_key in combined:
                    target = item
                    break

            if not target:
                return {"success": False, "error": f"Item matching id='{item_id}' or content='{content or title}' not found."}

            target["status"] = "completed"
            target["completed_at"] = datetime.now(timezone.utc).isoformat()
            _save_todos(items)
            return {
                "success": True,
                "action": "complete",
                "item_id": target.get("item_id"),
                "content": target.get("content") or target.get("title"),
                "status": "completed",
                "message": f"Marked task [{target.get('item_id')}] '{target.get('content') or target.get('title')}' as completed."
            }

        elif act == "delete":
            search_key = (item_id or content or title or "").strip().lower()
            idx_to_remove = None
            removed_item = None
            for idx, item in enumerate(items):
                if item_id and item.get("item_id") == item_id:
                    idx_to_remove = idx
                    removed_item = item
                    break
                combined = f"{item.get('item_id', '')} {item.get('title', '')} {item.get('content', '')}".lower()
                if search_key and search_key in combined:
                    idx_to_remove = idx
                    removed_item = item
                    break

            if idx_to_remove is None:
                return {"success": False, "error": f"Item matching id='{item_id}' or content='{content or title}' not found."}

            items.pop(idx_to_remove)
            _save_todos(items)
            return {
                "success": True,
                "action": "delete",
                "item_id": removed_item.get("item_id"),
                "content": removed_item.get("content") or removed_item.get("title"),
                "message": f"Deleted [{removed_item.get('item_id')}] '{removed_item.get('content') or removed_item.get('title')}'."
            }

        else:
            return {"success": False, "error": f"Unknown action '{action}'. Valid actions are 'add', 'list', 'complete', 'delete'."}


# ─── Tool 9: smart_clipboard_assistant ────────────────────────────────────────

def smart_clipboard_assistant(
    action: str = "read",
    text_to_copy: Optional[str] = None,
    content: Optional[str] = None
) -> Dict[str, Any]:
    """
    Everyday smart clipboard assistant allowing reading, writing, and history buffer inspection.
    Maintains a ring-buffer of the last 10 items (masked with mask_sensitive_data).
    """
    act = (action or "read").strip().lower()

    if act == "read":
        try:
            import pyperclip
            raw_text = pyperclip.paste() or ""
        except Exception:
            raw_text = ""

        masked_text = mask_sensitive_data(raw_text) if raw_text else ""
        if raw_text:
            with _clipboard_lock:
                if not _CLIPBOARD_HISTORY or _CLIPBOARD_HISTORY[-1].get("raw") != raw_text:
                    _CLIPBOARD_HISTORY.append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "text": masked_text,
                        "raw": raw_text,
                        "length": len(raw_text)
                    })
                    if len(_CLIPBOARD_HISTORY) > 10:
                        _CLIPBOARD_HISTORY.pop(0)

        return {
            "success": True,
            "action": "read",
            "content": raw_text,
            "masked_content": masked_text,
            "character_count": len(raw_text),
            "preview": raw_text[:300] if raw_text else "",
            "message": f"Read {len(raw_text)} characters from clipboard." if raw_text else "Clipboard is currently empty."
        }

    elif act == "write":
        write_val = text_to_copy if text_to_copy is not None else content
        if write_val is None:
            return {"success": False, "error": "text_to_copy or content is required for action='write'."}
        text_str = str(write_val)
        try:
            import pyperclip
            pyperclip.copy(text_str)
        except Exception as e:
            return {"success": False, "error": f"Failed to write to clipboard: {e}"}

        masked_text = mask_sensitive_data(text_str)
        with _clipboard_lock:
            _CLIPBOARD_HISTORY.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "text": masked_text,
                "raw": text_str,
                "length": len(text_str)
            })
            if len(_CLIPBOARD_HISTORY) > 10:
                _CLIPBOARD_HISTORY.pop(0)

        return {
            "success": True,
            "action": "write",
            "character_count": len(text_str),
            "preview": text_str[:200],
            "message": f"Successfully copied {len(text_str)} characters to clipboard."
        }

    elif act == "history":
        with _clipboard_lock:
            history_copy = [
                {"timestamp": h["timestamp"], "text": h["text"], "length": h["length"]}
                for h in _CLIPBOARD_HISTORY
            ]
        return {
            "success": True,
            "action": "history",
            "count": len(history_copy),
            "history": history_copy
        }

    else:
        return {"success": False, "error": f"Unknown action '{action}'. Valid actions are 'read', 'write', 'history'."}


# ─── Tool 10: read_and_summarize_webpage ──────────────────────────────────────

def read_and_summarize_webpage(
    url: str,
    focus_question: Optional[str] = None
) -> Dict[str, Any]:
    """
    Fetches any public article, documentation page, or blog URL, strips navigation, ads,
    scripts, and styles, and returns clean readable text structured for instant summarization.
    """
    clean_url = (url or "").strip().strip('"').strip("'")
    if not clean_url:
        return {"success": False, "error": "url parameter is required."}
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    try:
        import requests
        from bs4 import BeautifulSoup
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        })
        resp = session.get(clean_url, timeout=15, allow_redirects=True)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else clean_url

        # Remove clutter
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "form"]):
            tag.decompose()

        # Extract text
        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)

        word_count = len(clean_text.split())
        char_count = len(clean_text)

        # Cap at 15,000 characters for token safety
        capped_text = clean_text[:15000]
        if char_count > 15000:
            capped_text += f"\n\n[Note: Webpage text truncated at 15,000 chars of {char_count} total characters.]"

        return {
            "success": True,
            "url": clean_url,
            "title": title,
            "character_count": char_count,
            "word_count": word_count,
            "focus_question": focus_question,
            "extracted_text": capped_text,
            "message": f"Successfully extracted {word_count} words from '{title}'."
        }
    except Exception as e:
        error_log.error(f"Failed to read webpage {clean_url}: {e}")
        return {
            "success": False,
            "url": clean_url,
            "error": f"Failed to fetch or parse webpage: {e}"
        }


# ─── Tool 11: compose_and_launch_message ──────────────────────────────────────

def compose_and_launch_message(
    recipient: str = "",
    subject: str = "",
    body: str = "",
    channel: str = "clipboard",
    open_client: bool = False
) -> Dict[str, Any]:
    """
    Everyday Email & Message Composer Tool (Phase 7.0).
    Formats a clean email or message draft, copies the formatted body to the system clipboard,
    and optionally opens Gmail or the default mailto client with pre-populated fields.
    """
    import urllib.parse
    import webbrowser

    clean_recipient = (recipient or "").strip()
    clean_subject = (subject or "").strip()
    clean_body = (body or "").strip()
    chan = (channel or "clipboard").strip().lower()

    # Smart Email Draft Synthesis (Phase 8.0)
    RAW_COMMAND_PREFIXES = (
        "draft an email", "write an email", "compose an email",
        "compose a message", "draft a message", "write a message",
        "help me draft", "draft email", "write email"
    )
    clean_lower = clean_body.lower()
    is_command = any(clean_lower.startswith(p) for p in RAW_COMMAND_PREFIXES)

    if not clean_body or is_command:
        # 1. Read user_name from user_preferences.json if available
        signer_name = "JARVIS User"
        prefs_file = Path(r"D:\Jarvis\data\user_preferences.json")
        if prefs_file.exists():
            try:
                with open(prefs_file, "r", encoding="utf-8") as f:
                    prefs_data = json.load(f)
                    if prefs_data.get("user_name"):
                        uname = prefs_data["user_name"].strip()
                        if uname:
                            signer_name = uname
            except Exception:
                pass

        # 2. Derive recipient display name
        if clean_recipient:
            prefix = clean_recipient.split("@")[0].strip()
            recipient_display = prefix.capitalize() if prefix else "there"
        else:
            recipient_display = "there"

        # 3. Extract topic from clean_subject or clean_body
        topic = ""
        if clean_subject and not any(clean_subject.lower().startswith(p) for p in RAW_COMMAND_PREFIXES):
            sub = clean_subject
            for pre in ("regarding ", "about ", "subject: "):
                if sub.lower().startswith(pre):
                    sub = sub[len(pre):].strip()
            topic = sub.strip()

        if not topic and clean_body:
            m = re.search(r"(?:about|regarding)\s+([^,.\n]+)", clean_body, flags=re.IGNORECASE)
            if m:
                topic = m.group(1).strip()

        if not topic:
            topic = "our upcoming discussion"

        formatted_body = (
            f"Hi {recipient_display},\n\n"
            f"I hope you are doing well. I am writing to follow up regarding {topic}.\n\n"
            f"Please let me know your thoughts or when might be a convenient time to connect.\n\n"
            f"Best regards,\n"
            f"{signer_name}"
        )
        if not clean_subject:
            clean_subject = f"Regarding {topic}"
    else:
        # Keep explicit non-command body verbatim
        formatted_body = clean_body

    # Always copy formatted body to the system clipboard
    copied = False
    try:
        import pyperclip
        pyperclip.copy(formatted_body)
        copied = True
    except Exception:
        try:
            proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE, text=True)
            proc.communicate(input=formatted_body)
            copied = True
        except Exception:
            copied = False

    # Also register in clipboard history if available
    if formatted_body:
        with _clipboard_lock:
            masked = mask_sensitive_data(formatted_body)
            _CLIPBOARD_HISTORY.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "text": masked,
                "raw": formatted_body,
                "length": len(formatted_body)
            })
            if len(_CLIPBOARD_HISTORY) > 10:
                _CLIPBOARD_HISTORY.pop(0)

    url_opened = ""
    client_launched = False

    if open_client:
        to_enc = urllib.parse.quote(clean_recipient)
        su_enc = urllib.parse.quote(clean_subject)
        body_enc = urllib.parse.quote(formatted_body)

        if chan == "gmail":
            url_opened = f"https://mail.google.com/mail/?view=cm&fs=1&to={to_enc}&su={su_enc}&body={body_enc}"
            try:
                webbrowser.open(url_opened)
                client_launched = True
            except Exception as e:
                log.warning(f"Could not open Gmail compose URL: {e}")
        elif chan in ("mailto", "email"):
            url_opened = f"mailto:{clean_recipient}?subject={su_enc}&body={body_enc}"
            try:
                webbrowser.open(url_opened)
                client_launched = True
            except Exception as e:
                log.warning(f"Could not open mailto URL: {e}")

    status_msg = f"Message drafted and copied to clipboard ({len(formatted_body)} chars)."
    if client_launched:
        status_msg += f" Opened {chan} client."

    return {
        "success": True,
        "recipient": clean_recipient,
        "subject": clean_subject,
        "body": formatted_body,
        "channel": chan,
        "open_client": open_client,
        "client_launched": client_launched,
        "url": url_opened,
        "copied_to_clipboard": copied,
        "character_count": len(formatted_body),
        "message": status_msg
    }
