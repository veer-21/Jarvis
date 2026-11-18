"""
JARVIS Daemon Instance Provider
Ensures a shared singleton instance of ProactiveDaemon is accessible to tools and main entry points.
"""

from typing import Optional
from core.daemon import ProactiveDaemon

_global_daemon: Optional[ProactiveDaemon] = None

def get_daemon() -> ProactiveDaemon:
    """Return the shared ProactiveDaemon instance, creating one if not yet initialized."""
    global _global_daemon
    if _global_daemon is None:
        _global_daemon = ProactiveDaemon()
        _global_daemon.start()
    return _global_daemon

_shared_brain = None


def set_shared_brain(brain) -> None:
    """Register the running Brain so background jobs reuse it instead of creating new ones."""
    global _shared_brain
    _shared_brain = brain


def get_shared_brain():
    return _shared_brain


def set_daemon(daemon: ProactiveDaemon) -> None:
    """Set the shared ProactiveDaemon instance."""
    global _global_daemon
    _global_daemon = daemon
