"""
JARVIS Desktop Automation Tools
Provides system-level automation capabilities:
  - take_screenshot       : Capture the full screen
  - get_active_window     : Return the title of the focused window
  - type_text             : Type text at the current cursor position
  - press_key             : Press a keyboard key or combo (e.g. ctrl+c)
  - move_mouse            : Move mouse to screen coordinates
  - click_mouse           : Click at current or specified position
  - scroll_mouse          : Scroll up or down
  - open_application      : Launch a Windows application by name/path
  - get_system_info       : CPU, RAM, disk usage
"""

import os
import subprocess
import platform
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from core.logger import log, error_log

# ─── Optional Dependencies ───────────────────────────────────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = True  # Move mouse to top-left corner to abort
    pyautogui.PAUSE    = 0.05  # 50ms pause between actions
    HAS_PYAUTOGUI = True
except (ImportError, KeyError, Exception) as e:
    HAS_PYAUTOGUI = False
    log.warning(f"pyautogui not available ({e}) — desktop automation disabled.")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    log.warning("psutil not installed — system monitoring limited. Run: pip install psutil")

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import winocr
    HAS_WINOCR = True
except ImportError:
    HAS_WINOCR = False

try:
    import easyocr
    import numpy as np
    HAS_EASYOCR = True
    ocr_reader = None
except ImportError:
    HAS_EASYOCR = False

try:
    import pytesseract
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False

# ─── Emergency Kill Switch & Sleep Prevention ────────────────────────────────
_EMERGENCY_STOP = False

def trigger_emergency_stop() -> str:
    """Instantly halt any running desktop automation and lock digital hands."""
    global _EMERGENCY_STOP
    _EMERGENCY_STOP = True
    log.critical("[SAFETY] Emergency Dead-Man's Switch activated! Halting desktop automation.")
    return "EMERGENCY STOP ACTIVATED: Desktop automation has been suspended."

def reset_emergency_stop() -> str:
    """Reset the emergency abort switch."""
    global _EMERGENCY_STOP
    _EMERGENCY_STOP = False
    log.info("[SAFETY] Emergency switch reset.")
    return "Emergency stop reset. Automation re-enabled."

def is_emergency_stopped() -> bool:
    """Check if emergency switch is triggered."""
    return _EMERGENCY_STOP

def prevent_windows_sleep(enable: bool = True) -> bool:
    """
    Prevent Windows from sleeping or blanking the display while a task is running.
    Uses Win32 SetThreadExecutionState.
    """
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_DISPLAY_REQUIRED = 0x00000002
        if enable:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
            log.info("[OS Power] Sleep prevention enabled for active task.")
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            log.info("[OS Power] Sleep prevention released.")
        return True
    except Exception as e:
        log.warning(f"[OS Power] Could not set thread execution state: {e}")
        return False

# ─── Screenshot Directory ────────────────────────────────────────────────────
SCREENSHOT_DIR = Path(__file__).parent.parent / "data" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ─── Tools ───────────────────────────────────────────────────────────────────

def take_screenshot(filename: Optional[str] = None) -> str:
    """
    Capture a full screenshot of the screen and save it to disk.
    Returns the file path of the saved screenshot.

    Args:
        filename: Optional custom filename (without extension). Auto-generates timestamp if not provided.
    """
    if not HAS_PYAUTOGUI:
        return "Error: pyautogui is not installed. Run: pip install pyautogui pillow"

    try:
        if not filename:
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        filepath = SCREENSHOT_DIR / f"{filename}.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(filepath)
        log.info(f"Screenshot saved: {filepath}")
        return f"Screenshot saved to: {filepath}"
    except Exception as e:
        error_log.error(f"Screenshot failed: {e}")
        if "screen grab failed" in str(e).lower() or "display" in str(e).lower():
            return "Error: Screen capture requires an active, unlocked Windows desktop session (headless or locked sessions cannot capture screen pixels)."
        return f"Error taking screenshot: {str(e)}"


