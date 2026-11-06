"""
JARVIS Windows UI Automation (UIA) Tools (Phase 1)
Provides programmatic accessibility tree inspection, targeting, and manipulation
for Windows desktop applications using UI Automation (UIA).

Inspired by microsoft/UFO:
Replaces brittle screen coordinate clicks with deterministic programmatic control.
"""

import os
import sys
import time
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field

from core.logger import log, error_log

# ─── Pydantic Parameter Schemas ───────────────────────────────────────────────

class UiaInspectWindowArgs(BaseModel):
    window_title: Optional[str] = Field(default=None, description="Title or partial title of window to inspect. If omitted, inspects active window.")
    max_depth: int = Field(default=3, description="Maximum tree traversal depth (default: 3).")

class UiaClickElementArgs(BaseModel):
    automation_id: Optional[str] = Field(default=None, description="AutomationId of the control to click (e.g. 'btnSave').")
    name: Optional[str] = Field(default=None, description="Name or label of the control (e.g. 'Save', 'Submit').")
    control_type: Optional[str] = Field(default=None, description="UIA ControlType (e.g. 'Button', 'MenuItem', 'TabItem').")
    window_title: Optional[str] = Field(default=None, description="Title or partial title of the target window.")

class UiaSetTextArgs(BaseModel):
    text: str = Field(..., description="Text string to enter into the edit control.")
    automation_id: Optional[str] = Field(default=None, description="AutomationId of target Edit or TextBox control.")
    name: Optional[str] = Field(default=None, description="Name or label of target Edit or TextBox control.")
    window_title: Optional[str] = Field(default=None, description="Title or partial title of the target window.")

class UiaGetTextArgs(BaseModel):
    automation_id: Optional[str] = Field(default=None, description="AutomationId of target control to read.")
    name: Optional[str] = Field(default=None, description="Name or label of target control to read.")
    window_title: Optional[str] = Field(default=None, description="Title or partial title of the target window.")

class UiaListWindowsArgs(BaseModel):
    filter_empty: bool = Field(default=True, description="Whether to filter out windows with empty titles.")


# ─── Helper Functions ─────────────────────────────────────────────────────────

def _get_pywinauto_desktop():
    """Lazily import and instantiate pywinauto Desktop with UIA backend."""
    try:
        from pywinauto import Desktop
        return Desktop(backend="uia")
    except ImportError as e:
        error_log.error(f"pywinauto not available: {e}")
        return None
    except Exception as e:
        error_log.error(f"Failed to initialize pywinauto Desktop: {e}")
        return None


def _find_window(desktop, window_title: Optional[str] = None):
    """Find a top-level window by title or return foreground window."""
    if not desktop:
        return None
    
    try:
        windows = desktop.windows()
        if not windows:
            return None

        if window_title:
            wt_lower = window_title.lower().strip()
            # Try exact match first, then substring
            for w in windows:
                try:
                    title = w.window_text().lower()
                    if wt_lower == title or wt_lower in title:
                        return w
                except Exception:
                    continue
            return None
        else:
            # Return the first top-level window that is visible and non-empty
            for w in windows:
                try:
                    if w.is_visible() and w.window_text().strip():
                        return w
                except Exception:
                    continue
            return windows[0] if windows else None
    except Exception as e:
        error_log.error(f"Error finding window '{window_title}': {e}")
        return None


# ─── Primary Tool Implementations ─────────────────────────────────────────────

def uia_list_windows(filter_empty: bool = True) -> Dict[str, Any]:
    """
    List all top-level windows currently discovered on the Windows UIA desktop.
    """
    desktop = _get_pywinauto_desktop()
    if not desktop:
        return {"success": False, "error": "UIA desktop backend is unavailable.", "windows": []}

    try:
        results = []
        for w in desktop.windows():
            try:
                title = w.window_text()
                if filter_empty and not title.strip():
                    continue
                info = {
                    "title": title,
                    "handle": w.handle,
                    "process_id": getattr(w.element_info, "process_id", None),
                    "control_type": getattr(w.element_info, "control_type", "Window"),
                    "is_visible": w.is_visible(),
                }
                results.append(info)
            except Exception:
                continue

        log.info(f"[UIA] Discovered {len(results)} top-level windows.")
        return {
            "success": True,
            "count": len(results),
            "windows": results
        }
    except Exception as e:
        error_log.error(f"[UIA] Failed to list windows: {e}")
        return {"success": False, "error": str(e), "windows": []}


def uia_inspect_window(window_title: Optional[str] = None, max_depth: int = 3) -> Dict[str, Any]:
    """
    Inspect the accessibility tree of a window, returning clickable and readable controls.
    """
    desktop = _get_pywinauto_desktop()
    if not desktop:
        return {"success": False, "error": "UIA desktop backend is unavailable.", "elements": []}

    target_win = _find_window(desktop, window_title)
    if not target_win:
        return {
            "success": False,
            "error": f"Window matching '{window_title}' not found.",
            "elements": []
        }

    try:
        win_title = target_win.window_text()
        elements = []

        def _traverse(ctrl, depth):
            if depth > max_depth:
                return
            try:
                children = ctrl.children()
            except Exception:
                return

            for child in children:
                try:
                    elem_info = child.element_info
                    name = elem_info.name or ""
                    auto_id = elem_info.automation_id or ""
                    ctrl_type = elem_info.control_type or ""
                    rect = getattr(elem_info, "rectangle", None)

                    if name or auto_id:
                        elements.append({
                            "name": name,
                            "automation_id": auto_id,
                            "control_type": ctrl_type,
                            "depth": depth,
                            "rect": [rect.left, rect.top, rect.right, rect.bottom] if rect else None
                        })
                    _traverse(child, depth + 1)
                except Exception:
                    continue

        _traverse(target_win, depth=1)
        log.info(f"[UIA] Inspected window '{win_title}': found {len(elements)} actionable controls.")
        return {
            "success": True,
            "window_title": win_title,
            "control_count": len(elements),
            "elements": elements[:100]  # Cap at 100 to avoid payload bloating
        }
    except Exception as e:
        error_log.error(f"[UIA] Error inspecting window: {e}")
        return {"success": False, "error": str(e), "elements": []}


