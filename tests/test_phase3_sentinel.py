"""
JARVIS Phase 3: Hardware Sentinel & Ambient Proactive Triggers Test Suite
Verifies:
1. Hardware power budgeting & telemetry computation (NORMAL, BALANCED, POWER_SAVER, CRITICAL_SAVER).
2. Dynamic ReasoningEngine token budgeting adaptation.
3. AmbientSentinel folder clutter detection.
4. AmbientSentinel smart clipboard intelligence (JSON, URL, Python traceback, file path).
5. Multi-channel proactive suggestion dispatch (WebSocket & AgentBus).
6. ProactiveDaemon sentinel integration.
7. ResultVerifier verification levels and post-condition checks for sentinel tools.
8. Brain tool routing and registration.
"""

import os
import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.sentinel import (
    PowerProfile,
    HardwareMetrics,
    AmbientSuggestion,
    HardwareSentinel,
    AmbientSentinel,
    hardware_sentinel,
    ambient_sentinel,
    sentinel_get_hardware_status,
    sentinel_run_ambient_scan,
    sentinel_set_power_profile,
)
from core.brain.verifier import ResultVerifier, VerificationLevel
from core.brain.brain import Brain
from core.daemon import ProactiveDaemon


class TestPhase3SentinelSuite:

    @pytest.fixture(autouse=True)
    def reset_sentinel_state(self):
        """Ensure clean sentinel state before and after each test."""
        hardware_sentinel.set_manual_override(None)
        ambient_sentinel._last_alert_times.clear()
        ambient_sentinel._last_clipboard_seen = None
        yield
        hardware_sentinel.set_manual_override(None)
        ambient_sentinel._last_alert_times.clear()
        ambient_sentinel._last_clipboard_seen = None

    # ── 1. Telemetry & Metrics Model ──────────────────────────────────────────

    def test_hardware_sentinel_metrics_collection(self):
        metrics = hardware_sentinel.inspect_hardware()
        assert isinstance(metrics, HardwareMetrics)
        assert 0.0 <= metrics.cpu_percent <= 100.0
        assert 0.0 <= metrics.ram_percent <= 100.0
        assert 0.0 <= metrics.disk_percent <= 100.0
        assert metrics.power_profile in list(PowerProfile)
        assert metrics.timestamp is not None

    # ── 2. Deterministic Power Profile Rules ───────────────────────────────────

    def test_power_profile_deterministic_rules(self):
        # AC plugged in (or desktop with no battery) -> NORMAL
        assert HardwareSentinel.compute_power_profile(None, True, cpu_percent=10.0) == PowerProfile.NORMAL
        assert HardwareSentinel.compute_power_profile(80.0, True, cpu_percent=15.0) == PowerProfile.NORMAL

        # AC plugged in but CPU saturated (>88%) -> POWER_SAVER
        assert HardwareSentinel.compute_power_profile(80.0, True, cpu_percent=90.0) == PowerProfile.POWER_SAVER

        # Battery discharging >= 50% -> NORMAL
        assert HardwareSentinel.compute_power_profile(75.0, False, cpu_percent=20.0) == PowerProfile.NORMAL

        # Battery discharging 25% - 49% -> BALANCED
        assert HardwareSentinel.compute_power_profile(40.0, False, cpu_percent=20.0) == PowerProfile.BALANCED

        # Battery discharging 15% - 24% -> POWER_SAVER
        assert HardwareSentinel.compute_power_profile(20.0, False, cpu_percent=10.0) == PowerProfile.POWER_SAVER

        # Battery discharging < 15% -> CRITICAL_SAVER
        assert HardwareSentinel.compute_power_profile(10.0, False, cpu_percent=5.0) == PowerProfile.CRITICAL_SAVER

    # ── 3. Manual Override and Profile Transition Listeners ────────────────────

    def test_manual_override_and_listeners(self):
        hs = HardwareSentinel()
        observed_profiles = []

        def listener(profile: PowerProfile):
            observed_profiles.append(profile)

        hs.register_profile_listener(listener)
        hs.inspect_hardware()

        # Set override to POWER_SAVER
        hs.set_manual_override(PowerProfile.POWER_SAVER)
        assert hs.get_manual_override() == PowerProfile.POWER_SAVER
        assert hs.inspect_hardware().power_profile == PowerProfile.POWER_SAVER

        # Clear override
        hs.set_manual_override(None)
        assert hs.get_manual_override() is None

        # Verify listener received transition event
        assert PowerProfile.POWER_SAVER in observed_profiles

    # ── 4. ReasoningEngine Dynamic Throttling ──────────────────────────────────

    def test_reasoning_engine_adaptive_throttling(self):
        from core.brain.reasoning_engine import ReasoningEngine

        engine = ReasoningEngine(api_key="test_key", model_name="gemini-2.0-flash")
        assert hasattr(engine, "set_power_profile")
        assert hasattr(engine, "get_power_profile")

        engine.set_power_profile(PowerProfile.NORMAL)
        assert engine.get_power_profile() == "NORMAL"

        engine.set_power_profile("POWER_SAVER")
        assert engine.get_power_profile() == "POWER_SAVER"

        engine.set_power_profile("CRITICAL_SAVER")
        assert engine.get_power_profile() == "CRITICAL_SAVER"

    # ── 5. Folder Clutter Detection ───────────────────────────────────────────

    def test_ambient_sentinel_folder_clutter_detection(self, tmp_path):
        sentinel = AmbientSentinel(clutter_threshold=5, cooldown_seconds=0)

        # Initially empty folder -> 0 suggestions
        sugs = sentinel.check_folder_clutter(target_dir=str(tmp_path))
        assert len(sugs) == 0

        # Create 6 unorganized files in tmp_path
        for i in range(6):
            (tmp_path / f"document_{i}.pdf").write_text("dummy content")

        # Also create a subfolder and a .tmp file to verify filtering
        (tmp_path / "Subfolder").mkdir()
        (tmp_path / "temp.tmp").write_text("temp")

        sugs = sentinel.check_folder_clutter(target_dir=str(tmp_path))
        assert len(sugs) == 1
        suggestion = sugs[0]
        assert suggestion.category == "folder_clutter"
        assert suggestion.suggested_action == "smart_organize_folder"
        assert suggestion.action_params["directory_path"] == str(tmp_path.resolve())

    # ── 6. Clipboard Intelligence: JSON ───────────────────────────────────────

    def test_ambient_clipboard_json_detection(self):
        sentinel = AmbientSentinel()
        json_payload = json.dumps({"status": "active", "code": 200, "message": "all systems operational"})
        sug = sentinel.analyze_clipboard_text(json_payload)

        assert sug is not None
        assert sug.category == "clipboard_json"
        assert "JSON" in sug.title
        assert sug.suggested_action == "smart_clipboard_assistant"

    # ── 7. Clipboard Intelligence: URL ────────────────────────────────────────

    def test_ambient_clipboard_url_detection(self):
        sentinel = AmbientSentinel()
        url = "https://github.com/microsoft/UFO"
        sug = sentinel.analyze_clipboard_text(url)

        assert sug is not None
        assert sug.category == "clipboard_url"
        assert "URL" in sug.title
        assert sug.suggested_action == "read_and_summarize_webpage"
        assert sug.action_params["url"] == url

    # ── 8. Clipboard Intelligence: Python Traceback ───────────────────────────

    def test_ambient_clipboard_traceback_detection(self):
        sentinel = AmbientSentinel()
        traceback_text = """
Traceback (most recent call last):
  File "main.py", line 42, in execute
    raise ZeroDivisionError("division by zero")
ZeroDivisionError: division by zero
        """.strip()
        sug = sentinel.analyze_clipboard_text(traceback_text)

        assert sug is not None
        assert sug.category == "clipboard_error"
        assert "Traceback" in sug.title
        assert sug.suggested_action == "repl_execute_python"

    # ── 9. Clipboard Intelligence: Local File Path ────────────────────────────

    def test_ambient_clipboard_file_path_detection(self, tmp_path):
        sentinel = AmbientSentinel()
        sample_file = tmp_path / "analysis.txt"
        sample_file.write_text("Sample data")

        sug = sentinel.analyze_clipboard_text(str(sample_file))
        assert sug is not None
        assert sug.category == "clipboard_file"
        assert "File Path" in sug.title
        assert sug.suggested_action == "summarize_local_document"

    # ── 10. Multi-Channel Suggestion Dispatch ──────────────────────────────────

    def test_multi_channel_suggestion_dispatch(self):
        sentinel = AmbientSentinel()
        sug = AmbientSuggestion(
            category="system_alert",
            title="System Alert Test",
            message="Testing multi-channel dispatch.",
            suggested_action="none"
        )

        with patch("api.ws_manager.ws_manager.safe_broadcast") as mock_ws, \
             patch("core.agents.agent_bus.AgentBus.broadcast") as mock_bus:
            dispatched = sentinel.dispatch_suggestion(sug, notify_toast=False, broadcast_ws=True, emit_bus=True)
            assert dispatched is True
            assert mock_ws.called
            assert mock_bus.called

    # ── 11. ProactiveDaemon Sentinel Integration ──────────────────────────────

    def test_proactive_daemon_sentinel_integration(self):
        daemon = ProactiveDaemon(sentinel_interval_seconds=1)
        assert hasattr(daemon, "hardware_sentinel")
        assert hasattr(daemon, "ambient_sentinel")
        assert hasattr(daemon, "get_hardware_status")
        assert hasattr(daemon, "get_power_profile")
        assert hasattr(daemon, "trigger_ambient_scan")

        status = daemon.get_hardware_status()
        assert "power_profile" in status
        assert "cpu_percent" in status

        profile = daemon.get_power_profile()
        assert profile in [p.value for p in PowerProfile]

        # Trigger internal check routine without throwing
        daemon._check_sentinel()

    # ── 12. ResultVerifier Levels for Sentinel Tools ──────────────────────────

    def test_result_verifier_levels_for_sentinel_tools(self):
        assert ResultVerifier.get_tool_verification_level("sentinel_get_hardware_status") == VerificationLevel.LEVEL_2
        assert ResultVerifier.get_tool_verification_level("sentinel_run_ambient_scan") == VerificationLevel.LEVEL_2
        assert ResultVerifier.get_tool_verification_level("sentinel_set_power_profile") == VerificationLevel.LEVEL_1

        # Test verification of success results
        vr_status = ResultVerifier.verify_tool_result("sentinel_get_hardware_status", {}, {
            "success": True,
            "power_profile": "NORMAL",
            "cpu_percent": 12.5,
            "battery_percent": 85.0
        })
        assert vr_status.verified is True
        assert vr_status.level == VerificationLevel.LEVEL_2

        vr_scan = ResultVerifier.verify_tool_result("sentinel_run_ambient_scan", {}, {
            "success": True,
            "suggestions_count": 2,
            "suggestions": [{"category": "folder_clutter"}]
        })
        assert vr_scan.verified is True
        assert vr_scan.level == VerificationLevel.LEVEL_2

        vr_prof = ResultVerifier.verify_tool_result("sentinel_set_power_profile", {"profile": "POWER_SAVER"}, {
            "success": True,
            "profile": "POWER_SAVER",
            "mode": "manual_override"
        })
        assert vr_prof.verified is True
        assert vr_prof.level == VerificationLevel.LEVEL_1

    # ── 13. Tool Router & Brain Integration ───────────────────────────────────

    def test_sentinel_tools_registered_in_brain(self):
        brain = Brain()
        registered = brain.tools._registry

        assert "sentinel_get_hardware_status" in registered
        assert "sentinel_run_ambient_scan" in registered
        assert "sentinel_set_power_profile" in registered

        # Execute sentinel_get_hardware_status via brain
        res1 = brain.tools.execute_tool("sentinel_get_hardware_status", {})
        assert res1.success is True
        assert "power_profile" in res1.output

        # Execute sentinel_set_power_profile via brain
        res2 = brain.tools.execute_tool("sentinel_set_power_profile", {"profile": "POWER_SAVER"})
        assert res2.success is True
        assert "POWER_SAVER" in str(res2.output)

        # Reset power profile to AUTO
        res3 = brain.tools.execute_tool("sentinel_set_power_profile", {"profile": "AUTO"})
        assert res3.success is True