def analyze_screen(image: Optional[Any] = None) -> str:
    """
    Take a screenshot (or analyze provided image) and extract visible text using OCR.
    Useful for reading error messages, UI elements, or understanding screen context.
    
    Args:
        image: Optional PIL Image or image file path. If None, captures the current screen.
    """
    if not HAS_WINOCR and not HAS_EASYOCR and not HAS_PYTESSERACT:
        return "Error: No OCR engine is available. Run: pip install winocr"

    screenshot = None
    if image is not None:
        if isinstance(image, str):
            from PIL import Image
            screenshot = Image.open(image)
        else:
            screenshot = image
    else:
        if not HAS_PYAUTOGUI:
            return "Error: Cannot capture screen. pyautogui is not installed."
        try:
            screenshot = pyautogui.screenshot()
        except Exception as e:
            if "screen grab failed" in str(e).lower() or "display" in str(e).lower():
                return "Error: Screen analysis requires an active, unlocked Windows desktop session (headless or locked sessions cannot capture screen pixels)."
            return f"Error capturing screen for analysis: {str(e)}"

    try:
        if HAS_WINOCR:
            import asyncio
            import concurrent.futures
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    res = pool.submit(winocr.recognize_pil_sync, screenshot).result()
            else:
                res = winocr.recognize_pil_sync(screenshot)

            text = res.get("text", "").strip()
            log.info(f"Screen analyzed via winocr. Extracted {len(text)} characters.")
            return f"Visible text on screen:\n{text}" if text else "No text detected on screen."

        elif HAS_EASYOCR:
            global ocr_reader
            if ocr_reader is None:
                log.info("Initializing EasyOCR models...")
                import logging
                logging.getLogger("easyocr").setLevel(logging.ERROR)
                ocr_reader = easyocr.Reader(['en'], gpu=False)
            
            img_np = np.array(screenshot)
            results = ocr_reader.readtext(img_np, detail=0)
            text = "\n".join(results).strip()
            log.info(f"Screen analyzed via EasyOCR. Extracted {len(text)} characters.")
            return f"Visible text on screen:\n{text}" if text else "No text detected on screen."

        elif HAS_PYTESSERACT:
            text = pytesseract.image_to_string(screenshot).strip()
            log.info(f"Screen analyzed via PyTesseract. Extracted {len(text)} characters.")
            return f"Visible text on screen:\n{text}" if text else "No text detected on screen."

    except Exception as e:
        error_log.error(f"Screen analysis failed: {e}")
        return f"Error analyzing screen: {str(e)}"


def get_active_window() -> str:
    """Return the title of the currently active/focused window."""
    try:
        if platform.system() == "Windows":
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return f"Active window: '{buf.value}'"
        else:
            return "Active window detection only supported on Windows."
    except Exception as e:
        return f"Error getting active window: {str(e)}"


def type_text(text: str, interval: float = 0.03) -> str:
    """
    Type text at the current cursor position using the keyboard.

    Args:
        text:     The text string to type.
        interval: Delay between each keypress in seconds (default 0.03s).
    """
    if _EMERGENCY_STOP:
        return "Aborted: Emergency kill switch is ACTIVE. Actions blocked."

    # Try PyAutoGUI first if available and cursor is not at failsafe corner
    if HAS_PYAUTOGUI:
        try:
            pyautogui.FAILSAFE = False
            pyautogui.typewrite(text, interval=interval)
            log.info(f"Typed text: {text[:50]}...")
            return f"Successfully typed: '{text[:50]}{'...' if len(text)>50 else ''}'"
        except Exception as e:
            log.warning(f"PyAutoGUI typewrite failed ({e}). Falling back to Win32 keybd_event...")

    # Windows API fallback
    if platform.system() == "Windows":
        try:
            import ctypes
            import time
            user32 = ctypes.windll.user32
            for char in text:
                vk = user32.VkKeyScanW(ord(char))
                if vk != -1:
                    shift = (vk >> 8) & 1
                    code = vk & 0xFF
                    if shift:
                        user32.keybd_event(0x10, 0, 0, 0) # Shift down
                    user32.keybd_event(code, 0, 0, 0)
                    user32.keybd_event(code, 0, 2, 0)
                    if shift:
                        user32.keybd_event(0x10, 0, 2, 0) # Shift up
                time.sleep(interval)
            log.info(f"Typed text via Win32: {text[:50]}...")
            return f"Successfully typed: '{text[:50]}{'...' if len(text)>50 else ''}'"
        except Exception as e:
            return f"Error typing text via Win32: {str(e)}"

    return "Error: Neither PyAutoGUI nor Win32 typing succeeded."


def press_key(keys: str) -> str:
    """
    Press a keyboard key or key combination.
    Use '+' to combine keys (e.g., 'ctrl+c', 'alt+tab', 'win+d').

    Args:
        keys: Key name or combination string (e.g., 'enter', 'ctrl+s', 'f5').
    """
    if _EMERGENCY_STOP:
        return "Aborted: Emergency kill switch is ACTIVE. Actions blocked."

    if HAS_PYAUTOGUI:
        try:
            pyautogui.FAILSAFE = False
            if "+" in keys:
                key_list = [k.strip() for k in keys.split("+")]
                pyautogui.hotkey(*key_list)
            else:
                pyautogui.press(keys.strip())
            log.info(f"Key pressed: {keys}")
            return f"Key pressed: '{keys}'"
        except Exception as e:
            log.warning(f"PyAutoGUI press_key failed ({e}). Falling back to Win32...")

    # Windows fallback
    if platform.system() == "Windows":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            key_map = {
                "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "tab": 0x09, "space": 0x20,
                "backspace": 0x08, "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B
            }
            clean_key = keys.lower().strip()
            vk_code = key_map.get(clean_key)
            if vk_code:
                user32.keybd_event(vk_code, 0, 0, 0)
                user32.keybd_event(vk_code, 0, 2, 0)
                return f"Key pressed via Win32: '{keys}'"
        except Exception as e:
            return f"Error pressing key via Win32: {str(e)}"

    return f"Error pressing key '{keys}'"


