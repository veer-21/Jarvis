# Releasing JARVIS

## Release checklist

1. `uv run pytest -q` and `uv run python scripts/run_eval.py` pass (CI must be green).
2. Bump the version in `desktop/package.json`, `pyproject.toml` and `core/diagnostics.py` (`APP_VERSION`).
3. Smoke-test a fresh install on a **clean machine** (a VM or a second Windows user account —
   Windows 11 Home has no Windows Sandbox):
   - install, finish the wizard with a real key, chat, set a reminder, add a to-do,
     approve and deny a permission prompt, check Activity, export diagnostics;
   - quit from the tray and confirm no `jarvis-backend.exe` keeps running;
   - uninstall and confirm the app is gone (data in `%LOCALAPPDATA%\JARVIS` is kept by design).
4. Tag and push: `git tag v0.9.1 && git push origin v0.9.1`. The **Release** workflow builds the
   installer and publishes a GitHub release with `latest.yml`, which the in-app auto-updater uses.

## Building locally

```powershell
uv sync --extra packaging --extra voice
uv run python scripts/build_installer.py          # full installer -> desktop\release\
uv run python scripts/build_installer.py --dir    # unpacked app for quick testing
```

The backend bundle (`packaging/dist/jarvis-backend`, ~400 MB) excludes optional heavy features
(offline speech recognition, Playwright browsers); those are add-ons.

## Code signing (removes the SmartScreen warning)

Unsigned installers show "Windows protected your PC". To sign:

1. Buy a code-signing certificate (OV or EV) from a certificate authority, or use Azure Trusted
   Signing. This is an owner decision with a yearly cost.
2. Export it as a `.pfx`, base64-encode it, and add repository secrets
   `WINDOWS_CERT_BASE64` and `WINDOWS_CERT_PASSWORD`. electron-builder signs automatically.

## Crash reports

Crash reporting is opt-in for users. To receive reports, create a Sentry project, and ship the
DSN as the `SENTRY_DSN` environment variable for the backend (and install the `telemetry` extra).
Without a DSN nothing is ever sent, even if a user enables the setting.

## Auto-update

`electron-updater` checks the latest GitHub release on start-up in packaged builds
(`desktop/electron/main.js`, `build.publish` in `desktop/package.json`).
