"""
JARVIS Phase 3: Hardware Sentinel & Ambient Proactive Triggers Engine
Provides hardware power budgeting, battery telemetry, thermal/CPU load detection,
adaptive LLM throttling, proactive folder declutter detection, smart clipboard
intelligence, and multi-channel proactive notifications (Windows Toast, WebSocket, AgentBus).
"""

import os
import re
import json
import time
import uuid
import psutil
import threading
from enum import Enum
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
from pydantic import BaseModel, Field

from core.logger import log, error_log


# ─── Data Enums & Models ────────────────────────────────────────────────────────

class PowerProfile(str, Enum):
    NORMAL = "NORMAL"                  # AC power or Battery > 50%
    BALANCED = "BALANCED"              # Battery between 25% and 50%
    POWER_SAVER = "POWER_SAVER"        # Battery 15-25% or sustained CPU > 85%
    CRITICAL_SAVER = "CRITICAL_SAVER"  # Battery < 15%


class HardwareMetrics(BaseModel):
    battery_percent: Optional[float] = None
    power_plugged: Optional[bool] = None
    battery_secs_left: Optional[int] = None
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    disk_percent: float = 0.0
    power_profile: PowerProfile = PowerProfile.NORMAL
    thermal_throttling_suspected: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AmbientSuggestion(BaseModel):
    id: str = Field(default_factory=lambda: f"sug_{uuid.uuid4().hex[:8]}")
    category: str  # "folder_clutter", "clipboard_json", "clipboard_url", "clipboard_error", "low_battery", "system_alert"
    title: str
    message: str
    suggested_action: str
    action_params: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─── Tool Parameter Schemas ─────────────────────────────────────────────────────

class SentinelGetHardwareStatusArgs(BaseModel):
    pass


class SentinelRunAmbientScanArgs(BaseModel):
    folder_path: Optional[str] = Field(None, description="Optional target directory to inspect for clutter (defaults to Downloads and Desktop)")


class SentinelSetPowerProfileArgs(BaseModel):
    profile: str = Field(..., description="Target power profile ('NORMAL', 'BALANCED', 'POWER_SAVER', 'CRITICAL_SAVER')")


# ─── Hardware Sentinel Engine ───────────────────────────────────────────────────

class HardwareSentinel:
    """
    Monitors host hardware vitals (battery, CPU, RAM, disk) and computes
    dynamic power budget profiles to adaptively throttle AI models and background tasks.
    """

    def __init__(self):
        self._manual_override: Optional[PowerProfile] = None
        self._profile_listeners: List[Callable[[PowerProfile], None]] = []
        self._last_metrics: Optional[HardwareMetrics] = None
        self._lock = threading.Lock()

    def register_profile_listener(self, callback: Callable[[PowerProfile], None]) -> None:
        """Register a callback to be notified when the power profile changes."""
        with self._lock:
            if callback not in self._profile_listeners:
                self._profile_listeners.append(callback)

    def set_manual_override(self, profile: Optional[PowerProfile]) -> None:
        """Set or clear a manual power profile override."""
        with self._lock:
            self._manual_override = profile
        log.info(f"[HardwareSentinel] Manual power profile override set to: {profile}")
        self.inspect_hardware()

    def get_manual_override(self) -> Optional[PowerProfile]:
        with self._lock:
            return self._manual_override

    @staticmethod
    def compute_power_profile(
        battery_percent: Optional[float],
        power_plugged: Optional[bool],
        cpu_percent: float = 0.0
    ) -> PowerProfile:
        """
        Deterministic power profile computation based on power state and CPU load.
        """
        # If desktop with no battery sensor or plugged into AC power
        if power_plugged is True or battery_percent is None:
            if cpu_percent >= 88.0:
                return PowerProfile.POWER_SAVER
            return PowerProfile.NORMAL

        # Discharging on battery
        if battery_percent < 15.0:
            return PowerProfile.CRITICAL_SAVER
        elif battery_percent < 25.0:
            return PowerProfile.POWER_SAVER
        elif battery_percent < 50.0:
            return PowerProfile.BALANCED
        else:
            if cpu_percent >= 88.0:
                return PowerProfile.POWER_SAVER
            return PowerProfile.NORMAL

    def inspect_hardware(self) -> HardwareMetrics:
        """
        Collect real-time hardware telemetry and compute current power profile.
        """
        try:
            battery = psutil.sensors_battery()
        except Exception as e:
            log.debug(f"psutil sensors_battery unavailable: {e}")
            battery = None

        bat_pct = float(battery.percent) if battery else None
        plugged = bool(battery.power_plugged) if battery else None
        secs_left = int(battery.secsleft) if (battery and battery.secsleft > 0) else None

        try:
            cpu = float(psutil.cpu_percent(interval=None))
        except Exception:
            cpu = 0.0

        try:
            ram = float(psutil.virtual_memory().percent)
        except Exception:
            ram = 0.0

        try:
            disk = float(psutil.disk_usage(os.getenv("SystemDrive", "C:") + "\\").percent)
        except Exception:
            disk = 0.0

        with self._lock:
            if self._manual_override is not None:
                profile = self._manual_override
            else:
                profile = self.compute_power_profile(bat_pct, plugged, cpu)

        # Detect potential thermal throttling / CPU saturation
        thermal_suspected = cpu > 92.0

        metrics = HardwareMetrics(
            battery_percent=bat_pct,
            power_plugged=plugged,
            battery_secs_left=secs_left,
            cpu_percent=cpu,
            ram_percent=ram,
            disk_percent=disk,
            power_profile=profile,
            thermal_throttling_suspected=thermal_suspected,
        )

        old_profile = self._last_metrics.power_profile if self._last_metrics else None
        self._last_metrics = metrics

        # Notify listeners if profile transitioned
        if old_profile is not None and old_profile != profile:
            log.info(f"[HardwareSentinel] Power profile transitioned: {old_profile} -> {profile}")
            with self._lock:
                listeners = list(self._profile_listeners)
            for listener in listeners:
                try:
                    listener(profile)
                except Exception as err:
                    error_log.error(f"[HardwareSentinel] Listener error: {err}")

        return metrics

    def get_last_metrics(self) -> HardwareMetrics:
        if self._last_metrics is None:
            return self.inspect_hardware()
        return self._last_metrics


