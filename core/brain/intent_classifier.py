"""
JARVIS Brain — Intent Classifier
Lightweight local intent classifier that intercepts simple commands
and executes them locally for zero-latency response.

Supports fuzzy matching to handle STT transcription artifacts like
"open the Chrome", "can you open notepad please", etc.
"""

import re
import time
from typing import Optional, Dict, Any, Tuple
from core.logger import log


class IntentClassifier:
    """
    Lightweight local intent classifier.
    Intercepts simple commands to bypass the LLM and execute locally for zero latency.
    """

    # ─── URL Shortcuts ────────────────────────────────────────────────────────
    _URL_SHORTCUTS: Dict[str, str] = {
        "youtube":      "https://www.youtube.com",
        "google":       "https://www.google.com",
        "gmail":        "https://mail.google.com",
        "github":       "https://github.com",
        "whatsapp":     "https://web.whatsapp.com",
        "twitter":      "https://twitter.com",
        "x":            "https://x.com",
        "reddit":       "https://www.reddit.com",
        "instagram":    "https://www.instagram.com",
        "facebook":     "https://www.facebook.com",
        "linkedin":     "https://www.linkedin.com",
        "amazon":       "https://www.amazon.com",
        "netflix":      "https://www.netflix.com",
        "chatgpt":      "https://chat.openai.com",
        "stackoverflow": "https://stackoverflow.com",
        "stack overflow": "https://stackoverflow.com",
    }

    # ─── Filler words that STT often adds ─────────────────────────────────────
    _FILLER_WORDS = [
        "please", "can you", "could you", "would you", "will you",
        "hey", "yo", "just", "go ahead and", "go and",
        "the", "a", "an", "my", "for me", "now",
        "jarvis", "hey jarvis",
    ]

    def __init__(self):
        # Direct regex patterns — checked AFTER filler stripping
        self.patterns = [
            # App launching
            (re.compile(r"^(?:open|launch|start|run)\s+(.+)$", re.IGNORECASE),
             self._route_open),

            # App closing
            (re.compile(r"^(?:close|kill|stop|quit|exit)\s+(.+)$", re.IGNORECASE),
             "execute_command", self._extract_close_app),

            # Web search
            (re.compile(r"^(?:search|google|search (?:google |the web )?for)\s+(.+)$", re.IGNORECASE),
             "open_url", self._extract_search),

            # Type text
            (re.compile(r"^(?:type|write)\s+(.+)$", re.IGNORECASE),
             "type_text", self._extract_type_text),

            # Key presses
            (re.compile(r"^(?:press|hit)\s+(.+)$", re.IGNORECASE),
             "press_key", self._extract_key_press),

            # Volume
            (re.compile(r"^(?:volume up|turn up (?:the )?volume|increase volume)$", re.IGNORECASE),
             "press_key", lambda m: {"keys": "volumeup"}),
            (re.compile(r"^(?:volume down|turn down (?:the )?volume|decrease volume)$", re.IGNORECASE),
             "press_key", lambda m: {"keys": "volumedown"}),
            (re.compile(r"^(?:mute|mute (?:the )?volume|unmute)$", re.IGNORECASE),
             "press_key", lambda m: {"keys": "volumemute"}),

            # System commands
            (re.compile(r"^(?:shutdown|shut down) (?:the )?(?:pc|computer|system)$", re.IGNORECASE),
             "execute_command", lambda m: {"command": "shutdown /s /t 0"}),
            (re.compile(r"^(?:restart|reboot) (?:the )?(?:pc|computer|system)$", re.IGNORECASE),
             "execute_command", lambda m: {"command": "shutdown /r /t 0"}),
            (re.compile(r"^(?:lock|lock (?:the )?(?:pc|computer|screen))$", re.IGNORECASE),
             "execute_command", lambda m: {"command": "rundll32.exe user32.dll,LockWorkStation"}),

            # Screenshot
            (re.compile(r"^(?:take )?(?:a )?screenshot[.!?]?$", re.IGNORECASE),
             "take_screenshot", lambda m: {}),

            # System info
            (re.compile(r"^(?:system status|system info|what is (?:the )?(?:current )?system status)[\??]?$", re.IGNORECASE),
             "get_system_info", lambda m: {}),

            # List files
            (re.compile(r"^(?:list files|show (?:me )?(?:the )?files|what files are (?:in )?(?:the )?(?:current )?directory)[\??]?$", re.IGNORECASE),
             "list_directory", lambda m: {"path": "."}),

            # Time
            (re.compile(r"^(?:what(?:'s| is) the time|what time is it|current time|time)[\??]?$", re.IGNORECASE),
             "_local_time", lambda m: {}),

            # Date
            (re.compile(r"^(?:what(?:'s| is) (?:the )?(?:today'?s? )?date|what date is it|today'?s? date|date)[\??]?$", re.IGNORECASE),
             "_local_date", lambda m: {}),

            # Weather
            (re.compile(r"^(?:what(?:'s| is) the weather|weather|how is the weather|what is the weather like)(?: right now| today| outside)?[\??]?$", re.IGNORECASE),
             "get_weather", lambda m: {"location": ""}),
        ]

    def classify(self, text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Classify text and return the target tool and arguments, if it matches a local intent.

        Args:
            text: The user input text.

        Returns:
            Tuple of (tool_name, arguments) or None if no local intent is matched.
        """
        t0 = time.perf_counter()
        original = text.strip()

        # Strip filler words for more reliable matching
        cleaned = self._strip_fillers(original)

        for entry in self.patterns:
            if len(entry) == 2:
                # Special router function (e.g., _route_open)
                pattern, router_fn = entry
                match = pattern.match(cleaned)
                if match:
                    result = router_fn(match)
                    if result:
                        tool_name, args = result
                        elapsed_ms = (time.perf_counter() - t0) * 1000
                        log.info(
                            f"[LOCAL] \"{original}\" → {tool_name}({args}) ({elapsed_ms:.1f}ms)"
                        )
                        return tool_name, args
            else:
                pattern, tool_name, extractor = entry
                match = pattern.match(cleaned)
                if match:
                    args = extractor(match)
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    log.info(
                        f"[LOCAL] \"{original}\" → {tool_name}({args}) ({elapsed_ms:.1f}ms)"
                    )
                    return tool_name, args

        return None

    # ─── Filler Stripping ─────────────────────────────────────────────────────

    def _strip_fillers(self, text: str) -> str:
        """Remove common filler words that STT engines add."""
        result = text.lower().strip()

        # Remove trailing punctuation
        result = re.sub(r'[.!?]+$', '', result).strip()

        # Remove leading fillers
        for filler in sorted(self._FILLER_WORDS, key=len, reverse=True):
            pattern = re.compile(r'^' + re.escape(filler) + r'\s+', re.IGNORECASE)
            result = pattern.sub('', result).strip()

        # Remove trailing fillers
        for filler in ["please", "for me", "now"]:
            pattern = re.compile(r'\s+' + re.escape(filler) + r'$', re.IGNORECASE)
            result = pattern.sub('', result).strip()

        return result

    # ─── Routers ──────────────────────────────────────────────────────────────

    def _route_open(self, match: re.Match) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Smart router for 'open X' commands.
        Checks if X is a URL shortcut first, then falls back to app launch.
        """
        target = match.group(1).strip().lower()

        # Remove trailing filler that might have survived
        target = re.sub(r'\s+(please|for me|now)$', '', target, flags=re.IGNORECASE).strip()

        # Check URL shortcuts
        for shortcut, url in self._URL_SHORTCUTS.items():
            if target == shortcut or target == f"the {shortcut}" or target == f"my {shortcut}":
                return "_open_url_local", {"url": url}

        # Otherwise, launch as application
        return "open_application", {"app_name": target}

    # ─── Extractors ───────────────────────────────────────────────────────────

    def _extract_close_app(self, match: re.Match) -> Dict[str, Any]:
        app_name = match.group(1).strip()
        return {"command": f"taskkill /F /IM {app_name}.exe /T"}

    def _extract_search(self, match: re.Match) -> Dict[str, Any]:
        query = match.group(1).strip()
        import urllib.parse
        return {"_open_url_local": f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"}

    def _extract_type_text(self, match: re.Match) -> Dict[str, Any]:
        return {"text": match.group(1).strip()}

    def _extract_key_press(self, match: re.Match) -> Dict[str, Any]:
        keys = match.group(1).strip().lower()
        # Normalize common voice phrases
        key_map = {
            "enter": "enter", "return": "enter",
            "escape": "escape", "esc": "escape",
            "space": "space", "spacebar": "space",
            "backspace": "backspace", "delete": "delete",
            "tab": "tab",
            "control c": "ctrl+c", "ctrl c": "ctrl+c",
            "control v": "ctrl+v", "ctrl v": "ctrl+v",
            "control z": "ctrl+z", "ctrl z": "ctrl+z",
            "control s": "ctrl+s", "ctrl s": "ctrl+s",
            "alt tab": "alt+tab",
            "alt f4": "alt+f4",
        }
        resolved = key_map.get(keys, keys)
        return {"keys": resolved}

    # ─── Local Built-in Functions ─────────────────────────────────────────────

    @staticmethod
    def execute_local(tool_name: str, args: dict) -> Optional[str]:
        """
        Execute built-in local functions that don't need the ToolRouter.
        Returns a string response, or None if the tool_name isn't a local built-in.
        """
        from datetime import datetime

        if tool_name == "_local_time":
            now = datetime.now()
            return f"The current time is {now.strftime('%I:%M %p')}."

        if tool_name == "_local_date":
            now = datetime.now()
            return f"Today is {now.strftime('%A, %B %d, %Y')}."
            
        if tool_name == "_open_url_local":
            import webbrowser
            url = args.get("url", args.get("_open_url_local"))
            webbrowser.open(url)
            return f"Opening {url} in your default browser."

        return None  # Not a local built-in
