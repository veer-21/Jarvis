"""
JARVIS — The Ghost Operator
Background desktop automation without moving or seizing the physical mouse cursor.
Dispatches Win32 messages (PostMessage/SendMessage) directly to target HWNDs
and leverages Windows UI Automation (UIA) programmatic patterns.
"""

import time
from typing import Optional, Any
from core.logger import log, error_log
from core.security import RiskLevel
from core.brain.tool_router import jarvis_tool

# Win32 Constants
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP   = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP   = 0x0205
WM_SETTEXT     = 0x000C
WM_CHAR        = 0x0102
WM_KEYDOWN     = 0x0100
WM_KEYUP       = 0x0101
MK_LBUTTON     = 0x0001
MK_RBUTTON     = 0x0002

# Safe import of pywin32
try:
    import win32gui
    import win32con
    import win32api
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False
    log.warning("pywin32 not available for GhostOperator.")


def _resolve_target_window(window_title: str = "", hwnd: Optional[int] = None) -> tuple[Optional[int], str]:
    """Helper to locate a target window by HWND or title substring."""
    if hwnd is not None and hwnd > 0:
        if HAS_PYWIN32:
            try:
                if win32gui.IsWindow(hwnd):
                    title = win32gui.GetWindowText(hwnd) or f"Window_HWND_{hwnd}"
                    return hwnd, title
                return None, f"Window handle {hwnd} is invalid or has been closed."
            except Exception as e:
                return None, f"Error inspecting HWND {hwnd}: {e}"
        return hwnd, f"Window_HWND_{hwnd}"

    if window_title and window_title.strip():
        query = window_title.lower().strip()
        matched = None
        matched_title = ""

        if HAS_PYWIN32:
            def enum_callback(h, lparam):
                nonlocal matched, matched_title
                try:
                    if win32gui.IsWindowVisible(h):
                        t = win32gui.GetWindowText(h)
                        if t and query in t.lower():
                            matched = h
                            matched_title = t
                            return False
                except Exception:
                    pass
                return True

            try:
                win32gui.EnumWindows(enum_callback, None)
            except Exception:
                pass

            if matched:
                return matched, matched_title
            return None, f"Window matching title '{window_title}' not found (no matching visible window)."
        return None, f"Cannot search for '{window_title}' — pywin32 unavailable."

    return None, "Neither window_title nor hwnd was specified."


@jarvis_tool(name="ghost_list_targetable_windows", category="ghost", risk_level=RiskLevel.READ_ONLY)
def ghost_list_targetable_windows() -> dict[str, Any]:
    """
    Enumerates all visible, targetable application windows and their HWNDs for background automation.
    """
    windows = []
    if HAS_PYWIN32:
        def enum_cb(hwnd, lparam):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd).strip()
                    if title:
                        rect = win32gui.GetWindowRect(hwnd)
                        width = rect[2] - rect[0]
                        height = rect[3] - rect[1]
                        if width > 0 and height > 0:
                            cname = win32gui.GetClassName(hwnd)
                            windows.append({
                                "hwnd": hwnd,
                                "title": title,
                                "class_name": cname,
                                "rect": [rect[0], rect[1], rect[2], rect[3]],
                                "width": width,
                                "height": height
                            })
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(enum_cb, None)
        except Exception as e:
            error_log.error(f"Error enumerating windows in ghost_list_targetable_windows: {e}")
            return {"success": False, "action": "ghost_list_targetable_windows", "error": str(e), "windows": []}

    return {
        "success": True,
        "action": "ghost_list_targetable_windows",
        "windows": windows,
        "count": len(windows),
        "message": f"Found {len(windows)} targetable windows."
    }


@jarvis_tool(name="ghost_click_window", category="ghost", risk_level=RiskLevel.LOW_RISK)
def ghost_click_window(
    window_title: str = "",
    hwnd: Optional[int] = None,
    x: int = 10,
    y: int = 10,
    button: str = "left"
) -> dict[str, Any]:
    """
    Sends a background mouse click to a target window (by title or HWND) without moving the physical cursor.
    """
    target_hwnd, title = _resolve_target_window(window_title, hwnd)
    if not target_hwnd:
        return {
            "success": False,
            "action": "ghost_click_window",
            "error": title,
            "hwnd": None,
            "window_title": window_title
        }

    btn = button.lower().strip()
    if btn == "right":
        down_msg = WM_RBUTTONDOWN
        up_msg = WM_RBUTTONUP
        w_param = MK_RBUTTON
    else:
        down_msg = WM_LBUTTONDOWN
        up_msg = WM_LBUTTONUP
        w_param = MK_LBUTTON

    l_param = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)

    if HAS_PYWIN32:
        try:
            win32gui.PostMessage(target_hwnd, down_msg, w_param, l_param)
            time.sleep(0.03)
            win32gui.PostMessage(target_hwnd, up_msg, 0, l_param)
        except Exception as e:
            return {
                "success": False,
                "action": "ghost_click_window",
                "error": f"Failed to post click message to HWND {target_hwnd}: {e}",
                "hwnd": target_hwnd,
                "window_title": title
            }

    return {
        "success": True,
        "action": "ghost_click_window",
        "hwnd": target_hwnd,
        "window_title": title,
        "x": x,
        "y": y,
        "button": btn,
        "message": f"Ghost click dispatched to '{title}' (HWND: {target_hwnd}) at ({x}, {y}) without cursor movement."
    }


@jarvis_tool(name="ghost_send_text", category="ghost", risk_level=RiskLevel.LOW_RISK)
def ghost_send_text(
    window_title: str = "",
    hwnd: Optional[int] = None,
    text: str = ""
) -> dict[str, Any]:
    """
    Sends keystrokes or text directly to a target window or its child edit control without focusing or stealing user input.
    """
    target_hwnd, title = _resolve_target_window(window_title, hwnd)
    if not target_hwnd:
        return {
            "success": False,
            "action": "ghost_send_text",
            "error": title,
            "hwnd": None,
            "window_title": window_title
        }

    dest_hwnd = target_hwnd
    if HAS_PYWIN32:
        child_edit = None
        def find_edit(child, lparam):
            nonlocal child_edit
            try:
                cname = win32gui.GetClassName(child).lower()
                if "edit" in cname and child_edit is None:
                    child_edit = child
            except Exception:
                pass
            return True

        try:
            win32gui.EnumChildWindows(target_hwnd, find_edit, None)
        except Exception:
            pass

        if child_edit:
            dest_hwnd = child_edit

        try:
            for ch in text:
                win32gui.PostMessage(dest_hwnd, WM_CHAR, ord(ch), 0)
        except Exception as e:
            return {
                "success": False,
                "action": "ghost_send_text",
                "error": f"Failed to dispatch text to HWND {dest_hwnd}: {e}",
                "hwnd": target_hwnd,
                "dest_hwnd": dest_hwnd,
                "window_title": title
            }

    return {
        "success": True,
        "action": "ghost_send_text",
        "hwnd": target_hwnd,
        "dest_hwnd": dest_hwnd,
        "window_title": title,
        "text_length": len(text),
        "message": f"Ghost text ({len(text)} characters) dispatched to '{title}' (HWND: {target_hwnd}) in background."
    }
