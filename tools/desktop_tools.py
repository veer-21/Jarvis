import platform
import time
from typing import Dict, Any, List
from core.logger import log, error_log

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
except ImportError:
    error_log.warning("pyautogui not installed.")

try:
    import pygetwindow as gw
except ImportError:
    error_log.warning("pygetwindow not installed.")

class DesktopManager:
    """Manages Desktop Operations (keyboard, mouse, windows)."""
    
    def type_text(self, text: str) -> bool:
        log.info(f"[Desktop] Typing text: {text[:20]}...")
        try:
            pyautogui.write(text, interval=0.01)
            return True
        except Exception as e:
            error_log.error(f"Failed to type text: {e}")
            return False

    def press_key(self, key: str) -> bool:
        log.info(f"[Desktop] Pressing key: {key}")
        try:
            pyautogui.press(key)
            return True
        except Exception as e:
            error_log.error(f"Failed to press key: {e}")
            return False

    def hotkey(self, *keys: str) -> bool:
        log.info(f"[Desktop] Hotkey: {'+'.join(keys)}")
        try:
            pyautogui.hotkey(*keys)
            return True
        except Exception as e:
            error_log.error(f"Failed to press hotkey: {e}")
            return False

    def click(self, x: int, y: int) -> bool:
        log.info(f"[Desktop] Clicking at ({x}, {y})")
        try:
            pyautogui.click(x=x, y=y)
            return True
        except Exception as e:
            error_log.error(f"Failed to click: {e}")
            return False

    def screenshot(self, path: str) -> bool:
        log.info(f"[Desktop] Taking screenshot: {path}")
        try:
            pyautogui.screenshot(path)
            return True
        except Exception as e:
            error_log.error(f"Failed to take screenshot: {e}")
            return False

    def get_windows(self) -> List[str]:
        log.info("[Desktop] Listing active windows")
        try:
            return [w.title for w in gw.getAllWindows() if w.title]
        except Exception as e:
            error_log.error(f"Failed to list windows: {e}")
            return []

    def activate_window(self, title: str) -> bool:
        log.info(f"[Desktop] Activating window: {title}")
        try:
            windows = gw.getWindowsWithTitle(title)
            if not windows:
                return False
            win = windows[0]
            win.activate()
            return True
        except Exception as e:
            error_log.error(f"Failed to activate window: {e}")
            return False

_manager = DesktopManager()

def desktop_type(text: str) -> str:
    return "Success" if _manager.type_text(text) else "Failed"

def desktop_press(key: str) -> str:
    return "Success" if _manager.press_key(key) else "Failed"

def desktop_hotkey(*keys: str) -> str:
    return "Success" if _manager.hotkey(*keys) else "Failed"

def desktop_click(x: int, y: int) -> str:
    return "Success" if _manager.click(x, y) else "Failed"

def desktop_screenshot(path: str) -> str:
    return "Success" if _manager.screenshot(path) else "Failed"

def desktop_list_windows() -> str:
    return str(_manager.get_windows())

def desktop_activate_window(title: str) -> str:
    return "Success" if _manager.activate_window(title) else "Failed"
