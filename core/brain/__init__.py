"""
JARVIS Brain Package
Modular AI reasoning architecture with specialized sub-engines.

Usage:
    from core.brain import Brain

    # Backward compatibility:
    from core.brain import JarvisBrain  # Alias for Brain
"""

from core.brain.brain import Brain

# Backward compatibility alias
JarvisBrain = Brain

__all__ = ["Brain", "JarvisBrain"]
