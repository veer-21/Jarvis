"""
Build the JARVIS Windows installer in one command:

    venv\\Scripts\\python.exe scripts\\build_installer.py            # full installer (desktop\\release\\*.exe)
    venv\\Scripts\\python.exe scripts\\build_installer.py --dir      # unpacked app only (faster, for testing)
    venv\\Scripts\\python.exe scripts\\build_installer.py --backend-only

Steps: build the React UI -> bundle the Python backend with PyInstaller -> package the
Electron app with electron-builder (NSIS installer). Code signing happens automatically when
CSC_LINK / CSC_KEY_PASSWORD are set in the environment (see docs/RELEASING.md).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"
PACKAGING = ROOT / "packaging"


def run(cmd: list[str], cwd: Path) -> None:
    print(f"\n>>> {' '.join(cmd)}  (in {cwd.relative_to(ROOT) if cwd != ROOT else '.'})", flush=True)
    started = time.time()
    subprocess.run(cmd, cwd=cwd, check=True, shell=(sys.platform == "win32" and cmd[0] in ("npm", "npx")))
    print(f"    done in {time.time() - started:.0f}s", flush=True)


def build_ui() -> None:
    if not (DESKTOP / "node_modules").exists():
        run(["npm", "ci"], DESKTOP)
    run(["npm", "run", "build"], DESKTOP)


def build_backend() -> Path:
    shutil.rmtree(PACKAGING / "build", ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", str(PACKAGING / "jarvis_backend.spec"), "--noconfirm",
         "--distpath", str(PACKAGING / "dist"), "--workpath", str(PACKAGING / "build")], ROOT)
    exe = PACKAGING / "dist" / "jarvis-backend" / "jarvis-backend.exe"
    if not exe.exists():
        raise SystemExit(f"Backend build failed: {exe} not found")
    size_mb = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file()) / 1e6
    print(f"    backend bundle: {exe.parent} ({size_mb:.0f} MB)")
    return exe


def build_app(unpacked: bool) -> None:
    args = ["npx", "electron-builder", "--win"] + (["--dir"] if unpacked else []) + ["--publish", "never"]
    run(args, DESKTOP)
    out = DESKTOP / "release"
    print("\nOutput:")
    for item in sorted(out.iterdir()):
        print(f"  {item}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="store_true", help="build the unpacked app instead of the installer")
    ap.add_argument("--backend-only", action="store_true")
    args = ap.parse_args()

    build_ui()
    build_backend()
    if not args.backend_only:
        build_app(unpacked=args.dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
