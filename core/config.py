import os
from dotenv import load_dotenv

load_dotenv()

def _secret(name: str, *aliases: str):
    # Windows Credential Manager first, then environment / .env (see core/secrets_store.py).
    from core.secrets_store import resolve
    return resolve(name, *aliases)


def get_api_key():
    return _secret("GEMINI_API_KEY", "GOOGLE_API_KEY")

def get_groq_api_key():
    return _secret("GROQ_API_KEY")

def get_openai_api_key():
    return _secret("OPENAI_API_KEY")

def _setting(name: str, default):
    # settings.json (set from the app) > environment / .env > default. See core/settings.py.
    from core.settings import get_setting
    return get_setting(name, default)


def get_ollama_host():
    return _setting("ollama_host", None)

def get_primary_engine():
    return str(_setting("primary_engine", "gemini")).lower()

def get_groq_model():
    from core.brain.llm_providers import DEFAULT_GROQ_MODEL
    return _setting("groq_model", DEFAULT_GROQ_MODEL)

def get_model_name():
    from core.brain.llm_providers import DEFAULT_GEMINI_MODEL
    return _setting("gemini_model", DEFAULT_GEMINI_MODEL)


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
    return _setting("voice_engine", "edge-tts")  # Options: edge-tts, elevenlabs

def get_voice_profile():
    return _setting("voice_profile", "Jarvis Classic")

def get_wake_words():
    # Comma separated list
    ww = os.environ.get("WAKE_WORDS", "jarvis,travis")
    return [w.strip() for w in ww.split(",") if w.strip()]
