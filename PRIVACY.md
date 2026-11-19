# JARVIS Privacy Policy

_Last updated: 2026-11-19 · Applies to the JARVIS desktop app (beta)._

JARVIS is designed to keep your information on your own computer. This page explains exactly what
is stored, what leaves your PC, and how to delete it.

## What stays on your computer

| Data | Where | Notes |
|---|---|---|
| Conversations (recent history) | `%LOCALAPPDATA%\JARVIS\memory` | Passwords, keys, card numbers and similar are redacted before saving |
| Long-term memories (preferences, facts you share) | same | Only stored for meaningful messages; never credentials; "forget …" deletes them |
| Reminders, to-dos, settings, activity log | `%LOCALAPPDATA%\JARVIS` | Activity entries have secrets masked |
| AI provider API keys | Windows Credential Manager ("JARVIS/…") | Protected by your Windows login; never shown again in the app |
| Memory encryption key | `%LOCALAPPDATA%\JARVIS\security` | Protected with Windows DPAPI (only your Windows account can unlock it) |
| Logs | `%LOCALAPPDATA%\JARVIS\logs` | Used for troubleshooting; never uploaded automatically |

Nobody else — including the makers of JARVIS — can access this data. There are no accounts and no
server of ours involved.

## What leaves your computer

1. **Your messages go to the AI provider you choose** (Google Gemini, Groq or OpenAI), together
   with relevant memories and recent conversation needed to answer, and descriptions of the tools
   JARVIS can use. Those providers process it under their own privacy policies and terms. If you
   use **Local AI (Ollama)**, nothing is sent anywhere.
2. **Web tools** (search, reading pages, weather, news) contact the websites involved, like a
   browser would.
3. **Voice**: the default Windows voice works offline. The optional Microsoft Edge voice sends
   the reply text to Microsoft to generate audio. Speech recognition is offline when the voice
   add-on is installed; the optional Google speech recognition (off by default) sends your
   recorded audio to Google.
4. **Crash reports** are **off by default**. If you turn them on in Settings, error reports (with
   secrets, request data and local variables removed) are sent to the developers' error tracker.
5. **Updates**: the app checks the project's GitHub releases for new versions.

JARVIS has **no analytics, advertising or tracking**.

## Exporting diagnostics

**Settings → Export diagnostics** creates a zip on your PC that you can choose to share for
support. It contains system information, settings, which providers are configured (yes/no only),
recent activity and log excerpts with credentials redacted. It does **not** contain your API
keys, memories, conversations or file contents.

## Deleting your data

- Say "forget …" to remove specific memories, or **Reset** to clear the current session.
- Uninstalling keeps your data so you can reinstall. To delete everything, remove
  `%LOCALAPPDATA%\JARVIS` and the "JARVIS/…" entries in Windows Credential Manager.

## Contact

Questions about privacy: open an issue on the project's GitHub page.
