# JARVIS User Guide

JARVIS is a personal assistant that lives on your Windows PC. You talk to it (by typing or
voice), and it can chat, remember things you tell it, set reminders, keep your to-do list, find
and organize files, look things up on the web and open apps for you.

It **always asks before doing anything risky**, and you can see everything it did.

---

## 1. Install

1. Download **JARVIS Setup.exe** from the releases page and run it.
   - If Windows SmartScreen says "Windows protected your PC", choose **More info → Run anyway**.
     (This appears until the installer is code-signed.)
2. Start **JARVIS** from the Start menu or the desktop shortcut.
3. The first start can take up to a minute.

JARVIS keeps running in the **system tray** (bottom-right, near the clock) when you close the
window. Press **Ctrl + Shift + J** to show or hide it. To exit completely, right-click the tray
icon → **Quit JARVIS**.

## 2. First-run setup (2 minutes)

The setup wizard opens automatically:

1. **About you** — your name and city (for greetings and weather).
2. **Choose your AI** — JARVIS needs an AI model to think. Pick one:
   - **Google Gemini** (recommended, free tier): click **Get a key**, sign in with Google, create a
     key, paste it, press **Test**, then **Save key**.
   - **Groq** (fast, free tier) or **OpenAI** (paid) work the same way.
   - **Local AI (Ollama)**: fully private and offline. Install Ollama, run `ollama pull llama3.2`,
     then choose **Use local AI**. Needs a reasonably powerful PC.
3. **Privacy & permissions** — what stays on your PC and what is sent to the AI.
4. **Ready check** — shows what works on your PC. Only the AI model is required.

You can reopen the wizard any time with **Setup**, and change everything in **Settings**.

## 3. Things to try

| Say or type | What happens |
|---|---|
| "Remind me in 20 minutes to call Mom" | Sets a reminder (Windows notification when it's time) |
| "Add buy milk to my to-do list" / "Show my to-do list" | Manages your to-dos (also in the bar at the top) |
| "Give me my daily briefing" | Weather, your tasks and PC status |
| "Summarize https://…" | Reads and summarizes a web page |
| "Find PDF files in my Downloads" | Searches your files |
| "Preview organizing my Downloads folder" | Shows what would be moved, without changing anything |
| "Clean up my Downloads folder" | Asks your permission, then sorts files into folders (can be undone) |
| "My favourite colour is teal" … later "What's my favourite colour?" | JARVIS remembers |
| "Forget my favourite colour" | Removes it from memory |
| "What time is it?" | Instant answer, no AI needed |

The **1-Click Daily Routines** at the top run common requests for you.

**Everyday Mode** (default) shows routines, your to-dos and reminders and the chat. **Pro HUD
Mode** (top bar) adds a timeline of each step JARVIS takes and live system metrics.

## 4. Permissions — JARVIS asks first

When a request would change something (write or delete a file, run code, type into another app,
change a setting), a **permission card** shows exactly what will run:

- **Allow** — do it once. **Don't allow** — nothing happens.
- **Always allow this action** — only offered for low-risk actions. High-risk actions always ask.
- Remove saved permissions any time in **Settings → Saved permissions**.

JARVIS never reads password files, SSH keys or browser data, and after it reads something from
the web it asks again before taking actions (a web page can't trick it into acting on its own).

## 5. Activity

**Activity** (top bar) lists everything JARVIS did on your PC — every tool it ran, anything that
was blocked, and every permission you gave. Click an entry for details.

## 6. Voice (optional)

- Click the **microphone** to speak, or hold **F9** when JARVIS is listening.
- **Voice on/off** (top bar) makes JARVIS read replies aloud.
- By default JARVIS uses the offline Windows voice. You can choose the online Microsoft Edge
  voice in **Settings → Voice**.
- Speech recognition works offline when the voice add-on is installed. Using Google's free online
  recognition is off by default (it sends your audio to Google) and can be enabled in Settings.

## 7. Settings

- **AI providers** — add or replace keys (they are stored in Windows Credential Manager and never
  shown again), choose the main AI. If one provider is down, JARVIS automatically uses another.
- **Saved permissions**, **Voice**, **App lock PIN** (protects the browser version),
  **crash reports** (off by default) and **Export diagnostics**.

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| "JARVIS could not start" | Click **Try again**. If it keeps failing, use **Open logs folder** and send the logs. |
| Replies say every AI provider is unavailable | Check your internet, then **Settings → AI providers → Test**. Your key may be expired or over quota. |
| A reply is wrong or JARVIS did the wrong thing | Check **Activity** to see what it did; most actions can be undone (e.g. folder organization). |
| Need help | **Settings → Export diagnostics** creates a zip without your keys, memories or conversations. |

## 9. Uninstall

**Windows Settings → Apps → JARVIS → Uninstall.** Your data is kept in
`%LOCALAPPDATA%\JARVIS` in case you reinstall; delete that folder to remove it completely, and
remove the "JARVIS/…" entries in **Credential Manager → Windows Credentials**.