# ─── Ambient Sentinel Engine ────────────────────────────────────────────────────

class AmbientSentinel:
    """
    Proactively detects environmental triggers:
    1. Unorganized file accumulation in Downloads & Desktop.
    2. Meaningful clipboard entries (JSON, URLs, Python errors, file paths).
    3. Multi-channel proactive suggestion dispatch (Windows Toast, WebSocket, AgentBus).
    """

    def __init__(self, clutter_threshold: int = 15, cooldown_seconds: int = 300):
        self.clutter_threshold = clutter_threshold
        self.cooldown_seconds = cooldown_seconds
        self._last_alert_times: Dict[str, float] = {}
        self._last_clipboard_seen: Optional[str] = None
        self._dispatched_suggestions: List[AmbientSuggestion] = []
        self._lock = threading.Lock()

    def _in_cooldown(self, key: str) -> bool:
        now = time.time()
        last = self._last_alert_times.get(key, 0.0)
        return (now - last) < self.cooldown_seconds

    def _record_alert(self, key: str) -> None:
        self._last_alert_times[key] = time.time()

    def check_folder_clutter(self, target_dir: Optional[str] = None) -> List[AmbientSuggestion]:
        """
        Inspect directories for unorganized files.
        Ignores hidden files, .tmp/.crdownload partial downloads, and existing subdirectories.
        """
        suggestions: List[AmbientSuggestion] = []

        dirs_to_check: List[Path] = []
        if target_dir:
            dirs_to_check.append(Path(os.path.expandvars(target_dir)).resolve())
        else:
            home = Path.home()
            downloads = home / "Downloads"
            desktop = home / "Desktop"
            if downloads.exists() and downloads.is_dir():
                dirs_to_check.append(downloads)
            if desktop.exists() and desktop.is_dir():
                dirs_to_check.append(desktop)

        for folder in dirs_to_check:
            folder_key = f"clutter_{folder.name.lower()}"
            if self._in_cooldown(folder_key):
                continue

            try:
                unorganized_files = [
                    f for f in folder.iterdir()
                    if f.is_file()
                    and not f.name.startswith(".")
                    and not f.name.endswith((".tmp", ".crdownload", ".part"))
                    and f.name.lower() != "undo_manifest.json"
                ]
            except Exception as e:
                log.debug(f"[AmbientSentinel] Could not inspect {folder}: {e}")
                continue

            count = len(unorganized_files)
            if count >= self.clutter_threshold:
                self._record_alert(folder_key)
                sug = AmbientSuggestion(
                    category="folder_clutter",
                    title=f"Declutter Suggestion: {folder.name}",
                    message=f"Your {folder.name} folder has {count} unorganized files. Would you like JARVIS to categorize them automatically?",
                    suggested_action="smart_organize_folder",
                    action_params={"directory_path": str(folder), "dry_run": False}
                )
                suggestions.append(sug)
                log.info(f"[AmbientSentinel] Generated clutter suggestion for {folder} ({count} files)")

        return suggestions

    def analyze_clipboard_text(self, text: Optional[str]) -> Optional[AmbientSuggestion]:
        """
        Analyze clipboard payload and detect structured opportunities:
        - Formatted or unformatted JSON
        - Web URLs
        - Python stack trace / exception
        - Existing local file paths
        """
        if not text:
            return None

        raw = text.strip()
        if len(raw) < 5 or len(raw) > 50000:
            return None

        # 1. Python Stack Trace / Exception
        if "Traceback (most recent call last):" in raw or (
            re.search(r"^[A-Z][a-zA-Z0-9]+(?:Error|Exception):", raw, re.MULTILINE) and "\n" in raw
        ):
            return AmbientSuggestion(
                category="clipboard_error",
                title="Exception Traceback Detected",
                message="A programming error or traceback was copied to your clipboard. Would you like JARVIS to analyze the root cause?",
                suggested_action="repl_execute_python",
                action_params={"code": f"# Analyze exception:\n'''\n{raw[:2000]}\n'''"}
            )

        # 2. JSON Payload
        if (raw.startswith("{") and raw.endswith("}")) or (raw.startswith("[") and raw.endswith("]")):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, (dict, list)) and len(parsed) >= 2:
                    return AmbientSuggestion(
                        category="clipboard_json",
                        title="JSON Data Detected",
                        message="Valid JSON data was detected on your clipboard. Inspect, format, or convert with JARVIS?",
                        suggested_action="smart_clipboard_assistant",
                        action_params={"action": "read"}
                    )
            except Exception:
                pass

        # 3. HTTP/HTTPS URL
        if re.match(r"^https?://[^\s/$.?#].[^\s]*$", raw, re.IGNORECASE):
            return AmbientSuggestion(
                category="clipboard_url",
                title="Web URL Detected",
                message=f"Copied link: {raw[:50]}... Fetch webpage summary or open in browser?",
                suggested_action="read_and_summarize_webpage",
                action_params={"url": raw}
            )

        # 4. Local File / Directory Path
        try:
            candidate_path = Path(raw)
            if candidate_path.exists() and candidate_path.is_file():
                return AmbientSuggestion(
                    category="clipboard_file",
                    title="File Path Detected",
                    message=f"Local file path detected: {candidate_path.name}. Would you like JARVIS to summarize or inspect it?",
                    suggested_action="summarize_local_document",
                    action_params={"file_path": str(candidate_path)}
                )
        except Exception:
            pass

        return None

    def poll_clipboard(self) -> Optional[AmbientSuggestion]:
        """
        Poll clipboard safely and generate a suggestion if novel content is detected.
        """
        try:
            import pyperclip
            raw_text = pyperclip.paste()
        except Exception:
            raw_text = None

        if not raw_text or raw_text == self._last_clipboard_seen:
            return None

        self._last_clipboard_seen = raw_text
        sug = self.analyze_clipboard_text(raw_text)
        if sug:
            clip_key = f"clip_{sug.category}_{hash(raw_text[:60])}"
            if self._in_cooldown(clip_key):
                return None
            self._record_alert(clip_key)
            return sug
        return None

    def dispatch_suggestion(
        self,
        suggestion: AmbientSuggestion,
        notify_toast: bool = True,
        broadcast_ws: bool = True,
        emit_bus: bool = True
    ) -> bool:
        """
        Dispatch a proactive suggestion across multiple delivery channels.
        """
        with self._lock:
            self._dispatched_suggestions.append(suggestion)
            if len(self._dispatched_suggestions) > 100:
                self._dispatched_suggestions = self._dispatched_suggestions[-100:]

        log.info(f"[AmbientSentinel] Dispatching [{suggestion.category}]: {suggestion.title}")

        # 1. Native Windows Toast Notification (Cooperative non-blocking background thread)
        if notify_toast and os.name == "nt":
            def _toast():
                try:
                    import subprocess
                    ps_script = """
                    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
                    $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
                    $textNodes = $template.GetElementsByTagName("text")
                    $textNodes.Item(0).AppendChild($template.CreateTextNode($env:JARVIS_TOAST_TITLE)) > $null
                    $textNodes.Item(1).AppendChild($template.CreateTextNode($env:JARVIS_TOAST_MSG)) > $null
                    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("JARVIS Sentinel")
                    $notification = [Windows.UI.Notifications.ToastNotification]::new($template)
                    $notifier.Show($notification)
                    """
                    env = os.environ.copy()
                    env["JARVIS_TOAST_TITLE"] = str(suggestion.title)
                    env["JARVIS_TOAST_MSG"] = str(suggestion.message)
                    subprocess.run(
                        ["powershell", "-NoProfile", "-Command", ps_script],
                        env=env,
                        capture_output=True,
                        timeout=5
                    )
                except Exception as e:
                    log.debug(f"[AmbientSentinel] Toast dispatch fallback: {e}")

            threading.Thread(target=_toast, daemon=True, name="JarvisSentinelToast").start()

        # 2. WebSocket Broadcast (To Cyberpunk HUD & React Desktop App)
        if broadcast_ws:
            try:
                from api.ws_manager import ws_manager
                ws_manager.safe_broadcast({
                    "type": "ambient_suggestion",
                    "suggestion": suggestion.model_dump()
                })
            except Exception as e:
                log.debug(f"[AmbientSentinel] WebSocket broadcast skipped: {e}")

        # 3. AgentBus Broadcast
        if emit_bus:
            try:
                from core.agents.agent_bus import AgentBus
                bus = AgentBus.get_bus()
                bus.broadcast({
                    "sender": "sentinel",
                    "content": suggestion.title,
                    "type": "ambient:suggestion",
                    "suggestion": suggestion.model_dump()
                })
            except Exception as e:
                log.debug(f"[AmbientSentinel] AgentBus event skipped: {e}")

        return True

    def run_ambient_scan(self, target_folder: Optional[str] = None) -> List[AmbientSuggestion]:
        """
        Run a full ambient scan across configured folders and clipboard.
        """
        results: List[AmbientSuggestion] = []

        # 1. Folder clutter
        clutter_sugs = self.check_folder_clutter(target_folder)
        for s in clutter_sugs:
            self.dispatch_suggestion(s)
            results.append(s)

        # 2. Clipboard
        clip_sug = self.poll_clipboard()
        if clip_sug:
            self.dispatch_suggestion(clip_sug)
            results.append(clip_sug)

        return results


