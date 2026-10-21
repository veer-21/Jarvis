"""
JARVIS Brain — Context & Follow-Up Tracker
Tracks referential context across dialogue turns:
- Candidate entity lists (e.g. search hits: "the second one", "that file")
- In-flight active task references
- Cancellation intent detection ("stop", "cancel that", "never mind", "abort")
"""

import re
from typing import Optional, Any
from dataclasses import dataclass, field

@dataclass
class FollowUpContext:
    last_user_query: str = ""
    last_assistant_response: str = ""
    last_candidates: list[Any] = field(default_factory=list)
    last_selected_item: Optional[Any] = None
    last_window_context: Optional[dict] = None
    active_task_id: Optional[str] = None
    topic: Optional[str] = None

class ContextTracker:
    """Manages active task state, screen/window context, and conversation-level referential continuity."""

    CANCELLATION_PATTERNS = [
        re.compile(r"^\s*stop(\s+it|\s+the\s+task|\s+the\s+current\s+task|\s+task|\s+what\s+you('re|\s+are)\s+doing|\s+everything)?\s*$", re.I),
        re.compile(r"^\s*cancel(\s+that|\s+the\s+task|\s+the\s+current\s+task|\s+task|\s+what\s+you('re|\s+are)\s+doing|\s+everything)?\s*$", re.I),
        re.compile(r"^\s*never\s*mind(,\s*stop|\s+stop)?\s*$", re.I),
        re.compile(r"^\s*don'?t\s+do\s+it\s*$", re.I),
        re.compile(r"^\s*abort(\s+the\s+task|\s+the\s+current\s+task|\s+the\s+current\s+operation|\s+the\s+operation|\s+task|\s+what\s+you('re|\s+are)\s+doing)?\s*$", re.I),
        re.compile(r"^\s*halt(\s+the\s+task|\s+the\s+current\s+task|\s+everything)?\s*$", re.I),
    ]

    DEICTIC_CONTEXT_PATTERNS = [
        re.compile(r"\b(what('s| is) on my screen|read my screen|summarize (what's on )?my screen|explain (this|my) screen|look at my screen)\b", re.I),
        re.compile(r"\b(summarize this window|explain this window|what is this window|what's in this window)\b", re.I),
        re.compile(r"\b(draft a reply to this|help me reply to this|reply to this|respond to this|answer this)\b", re.I),
        re.compile(r"\b(what does this error mean|explain this error|fix this error)\b", re.I),
        re.compile(r"\b(summarize this|explain this|what is this)\b", re.I),
    ]

    ORDINAL_MAP = {
        "first": 0, "1st": 0, "one": 0, "1": 0,
        "second": 1, "2nd": 1, "two": 1, "2": 1,
        "third": 2, "3rd": 2, "three": 2, "3": 2,
        "fourth": 3, "4th": 3, "four": 3, "4": 3,
        "fifth": 4, "5th": 4, "five": 4, "5": 4,
        "last": -1
    }

    def __init__(self):
        self.context = FollowUpContext()

    def update_exchange(self, user_query: str, assistant_response: str, candidates: Optional[list] = None) -> None:
        """Update last exchange and candidate list."""
        self.context.last_user_query = user_query
        self.context.last_assistant_response = assistant_response
        if candidates is not None:
            self.context.last_candidates = candidates

    def set_candidates(self, candidates: list) -> None:
        """Set candidate entities (e.g. files found in a search)."""
        self.context.last_candidates = candidates

    def set_active_task(self, task_id: Optional[str]) -> None:
        """Set currently executing task ID."""
        self.context.active_task_id = task_id

    def is_cancellation(self, user_input: str) -> bool:
        """Check if user input represents a cancellation directive."""
        clean = user_input.strip().rstrip(".!?")
        return any(p.search(clean) for p in self.CANCELLATION_PATTERNS)

    def resolve_reference(self, user_input: str) -> Optional[Any]:
        """
        Resolves referential phrases such as 'the second one', 'the first file', 'open that one'.
        Returns the referenced object from last_candidates, or None.
        """
        text = user_input.lower().strip()
        
        # Check for ordinal patterns like 'the second one', 'open the 2nd'
        match = re.search(r"\b(the\s+)?(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last)\s*(one|file|item|option)?\b", text)
        if match and self.context.last_candidates:
            ordinal = match.group(2)
            idx = self.ORDINAL_MAP.get(ordinal)
            if idx is not None:
                if idx == -1:
                    item = self.context.last_candidates[-1]
                elif 0 <= idx < len(self.context.last_candidates):
                    item = self.context.last_candidates[idx]
                else:
                    item = None
                
                if item:
                    self.context.last_selected_item = item
                    return item

        # Check for 'that one' or 'that file'
        if ("that one" in text or "that file" in text) and self.context.last_selected_item:
            return self.context.last_selected_item
        elif ("that one" in text or "that file" in text) and self.context.last_candidates:
            return self.context.last_candidates[0]

        return None

    def resolve_references(self, user_input: str) -> str:
        """Resolve references within user input text."""
        ref = self.resolve_reference(user_input)
        if ref:
            return re.sub(r"\b(that file|that one|the first file|the second file)\b", str(ref), user_input, flags=re.I)
        return user_input

    def is_active_context_request(self, user_input: str) -> bool:
        """Check if user input represents a deictic request about active screen, window, or error."""
        clean = user_input.strip().rstrip(".!?")
        return any(p.search(clean) for p in self.DEICTIC_CONTEXT_PATTERNS)

    def set_window_context(self, window_ctx: dict) -> None:
        """Cache the most recent active window context."""
        self.context.last_window_context = window_ctx

    def get_window_context(self) -> Optional[dict]:
        """Retrieve the cached active window context."""
        return self.context.last_window_context

