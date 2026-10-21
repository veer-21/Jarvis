"""
JARVIS — Active Window & Screen Context Tools
Provides foreground window inspection, active application tracking, clipboard capture,
and on-screen OCR text recognition for vision-grounded screen assistance.
"""

import os
import sys
import ctypes
import asyncio
import concurrent.futures
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from core.logger import log, error_log
from core.security import mask_sensitive_data

# Optional imports with graceful fallbacks
try:
    import psutil
except ImportError:
    psutil = None

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import pyautogui
except ImportError:
    pyautogui = None


# ─── Pydantic Schema ─────────────────────────────────────────────────────────

class GetActiveWindowContextInput(BaseModel):
    include_ocr: bool = Field(True, description="Whether to capture on-screen OCR text from the active window")
    include_clipboard: bool = Field(True, description="Whether to inspect current clipboard contents for selected text")


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _ocr_coroutine(image):
    """Asynchronously calls winocr on an image."""
    import winocr
    res = await winocr.recognize_pil(image, "en")
    return getattr(res, "text", "") or ""


def _extract_ocr_from_image(image) -> str:
    """Safely extracts text using winocr in a dedicated thread/event loop."""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, _ocr_coroutine(image))
            return future.result(timeout=4.0) or ""
    except Exception as e:
        log.debug(f"[ContextTools] OCR extraction bypassed or unavailable: {e}")
        return ""


# ─── Tool Implementation ─────────────────────────────────────────────────────

def get_active_window_context(
    include_ocr: bool = True,
    include_clipboard: bool = True
) -> Dict[str, Any]:
    """
    Captures the active foreground window context, process name, current clipboard text,
    and on-screen OCR text for vision-grounded screen assistance.
    Masks any sensitive credentials or keys before returning.
    """
    window_title = "Desktop / Active Workspace"
    process_name = "explorer.exe"
    pid = 0
    rect = (0, 0, 800, 600)

    # 1. Win32 Active Window Inspection
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    if buff.value:
                        window_title = buff.value.strip()

                p = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
                if p.value:
                    pid = p.value
                    if psutil:
                        try:
                            proc = psutil.Process(pid)
                            process_name = proc.name()
                        except Exception:
                            process_name = f"pid_{pid}"

                class RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long)
                    ]
                r = RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                    rect = (r.left, r.top, r.right, r.bottom)
        except Exception as e:
            log.debug(f"[ContextTools] Win32 inspection fallback: {e}")

    # 2. Clipboard Extraction
    clipboard_text = ""
    if include_clipboard and pyperclip:
        try:
            raw_clip = pyperclip.paste()
            if raw_clip and isinstance(raw_clip, str):
                clipboard_text = raw_clip[:4000].strip()
        except Exception as e:
            log.debug(f"[ContextTools] Clipboard read failed: {e}")

    # 3. OCR Text Extraction
    ocr_text = ""
    if include_ocr and pyautogui:
        try:
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            if width > 50 and height > 50 and left >= 0 and top >= 0:
                screenshot = pyautogui.screenshot(region=(left, top, width, height))
            else:
                screenshot = pyautogui.screenshot()
            
            raw_ocr = _extract_ocr_from_image(screenshot)
            if raw_ocr:
                ocr_text = raw_ocr[:8000].strip()
        except Exception as e:
            log.debug(f"[ContextTools] Screenshot / OCR failed: {e}")

    # 4. Mask sensitive secrets
    masked_window_title = mask_sensitive_data(window_title)
    masked_clipboard = mask_sensitive_data(clipboard_text)
    masked_ocr = mask_sensitive_data(ocr_text)

    word_count = len(masked_ocr.split()) if masked_ocr else 0
    clip_words = len(masked_clipboard.split()) if masked_clipboard else 0

    summary = (
        f"Active window: '{masked_window_title}' (Application: {process_name}, PID: {pid}). "
        f"Captured {word_count} words from active screen and {clip_words} words from clipboard."
    )

    return {
        "success": True,
        "window_title": masked_window_title,
        "process_name": process_name,
        "pid": pid,
        "clipboard_text": masked_clipboard,
        "ocr_text": masked_ocr,
        "has_selection": bool(masked_clipboard),
        "summary": summary
    }
