import time
import subprocess
from tools.automation_tools import type_text

print("[JARVIS] Launching Notepad directly from your interactive terminal...")
subprocess.Popen(["notepad.exe"])
time.sleep(1.5)

print("[JARVIS] Typing live on your screen...")
msg = "Hello Veer!\n\nThis is JARVIS typing live on your screen!\nYour autonomous AI assistant is fully working."
type_text(msg)
print("[JARVIS] Done! Look at your Notepad window.")
