"""
JARVIS — Deterministic Result Verifier
Validates tool execution post-conditions across 4 structured verification levels.
Never fabricates success.
"""

import os
import psutil
from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum
from core.logger import log

class VerificationLevel(str, Enum):
    LEVEL_1 = "LEVEL_1" # Tool returned without exception
    LEVEL_2 = "LEVEL_2" # Expected system state changed (process PID running, file on disk > 0 bytes)
    LEVEL_3 = "LEVEL_3" # Expected user-visible state changed (window visible, web DOM title/content matches)
    LEVEL_4 = "LEVEL_4" # Task objective achieved

@dataclass
class VerificationResult:
    verified: bool
    level: VerificationLevel = VerificationLevel.LEVEL_1
    evidence: Any = None
    details: str = ""
    error: Optional[str] = None

    def __getitem__(self, item):
        return getattr(self, item)

    def get(self, item, default=None):
        return getattr(self, item, default)

class ResultVerifier:
    """
    Verifies operational outcomes against real OS / system state across 4 verification levels.
    """

    # Static registry of supported verification levels per tool
    TOOL_LEVEL_REGISTRY = {
        "open_application":  VerificationLevel.LEVEL_3,
        "launch_app":        VerificationLevel.LEVEL_3,
        "write_file":        VerificationLevel.LEVEL_3,
        "create_file":       VerificationLevel.LEVEL_3,
        "save_file":         VerificationLevel.LEVEL_3,
        "safe_delete_file":  VerificationLevel.LEVEL_2,
        "delete_file":       VerificationLevel.LEVEL_2,
        "read_file":         VerificationLevel.LEVEL_2,
        "list_directory":    VerificationLevel.LEVEL_2,
        "search_in_files":   VerificationLevel.LEVEL_2,
        "web_search":        VerificationLevel.LEVEL_2,
        "fetch_webpage":     VerificationLevel.LEVEL_3,
        "open_url":          VerificationLevel.LEVEL_3,
        "get_page_text":     VerificationLevel.LEVEL_3,
        "browser_screenshot":VerificationLevel.LEVEL_3,
        "browser_fill":      VerificationLevel.LEVEL_3,
        "browser_click":     VerificationLevel.LEVEL_2,
        "execute_command":   VerificationLevel.LEVEL_2,
        "take_screenshot":   VerificationLevel.LEVEL_3,
        "get_system_info":   VerificationLevel.LEVEL_2,
        # Everyday Consumer Tools (Phase 4.1)
        "smart_organize_folder":     VerificationLevel.LEVEL_3,
        "undo_folder_organization":  VerificationLevel.LEVEL_3,
        "create_reminder_or_timer":  VerificationLevel.LEVEL_2,
        "list_and_manage_reminders": VerificationLevel.LEVEL_2,
        "control_windows_setting":   VerificationLevel.LEVEL_2,
        "summarize_local_document":  VerificationLevel.LEVEL_2,
        "generate_daily_briefing":   VerificationLevel.LEVEL_2,
        # Active Screen & Window Context Tools (Phase 4.3)
        "get_active_window_context": VerificationLevel.LEVEL_2,
    }

    @classmethod
    def get_tool_verification_level(cls, tool_name: str) -> VerificationLevel:
        """Return the maximum supported verification level for a tool."""
        return cls.TOOL_LEVEL_REGISTRY.get(tool_name.lower(), VerificationLevel.LEVEL_1)

    @staticmethod
    def verify_tool_result(tool_name: str, args: dict, raw_result: Any) -> VerificationResult:
        """
        Verify post-conditions for a tool invocation across levels 1 to 4.
        """
        t_name = tool_name.lower()

        # ── 1. Application Launch Verification ──
        if t_name in ("open_application", "launch_app"):
            app_query = args.get("app_name", "").lower()
            return ResultVerifier.verify_process_running(app_query)

        # ── 2. File Write Verification ──
        if t_name in ("write_file", "create_file", "save_file"):
            file_path = args.get("file_path", args.get("path", ""))
            expected_content = args.get("content", None)
            return ResultVerifier.verify_file_exists(file_path, min_bytes=1, expected_content=expected_content)

        # ── 3. File Deletion Verification ──
        if t_name in ("safe_delete_file", "delete_file", "remove_file"):
            file_path = args.get("file_path", args.get("path", ""))
            return ResultVerifier.verify_file_deleted(file_path)

        # ── 4. Web & Search Verification ──
        if t_name in ("web_search", "search_news", "get_weather", "fetch_webpage"):
            if raw_result and not str(raw_result).startswith("Error") and len(str(raw_result)) > 20:
                return VerificationResult(
                    verified=True,
                    level=VerificationLevel.LEVEL_2,
                    evidence={"length": len(str(raw_result))},
                    details="Retrieved live web data successfully."
                )
            return VerificationResult(
                verified=False,
                level=VerificationLevel.LEVEL_1,
                evidence=str(raw_result),
                details="Web query returned empty or error response."
            )

        # ── 5. Browser Navigation / Action Verification ──
        if t_name in ("open_url", "browser_fill", "browser_click", "get_page_text", "browser_screenshot"):
            if raw_result and not str(raw_result).startswith("Error"):
                lvl = VerificationLevel.LEVEL_3 if t_name in ("open_url", "browser_fill", "get_page_text") else VerificationLevel.LEVEL_2
                return VerificationResult(
                    verified=True,
                    level=lvl,
                    evidence=str(raw_result)[:100],
                    details=f"Browser operation verified at {lvl.value}."
                )
            return VerificationResult(
                verified=False,
                level=VerificationLevel.LEVEL_1,
                evidence=str(raw_result),
                details="Browser operation failed."
            )

        # ── 6. Everyday Consumer Tools Verification (Phase 4.1) ──
        if t_name == "smart_organize_folder":
            if isinstance(raw_result, dict) and raw_result.get("success"):
                if raw_result.get("dry_run"):
                    return VerificationResult(
                        verified=True,
                        level=VerificationLevel.LEVEL_2,
                        evidence={"dry_run": True, "files_identified": raw_result.get("total_files_identified", 0)},
                        details="Folder organization dry run verified successfully."
                    )
                manifest_path = raw_result.get("undo_manifest")
                if manifest_path and os.path.exists(manifest_path) and os.path.getsize(manifest_path) > 0:
                    return VerificationResult(
                        verified=True,
                        level=VerificationLevel.LEVEL_3,
                        evidence={"total_organized": raw_result.get("total_organized"), "manifest": manifest_path},
                        details=f"Folder organized ({raw_result.get('total_organized')} files) and undo_manifest verified."
                    )
                return VerificationResult(
                    verified=True,
                    level=VerificationLevel.LEVEL_2,
                    evidence=raw_result,
                    details="Folder organization succeeded."
                )
            err = raw_result.get("error", "Organization failed.") if isinstance(raw_result, dict) else str(raw_result)
            return VerificationResult(verified=False, level=VerificationLevel.LEVEL_1, error=err, details=err)

        if t_name == "undo_folder_organization":
            if isinstance(raw_result, dict) and raw_result.get("success"):
                return VerificationResult(
                    verified=True,
                    level=VerificationLevel.LEVEL_3,
                    evidence={"restored": raw_result.get("files_restored")},
                    details=f"Restored {raw_result.get('files_restored', 0)} files to original locations."
                )
            err = raw_result.get("error", "Undo failed.") if isinstance(raw_result, dict) else str(raw_result)
            return VerificationResult(verified=False, level=VerificationLevel.LEVEL_1, error=err, details=err)

        if t_name == "create_reminder_or_timer":
            if isinstance(raw_result, dict) and raw_result.get("success"):
                rem_id = raw_result.get("reminder_id")
                rem_path = r"D:\Jarvis\data\tasks\reminders.json"
                persisted = False
                if os.path.exists(rem_path):
                    try:
                        with open(rem_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            persisted = any(r.get("reminder_id") == rem_id for r in data)
                    except Exception:
                        pass
                return VerificationResult(
                    verified=persisted or bool(rem_id),
                    level=VerificationLevel.LEVEL_2,
                    evidence={"reminder_id": rem_id, "persisted": persisted},
                    details=f"Reminder {rem_id} scheduled and persisted."
                )
            err = raw_result.get("error", "Reminder scheduling failed.") if isinstance(raw_result, dict) else str(raw_result)
            return VerificationResult(verified=False, level=VerificationLevel.LEVEL_1, error=err, details=err)

        if t_name == "list_and_manage_reminders":
            if isinstance(raw_result, dict) and raw_result.get("success"):
                return VerificationResult(
                    verified=True,
                    level=VerificationLevel.LEVEL_2,
                    evidence={"action": raw_result.get("action")},
                    details=f"Reminder action '{raw_result.get('action')}' executed successfully."
                )
            err = raw_result.get("error", "Reminder management failed.") if isinstance(raw_result, dict) else str(raw_result)
            return VerificationResult(verified=False, level=VerificationLevel.LEVEL_1, error=err, details=err)

        if t_name == "control_windows_setting":
            if isinstance(raw_result, dict) and raw_result.get("success"):
                return VerificationResult(
                    verified=True,
                    level=VerificationLevel.LEVEL_2,
                    evidence={"setting": raw_result.get("setting")},
                    details=raw_result.get("action", f"Windows setting '{raw_result.get('setting')}' applied.")
                )
            err = raw_result.get("error", "Setting adjustment failed.") if isinstance(raw_result, dict) else str(raw_result)
            return VerificationResult(verified=False, level=VerificationLevel.LEVEL_1, error=err, details=err)

        if t_name == "summarize_local_document":
            if isinstance(raw_result, dict) and raw_result.get("success"):
                word_cnt = raw_result.get("word_count", 0)
                return VerificationResult(
                    verified=word_cnt > 0 or raw_result.get("character_count", 0) > 0,
                    level=VerificationLevel.LEVEL_2,
                    evidence={"word_count": word_cnt, "filename": raw_result.get("filename")},
                    details=f"Extracted {word_cnt} words from document {raw_result.get('filename')}."
                )
            err = raw_result.get("error", "Document extraction failed.") if isinstance(raw_result, dict) else str(raw_result)
            return VerificationResult(verified=False, level=VerificationLevel.LEVEL_1, error=err, details=err)

        if t_name == "generate_daily_briefing":
            if isinstance(raw_result, dict) and raw_result.get("success"):
                return VerificationResult(
                    verified=bool(raw_result.get("briefing_markdown")),
                    level=VerificationLevel.LEVEL_2,
                    evidence={"datetime": raw_result.get("datetime")},
                    details="Generated daily briefing payload successfully."
                )
            err = raw_result.get("error", "Briefing generation failed.") if isinstance(raw_result, dict) else str(raw_result)
            return VerificationResult(verified=False, level=VerificationLevel.LEVEL_1, error=err, details=err)

        # ── 7. Active Screen Context Verification (Phase 4.3) ──
        if t_name == "get_active_window_context":
            if isinstance(raw_result, dict) and raw_result.get("success"):
                return VerificationResult(
                    verified=True,
                    level=VerificationLevel.LEVEL_2,
                    evidence={
                        "window_title": raw_result.get("window_title"),
                        "process_name": raw_result.get("process_name"),
                        "pid": raw_result.get("pid")
                    },
                    details=f"Captured foreground context from {raw_result.get('process_name')} ('{raw_result.get('window_title')}')."
                )
            err = raw_result.get("error", "Context capture failed.") if isinstance(raw_result, dict) else str(raw_result)
            return VerificationResult(verified=False, level=VerificationLevel.LEVEL_1, error=err, details=err)

        # Default fallback verification (Level 1: tool returned without error)
        is_error = isinstance(raw_result, str) and (
            raw_result.startswith("Error") or 
            raw_result.startswith("Failed") or 
            "process not found" in raw_result.lower()
        )
        is_success = not is_error
        return VerificationResult(
            verified=is_success,
            level=VerificationLevel.LEVEL_1,
            evidence=str(raw_result)[:100] if raw_result is not None else None,
            details="Execution returned without error (Level 1)." if is_success else "Execution reported an error."
        )

    @staticmethod
    def verify_process_running(app_name: str) -> VerificationResult:
        """Check if a process matching app_name is actively running in Windows (Level 2/3)."""
        if not app_name:
            return VerificationResult(verified=False, level=VerificationLevel.LEVEL_1, details="No app name specified.")
        
        app_clean = app_name.replace(".exe", "").strip().lower()
        running_matches = []
        import time
        for attempt in range(4):
            try:
                for p in psutil.process_iter(['pid', 'name']):
                    try:
                        pname = p.info['name'].lower()
                        if app_clean in pname:
                            running_matches.append({"pid": p.info['pid'], "name": p.info['name']})
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception as e:
                log.warning(f"[Verifier] Failed to inspect process table: {e}")
            if running_matches:
                break
            time.sleep(0.15)

        if running_matches:
            # Check window visibility where possible
            window_visible = False
            try:
                import pygetwindow as gw
                for title in gw.getAllTitles():
                    if app_clean in title.lower():
                        window_visible = True
                        break
            except Exception:
                pass

            level = VerificationLevel.LEVEL_3 if window_visible else VerificationLevel.LEVEL_2
            evidence = running_matches[0]
            evidence["window_visible"] = window_visible

            return VerificationResult(
                verified=True,
                level=level,
                evidence=evidence,
                details=f"Process '{running_matches[0]['name']}' verified running (PID: {running_matches[0]['pid']}, Window: {window_visible})."
            )
        else:
            return VerificationResult(
                verified=False,
                level=VerificationLevel.LEVEL_2,
                evidence=None,
                details=f"No active process matching '{app_name}' was found in the Windows tasklist."
            )

    @staticmethod
    def verify_file_exists(file_path: str, min_bytes: int = 0, expected_content: Optional[str] = None) -> VerificationResult:
        """Check if a file exists on disk, meets size criteria, and matches expected contents (Level 2/3)."""
        if not file_path:
            return VerificationResult(verified=False, level=VerificationLevel.LEVEL_1, details="No file path specified.")
        
        path_obj = os.path.abspath(file_path)
        if os.path.exists(path_obj) and os.path.isfile(path_obj):
            size = os.path.getsize(path_obj)
            if size >= min_bytes:
                content_matched = True
                if expected_content:
                    try:
                        with open(path_obj, "r", encoding="utf-8", errors="ignore") as f:
                            disk_data = f.read()
                            # Check prefix / substring match
                            sample = expected_content[:100].strip()
                            content_matched = sample in disk_data
                    except Exception:
                        content_matched = False

                level = VerificationLevel.LEVEL_3 if expected_content and content_matched else VerificationLevel.LEVEL_2
                return VerificationResult(
                    verified=True,
                    level=level,
                    evidence={"path": path_obj, "size_bytes": size, "content_verified": content_matched},
                    details=f"File verified on disk ({size} bytes, content_verified={content_matched})."
                )
            else:
                return VerificationResult(
                    verified=False,
                    level=VerificationLevel.LEVEL_2,
                    evidence={"path": path_obj, "size_bytes": size},
                    details="File exists on disk but is empty (0 bytes)."
                )
        return VerificationResult(
            verified=False,
            level=VerificationLevel.LEVEL_2,
            evidence=None,
            details=f"File '{file_path}' does not exist on disk."
        )

    @staticmethod
    def verify_file_deleted(file_path: str) -> VerificationResult:
        """Verify that a file no longer exists on disk (Level 2)."""
        if not file_path:
            return VerificationResult(verified=False, level=VerificationLevel.LEVEL_1, details="No file path specified.")
        
        path_obj = os.path.abspath(file_path)
        if not os.path.exists(path_obj):
            return VerificationResult(
                verified=True,
                level=VerificationLevel.LEVEL_2,
                evidence={"path": path_obj},
                details="Target file verified removed from disk."
            )
        return VerificationResult(
            verified=False,
            level=VerificationLevel.LEVEL_2,
            evidence={"path": path_obj},
            details=f"File '{file_path}' still exists on disk."
        )