def open_application(app_name: str) -> str:
    """
    Launch a Windows application by name or executable path.
    Supports common app names like 'notepad', 'chrome', 'calculator', 'explorer'.

    Args:
        app_name: Application name or full executable path.
    """
    # Common app name aliases
    APP_ALIASES: dict[str, str] = {
        "chrome":       "chrome",
        "google chrome": "chrome",
        "browser":      "chrome",
        "notepad":      "notepad",
        "calculator":   "calc",
        "calc":         "calc",
        "paint":        "mspaint",
        "explorer":     "explorer",
        "file manager": "explorer",
        "file explorer": "explorer",
        "files":        "explorer",
        "cmd":          "cmd",
        "command prompt": "cmd",
        "terminal":     "wt",
        "powershell":   "powershell",
        "word":         "winword",
        "excel":        "excel",
        "powerpoint":   "powerpnt",
        "outlook":      "outlook",
        "vscode":       "code",
        "vs code":      "code",
        "visual studio code": "code",
        "spotify":      "spotify",
        "discord":      "discord",
        "task manager": "taskmgr",
        "settings":     "ms-settings:",
        "control panel": "control",
        "snipping tool": "snippingtool",
        "snip":         "snippingtool",
        "edge":         "msedge",
        "microsoft edge": "msedge",
        "firefox":      "firefox",
        "teams":        "msteams",
        "slack":        "slack",
        "zoom":         "zoom",
        "obs":          "obs64",
        "obs studio":   "obs64",
        "steam":        "steam",
        "vlc":          "vlc",
        "media player": "wmplayer",
    }

    resolved = APP_ALIASES.get(app_name.lower().strip(), app_name)
    try:
        subprocess.Popen(f"start {resolved}", shell=True)
        log.info(f"Application launched: {app_name} (resolved: {resolved})")
        return f"Launched '{app_name}' successfully."
    except Exception as e:
        error_log.error(f"Failed to open {app_name}: {e}")
        return f"Failed to open '{app_name}': {str(e)}"


def click_mouse(x: Optional[int] = None, y: Optional[int] = None, clicks: int = 1, button: str = "left") -> str:
    """
    Click mouse at specific screen coordinates or current position.

    Args:
        x: X-coordinate (optional). If None, clicks at current mouse position.
        y: Y-coordinate (optional). If None, clicks at current mouse position.
        clicks: Number of clicks (1 for single click, 2 for double click).
        button: Mouse button ('left', 'right', 'middle'). Default 'left'.
    """
    if _EMERGENCY_STOP:
        return "Aborted: Emergency kill switch is ACTIVE. Mouse actions blocked."
    if not HAS_PYAUTOGUI:
        return "Error: pyautogui is not installed."
    try:
        if x is not None and y is not None:
            pyautogui.click(x=x, y=y, clicks=clicks, button=button)
            return f"Clicked {button} button at ({x}, {y}) {clicks} time(s)."
        else:
            pyautogui.click(clicks=clicks, button=button)
            pos = pyautogui.position()
            return f"Clicked {button} button at current position ({pos.x}, {pos.y}) {clicks} time(s)."
    except Exception as e:
        if "screen grab failed" in str(e).lower() or "display" in str(e).lower() or "failsafe" in str(e).lower():
            return "Error: Mouse action requires an active, unlocked Windows desktop session."
        return f"Error clicking mouse: {str(e)}"


def move_mouse(x: int, y: int, duration: float = 0.2) -> str:
    """
    Move mouse to specified coordinates.

    Args:
        x: X-coordinate.
        y: Y-coordinate.
        duration: Time in seconds for the move animation (default 0.2s).
    """
    if _EMERGENCY_STOP:
        return "Aborted: Emergency kill switch is ACTIVE. Mouse actions blocked."
    if not HAS_PYAUTOGUI:
        return "Error: pyautogui is not installed."
    try:
        pyautogui.moveTo(x=x, y=y, duration=duration)
        return f"Moved mouse to ({x}, {y})."
    except Exception as e:
        if "screen grab failed" in str(e).lower() or "display" in str(e).lower() or "failsafe" in str(e).lower():
            return "Error: Mouse action requires an active, unlocked Windows desktop session."
        return f"Error moving mouse: {str(e)}"


