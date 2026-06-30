"""
JARVIS — Main Entry Point
Production CLI for the JARVIS AI Operating System.

Usage:
    python main.py                  # Interactive text mode (default)
    python main.py --voice          # Voice interaction mode
    python main.py --task "..."     # Execute a single autonomous task
    python main.py --api            # Start the FastAPI backend server
    python main.py --status         # Print system status and exit
"""

import os
import sys
import argparse
import signal
from datetime import datetime
from pathlib import Path

# ─── Environment ──────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

# ─── Core Modules ─────────────────────────────────────────────────────────────
from core.logger   import log
from core.config   import get_api_key, get_model_name
from core.brain    import JarvisBrain
from core.memory   import JarvisMemory
from core.voice    import VoiceInterface
from core.security import owner_auth, guard


# ─── Banner ───────────────────────────────────────────────────────────────────
BANNER = r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
  Just A Rather Very Intelligent System  v2.0
"""


# ─── Graceful Shutdown ────────────────────────────────────────────────────────
_SHUTDOWN = False

def _signal_handler(sig, frame):
    global _SHUTDOWN
    _SHUTDOWN = True
    print("\n\n[JARVIS] Emergency shutdown signal received. Closing systems gracefully...")

signal.signal(signal.SIGINT,  _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ─── System Bootstrap ─────────────────────────────────────────────────────────

def bootstrap() -> tuple[JarvisBrain, JarvisMemory, VoiceInterface]:
    """
    Initialize all JARVIS subsystems in order and return them.
    """
    print(BANNER)
    print("=" * 55)
    print(f"  Initializing Systems — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    # 1. Validate API key
    api_key = get_api_key()
    if not api_key:
        print("\n[ERROR] GEMINI_API_KEY is not set.")
        print("  Please edit your .env file and add:")
        print("  GEMINI_API_KEY=your_key_here\n")
        sys.exit(1)

    # 2. Memory
    print("[1/4] Memory System...", end=" ", flush=True)
    memory = JarvisMemory()
    print("ONLINE ✅")

    # 3. Brain
    print(f"[2/4] AI Brain ({get_model_name()})...", end=" ", flush=True)
    brain = JarvisBrain(api_key=api_key, memory=memory)
    print("ONLINE ✅")

    # 4. Voice
    print("[3/3] Voice Interface...", end=" ", flush=True)
    voice = VoiceInterface()
    print("ONLINE ✅")

    mem_stats = memory.stats()
    print("=" * 55)
    print(f"  All systems operational.")
    print(f"  Memory: {mem_stats['long_term_memories']} stored memories")
    print(f"  Type 'exit', 'quit', or press Ctrl+C to shutdown")
    print("=" * 55)
    log.info("JARVIS bootstrap complete.")
    return brain, memory, voice


# ─── Interaction Modes ────────────────────────────────────────────────────────

def init_project_brain() -> None:
    """Initialize a Project Brain compliant memory structure in the current directory."""
    import os
    from pathlib import Path
    
    brain_dir = Path(os.getcwd()) / "brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    
    files = {
        "master-memory.md": "# Project Brain — Master Memory\n\n- Key Architecture:\n- Decisions:\n- Patterns:\n- Known Issues:\n- Roadmap Snapshot:\n",
        "memory.md": "# Project Brain — Central Memory\n\n- Project Summary:\n- Key Features:\n- Current State:\n- Active Work:\n",
        "architecture.md": "# Project Brain — Architecture Reference\n\n- Frontend:\n- Backend:\n- Database:\n- Services:\n- Integrations:\n",
        "patterns.md": "# Project Brain — Patterns\n\n- Coding & design patterns used in the codebase:\n",
        "decisions.md": "# Project Brain — Decisions Log\n\n- Architectural decisions and rationales:\n",
        "mistakes.md": "# Project Brain — Mistakes Log\n\n- Pitfalls to avoid and previous bug fixes:\n",
        "roadmap.md": "# Project Brain — Roadmap\n\n- Future milestones and phases:\n",
        "glossary.md": "# Project Brain — Glossary\n\n- Terms and definitions:\n",
        "dependency-graph.md": "# Project Brain — Dependency Graph\n\n- Module and file relationship mappings:\n",
        "feature-map.md": "# Project Brain — Feature Map\n\n- Mapping features to files and code coordinates:\n"
    }
    
    created = []
    skipped = []
    
    for filename, content in files.items():
        filepath = brain_dir / filename
        if not filepath.exists():
            filepath.write_text(content, encoding="utf-8")
            created.append(filename)
        else:
            skipped.append(filename)
            
    agents_file = Path(os.getcwd()) / "AGENTS.md"
    if not agents_file.exists():
        agents_file.write_text("# Agent Architecture\n\n- Roles and responsibilities of specialized agents:\n", encoding="utf-8")
        created.append("AGENTS.md")
    else:
        skipped.append("AGENTS.md")
        
    print(f"\n[Project Brain] Scaffold complete in {brain_dir.parent.resolve()}")
    if created:
        print(f"  Created: {', '.join(created)}")
    if skipped:
        print(f"  Skipped (already exists): {', '.join(skipped)}")


def run_text_mode(brain: JarvisBrain, voice: VoiceInterface) -> None:
    """Interactive text-based CLI loop."""
    print("\n[MODE] Text Interaction — Type your command below.\n")

    while not _SHUTDOWN:
        try:
            user_input = input("YOU  ▶  ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        # Built-in commands
        cmd = user_input.lower()
        if cmd in ("exit", "quit", "shutdown", "goodbye"):
            voice.speak("Shutting down all systems. Goodbye, sir.")
            break
        elif cmd in ("status", "sys status"):
            _print_status(brain)
            continue
        elif cmd.startswith("task:"):
            task_desc = user_input[5:].strip()
            print(f"\n[JARVIS] Starting autonomous task execution: {task_desc}")
            result = brain.execute_task(task_desc)
            print(result)
            continue
        elif cmd in ("reset", "reset chat"):
            print(brain.reset_chat())
            continue
        elif cmd in ("memory stats", "memory"):
            if brain._memory:
                print(f"\nMemory Stats: {brain._memory.stats()}")
            else:
                print("Memory system not attached.")
            continue
        elif cmd == "brain init":
            init_project_brain()
            continue
        elif cmd == "brain update":
            print("\n[JARVIS] Running Project Brain auto-update cycle...")
            from core.agents.base_agent import AgentMessage
            msg = AgentMessage(sender="cli", recipient="memory", content="", metadata={"action": "update_project_brain"})
            res = brain._memory_agent.process(msg)
            print(f"\n[JARVIS] Update result: {res.content}")
            continue

        # Normal AI response
        response = brain.process_input(user_input)
        voice.speak(response)


def run_voice_mode(brain: JarvisBrain, voice: VoiceInterface) -> None:
    """Continuous voice interaction loop."""
    print("\n[MODE] Voice Interaction — Speak to JARVIS.\n")
    voice.speak("Voice systems online. I am listening, sir.")

    while not _SHUTDOWN:
        try:
            user_input = voice.listen(wait_for_wake_word=True)
        except KeyboardInterrupt:
            break

        if not user_input:
            continue

        user_input_lower = user_input.lower().strip()

        # Voice exit commands
        if any(kw in user_input_lower for kw in ("shut down", "shutdown", "goodbye", "exit")):
            voice.speak("Shutting down systems. Goodbye, sir.")
            break

        # Task mode trigger
        if user_input_lower.startswith("execute task"):
            task_desc = user_input[12:].strip()
            voice.speak(f"Understood. Executing task: {task_desc}")
            result = brain.execute_task(task_desc)
            # Speak a short summary
            voice.speak("Task execution complete. See console for full report.")
            print(result)
            continue

        print(f"\nYOU (Voice): {user_input}")
        response = brain.process_input(user_input)
        voice.speak(response)


def run_single_task(brain: JarvisBrain, task: str) -> None:
    """Execute one autonomous task and exit."""
    print(f"\n[JARVIS] Autonomous Task Mode: {task}\n")
    result = brain.execute_task(task)
    print(result)


def run_api_server() -> None:
    """Start the FastAPI backend server."""
    try:
        import uvicorn
        import threading
        import webbrowser
        
        print("\n[JARVIS] Starting API Server on http://localhost:7799\n")
        
        # Auto-open the UI in the default browser after a short delay to let server start
        def open_browser():
            print("\n[JARVIS] Launching Dashboard UI in your default browser...")
            webbrowser.open("http://localhost:7799/")
            
        threading.Timer(1.5, open_browser).start()
        
        uvicorn.run(
            "api.server:app",
            host="0.0.0.0",
            port=7799,
            reload=False,
            log_level="info",
        )
    except ImportError:
        print("[ERROR] uvicorn is not installed. Run: pip install uvicorn")
        sys.exit(1)


def _print_status(brain: JarvisBrain) -> None:
    """Print system status summary."""
    status = brain.status()
    print("\n── JARVIS System Status ──────────────────────")
    for k, v in status.items():
        print(f"  {k:<20}: {v}")
    print("─────────────────────────────────────────────\n")


# ─── CLI Entry Point ─────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="JARVIS — Personal AI Operating System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--voice",  action="store_true", help="Run in voice interaction mode")
    parser.add_argument("--text",   action="store_true", help="Run in text interaction mode (default)")
    parser.add_argument("--task",   type=str,            help="Execute a single autonomous task")
    parser.add_argument("--api",    action="store_true", help="Start the FastAPI backend server")
    parser.add_argument("--status", action="store_true", help="Print system status and exit")
    parser.add_argument("--offline", action="store_true", help="Run in local offline mode (requires Ollama)")
    parser.add_argument("--brain-init", action="store_true", help="Initialize the Project Brain documentation templates")
    parser.add_argument("--brain-update", action="store_true", help="Analyze memory logs and update Project Brain files")
    args = parser.parse_args()

    if args.offline:
        os.environ["JARVIS_OFFLINE"] = "1"

    # Project Brain Init (does not require full system bootstrap)
    if args.brain_init:
        init_project_brain()
        return

    # API server doesn't need full bootstrap
    if args.api:
        if args.voice:
            os.environ["JARVIS_VOICE_MODE"] = "1"
        run_api_server()
        return

    # Bootstrap all systems
    try:
        brain, memory, voice = bootstrap()
    except Exception as e:
        print(f"\n[FATAL] JARVIS failed to start: {e}")
        log.critical(f"Bootstrap failed: {e}")
        sys.exit(1)

    # Project Brain Update
    if args.brain_update:
        print("\n[JARVIS] Running Project Brain auto-update cycle...")
        from core.agents.base_agent import AgentMessage
        msg = AgentMessage(sender="cli", recipient="memory", content="", metadata={"action": "update_project_brain"})
        res = brain._memory_agent.process(msg)
        print(f"\n[JARVIS] Update result: {res.content}")
        return

    # Status-only mode
    if args.status:
        _print_status(brain)
        return

    # Single task mode
    if args.task:
        run_single_task(brain, args.task)
        return

    # Interactive modes
    if args.voice:
        run_voice_mode(brain, voice)
    else:
        # Default: text mode
        run_text_mode(brain, voice)

    print("\n[JARVIS] Systems offline. Goodbye.")
    log.info("JARVIS shutdown complete.")


if __name__ == "__main__":
    main()
