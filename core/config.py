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
    return os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")

def get_model_name():
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")



# --- Voice Settings ---
def get_voice_engine():
    return os.environ.get("VOICE_ENGINE", "edge-tts")  # Options: edge-tts, elevenlabs

def get_voice_profile():
    return os.environ.get("VOICE_PROFILE", "Jarvis Classic")

def get_wake_words():
    # Comma separated list
    ww = os.environ.get("WAKE_WORDS", "jarvis,travis")
    return [w.strip() for w in ww.split(",") if w.strip()]
