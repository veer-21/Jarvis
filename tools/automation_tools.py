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
from typing import Optional

from core.logger import log, error_log

# ─── Optional Dependencies ───────────────────────────────────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = True  # Move mouse to top-left corner to abort
    pyautogui.PAUSE    = 0.05  # 50ms pause between actions
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False
    log.warning("pyautogui not installed — desktop automation disabled. Run: pip install pyautogui")

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
        return f"Error taking screenshot: {str(e)}"


def analyze_screen() -> str:
    """
    Take a screenshot and extract all visible text from the screen using OCR.
    Useful for reading error messages, UI elements, or understanding screen context.
    """
    if not HAS_PYAUTOGUI:
        return "Error: Cannot capture screen. pyautogui is not installed."
    
    if not HAS_EASYOCR and not HAS_PYTESSERACT:
        return "Error: Neither easyocr nor pytesseract are installed. OCR is disabled."

    try:
        screenshot = pyautogui.screenshot()
        
        if HAS_EASYOCR:
            global ocr_reader
            if ocr_reader is None:
                log.info("Initializing EasyOCR models...")
                import logging
                logging.getLogger("easyocr").setLevel(logging.ERROR)
                ocr_reader = easyocr.Reader(['en'], gpu=False)
            
            img_np = np.array(screenshot)
            results = ocr_reader.readtext(img_np, detail=0)
            text = "\n".join(results)
            log.info(f"Screen analyzed via EasyOCR. Extracted {len(text)} characters.")
            return f"Visible text on screen:\n{text}"
            
        elif HAS_PYTESSERACT:
            text = pytesseract.image_to_string(screenshot)
            log.info(f"Screen analyzed via PyTesseract. Extracted {len(text)} characters.")
            return f"Visible text on screen:\n{text}"
            
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
    if not HAS_PYAUTOGUI:
        return "Error: pyautogui is not installed."
    try:
        pyautogui.typewrite(text, interval=interval)
        log.info(f"Typed text: {text[:50]}...")
        return f"Successfully typed: '{text[:50]}{'...' if len(text)>50 else ''}'"
    except Exception as e:
        return f"Error typing text: {str(e)}"


def press_key(keys: str) -> str:
    """
    Press a keyboard key or key combination.
    Use '+' to combine keys (e.g., 'ctrl+c', 'alt+tab', 'win+d').

    Args:
        keys: Key name or combination string (e.g., 'enter', 'ctrl+s', 'f5').
    """
    if not HAS_PYAUTOGUI:
        return "Error: pyautogui is not installed."
    try:
        if "+" in keys:
            key_list = [k.strip() for k in keys.split("+")]
            pyautogui.hotkey(*key_list)
        else:
            pyautogui.press(keys.strip())
        log.info(f"Key pressed: {keys}")
        return f"Key pressed: '{keys}'"
    except Exception as e:
        return f"Error pressing key '{keys}': {str(e)}"


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