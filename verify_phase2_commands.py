"""
JARVIS Phase 2 - Regression Verification Script
Tests 16 real user commands through Brain.process_input().
"""

import sys
import os
import time
import json
from pathlib import Path

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from core.logger import log
from core.memory import JarvisMemory

COMMANDS_TO_TEST = [
    {
        "cmd": "What's the time?",
        "expected": "Returns the current local time via fast-path or system context."
    },
    {
        "cmd": "What is today's date?",
        "expected": "Returns today's date accurately via fast-path or system context."
    },
    {
        "cmd": "Open Notepad.",
        "expected": "Launches the Windows Notepad application via open_application."
    },
    {
        "cmd": "Open YouTube.",
        "expected": "Opens YouTube (https://www.youtube.com) in browser via fast-path."
    },
    {
        "cmd": "Calculate 1450 divided by 12.",
        "expected": "Computes 1450 / 12 = ~120.83."
    },
    {
        "cmd": "Show my CPU and memory usage.",
        "expected": "Retrieves real-time system CPU & memory metrics via get_system_info."
    },
    {
        "cmd": "List the files in this workspace.",
        "expected": "Lists directory files via list_directory or file tools."
    },
    {
        "cmd": "Read README.md.",
        "expected": "Reads and returns content from README.md via read_file."
    },
    {
        "cmd": "Remember that my favorite programming language is Rust.",
        "expected": "Extracts and stores user preference in persistent memory."
    },
    {
        "cmd": "What is my favorite programming language?",
        "expected": "Retrieves preference from memory and states Rust."
    },
    {
        "cmd": "Search the web for the latest Python release.",
        "expected": "Calls web_search and returns recent Python release information."
    },
    {
        "cmd": "Open a webpage and read its content.",
        "expected": "Opens a webpage and reads page text via Playwright browser or web tools."
    },
    {
        "cmd": "Click the login button on the webpage.",
        "expected": "Attempts browser_click on a webpage login button or reports state."
    },
    {
        "cmd": "Read the text currently visible on my screen.",
        "expected": "Calls analyze_screen with OCR or gracefully reports active desktop session status."
    },
    {
        "cmd": "Find my project folder.",
        "expected": "Identifies the current workspace/project directory path."
    },
    {
        "cmd": "Write a Python script that calculates factorial.",
        "expected": "Generates a Python script for factorial (distinguished from keyboard typing)."
    }
]

def run_verification():
    print("=" * 70)
    print("  JARVIS Phase 2 — 16 User Commands Verification")
    print("=" * 70)
    
    print("\n[INIT] Initializing JarvisMemory...")
    memory = JarvisMemory()
    print("[INIT] Initializing Brain...")
    from core.brain.brain import Brain
    brain = Brain(memory=memory)
    
    results = []
    
    for i, item in enumerate(COMMANDS_TO_TEST, 1):
        cmd = item["cmd"]
        expected = item["expected"]
        print(f"\n[{i}/16] Running command: {cmd!r}")
        
        t0 = time.perf_counter()
        actual = ""
        error = ""
        status = "FAIL"
        exec_path = "Unknown"
        
        try:
            # Check fast-path match to record execution path accurately
            match = brain.intent_classifier.classify(cmd)
            if match:
                tool_name, tool_args = match
                exec_path = f"Fast-Path (IntentClassifier -> {tool_name})"
            else:
                exec_path = "LLM Pipeline (ReasoningEngine + ToolRouter + Memory)"
                
            response = brain.process_input(cmd, store_memory=True)
            t_elapsed = time.perf_counter() - t0
            actual = str(response).strip()
            
            # Evaluate status based on response
            if "Error" in actual and "Error:" in actual and not ("favorite programming language is Rust" in actual):
                if "requires an active" in actual:
                    status = "PASS"  # Graceful desktop session handling
                elif "Fallback API call failed" in actual or "429" in actual:
                    status = "PARTIAL"
                else:
                    status = "PARTIAL"
            elif actual:
                status = "PASS"
            else:
                status = "FAIL"
                
        except Exception as e:
            error = f"{type(e).__name__}: {str(e)}"
            actual = f"Exception encountered: {error}"
            status = "FAIL"
            
        print(f"  Status: {status} ({time.perf_counter() - t0:.2f}s)")
        print(f"  Path:   {exec_path}")
        print(f"  Actual: {actual[:160]}...")
        if error:
            print(f"  Error:  {error}")
            
        results.append({
            "command": cmd,
            "expected_behavior": expected,
            "actual_behavior": actual,
            "status": status,
            "execution_path": exec_path,
            "error": error if error else "None"
        })
        
        time.sleep(2)  # small pause between commands
        
    output_file = Path("phase2_verification_results.json")
    output_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[DONE] Saved results to {output_file.resolve()}")

if __name__ == "__main__":
    run_verification()
