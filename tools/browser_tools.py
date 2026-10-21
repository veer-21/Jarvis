"""
JARVIS Browser Automation Tools (Playwright)
Provides headless and headed browser control:
  - open_url              : Navigate to a URL
  - browser_screenshot    : Screenshot a webpage
  - get_page_text         : Extract readable text from a webpage via browser
  - browser_click         : Click an element by selector or text
  - browser_fill          : Fill an input field
  - browser_execute       : Run JavaScript on a page
  - close_browser         : Shut down the browser

Note: On first use, run `playwright install chromium` to download the browser.
"""

import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional

from core.logger import log, error_log

# ─── Optional Playwright ──────────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    log.warning("playwright not installed — browser automation disabled. Run: pip install playwright && playwright install chromium")


SCREENSHOT_DIR = Path(__file__).parent.parent / "data" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# ─── Browser State (singleton) ────────────────────────────────────────────────
_playwright_instance = None
_browser: Optional["Browser"] = None
_context: Optional["BrowserContext"] = None
_page: Optional["Page"] = None


def _ensure_browser(headless: bool = True) -> tuple:
    """Lazily start Playwright and return (playwright, browser, context, page)."""
    global _playwright_instance, _browser, _context, _page

    if not HAS_PLAYWRIGHT:
        raise RuntimeError("playwright is not installed. Run: pip install playwright && playwright install chromium")

    if _browser is None or not _browser.is_connected():
        log.info("Starting Playwright browser...")
        _playwright_instance = sync_playwright().start()
        try:
            _browser = _playwright_instance.chromium.launch(channel="chromium", headless=headless)
        except Exception:
            _browser = _playwright_instance.chromium.launch(headless=headless)
        _context  = _browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
            ),
        )
        _page = _context.new_page()
        log.info("Browser launched successfully.")

    return _playwright_instance, _browser, _context, _page


# ─── Tools ───────────────────────────────────────────────────────────────────

def open_url(url: str, wait_for: str = "domcontentloaded") -> str:
    """
    Open a URL in the automated browser. Creates browser if not already running.

    Args:
        url:      The full URL to navigate to.
        wait_for: Wait condition — 'load', 'domcontentloaded', or 'networkidle'.
    """
    if not HAS_PLAYWRIGHT:
        return "Error: playwright is not installed. Run: pip install playwright && playwright install chromium"
    try:
        _, _, _, page = _ensure_browser()
        page.goto(url, wait_until=wait_for, timeout=30_000)
        title = page.title()
        log.info(f"Browser navigated to: {url} — Title: {title}")
        return f"Opened '{url}'. Page title: '{title}'"
    except Exception as e:
        error_log.error(f"open_url failed: {e}")
        return f"Error opening URL '{url}': {str(e)}"


def browser_screenshot(filename: Optional[str] = None) -> str:
    """
    Take a screenshot of the current browser page and save it.

    Args:
        filename: Optional filename (without extension). Auto-generated if not set.
    """
    if not HAS_PLAYWRIGHT:
        return "Error: playwright is not installed."
    try:
        _, _, _, page = _ensure_browser()
        if not filename:
            filename = f"browser_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        filepath = SCREENSHOT_DIR / f"{filename}.png"
        page.screenshot(path=str(filepath), full_page=True)
        log.info(f"Browser screenshot saved: {filepath}")
        return f"Browser screenshot saved to: {filepath}"
    except Exception as e:
        return f"Error taking browser screenshot: {str(e)}"


def get_page_text(url: Optional[str] = None, max_chars: int = 10_000) -> str:
    """
    Get the readable text content of the current browser page (or navigate to a URL first).
    More reliable than fetch_webpage for JavaScript-heavy sites.

    Args:
        url:       Optional URL to navigate to before extracting text.
        max_chars: Maximum characters of text to return.
    """
    if not HAS_PLAYWRIGHT:
        return "Error: playwright is not installed."
    try:
        _, _, _, page = _ensure_browser()
        if url:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # Extract text via JS innerText
        text = page.evaluate("() => document.body.innerText")
        text = text.strip() if text else ""

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[...truncated at {max_chars:,} chars]"

        current_url = page.url
        return f"Page text from {current_url}:\n{'─'*50}\n{text}"

    except Exception as e:
        return f"Error extracting page text: {str(e)}"


def browser_click(selector: str = "", text: str = "") -> str:
    """
    Click an element on the current page using a CSS selector or visible text.

    Args:
        selector: CSS selector (e.g., '#submit-btn', '.nav-link').
        text:     Visible text of the element to click (alternative to selector).
    """
    if not HAS_PLAYWRIGHT:
        return "Error: playwright is not installed."
    try:
        _, _, _, page = _ensure_browser()
        if text:
            page.get_by_text(text).first.click(timeout=10_000)
            log.info(f"Browser clicked element with text: '{text}'")
            return f"Clicked element with text: '{text}'"
        elif selector:
            page.locator(selector).first.click(timeout=10_000)
            log.info(f"Browser clicked selector: '{selector}'")
            return f"Clicked selector: '{selector}'"
        else:
            return "Error: Provide either 'selector' or 'text' to click."
    except Exception as e:
        return f"Error clicking element: {str(e)}"


def browser_fill(selector: str, value: str) -> str:
    """
    Fill an input or textarea field on the current page.

    Args:
        selector: CSS selector of the input element.
        value:    Text to enter into the field.
    """
    if not HAS_PLAYWRIGHT:
        return "Error: playwright is not installed."
    try:
        _, _, _, page = _ensure_browser()
        page.locator(selector).fill(value, timeout=10_000)
        log.info(f"Browser filled '{selector}' with value (length: {len(value)})")
        return f"Filled input '{selector}' with provided value."
    except Exception as e:
        return f"Error filling input '{selector}': {str(e)}"


def browser_execute_js(script: str) -> str:
    """
    Execute arbitrary JavaScript on the current page and return the result.

    Args:
        script: JavaScript code to execute (must be a valid JS expression or function).
    """
    if not HAS_PLAYWRIGHT:
        return "Error: playwright is not installed."
    try:
        _, _, _, page = _ensure_browser()
        result = page.evaluate(script)
        log.info(f"JS executed on page. Result type: {type(result).__name__}")
        return f"JS result: {str(result)[:2000]}"
    except Exception as e:
        return f"Error executing JavaScript: {str(e)}"


def close_browser() -> str:
    """Close the automated browser and free resources."""
    global _playwright_instance, _browser, _context, _page
    try:
        if _browser and _browser.is_connected():
            _browser.close()
        if _playwright_instance:
            _playwright_instance.stop()
        _browser = None
        _context = None
        _page    = None
        _playwright_instance = None
        log.info("Browser closed.")
        return "Browser closed successfully."
    except Exception as e:
        return f"Error closing browser: {str(e)}"
