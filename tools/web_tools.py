"""
JARVIS Web Tools
Provides internet research capabilities:
  - web_search         : DuckDuckGo search, returns top results
  - fetch_webpage      : Download and parse a webpage's main text
  - get_weather        : Current weather for a location (via wttr.in, no API key needed)
  - search_news        : Recent news headlines via DuckDuckGo news
"""

import json
import re
from typing import Optional
from urllib.parse import urlencode, quote_plus

from core.logger import log, error_log

# ─── Optional Dependencies ───────────────────────────────────────────────────
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    log.warning("requests not installed. Run: pip install requests")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    log.warning("beautifulsoup4 not installed. Run: pip install beautifulsoup4")

try:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False
    log.warning("ddgs / duckduckgo-search not installed. Run: pip install ddgs")


# ─── Shared Session ──────────────────────────────────────────────────────────
_SESSION = None

def _get_session():
    global _SESSION
    if _SESSION is None and HAS_REQUESTS:
        _SESSION = requests.Session()
        _SESSION.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        })
    return _SESSION


# ─── Tools ───────────────────────────────────────────────────────────────────

def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web using DuckDuckGo and return the top results.
    No API key required.

    Args:
        query:       The search query string.
        max_results: Number of results to return (1–10).
    """
    if not HAS_DDGS:
        return "Error: duckduckgo-search is not installed. Run: pip install duckduckgo-search"

    log.info(f"Web search: {query}")
    try:
        results = list(DDGS().text(query, max_results=min(max_results, 10)))

        if not results:
            return f"No results found for: '{query}'"

        lines = [f"Web Search Results for: '{query}'\n{'─'*50}"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            url   = r.get("href", "")
            body  = r.get("body", "")[:300]
            lines.append(f"\n[{i}] {title}\n    {url}\n    {body}")

        return "\n".join(lines)

    except Exception as e:
        error_log.error(f"Web search failed: {e}")
        return f"Web search failed: {str(e)}"


def fetch_webpage(url: str, max_chars: int = 8_000) -> str:
    """
    Fetch a webpage and return its main text content, stripped of HTML.
    Useful for reading articles, documentation, and web pages.

    Args:
        url:       The URL to fetch.
        max_chars: Maximum characters of text to return.
    """
    if not HAS_REQUESTS:
        return "Error: requests is not installed. Run: pip install requests"

    log.info(f"Fetching webpage: {url}")
    try:
        session = _get_session()
        response = session.get(url, timeout=15, allow_redirects=True)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return f"Warning: URL returned non-HTML content ({content_type}). Cannot parse."

        if HAS_BS4:
            soup = BeautifulSoup(response.text, "html.parser")
            # Remove script/style noise
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        else:
            # Crude fallback: strip HTML tags with regex
            text = re.sub(r"<[^>]+>", " ", response.text)
            text = re.sub(r"\s+", " ", text).strip()

        # Truncate
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[...truncated at {max_chars:,} chars]"

        return f"Content from {url}:\n{'─'*50}\n{text}"

    except requests.exceptions.Timeout:
        return f"Error: Request timed out fetching '{url}'."
    except requests.exceptions.HTTPError as e:
        return f"Error: HTTP {e.response.status_code} when fetching '{url}'."
    except Exception as e:
        error_log.error(f"fetch_webpage failed for {url}: {e}")
        return f"Error fetching webpage: {str(e)}"


def get_weather(location: str = "") -> str:
    """
    Get the current weather for a location.
    Uses the free wttr.in service — no API key required.

    Args:
        location: City name, coordinates, or airport code (e.g., 'London', 'New York', 'JFK'). If empty, uses current IP location.
    """
    if not HAS_REQUESTS:
        return "Error: requests is not installed. Run: pip install requests"

    log.info(f"Fetching weather for: {location if location else 'current location'}")
    try:
        session = _get_session()
        # Use a custom format for voice-friendly text: Location: Condition, Temp, Feels like
        # %l = location, %C = condition, %t = temp, %f = feels like
        fmt = "%l:+%C,+%t,+feels+like+%f"
        
        if location:
            encoded = quote_plus(location)
            url = f"https://wttr.in/{encoded}?format={fmt}"
        else:
            url = f"https://wttr.in/?format={fmt}"
            
        # Override the browser User-Agent to force plain text instead of HTML
        response = session.get(url, headers={"User-Agent": "curl/7.68.0"}, timeout=10)
        response.raise_for_status()
        
        weather_text = response.text.strip()
        if not weather_text or "<html" in weather_text.lower():
            return f"Could not retrieve weather for '{location}'."
        
        return f"The current weather in {weather_text}"

    except Exception as e:
        error_log.error(f"Weather fetch failed for {location}: {e}")
        return f"Error fetching weather: {str(e)}"


def search_news(query: str, max_results: int = 5) -> str:
    """
    Search for recent news articles using DuckDuckGo News.

    Args:
        query:       Topic or keywords to search news for.
        max_results: Number of headlines to return (1–10).
    """
    if not HAS_DDGS:
        return "Error: duckduckgo-search is not installed. Run: pip install duckduckgo-search"

    log.info(f"News search: {query}")
    try:
        results = list(DDGS().news(query, max_results=min(max_results, 10)))

        if not results:
            return f"No news found for: '{query}'"

        lines = [f"News Results for: '{query}'\n{'─'*50}"]
        for i, r in enumerate(results, 1):
            title  = r.get("title", "No title")
            url    = r.get("url", "")
            source = r.get("source", "Unknown source")
            date   = r.get("date", "")
            body   = r.get("body", "")[:200]
            lines.append(f"\n[{i}] {title}\n    Source: {source} | {date}\n    {url}\n    {body}")

        return "\n".join(lines)

    except Exception as e:
        error_log.error(f"News search failed: {e}")
        return f"News search failed: {str(e)}"
