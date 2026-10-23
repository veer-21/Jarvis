# 🤖 JARVIS AI Assistant — Everyday Consumer User Guide

Welcome to **JARVIS v4.0–v8.0 Consumer Edition**! This guide explains how to launch, configure, and use JARVIS as your daily personal AI operating system on Windows.

---

## 🚀 1. 1-Click Launch Options

JARVIS can be launched in three friendly ways on your PC:

1. **Desktop Shortcut (`JARVIS AI Assistant.lnk`)**:
   - Double-click the **JARVIS AI Assistant** icon on your Windows Desktop.
   - Starts the background services and opens your interactive assistant in your default browser.
2. **Web Assistant (`Start_Jarvis.bat`)**:
   - Double-click `Start_Jarvis.bat` in `D:\Jarvis`.
   - Automatically checks system ports, starts the FastAPI neural backend, validates health status, and opens `http://127.0.0.1:7799`.
3. **Floating Desktop HUD App (`Start_Jarvis_Desktop.bat`)**:
   - Double-click `Start_Jarvis_Desktop.bat` to launch the standalone Electron floating HUD window.
   - Supports transparent dark glassmorphism, window pinning, and global hotkey invocation.

---

## 🪄 2. First-Run Setup Wizard

When launching JARVIS for the first time (or clicking the **Setup Wizard** button in the top navigation bar), a 3-step wizard guides your initial setup:

1. **Your Name & City**:
   - Set what JARVIS should address you as (e.g. *Tony*, *Alex*, or *Sir*).
   - Enter your home city (e.g. *San Francisco*, *London*, or *New York*) for accurate morning weather and local briefings.
2. **AI Intelligence Engine**:
   - Enter your Google Gemini API key for cloud intelligence, or enable **Offline Mode** to run locally.
3. **Voice & Audio Profile**:
   - Choose your preferred voice engine and listening settings.

All settings are securely persisted in `data/user_preferences.json` and loaded automatically on every startup.

---

## 🖥️ 3. Everyday Mode vs. Pro HUD Mode

JARVIS features two visual modes tailored to your working style:

### Everyday Mode (Default)
Designed for seamless daily productivity:
- **8 1-Click Daily Routine Cards**: Instant shortcuts for frequent everyday requests.
- **Interactive My To-Dos & Active Reminders Bar**: Manage your tasks and active timers with 1-click chip buttons.
- **Smart Notification Toasts**: Native Windows notification toasts when your timers and reminders expire.

### Pro HUD Mode
Designed for advanced workflows, developers, and power users:
- Real-time 5-agent execution status (**Commander**, **Security**, **Memory**, **Operator**, **Refiner**).
- Audio visualizer with voice state transitions (`LISTENING`, `THINKING`, `SPEAKING`).
- Live system resource telemetry (CPU, RAM, Disk, System Uptime).

Use the **Everyday Mode / Pro HUD Mode** toggle switch in the top header to switch modes anytime.

---

## ⚡ 4. The 8 1-Click Daily Routine Cards

In Everyday Mode, the top bar provides instant 1-click execution cards:

| Card | Action | Description |
| :--- | :--- | :--- |
| 🌅 **Morning Briefing** | `Give me my daily briefing` | Combines current date, weather, system health, and today's reminders into a concise briefing. |
| 📁 **Organize Downloads** | `Preview organizing my Downloads folder` | Safely classifies files into categorized folders (`Documents`, `Images`, `Media`, etc.) with 1-click undo. |
| ✉️ **Draft an Email** | `Help me draft a professional email` | Synthesizes a clean email draft, copies it to your clipboard, and opens Gmail or your default mail client. |
| 🖥️ **Read My Screen** | `Read and summarize the text on my screen` | Extracts text from your foreground window and explains or summarizes what is on screen. |
| 📝 **Show My To-Dos** | `Show my personal to-do list and pending tasks` | Displays active tasks, notes, and pending checklist items. |
| 📋 **Clipboard Helper** | `Check clipboard history and format text` | Reads and formats your current clipboard and recent clip history. |
| ⏰ **Quick Reminder** | `Remind me in 15 minutes to take a break` | Schedules a local countdown timer with native Windows toast alerts. |
| ⚡ **Health Check** | `Check my computer speed, CPU, and memory` | Checks CPU load, RAM usage, and available storage. |