# ─── Global Sentinel Singletons ─────────────────────────────────────────────────

hardware_sentinel = HardwareSentinel()
ambient_sentinel = AmbientSentinel()


# ─── Sentinel Tool Wrappers for ToolRouter ──────────────────────────────────────

def sentinel_get_hardware_status() -> Dict[str, Any]:
    """
    Inspects battery level, AC power state, CPU load, RAM usage, and active power profile.
    Used by JARVIS to dynamically budget computation and advise the user on system vitals.
    """
    metrics = hardware_sentinel.inspect_hardware()
    return {
        "success": True,
        "power_profile": metrics.power_profile.value,
        "battery_percent": metrics.battery_percent,
        "power_plugged": metrics.power_plugged,
        "battery_secs_left": metrics.battery_secs_left,
        "cpu_percent": metrics.cpu_percent,
        "ram_percent": metrics.ram_percent,
        "disk_percent": metrics.disk_percent,
        "thermal_throttling_suspected": metrics.thermal_throttling_suspected,
        "timestamp": metrics.timestamp
    }


def sentinel_run_ambient_scan(folder_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Scans the local environment (Downloads, Desktop, clipboard) for proactive triggers,
    generating smart decluttering and contextual suggestions.
    """
    suggestions = ambient_sentinel.run_ambient_scan(target_folder=folder_path)
    return {
        "success": True,
        "suggestions_count": len(suggestions),
        "suggestions": [s.model_dump() for s in suggestions],
        "scanned_targets": [folder_path] if folder_path else ["Downloads", "Desktop", "Clipboard"]
    }


def sentinel_set_power_profile(profile: str) -> Dict[str, Any]:
    """
    Manually overrides the active hardware power profile ('NORMAL', 'BALANCED', 'POWER_SAVER', 'CRITICAL_SAVER', or 'AUTO').
    """
    p_upper = (profile or "AUTO").strip().upper()
    if p_upper == "AUTO":
        hardware_sentinel.set_manual_override(None)
        current = hardware_sentinel.inspect_hardware().power_profile.value
        return {
            "success": True,
            "profile": current,
            "mode": "automatic",
            "message": f"Hardware power profile restored to automatic detection ({current})."
        }

    try:
        target_profile = PowerProfile(p_upper)
        hardware_sentinel.set_manual_override(target_profile)
        return {
            "success": True,
            "profile": target_profile.value,
            "mode": "manual_override",
            "message": f"Hardware power profile manually set to {target_profile.value}."
        }
    except ValueError:
        valid_profiles = [p.value for p in PowerProfile] + ["AUTO"]
        return {
            "success": False,
            "error": f"Invalid power profile '{profile}'. Must be one of: {', '.join(valid_profiles)}"
        }
