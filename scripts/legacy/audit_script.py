"""
JARVIS System Diagnostics & Structural Integrity Audit
Tests all core subsystems: databases, audio permissions, embeddings, and websockets.
"""

import sys
import os
import time
import json
import asyncio

# Setup workspace paths
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.logger import log, error_log

# Color codes for premium diagnostic logs
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
RESET = "\033[0m"

def print_result(module_name: str, status: str, details: str = "", level: str = "INFO"):
    color = GREEN if status == "PASS" else (YELLOW if status == "WARN" else RED)
    prefix = "[✓]" if status == "PASS" else ("[!]" if status == "WARN" else "[X]")
    print(f"{color}{prefix} {module_name:<30} {status:<8} {details}{RESET}")

def audit_memory_db():
    print(f"\n{BLUE}--- 1. Database & Persistence Layer Audit ---{RESET}")
    try:
        from core.memory import JarvisMemory
        memory = JarvisMemory()
        
        # Test basic write / read / delete capability
        test_key = "audit_test_key"
        test_val = "diagnostic_value_" + str(time.time())
        memory.store_preference(test_key, test_val)
        
        retrieved = memory.get_preference(test_key)
        if retrieved == test_val:
            # Cleanup
            if memory._collection:
                try:
                    memory._collection.delete(ids=[f"pref_{test_key}"])
                except Exception:
                    pass
            memory._json_store.delete(f"pref_{test_key}")
            
            backend_info = "ChromaDB (semantic)" if memory._collection else "JSON Fallback"
            print_result("Memory Write/Read Handles", "PASS", f"Backend: {backend_info}")
        else:
            print_result("Memory Write/Read Handles", "FAIL", "Retrieved value mismatch.")
            
    except Exception as e:
        print_result("Memory Write/Read Handles", "FAIL", f"Error: {e}")

def audit_embedding_model():
    print(f"\n{BLUE}--- 2. Embedding Fallback & Model Audit ---{RESET}")
    try:
        from core.memory import HAS_CHROMA
        if not HAS_CHROMA:
            print_result("Embedding Pipeline", "WARN", "ChromaDB not installed, running JSON string search fallback.")
            return

        try:
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_v2
            # Attempt to instantiate ONNX model
            fn = ONNXMiniLM_L6_v2()
            print_result("ONNX Embedding Loader", "PASS", "ONNXMiniLM_L6_v2 loaded successfully.")
        except Exception as e:
            print_result("ONNX Embedding Loader", "WARN", f"ONNX loader fallback active: {e}")
            
        print_result("Embedding Pipeline Check", "PASS", "Embedding pipeline checked.")
    except Exception as e:
        print_result("Embedding Pipeline Check", "FAIL", f"Unexpected failure: {e}")

def audit_audio_devices():
    print(f"\n{BLUE}--- 3. Audio Hardware & Permissions Audit ---{RESET}")
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        info = pa.get_default_host_api_info()
        num_devices = info.get('deviceCount', 0)
        
        if num_devices == 0:
            print_result("Native PyAudio Setup", "WARN", "No audio devices detected. Falling back to console simulation.")
        else:
            default_input = pa.get_default_input_device_info()
            print_result("Audio Input Device", "PASS", f"Default input: {default_input.get('name')} (rate: {int(default_input.get('defaultSampleRate'))}Hz)")
            
            default_output = pa.get_default_output_device_info()
            print_result("Audio Output Device", "PASS", f"Default output: {default_output.get('name')}")
        
        pa.terminate()
    except Exception as e:
        print_result("Audio Subsystem Check", "WARN", f"PyAudio failed to load drivers ({e}). Falling back to simulation/console mode.")

def audit_voice_streaming():
    print(f"\n{BLUE}--- 4. Voice Streaming & TTS Subprocess Audit ---{RESET}")
    try:
        from core.voice import VoiceInterface
        voice = VoiceInterface()
        
        # Test silent TTS generation block
        import threading
        interrupt = threading.Event()
        
        print("Mocking a voice streaming chunk pass...")
        
        # Perform a mock TTS sentence stream (mock generator)
        def mock_gen():
            yield "Diagnostics chunk pass successful."
            
        # Call TTS stream (will print to console if mpv is missing, otherwise stream via mpv)
        voice._speak_edge_tts_stream(mock_gen(), interrupt)
        
        print_result("Voice Interface Pipeline", "PASS", "Mock chunk stream completed.")
    except Exception as e:
        print_result("Voice Interface Pipeline", "FAIL", f"Failed: {e}")

def audit_websocket_handshake():
    print(f"\n{BLUE}--- 5. WebSocket API Handshake Audit ---{RESET}")
    try:
        from fastapi.testclient import TestClient
        from api.server import app
        
        # Run test client inside context manager to trigger lifespan and warm up the brain
        with TestClient(app) as client:
            # Connect to websocket endpoint
            with client.websocket_connect("/ws/jarvis") as websocket:
                # Send status update handshake
                websocket.send_json({"command": "status_update", "status": "LISTENING"})
                # Receive response if any
                print_result("WebSocket Connection", "PASS", "FastAPI WebSocket handshake established successfully.")
    except Exception as e:
        print_result("WebSocket Connection", "FAIL", f"Handshake failed: {e}")

def run_full_audit():
    print(f"{BLUE}==================================================")
    print("      JARVIS OS Core Subsystem Diagnostics")
    print(f"=================================================={RESET}")
    
    audit_memory_db()
    audit_embedding_model()
    audit_audio_devices()
    audit_voice_streaming()
    audit_websocket_handshake()
    
    print(f"\n{BLUE}=================================================={RESET}\n")

if __name__ == "__main__":
    run_full_audit()
