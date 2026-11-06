"""
JARVIS Native COM Automation Tools (Phase 1)
Direct programmatic automation for Windows applications (Excel, Word, Shell) via COM.

Inspired by microsoft/UFO:
Provides background API manipulation of Office and Windows apps without GUI screen typing.
"""

import os
import sys
from pathlib import Path
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field

from core.logger import log, error_log

# ─── Pydantic Parameter Schemas ───────────────────────────────────────────────

class ComExcelReadArgs(BaseModel):
    file_path: str = Field(..., description="Absolute path to .xlsx or .xls file.")
    sheet_name: Optional[str] = Field(default=None, description="Sheet name to read. Defaults to active sheet.")
    max_rows: int = Field(default=100, description="Maximum rows to read (default: 100).")

class ComExcelWriteArgs(BaseModel):
    file_path: str = Field(..., description="Absolute path to target .xlsx file.")
    rows: List[List[Any]] = Field(..., description="2D list of row values to write, e.g. [['Name', 'Score'], ['Alice', 95]].")
    sheet_name: Optional[str] = Field(default=None, description="Sheet name to write to.")

class ComWordCreateArgs(BaseModel):
    file_path: str = Field(..., description="Target file path for created .docx document.")
    text_content: str = Field(..., description="Main text body for the document.")
    title: Optional[str] = Field(default=None, description="Optional title heading for document top.")

class ComGetRunningAppsArgs(BaseModel):
    pass


# ─── Helper Functions ─────────────────────────────────────────────────────────

def _init_com() -> bool:
    """Initialize COM apartment for the current thread and suppress CRT RPC noise."""
    try:
        import faulthandler
        if faulthandler.is_enabled():
            faulthandler.disable()
    except Exception:
        pass
    try:
        import pythoncom
        pythoncom.CoInitialize()
        return True
    except Exception:
        return False

def _uninit_com() -> None:
    """Uninitialize COM apartment for the current thread and restore faulthandler."""
    try:
        import pythoncom
        pythoncom.CoUninitialize()
    except Exception:
        pass
    try:
        import faulthandler
        if not faulthandler.is_enabled():
            faulthandler.enable()
    except Exception:
        pass


# ─── Primary COM Implementations ──────────────────────────────────────────────

def com_get_running_apps() -> Dict[str, Any]:
    """
    Check for active COM-registered applications (Excel, Word, Outlook, PowerPoint).
    """
    _init_com()
    apps = {}
    known_prog_ids = [
        ("Excel", "Excel.Application"),
        ("Word", "Word.Application"),
        ("Outlook", "Outlook.Application"),
        ("PowerPoint", "PowerPoint.Application")
    ]

    try:
        import win32com.client
        for friendly_name, prog_id in known_prog_ids:
            try:
                obj = win32com.client.GetActiveObject(prog_id)
                apps[friendly_name] = {
                    "running": True,
                    "prog_id": prog_id,
                    "visible": getattr(obj, "Visible", None)
                }
            except Exception:
                apps[friendly_name] = {"running": False, "prog_id": prog_id}
                
        return {
            "success": True,
            "apps": apps
        }
    except ImportError:
        return {"success": False, "error": "win32com.client is not available.", "apps": {}}
    except Exception as e:
        return {"success": False, "error": str(e), "apps": {}}
    finally:
        _uninit_com()


def com_excel_read(file_path: str, sheet_name: Optional[str] = None, max_rows: int = 100) -> Dict[str, Any]:
    """
    Read tabular data from Excel workbook via background COM dispatch (with openpyxl fallback).
    """
    p = Path(file_path).resolve()
    if not p.exists():
        return {"success": False, "error": f"File '{file_path}' does not exist."}

    _init_com()
    # Try native COM dispatch first if Excel is running or available
    try:
        import win32com.client
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        try:
            wb = excel.Workbooks.Open(str(p), ReadOnly=True)
            ws = wb.Sheets(sheet_name) if sheet_name else wb.ActiveSheet
            sheet_title = str(getattr(ws, "Name", "Active"))
            
            used_range = ws.UsedRange
            raw_data = used_range.Value
            del used_range
            del ws
            wb.Close(SaveChanges=False)
            del wb
            
            rows = []
            if raw_data:
                for row in list(raw_data)[:max_rows]:
                    rows.append([None if cell is None else str(cell) for cell in row])

            log.info(f"[COM] Successfully read {len(rows)} rows from Excel '{p.name}' via COM.")
            return {
                "success": True,
                "method": "COM_Excel_Dispatch",
                "filename": p.name,
                "sheet": sheet_title,
                "row_count": len(rows),
                "rows": rows
            }
        finally:
            try:
                excel.Quit()
                del excel
            except Exception:
                pass
    except Exception as com_err:
        log.warning(f"[COM] Native Excel COM read failed ({com_err}). Trying openpyxl fallback...")
    finally:
        _uninit_com()
        
    # Openpyxl fallback
    try:
        import openpyxl
        wb = openpyxl.load_workbook(p, data_only=True)
        ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active
        rows = []
        for row in list(ws.iter_rows(values_only=True))[:max_rows]:
            rows.append([None if c is None else str(c) for c in row])
        wb.close()
        
        return {
            "success": True,
            "method": "openpyxl_fallback",
            "filename": p.name,
            "sheet": ws.title,
            "row_count": len(rows),
            "rows": rows
        }
    except Exception as fallback_err:
        return {"success": False, "error": f"Failed to read Excel workbook: {fallback_err}"}