---

## ⌨️ 5. Global Hotkey (`Alt + Space`) & Screen Context

When using the desktop application, press **`Alt + Space`** from within any application (browser, code editor, PDF viewer, or spreadsheet) to summon JARVIS over your active screen.

Ask questions directly about what you are currently looking at:
- *"What does this error message mean?"*
- *"Summarize this document on my screen."*
- *"Help me reply to the message in this window."*

JARVIS inspects foreground window metadata and text without requiring manual screenshots or file uploads.

---

## 🗣️ 6. 25 Everyday Voice & Text Commands

Here are 25 practical commands you can speak or type to JARVIS right now:

### Folder Decluttering & Recovery
1. `"Preview organizing my Downloads folder"` — Performs a safe dry-run showing what would be sorted.
2. `"Clean up my Desktop folder"` — Moves loose files into categorized folders.
3. `"Undo folder organization in Downloads"` — Restores every moved file back to its exact original location.

### Reminders & Countdown Timers
4. `"Remind me in 10 minutes to submit the invoice"` — Sets a 10-minute timer.
5. `"Set a timer for 45 minutes to finish the presentation"` — Schedules a focus timer.
6. `"Show my active reminders"` — Lists all pending countdown timers.
7. `"Cancel reminder rem_abc123"` — Cancels a scheduled reminder.

### Personal To-Dos & Quick Notes
8. `"Add to-do: Review client contract by Friday"` — Adds a persistent task.
9. `"Show my to-do list"` — Displays pending tasks and checkboxes.
10. `"Mark task Review client contract as completed"` — Marks a to-do as finished.
11. `"Delete task Review client contract"` — Removes a task from storage.

### Document & Web Summarization
12. `"Summarize document sample.pdf"` — Extracts text from local PDF, Word (.docx), or text files.
13. `"Read and summarize https://news.ycombinator.com"` — Cleans web articles, removes ads, and provides a summary.
14. `"What are the key takeaways from contract.docx?"` — Answers questions focused on local files.
15. `"Explain this report on my Desktop"` — Locates and summarizes documents on your Desktop.

### Smart Email & Message Drafting
16. `"Draft an email to boss@company.com about quarterly review"` — Creates a polite email draft and copies it to clipboard.
17. `"Write an email about scheduling a demo meeting"` — Formats a ready-to-send message with your configured signature.
18. `"Compose an email to team@startup.io regarding sprint launch and open in Gmail"` — Opens Gmail with all fields pre-filled.

### Windows OS Controls & Clipboard
19. `"Turn the volume up"` — Increases master audio volume.
20. `"Mute volume"` — Toggles master volume mute.
21. `"Open task manager"` — Launches Windows Task Manager.
22. `"Open Windows settings"` — Opens Windows Settings app.
23. `"What is on my clipboard?"` — Reads current clipboard contents.
24. `"Copy to clipboard: Meeting notes for tomorrow"` — Writes formatted text to system clipboard.

### Daily Briefing & Health
25. `"Give me my morning briefing"` — Full briefing with date, weather, system stats, and upcoming tasks.

---

## 🛡️ 7. Privacy, Safety & Data Storage

- **Zero Cloud Leakage of Local Data**: Your files, to-dos, reminders, and clipboard history stay on your local disk in `D:\Jarvis\data\`.
- **Security Guard (`LOW_RISK` to `CRITICAL`)**: Actions that modify system state or files are vetted before execution. Destructive actions (like emptying the recycle bin) require explicit confirmation.
- **Persistent Recovery**: All pending timers and reminders are automatically recovered across system restarts.
