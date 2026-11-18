import os
from dotenv import load_dotenv

load_dotenv()

def get_api_key():
    return os.environ.get("GEMINI_API_KEY")

def get_groq_api_key():
    return os.environ.get("GROQ_API_KEY")

def get_openai_api_key():
    return os.environ.get("OPENAI_API_KEY")

def get_ollama_host():
    return os.environ.get("OLLAMA_HOST")

def get_primary_engine():
    return os.environ.get("PRIMARY_ENGINE", "gemini").lower()

def get_groq_model():
    return os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

def get_model_name():
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


# --- API Server / Network Exposure ---
# JARVIS can run shell commands and read files, so the API must never be reachable
# from other machines or from arbitrary websites by default.
_DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:7799",
    "http://127.0.0.1:7799",
    "http://localhost:3000",   # Vite dev server (desktop/)
    "http://127.0.0.1:3000",
    "file://",                 # Electron production build loaded via loadFile()
]

_DEFAULT_ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "[::1]",
    "testserver",              # Starlette/FastAPI TestClient (not a resolvable public host)
]


def _csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def get_api_host() -> str:
    """Interface the API binds to. Defaults to loopback only."""
    return os.environ.get("JARVIS_API_HOST", "127.0.0.1")


API_PORT = 7799


def get_api_port() -> int:
    # Intentionally fixed: both UIs (desktop/src/App.jsx, ui/index.html) and the .bat launchers
    # hard-code 7799. JARVIS_API_PORT has never been honoured, and existing .env files may carry
    # stale values. Make this configurable once the UI reads its backend URL from Electron (Phase 3).
    return API_PORT


def get_allowed_origins() -> list[str]:
    """Browser origins allowed to call the API (CORS + Origin enforcement)."""
    return _DEFAULT_ALLOWED_ORIGINS + _csv_env("JARVIS_ALLOWED_ORIGINS")


def get_allowed_hosts() -> list[str]:
    """Host header values accepted by the API (blocks DNS-rebinding attacks)."""
    return _DEFAULT_ALLOWED_HOSTS + _csv_env("JARVIS_ALLOWED_HOSTS")



# --- Voice Settings ---
def get_voice_engine():
    return os.environ.get("VOICE_ENGINE", "edge-tts")  # Options: edge-tts, elevenlabs

def get_voice_profile():
    return os.environ.get("VOICE_PROFILE", "Jarvis Classic")

def get_wake_words():
    # Comma separated list
    ww = os.environ.get("WAKE_WORDS", "jarvis,travis")
    return [w.strip() for w in ww.split(",") if w.strip()]