def com_excel_write(file_path: str, rows: List[List[Any]], sheet_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Write 2D row data to an Excel workbook via COM (or openpyxl fallback).
    """
    if not rows:
        return {"success": False, "error": "No data rows provided to write."}

    p = Path(file_path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    _init_com()
    # Try native COM dispatch first if Excel is available
    try:
        import win32com.client
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        try:
            if p.exists():
                wb = excel.Workbooks.Open(str(p))
                ws = wb.Sheets(sheet_name) if sheet_name else wb.ActiveSheet
            else:
                wb = excel.Workbooks.Add()
                ws = wb.ActiveSheet
                if sheet_name:
                    ws.Name = sheet_name

            for r_idx, row in enumerate(rows, start=1):
                for c_idx, val in enumerate(row, start=1):
                    ws.Cells(r_idx, c_idx).Value = val

            wb.SaveAs(str(p))
            wb.Close(SaveChanges=True)
            del ws
            del wb

            log.info(f"[COM] Wrote {len(rows)} rows to '{p}' via Excel COM.")
            return {
                "success": True,
                "method": "COM_Excel_Dispatch",
                "file_path": str(p),
                "rows_written": len(rows)
            }
        finally:
            try:
                excel.Quit()
                del excel
            except Exception:
                pass
    except Exception as com_err:
        log.warning(f"[COM] Native Excel COM write failed ({com_err}). Using openpyxl fallback...")
    finally:
        _uninit_com()

    # Openpyxl fallback
    try:
        import openpyxl
        if p.exists():
            wb = openpyxl.load_workbook(p)
            ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            if sheet_name:
                ws.title = sheet_name

        for row in rows:
            ws.append(row)

        wb.save(p)
        wb.close()

        return {
            "success": True,
            "method": "openpyxl_fallback",
            "file_path": str(p),
            "rows_written": len(rows)
        }
    except Exception as fallback_err:
        return {"success": False, "error": f"Failed to write Excel workbook: {fallback_err}"}


def com_word_create(file_path: str, text_content: str, title: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a formatted Word document via Word COM dispatch (with python-docx fallback).
    """
    p = Path(file_path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    _init_com()
    # Try native COM dispatch first if Word is available
    try:
        import win32com.client
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        try:
            doc = word.Documents.Add()
            if title:
                title_range = doc.Paragraphs.Add().Range
                title_range.Text = title + "\n"
                title_range.Font.Bold = True
                title_range.Font.Size = 16

            body_range = doc.Paragraphs.Add().Range
            body_range.Text = text_content
            body_range.Font.Size = 11

            doc.SaveAs(str(p))
            doc.Close()
            del doc

            log.info(f"[COM] Created Word doc '{p}' via Word COM.")
            return {
                "success": True,
                "method": "COM_Word_Dispatch",
                "file_path": str(p),
                "title": title,
                "bytes": p.stat().st_size if p.exists() else 0
            }
        finally:
            try:
                word.Quit()
                del word
            except Exception:
                pass
    except Exception as com_err:
        log.warning(f"[COM] Word COM dispatch failed ({com_err}). Using python-docx fallback...")
    finally:
        _uninit_com()

    # python-docx fallback
    try:
        import docx
        doc = docx.Document()
        if title:
            doc.add_heading(title, level=1)
        doc.add_paragraph(text_content)
        doc.save(p)

        return {
            "success": True,
            "method": "python_docx_fallback",
            "file_path": str(p),
            "title": title,
            "bytes": p.stat().st_size
        }
    except Exception as fallback_err:
        return {"success": False, "error": f"Failed to create Word document: {fallback_err}"}
