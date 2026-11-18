"""
JARVIS — Operating-system adapter

The one place for desktop integrations that differ per OS (notifications, opening files
and URLs). Tools call these helpers instead of embedding PowerShell / ctypes snippets, so a
macOS or Linux port only has to fill in this module.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from core.logger import log

IS_WINDOWS = os.name == "nt"

# Text is passed through environment variables, never interpolated into the script, so
# quotes, $variables or backticks in a title/message cannot inject PowerShell code.
_WINDOWS_TOAST_SCRIPT = """
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName("text")
$textNodes.Item(0).AppendChild($template.CreateTextNode($env:JARVIS_NOTIFY_TITLE)) > $null
$textNodes.Item(1).AppendChild($template.CreateTextNode($env:JARVIS_NOTIFY_MSG)) > $null
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:JARVIS_NOTIFY_APP)
$notification = [Windows.UI.Notifications.ToastNotification]::new($template)
$notifier.Show($notification)
"""


def _notify_now(title: str, message: str, app_id: str, fallback_dialog: bool) -> bool:
    if IS_WINDOWS:
        env = os.environ.copy()
        env["JARVIS_NOTIFY_TITLE"] = str(title)
        env["JARVIS_NOTIFY_MSG"] = str(message)
        env["JARVIS_NOTIFY_APP"] = str(app_id)
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", _WINDOWS_TOAST_SCRIPT],
                           env=env, capture_output=True, timeout=5)
            return True
        except Exception as e:
            log.debug(f"[os_adapter] Toast failed: {e}")
            if fallback_dialog:
                try:
                    import ctypes
                    ctypes.windll.user32.MessageBoxW(0, message or title, f"{app_id}: {title}", 0x40 | 0x10000)
                    return True
                except Exception:
                    pass
            return False
    if sys.platform == "darwin":
        try:
            subprocess.run(["osascript", "-e", "on run argv", "-e",
                            "display notification (item 2 of argv) with title (item 1 of argv)",
                            "-e", "end run", str(title), str(message)],
                           capture_output=True, timeout=5)
            return True
        except Exception:
            return False
    try:
        subprocess.run(["notify-send", str(title), str(message)], capture_output=True, timeout=5)
        return True
    except Exception:
        log.info(f"[Notification] {title}: {message}")
        return False


def show_notification(title: str, message: str, app_id: str = "JARVIS",
                      fallback_dialog: bool = False, background: bool = True) -> None:
    """Show a desktop notification. Non-blocking by default."""
    if background:
        threading.Thread(target=_notify_now, args=(title, message, app_id, fallback_dialog),
                         daemon=True, name="JarvisNotification").start()
    else:
        _notify_now(title, message, app_id, fallback_dialog)


def open_target(target: str) -> None:
    """Open a file, folder, app name or URL with the OS default handler (no shell involved)."""
    if IS_WINDOWS:
        os.startfile(target)  # ShellExecute, same lookup as Win+R
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])
