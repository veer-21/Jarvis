"""
JARVIS Brain — Memory Policy
Enforces strict separation between:
1. Conversation Context (transient rolling dialogue window)
2. Task State (active execution graph & context)
3. Long-Term Memory (curated knowledge, facts, project memory)
4. User Preferences (explicit rules, preferences, defaults)

Prevents memory pollution by filtering out transient searches, arithmetic,
and casual chatter from permanent vector/JSON storage.
"""

import re
from typing import Optional, Tuple
from enum import Enum

class MemoryTier(str, Enum):
    TRANSIENT_CONVERSATION = "TRANSIENT_CONVERSATION"
    TASK_STATE             = "TASK_STATE"
    USER_PREFERENCE        = "USER_PREFERENCE"
    LONG_TERM_KNOWLEDGE    = "LONG_TERM_KNOWLEDGE"
    DO_NOT_STORE           = "DO_NOT_STORE"

class MemoryPolicy:
    """Classifies user interaction and dictates persistence tier."""

    # Explicit triggers that signify persistent facts or preferences
    PREFERENCE_PATTERNS = [
        re.compile(r"\bremember that\b", re.I),
        re.compile(r"\bmy favorite\b", re.I),
        re.compile(r"\bi prefer\b", re.I),
        re.compile(r"\bi like\b", re.I),
        re.compile(r"\balways use\b", re.I),
        re.compile(r"\bnever use\b", re.I),
        re.compile(r"\bfrom now on\b", re.I),
        re.compile(r"\bmy default\b", re.I),
    ]

    # Transient interactions that must NEVER be persisted to long-term memory
    TRANSIENT_PATTERNS = [
        re.compile(r"\bwhat('?s| is) the time\b", re.I),
        re.compile(r"\bwhat('?s| is) today('?s)? date\b", re.I),
        re.compile(r"\bcalculate\b", re.I),
        re.compile(r"\b\d+\s*[\+\-\*\/]\s*\d+\b"),
        re.compile(r"\bshow (my )?(cpu|ram|memory|system)\b", re.I),
        re.compile(r"\blist (the )?files\b", re.I),
        re.compile(r"\bsearch the web for\b", re.I),
        re.compile(r"\bopen (notepad|chrome|youtube|browser|calculator)\b", re.I),
        re.compile(r"\b(hi|hello|hey|yo|good morning|bye|thanks|thank you)\b", re.I),
    ]

    @classmethod
    def classify_interaction(cls, user_text: str) -> Tuple[MemoryTier, Optional[str]]:
        """
        Classifies interaction into its proper persistence tier.
        Returns:
            (MemoryTier, category_label)
        """
        text = user_text.strip()
        
        # 1. Check for explicit memory deletion requests
        if re.search(r"\b(delete|forget|remove)\b.*\b(memory|preference)\b", text, re.I):
            return MemoryTier.DO_NOT_STORE, "delete_request"

        # 2. Check for explicit user preferences or permanent facts
        for pattern in cls.PREFERENCE_PATTERNS:
            if pattern.search(text):
                if any(w in text.lower() for w in ("prefer", "preference", "like", "favorite", "default")):
                    return MemoryTier.USER_PREFERENCE, "preference"
                return MemoryTier.LONG_TERM_KNOWLEDGE, "knowledge"

        # 3. Check for transient queries
        for pattern in cls.TRANSIENT_PATTERNS:
            if pattern.search(text):
                return MemoryTier.TRANSIENT_CONVERSATION, None

        # 4. Long / detailed instructions might be tasks or conversational
        if len(text.split()) > 15:
            return MemoryTier.TASK_STATE, "task"

        # Default is transient conversation
        return MemoryTier.TRANSIENT_CONVERSATION, None
