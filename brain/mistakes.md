# Project Brain — Mistakes Log

This log lists resolved issues, structural failures, and recommendations for avoiding regressions in the JARVIS codebase.

---

## 1. Blocking Voice Capture Loop

* **Problem**: When continuous voice recognition failed or switched to slower cloud transcription engines, the main UI/CLI process would freeze.
* **Cause**: Audio capture and speech recognition routines were running on the primary execution thread.
* **Fix**: Re-architect `core/voice_manager.py` to offload recording/streaming to a separate background thread using thread-safe queues.
* **Status**: Resolved.

---

## 2. Brittle Intent Classifier Matches

* **Problem**: Bypassing the LLM worked for "open chrome" but failed for "could you open chrome please" or "launch the browser".
* **Cause**: Rigid hardcoded regex anchors.
* **Fix**: Expand intent mappings to support broad optional prefixes and prepare for lightweight spaCy fuzzy-intent matching.
* **Status**: Partially Resolved (active work).

---

## 3. Powershell Command Execution Blockages

* **Problem**: Triggering python command lines like `venv\Scripts\pytest` on mapped drives (e.g. `d:`) inside PowerShell returned ObjectNotFound or DriveNotFound exceptions.
* **Cause**: Mapped drives and relative subdirectory paths run into security restrictions or missing drive contexts in child shell instances.
* **Fix**: Use absolute paths, specify the interpreter explicitly (e.g., `python test_architecture.py`), or invoke CMD instances directly via `cmd.exe /c` where necessary.
* **Status**: Resolved.
