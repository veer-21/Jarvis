"""
JARVIS Enhanced File Tools
Provides safe, audited file system operations:
  - read_file        : Read any text file
  - write_file       : Write/append to a file
  - list_directory   : List contents of a directory
  - safe_delete_file : Delete with confirmation gate
  - get_file_info    : Metadata about a file/directory
  - search_in_files  : Grep-like search across files
"""

import os
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

from core.logger import audit_log, log
from core.security import guard

# ─── Safety: Restricted Paths ────────────────────────────────────────────────
# JARVIS will never access or modify these paths without explicit override.
RESTRICTED_PATHS: list[str] = [
    os.environ.get("WINDIR", "C:/Windows").lower(),
    "c:/program files",
    "c:/program files (x86)",
    "c:/users/default",
]

def _is_restricted(path: str) -> bool:
    abs_path = Path(path).resolve().as_posix().lower()
    return any(abs_path.startswith(r) for r in RESTRICTED_PATHS)


# ─── Tools ───────────────────────────────────────────────────────────────────

def read_file(path: str, max_chars: int = 50_000) -> str:
    """
    Read the contents of a text file and return it as a string.
    Limits output to max_chars characters to avoid overwhelming the context window.

    Args:
        path: Absolute or relative path to the file.
        max_chars: Maximum characters to return (default 50,000).
    """
    try:
        path = os.path.expandvars(os.path.expanduser(path))
        resolved = Path(path).resolve()
        guard.log_file_access("READ", str(resolved), allowed=True)

        if not resolved.exists():
            return f"Error: File not found — {resolved}"
        if resolved.is_dir():
            return f"Error: '{resolved}' is a directory, not a file. Use list_directory instead."

        text = resolved.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[...truncated — file is {len(text):,} chars total]"
        log.info(f"File read: {resolved}")
        return text

    except PermissionError:
        return f"Error: Permission denied reading '{path}'."
    except Exception as e:
        return f"Error reading file: {str(e)}"


