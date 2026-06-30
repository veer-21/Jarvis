"""JARVIS Dependency Installer — run from any location"""
import subprocess, sys, os

PACKAGES = [
    "google-genai",
    "fastapi",
    "uvicorn[standard]",
    "pydantic",
    "python-multipart",
    "PyJWT",
    "bcrypt",
    "cryptography",
    "python-dotenv",
    "requests",
    "beautifulsoup4",
    "duckduckgo-search",
    "psutil",
    "pyautogui",
    "Pillow",
    "pyttsx3",
    "SpeechRecognition",
    "playwright",
]

VENV_PYTHON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "Scripts", "python.exe")
python_exe  = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable

print(f"Using Python: {python_exe}")
print(f"Installing {len(PACKAGES)} packages...\n")

result = subprocess.run(
    [python_exe, "-m", "pip", "install", "--upgrade"] + PACKAGES,
    capture_output=False,
)
sys.exit(result.returncode)
