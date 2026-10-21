"""
JARVIS — Phase Verification Bundler
Produces D:\Jarvis\jarvis_phase_verification.zip containing all modified and newly created
source files and verification_manifest.json for external auditing.
"""

import os
import sys
import json
import time
import hashlib
import zipfile
import subprocess
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(r"D:\Jarvis")
OUTPUT_ZIP_PATH = WORKSPACE_ROOT / "jarvis_phase_verification.zip"

ALLOWED_PREFIXES = (
    "core/",
    "api/",
    "tools/",
    "desktop/src/",
    "desktop/electron/",
    "ui/",
    "tests/",
    "scripts/",
)

EXCLUDED_PARTS = {
    "venv",
    ".venv",
    "node_modules",
    ".git",
    "__pycache__",
    ".pytest_cache",
    "chroma",
}


def compute_sha256(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def count_lines(filepath: Path) -> int:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def run_command(cmd: list[str]) -> tuple[int, str, str]:
    print(f"Running: {' '.join(cmd)}...")
    t0 = time.perf_counter()
    res = subprocess.run(
        cmd,
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    dt = time.perf_counter() - t0
    stdout = res.stdout if res.stdout is not None else ""
    stderr = res.stderr if res.stderr is not None else ""
    print(f"  Finished in {dt:.2f}s with exit code {res.returncode}")
    return res.returncode, stdout, stderr


def get_git_status_and_diff() -> tuple[str, str, list[str]]:
    # Get git status
    _, status_out, _ = run_command(["git", "status", "--porcelain"])
    _, diff_out, _ = run_command(["git", "diff"])

    candidates = set()
    for line in status_out.splitlines():
        line = line.strip()
        if not line:
            continue
        # Format is XY path or XY "path"
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            raw_path = parts[1].strip().strip('"').replace("\\", "/")
            if " -> " in raw_path:
                raw_path = raw_path.split(" -> ")[1].strip().strip('"').replace("\\", "/")
            candidates.add(raw_path)

    # Filter to allowed directories and exclusions
    included_files = []
    for rel_path in sorted(candidates):
        # Must match allowed prefix
        if not any(rel_path.startswith(p) for p in ALLOWED_PREFIXES):
            continue
        # Must not contain excluded directories
        path_parts = set(Path(rel_path).parts)
        if any(exc in path_parts for exc in EXCLUDED_PARTS):
            continue
        full_path = WORKSPACE_ROOT / rel_path
        if full_path.is_file():
            included_files.append(rel_path)

    return status_out, diff_out, included_files


def main():
    print(f"=== JARVIS Verification Bundler Started ===")
    print(f"Workspace: {WORKSPACE_ROOT}")
    print(f"Output: {OUTPUT_ZIP_PATH}")

    # Python executable
    py_exe = str(WORKSPACE_ROOT / "venv" / "Scripts" / "python.exe")
    if not os.path.exists(py_exe):
        py_exe = sys.executable

    # 1. Bytecode compilation
    compile_code, compile_stdout, compile_stderr = run_command(
        [py_exe, "-m", "compileall", "-q", "core", "api", "tools", "main.py", "tests"]
    )

    # 2. Pytest execution
    test_code, test_stdout, test_stderr = run_command(
        [py_exe, "-m", "pytest", "-v"]
    )

    # 3. Git status, diff & modified files
    git_status, git_diff, modified_files = get_git_status_and_diff()

    # Calculate metrics for each included file
    file_records = []
    for rel_path in modified_files:
        full_path = WORKSPACE_ROOT / rel_path
        sha = compute_sha256(full_path)
        lines = count_lines(full_path)
        file_records.append({
            "path": rel_path,
            "sha256": sha,
            "line_count": lines,
            "size_bytes": full_path.stat().st_size
        })

    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "platform": sys.platform,
        "compilation": {
            "command": f"{py_exe} -m compileall -q core api tools main.py tests",
            "exit_code": compile_code,
            "stdout": compile_stdout,
            "stderr": compile_stderr,
        },
        "pytest": {
            "command": f"{py_exe} -m pytest -v",
            "exit_code": test_code,
            "stdout": test_stdout,
            "stderr": test_stderr,
        },
        "git": {
            "status": git_status,
            "diff_summary_lines": len(git_diff.splitlines()),
            "diff": git_diff,
        },
        "files_included": file_records,
    }

    # 4. Create ZIP bundle
    print(f"Creating ZIP bundle at {OUTPUT_ZIP_PATH} with {len(modified_files)} files...")
    with zipfile.ZipFile(OUTPUT_ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # Write manifest
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        z.writestr("verification_manifest.json", manifest_bytes)

        # Write files
        for rel_path in modified_files:
            full_path = WORKSPACE_ROOT / rel_path
            z.write(full_path, arcname=rel_path)

    print(f"Successfully generated {OUTPUT_ZIP_PATH} ({OUTPUT_ZIP_PATH.stat().st_size} bytes)")
    print("=== Verification Bundler Completed ===")


if __name__ == "__main__":
    main()
