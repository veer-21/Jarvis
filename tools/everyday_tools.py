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


# ─── Global State & Persistence Paths ─────────────────────────────────────────

REMINDERS_FILE = Path(r"D:\Jarvis\data\tasks\reminders.json")
_active_timer_threads: Dict[str, threading.Timer] = {}
_reminders_lock = threading.Lock()

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
            ps_script = f"""
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName("text")
            $textNodes.Item(0).AppendChild($template.CreateTextNode("{title}")) > $null
            $textNodes.Item(1).AppendChild($template.CreateTextNode("{message}")) > $null
            $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("JARVIS")
            $notification = [Windows.UI.Notifications.ToastNotification]::new($template)
            $notifier.Show($notification)
            """
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, timeout=5)
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

    # 3. Weather
    weather_summary = "Weather information unavailable."
    try:
        from tools.web_tools import get_weather
        weather_res = get_weather(city if city != "auto" else "local")
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

    briefing_md = f"""# 🌅 Good Day, Sir! Here is your Daily Briefing

📅 **Date & Time**: {dt_str}
🌡️ **Weather**: {weather_summary}

💻 **System Status ({system_health['status']})**:
- CPU: {system_health['cpu_percent']}%
- Memory: {system_health['ram_percent']}% ({system_health['ram_used_gb']} GB / {system_health['ram_total_gb']} GB)
- Free Disk: {system_health['disk_free_gb']} GB on Drive C:

⏰ **Today's Reminders & Tasks**:
{reminders_bullets}
All core systems are operational and standing by for your commands.
"""

    return {
        "success": True,
        "datetime": dt_str,
        "system_health": system_health,
        "weather": weather_summary,
        "pending_reminders_count": len(pending),
        "pending_reminders": pending,
        "briefing_markdown": briefing_md,
    }
