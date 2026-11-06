"""
Tests for Phase 1: Windows UI Automation (UIA) & COM Hybrid Actions
Verifies:
1. UIA Tools: uia_list_windows, uia_inspect_window, uia_click_element, uia_set_text, uia_get_text
2. COM Tools: com_get_running_apps, com_excel_write, com_excel_read, com_word_create
3. ResultVerifier integration for UIA and COM tools (Levels 2 & 3)
4. ToolRouter and Brain registration & category tagging
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from tools.uia_tools import (
    uia_list_windows, uia_inspect_window, uia_click_element,
    uia_set_text, uia_get_text
)
from tools.com_tools import (
    com_get_running_apps, com_excel_write, com_excel_read, com_word_create
)
from core.brain.verifier import ResultVerifier, VerificationLevel
from core.brain.tool_router import ToolRouter
from tools import get_tool_registry, get_tool_categories


class TestPhase1UiaComSuite:

    # ─── 1. UIA Tool Suite ────────────────────────────────────────────────────

    def test_uia_list_windows_structure(self):
        result = uia_list_windows()
        assert isinstance(result, dict)
        assert "success" in result
        assert "windows" in result
        assert isinstance(result["windows"], list)

    def test_uia_inspect_window_missing_target(self):
        # Inspecting non-existent window returns clean failure
        result = uia_inspect_window(window_title="NonExistentWindow_XYZ_12345")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_uia_click_element_validation(self):
        # Neither automation_id nor name provided
        res = uia_click_element()
        assert res["success"] is False
        assert "must provide" in res["error"].lower()

    def test_uia_click_element_with_mock_desktop(self):
        mock_desktop = MagicMock()
        mock_win = MagicMock()
        mock_elem = MagicMock()
        mock_win.window_text.return_value = "Calculator"
        mock_win.child_window.return_value = mock_elem
        mock_elem.exists.return_value = True
        mock_desktop.windows.return_value = [mock_win]

        with patch("tools.uia_tools._get_pywinauto_desktop", return_value=mock_desktop):
            res = uia_click_element(automation_id="num5Button", window_title="Calculator")
            assert res["success"] is True
            assert res["action"] == "click"
            assert res["target"]["auto_id"] == "num5Button"

    def test_uia_set_text_with_mock_desktop(self):
        mock_desktop = MagicMock()
        mock_win = MagicMock()
        mock_elem = MagicMock()
        mock_win.window_text.return_value = "Notepad"
        mock_win.child_window.return_value = mock_elem
        mock_elem.exists.return_value = True
        mock_desktop.windows.return_value = [mock_win]

        with patch("tools.uia_tools._get_pywinauto_desktop", return_value=mock_desktop):
            res = uia_set_text(text="Hello from JARVIS UIA", automation_id="TextEditor", window_title="Notepad")
            assert res["success"] is True
            assert res["action"] == "set_text"
            assert res["text_length"] == len("Hello from JARVIS UIA")

    # ─── 2. COM Tool Suite ────────────────────────────────────────────────────

    def test_com_get_running_apps(self):
        res = com_get_running_apps()
        assert res["success"] is True
        assert "apps" in res
        assert "Excel" in res["apps"]
        assert "Word" in res["apps"]

    def test_com_excel_write_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = os.path.join(tmpdir, "test_data.xlsx")
            rows = [
                ["ID", "Name", "Score"],
                ["1", "Alice", "95"],
                ["2", "Bob", "88"]
            ]

            # Write via com_excel_write (COM or openpyxl fallback)
            write_res = com_excel_write(file_path=excel_path, rows=rows, sheet_name="Grades")
            assert write_res["success"] is True
            assert os.path.exists(excel_path)
            assert os.path.getsize(excel_path) > 0

            # Read via com_excel_read
            read_res = com_excel_read(file_path=excel_path, sheet_name="Grades")
            assert read_res["success"] is True
            assert read_res["row_count"] >= 3
            assert read_res["rows"][0][0] == "ID"
            assert read_res["rows"][1][1] == "Alice"

    def test_com_word_create(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            word_path = os.path.join(tmpdir, "test_report.docx")
            res = com_word_create(
                file_path=word_path,
                title="JARVIS System Report",
                text_content="This is a test report created via native COM automation."
            )
            assert res["success"] is True
            assert os.path.exists(word_path)
            assert os.path.getsize(word_path) > 0

    # ─── 3. ResultVerifier Integration ────────────────────────────────────────

    def test_result_verifier_for_uia_and_com(self):
        # UIA Click Verification
        uia_click_res = {
            "success": True,
            "action": "click",
            "method": "UIA_InvokePattern",
            "target": {"auto_id": "btnSubmit"}
        }
        v_click = ResultVerifier.verify_tool_result("uia_click_element", {}, uia_click_res)
        assert v_click.verified is True
        assert v_click.level == VerificationLevel.LEVEL_3

        # COM Excel Write Verification with ground truth file check
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"PK\x03\x04test_excel_content")
            tmp_excel = f.name

        try:
            com_write_res = {"success": True, "file_path": tmp_excel, "rows_written": 5}
            v_excel = ResultVerifier.verify_tool_result("com_excel_write", {"file_path": tmp_excel}, com_write_res)
            assert v_excel.verified is True
            assert v_excel.level == VerificationLevel.LEVEL_3
        finally:
            if os.path.exists(tmp_excel):
                os.remove(tmp_excel)

    # ─── 4. Tool Registry & Router Integration ────────────────────────────────

    def test_tool_registry_and_categories_discovery(self):
        registry = get_tool_registry()
        categories = get_tool_categories()

        # UIA tools discovered
        assert "uia_click_element" in registry
        assert "uia_set_text" in registry
        assert "uia_inspect_window" in registry
        assert "uia" in categories

        # COM tools discovered
        assert "com_excel_read" in registry
        assert "com_excel_write" in registry
        assert "com_word_create" in registry
        assert "com" in categories

    def test_tool_router_session_affinity(self):
        router = ToolRouter()
        schema_uia = MagicMock(category="uia")
        schema_com = MagicMock(category="com")
        schema_general = MagicMock(category="general")

        assert router._is_session_affine("uia_click_element", schema_uia) is True
        assert router._is_session_affine("com_excel_write", schema_com) is True
        assert router._is_session_affine("calculate_area", schema_general) is False

