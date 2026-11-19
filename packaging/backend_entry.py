"""
Entry point of the packaged JARVIS backend (jarvis-backend.exe).

The desktop app starts this process, passes JARVIS_LOCAL_TOKEN in the environment and talks to
it on 127.0.0.1:7799. Data lives in %LOCALAPPDATA%\JARVIS (see core/paths.py).
"""

import multiprocessing
import os
import sys


def main() -> None:
    multiprocessing.freeze_support()
    # Bundled UI (same React build the desktop window loads) for browser access.
    if getattr(sys, "frozen", False):
        os.environ.setdefault("JARVIS_UI_DIR", os.path.join(sys._MEIPASS, "ui"))  # type: ignore[attr-defined]
    import uvicorn
    from api.server import app
    from core.config import get_api_host, get_api_port

    uvicorn.run(app, host=get_api_host(), port=get_api_port(), log_level="info")


if __name__ == "__main__":
    main()
