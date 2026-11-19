"""
Test-suite isolation.

This module is imported by pytest before any test module, so the environment set here is
in place before `core.*` computes its paths or loads `.env`:

* JARVIS_DATA_DIR / JARVIS_LOG_DIR -> a throwaway temp folder. Tests can never read, modify
  or wipe the developer's real memory, keys, tasks, preferences or logs (an earlier version of
  the suite deleted the real ChromaDB collection on every run).
* Provider API keys -> empty. python-dotenv does not override variables that already exist,
  so tests can never make live (billable) LLM calls with the developer's keys.
* JARVIS_SECRET_BACKEND=memory -> secrets go to an in-process dict, never to the real
  Windows Credential Manager.
"""

import os
import shutil
import tempfile

_TEST_ROOT = tempfile.mkdtemp(prefix="jarvis-tests-")

os.environ["JARVIS_DATA_DIR"] = os.path.join(_TEST_ROOT, "data")
os.environ["JARVIS_LOG_DIR"] = os.path.join(_TEST_ROOT, "logs")
os.environ["JARVIS_SECRET_BACKEND"] = "memory"

for _key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY",
             "OLLAMA_HOST", "ELEVENLABS_API_KEY", "PICOVOICE_API_KEY", "PORCUPINE_ACCESS_KEY",
             "JARVIS_JWT_SECRET"):
    os.environ[_key] = ""


def pytest_sessionfinish(session, exitstatus):
    # Chroma may still hold file handles on Windows; best effort only.
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)


def pytest_collection_modifyitems(config, items):
    """Tests marked `desktop` launch real applications; they only run when explicitly enabled."""
    import pytest
    run_desktop = os.environ.get("JARVIS_RUN_DESKTOP_TESTS") == "1"
    run_integration = os.environ.get("JARVIS_RUN_INTEGRATION_TESTS") == "1"
    skip_desktop = pytest.mark.skip(reason="desktop test: set JARVIS_RUN_DESKTOP_TESTS=1 to run")
    skip_integration = pytest.mark.skip(reason="live web/browser test: set JARVIS_RUN_INTEGRATION_TESTS=1 to run")
    for item in items:
        if not run_desktop and "desktop" in item.keywords:
            item.add_marker(skip_desktop)
        if not run_integration and "integration" in str(item.fspath).replace("\\", "/").split("/"):
            item.add_marker(skip_integration)
