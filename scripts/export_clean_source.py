"""
JARVIS — Clean Source Bundler
Generates D:\Jarvis\jarvis_clean_source.zip containing all project source files,
strictly excluding virtual environments, dependencies, build caches, git objects, and archives.
"""

import os
import shutil
import zipfile
from pathlib import Path

WORKSPACE_ROOT = Path(r"D:\Jarvis")
OUTPUT_ZIP_PATH = WORKSPACE_ROOT / "jarvis_clean_source.zip"
OUTPUT_PHASE6_ZIP_PATH = WORKSPACE_ROOT / "jarvis_phase6_clean_source.zip"
OUTPUT_ZIP_PATHS = [OUTPUT_ZIP_PATH, OUTPUT_PHASE6_ZIP_PATH]

EXCLUDED_DIR_NAMES = {
    "venv",
    ".venv",
    "node_modules",
    ".git",
    "__pycache__",
    ".pytest_cache",
    "chroma",
    "chromadb",
    ".idea",
    ".vscode",
}

EXCLUDED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".zip",
    ".tar",
    ".gz",
}

EXCLUDED_FILENAMES = {
    ".env",
    "desktop_folder_without_nodemodules.zip",
    "jarvis_clean_source.zip",
    "jarvis_phase_verification.zip",
    "jarvis_phase6_clean_source.zip",
    "jarvis_phase6_verification.zip",
}


def build_clean_source_zip():
    print(f"=== Creating Clean Source ZIP at {OUTPUT_ZIP_PATH} ===")
    file_count = 0
    total_uncompressed_bytes = 0

    with zipfile.ZipFile(OUTPUT_ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(WORKSPACE_ROOT):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES and not d.startswith(".")]

            for file in files:
                filepath = Path(root) / file
                rel_path = filepath.relative_to(WORKSPACE_ROOT)
                rel_str = str(rel_path).replace("\\", "/")

                # Check excluded files
                if file in EXCLUDED_FILENAMES or file.endswith(".zip"):
                    continue
                if filepath.suffix.lower() in EXCLUDED_EXTENSIONS:
                    continue
                if any(part in EXCLUDED_DIR_NAMES for part in rel_path.parts):
                    continue

                zf.write(filepath, arcname=rel_str)
                file_count += 1
                total_uncompressed_bytes += filepath.stat().st_size

    zip_size = OUTPUT_ZIP_PATH.stat().st_size
    print(f"Successfully packaged {file_count} clean source files.")
    print(f"Uncompressed size: {total_uncompressed_bytes:,} bytes")
    print(f"Archive size: {zip_size:,} bytes")

    # Also output Phase 6 named archive
    shutil.copyfile(OUTPUT_ZIP_PATH, OUTPUT_PHASE6_ZIP_PATH)
    print(f"Successfully mirrored to {OUTPUT_PHASE6_ZIP_PATH} ({OUTPUT_PHASE6_ZIP_PATH.stat().st_size} bytes)")
    print("=== Clean Source ZIP Generation Complete ===")


if __name__ == "__main__":
    build_clean_source_zip()
