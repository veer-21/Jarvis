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

def set_daemon(daemon: ProactiveDaemon) -> None:
    """Set the shared ProactiveDaemon instance."""
    global _global_daemon
    _global_daemon = daemon