def uia_click_element(
    automation_id: Optional[str] = None,
    name: Optional[str] = None,
    control_type: Optional[str] = None,
    window_title: Optional[str] = None
) -> Dict[str, Any]:
    """
    Click a UI control deterministically using Windows UI Automation without screen coordinates.
    """
    if not automation_id and not name:
        return {"success": False, "error": "Must provide at least automation_id or name to click."}

    desktop = _get_pywinauto_desktop()
    if not desktop:
        return {"success": False, "error": "UIA desktop backend is unavailable."}

    target_win = _find_window(desktop, window_title)
    if not target_win:
        return {"success": False, "error": f"Target window '{window_title}' not found."}

    try:
        # Build search criteria
        criteria = {}
        if automation_id:
            criteria["auto_id"] = automation_id
        if name:
            criteria["title"] = name
        if control_type:
            criteria["control_type"] = control_type

        # Find child matching criteria
        elem = target_win.child_window(**criteria)
        if not elem.exists(timeout=2.0):
            return {
                "success": False,
                "error": f"Element matching {criteria} not found in '{target_win.window_text()}'.",
                "criteria": criteria
            }

        # Attempt invoke or click_input
        try:
            elem.invoke()
            method_used = "UIA_InvokePattern"
        except Exception:
            elem.click_input()
            method_used = "UIA_ClickInput"

        log.info(f"[UIA] Clicked control {criteria} via {method_used}.")
        return {
            "success": True,
            "action": "click",
            "method": method_used,
            "target": criteria,
            "window": target_win.window_text()
        }
    except Exception as e:
        error_log.error(f"[UIA] Failed to click element {automation_id or name}: {e}")
        return {"success": False, "error": str(e)}


def uia_set_text(
    text: str,
    automation_id: Optional[str] = None,
    name: Optional[str] = None,
    window_title: Optional[str] = None
) -> Dict[str, Any]:
    """
    Set text directly into an Edit or TextBox control via UIA ValuePattern.
    """
    if not automation_id and not name:
        return {"success": False, "error": "Must provide automation_id or name of edit control."}

    desktop = _get_pywinauto_desktop()
    if not desktop:
        return {"success": False, "error": "UIA desktop backend is unavailable."}

    target_win = _find_window(desktop, window_title)
    if not target_win:
        return {"success": False, "error": f"Target window '{window_title}' not found."}

    try:
        criteria = {"control_type": "Edit"}
        if automation_id:
            criteria["auto_id"] = automation_id
        if name:
            criteria["title"] = name

        elem = target_win.child_window(**criteria)
        if not elem.exists(timeout=2.0):
            # Fallback without control_type constraint
            criteria.pop("control_type", None)
            elem = target_win.child_window(**criteria)

        if not elem.exists(timeout=1.0):
            return {"success": False, "error": f"Edit control matching {criteria} not found."}

        # Set text via UIA pattern or type_keys
        try:
            elem.set_edit_text(text)
            method_used = "ValuePattern_SetText"
        except Exception:
            elem.set_focus()
            elem.type_keys(text, with_spaces=True)
            method_used = "TypeKeys_Direct"

        log.info(f"[UIA] Set text via {method_used} for control {criteria}.")
        return {
            "success": True,
            "action": "set_text",
            "method": method_used,
            "text_length": len(text),
            "target": criteria
        }
    except Exception as e:
        error_log.error(f"[UIA] Failed to set text: {e}")
        return {"success": False, "error": str(e)}


def uia_get_text(
    automation_id: Optional[str] = None,
    name: Optional[str] = None,
    window_title: Optional[str] = None
) -> Dict[str, Any]:
    """
    Read text from an accessibility control.
    """
    desktop = _get_pywinauto_desktop()
    if not desktop:
        return {"success": False, "error": "UIA desktop backend is unavailable."}

    target_win = _find_window(desktop, window_title)
    if not target_win:
        return {"success": False, "error": f"Target window '{window_title}' not found."}

    try:
        criteria = {}
        if automation_id:
            criteria["auto_id"] = automation_id
        if name:
            criteria["title"] = name

        elem = target_win.child_window(**criteria)
        if not elem.exists(timeout=2.0):
            return {"success": False, "error": f"Control matching {criteria} not found."}

        text_val = elem.window_text()
        return {
            "success": True,
            "text": text_val,
            "target": criteria,
            "window": target_win.window_text()
        }
    except Exception as e:
        error_log.error(f"[UIA] Failed to get text: {e}")
        return {"success": False, "error": str(e)}