def write_file(path: str, content: str, mode: str = "write") -> str:
    """
    Write content to a file.

    Args:
        path:    Path to the file. Parent directories will be created if needed.
        content: The text content to write.
        mode:    'write' (overwrite) or 'append'.
    """
    try:
        path = os.path.expandvars(os.path.expanduser(path))
        resolved = Path(path).resolve()

        if _is_restricted(str(resolved)):
            guard.log_file_access("WRITE_BLOCKED", str(resolved), allowed=False)
            return f"Error: Writing to '{resolved}' is restricted for security reasons."

        resolved.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            with open(resolved, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            resolved.write_text(content, encoding="utf-8")

        guard.log_file_access("WRITE", str(resolved), allowed=True)
        log.info(f"File written ({mode}): {resolved}")
        return f"Successfully wrote {len(content):,} characters to '{resolved}'."

    except PermissionError:
        return f"Error: Permission denied writing to '{path}'."
    except Exception as e:
        return f"Error writing file: {str(e)}"


def list_directory(path: str = ".") -> str:
    """
    List the contents of a directory, showing files and folders with sizes.

    Args:
        path: Directory path to list (default: current directory).
    """
    try:
        path = os.path.expandvars(os.path.expanduser(path))
        resolved = Path(path).resolve()

        if not resolved.exists():
            return f"Error: Path not found — {resolved}"
        if not resolved.is_dir():
            return f"Error: '{resolved}' is a file, not a directory."

        entries = []
        for item in sorted(resolved.iterdir()):
            if item.is_dir():
                entries.append(f"📁  {item.name}/")
            else:
                size = item.stat().st_size
                size_str = f"{size:,} B" if size < 1024 else f"{size/1024:.1f} KB"
                entries.append(f"📄  {item.name}  ({size_str})")

        if not entries:
            return f"Directory is empty: {resolved}"

        return f"Contents of '{resolved}' ({len(entries)} items):\n" + "\n".join(entries)

    except PermissionError:
        return f"Error: Permission denied accessing '{path}'."
    except Exception as e:
        return f"Error listing directory: {str(e)}"


def safe_delete_file(path: str) -> str:
    """
    Safely delete a file or empty directory. Always requires explicit owner confirmation.

    Args:
        path: Path to the file or directory to delete.
    """
    path = os.path.expandvars(os.path.expanduser(path))
    resolved = Path(path).resolve()

    if _is_restricted(str(resolved)):
        guard.log_file_access("DELETE_BLOCKED", str(resolved), allowed=False)
        return f"Error: Deleting '{resolved}' is restricted for security reasons."

    if not resolved.exists():
        return f"Error: '{resolved}' does not exist."

    # Always gate deletions — show confirmation prompt
    print(f"\n⚠️  JARVIS wants to DELETE: {resolved}")
    print(f"   Type: {'Directory' if resolved.is_dir() else 'File'}")
    try:
        approval = input("   Confirm deletion? (yes/no): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        approval = "no"

    if approval not in ("yes", "y"):
        guard.log_file_access("DELETE_DENIED", str(resolved), allowed=False)
        return "Deletion cancelled by owner."

    try:
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        guard.log_file_access("DELETE", str(resolved), allowed=True)
        log.info(f"File/Dir deleted: {resolved}")
        return f"Successfully deleted '{resolved}'."
    except Exception as e:
        return f"Error deleting '{path}': {str(e)}"


def get_file_info(path: str) -> str:
    """
    Return detailed metadata about a file or directory.

    Args:
        path: Path to inspect.
    """
    try:
        path = os.path.expandvars(os.path.expanduser(path))
        resolved = Path(path).resolve()

        if not resolved.exists():
            return f"Error: Path not found — {resolved}"

        stat = resolved.stat()
        info = {
            "path":         str(resolved),
            "name":         resolved.name,
            "type":         "directory" if resolved.is_dir() else "file",
            "size_bytes":   stat.st_size,
            "size_human":   f"{stat.st_size / 1024:.1f} KB",
            "created":      datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            "modified":     datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "extension":    resolved.suffix if resolved.is_file() else "N/A",
            "readable":     os.access(resolved, os.R_OK),
            "writable":     os.access(resolved, os.W_OK),
        }

        if resolved.is_dir():
            items = list(resolved.iterdir())
            info["children"] = len(items)

        lines = [f"File Info: {resolved.name}"]
        for k, v in info.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error getting file info: {str(e)}"


def search_in_files(directory: str, query: str, extension: str = ".txt") -> str:
    """
    Search for a text query across all files of a given extension in a directory.

    Args:
        directory: Root directory to search in.
        query:     Text to search for (case-insensitive).
        extension: File extension filter (default: .txt). Use '*' for all files.
    """
    try:
        directory = os.path.expandvars(os.path.expanduser(directory))
        root = Path(directory).resolve()
        if not root.is_dir():
            return f"Error: '{directory}' is not a valid directory."

        pattern = f"*{extension}" if extension != "*" else "*"
        matches = []

        for filepath in root.rglob(pattern):
            if not filepath.is_file():
                continue
            try:
                text = filepath.read_text(encoding="utf-8", errors="ignore")
                lines = text.splitlines()
                for line_no, line in enumerate(lines, start=1):
                    if query.lower() in line.lower():
                        rel = filepath.relative_to(root)
                        matches.append(f"{rel}:{line_no}:  {line.strip()[:120]}")
                        if len(matches) >= 50:
                            break
            except Exception:
                continue

            if len(matches) >= 50:
                break

        if not matches:
            return f"No matches found for '{query}' in '{directory}'."

        header = f"Found {len(matches)} match(es) for '{query}' in '{root}':\n"
        return header + "\n".join(matches)

    except Exception as e:
        return f"Error during file search: {str(e)}"