def scroll_mouse(clicks: int) -> str:
    """
    Scroll mouse wheel. Positive value scrolls up, negative scrolls down.

    Args:
        clicks: Number of scroll clicks (e.g. 5 for up, -5 for down).
    """
    if _EMERGENCY_STOP:
        return "Aborted: Emergency kill switch is ACTIVE. Mouse actions blocked."
    if not HAS_PYAUTOGUI:
        return "Error: pyautogui is not installed."
    try:
        pyautogui.scroll(clicks)
        return f"Scrolled mouse wheel by {clicks} units."
    except Exception as e:
        if "screen grab failed" in str(e).lower() or "display" in str(e).lower() or "failsafe" in str(e).lower():
            return "Error: Mouse action requires an active, unlocked Windows desktop session."
        return f"Error scrolling mouse: {str(e)}"


def list_open_windows() -> str:
    """
    List all visible open windows or active running desktop applications.
    Useful for seeing which applications are currently open and available to interact with.
    """
    if platform.system() != "Windows":
        return "Window listing only supported on Windows."

    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        windows = []

        def enum_windows_proc(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    if title and title not in ["Program Manager", "Default IME", "MSCTFIME UI"]:
                        windows.append(title)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        proc = WNDENUMPROC(enum_windows_proc)
        user32.EnumWindows(proc, 0)

        if windows:
            formatted = "\n".join(f"- {w}" for w in windows[:25])
            return f"Open Windows ({len(windows)} found):\n{formatted}"

        # Fallback: inspect GUI processes via psutil if desktop session isolation is active
        if HAS_PSUTIL:
            gui_apps = set()
            for p in psutil.process_iter(['name']):
                try:
                    name = p.info['name']
                    if name and name.lower().endswith('.exe'):
                        base = name[:-4].lower()
                        if base in ['chrome', 'msedge', 'code', 'antigravity ide', 'notepad', 'calc', 'whatsapp.root', 'spotify', 'explorer', 'discord', 'slack', 'teams']:
                            gui_apps.add(name[:-4])
                except Exception:
                    pass
            if gui_apps:
                formatted = "\n".join(f"- {app}" for app in sorted(gui_apps))
                return f"Running Desktop Applications ({len(gui_apps)} detected):\n{formatted}"

        return "No visible top-level windows detected."
    except Exception as e:
        return f"Error listing open windows: {str(e)}"


def focus_window(title_keyword: str) -> str:
    """
    Find an open application window by keyword and bring it to the foreground.

    Args:
        title_keyword: Substring of the window title or app name to match (case-insensitive).
    """
    if platform.system() != "Windows":
        return "Window focus is only supported on Windows."

    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        target_hwnd = None
        matched_title = ""
        keyword_lower = title_keyword.lower().strip()

        def enum_windows_proc(hwnd, lParam):
            nonlocal target_hwnd, matched_title
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    if keyword_lower in title.lower():
                        target_hwnd = hwnd
                        matched_title = title
                        return False  # stop enumeration
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        proc = WNDENUMPROC(enum_windows_proc)
        user32.EnumWindows(proc, 0)

        if target_hwnd:
            SW_RESTORE = 9
            user32.ShowWindow(target_hwnd, SW_RESTORE)
            user32.SetForegroundWindow(target_hwnd)
            log.info(f"Focused window: '{matched_title}' (HWND: {target_hwnd})")
            return f"Successfully brought '{matched_title}' to foreground."

        # Fallback: attempt to bring app up via open_application
        return open_application(title_keyword)

    except Exception as e:
        return f"Error focusing window matching '{title_keyword}': {str(e)}"


def get_system_info() -> str:
    """
    Return current system resource usage: CPU, RAM, disk, and process count.
    """
    if not HAS_PSUTIL:
        return "Error: psutil is not installed. Run: pip install psutil"

    try:
        cpu_pct    = psutil.cpu_percent(interval=1)
        cpu_count  = psutil.cpu_count()
        ram        = psutil.virtual_memory()
        disk       = psutil.disk_usage("/")
        net        = psutil.net_io_counters()
        proc_count = len(list(psutil.process_iter()))

        info = f"""System Status Report
{'─'*40}
CPU Usage:     {cpu_pct}%  ({cpu_count} cores)
RAM:           {ram.percent}% used  ({ram.used / 1e9:.1f} GB / {ram.total / 1e9:.1f} GB)
Disk (C:):     {disk.percent}% used  ({disk.used / 1e9:.1f} GB / {disk.total / 1e9:.1f} GB)
Network In:    {net.bytes_recv / 1e6:.1f} MB received
Network Out:   {net.bytes_sent / 1e6:.1f} MB sent
Processes:     {proc_count} running
Platform:      {platform.system()} {platform.release()}
"""
        return info.strip()

    except Exception as e:
        return f"Error getting system info: {str(e)}"