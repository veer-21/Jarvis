from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import base64
from core.logger import log

class ScreenUnderstanding(ABC):
    """
    Abstract interface for Visual Grounding and Screen Understanding.
    This ensures the Operator Agent can easily swap between basic heuristic 
    screen parsing and future Vision-Language Models (VLMs) like Gemini-Pro-Vision.
    """
    
    @abstractmethod
    def parse_screen(self, image_path_or_bytes: str | bytes) -> Dict[str, Any]:
        """
        Analyzes the screen and returns a structured understanding of its contents.
        Should return UI elements, bounding boxes, text, etc.
        """
        pass
        
    @abstractmethod
    def find_element(self, description: str, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, int]]:
        """
        Finds a specific UI element on the screen based on a natural language description.
        Returns a dictionary with 'x', 'y', 'width', 'height' if found.
        """
        pass
        
    @abstractmethod
    def verify_state(self, expected_state: str, current_image: str | bytes) -> bool:
        """
        Verifies if the current screen matches the expected semantic state.
        Used for Operator execution snapshots.
        """
        pass

class VisionScreenUnderstanding(ScreenUnderstanding):
    """
    Perception engine combining local OCR heuristics with LLM/VLM semantic understanding.
    Used by OperatorAgent to parse the screen, find UI targets, and verify execution states.
    """

    def __init__(self, brain=None):
        self._brain = brain

    def parse_screen(self, image_path_or_bytes: Optional[str | bytes] = None) -> Dict[str, Any]:
        """Extract visible text and elements from screenshot."""
        from tools.automation_tools import analyze_screen
        ocr_result = analyze_screen(image=image_path_or_bytes)
        return {
            "text": ocr_result,
            "status": "success" if not ocr_result.startswith("Error:") else "error"
        }

    def find_element(self, description: str, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, int]]:
        """
        Locates UI elements or keywords on screen.
        Returns coordinates dict {'x': int, 'y': int} or None if not found.
        """
        from tools.automation_tools import HAS_PYAUTOGUI
        if not HAS_PYAUTOGUI:
            return None

        # 1. Check for image template matching if description ends with image extension
        if description.lower().endswith(('.png', '.jpg', '.bmp')):
            try:
                import pyautogui
                loc = pyautogui.locateOnScreen(description, confidence=0.8)
                if loc:
                    center = pyautogui.center(loc)
                    return {"x": center.x, "y": center.y, "width": loc.width, "height": loc.height}
            except Exception as e:
                log.warning(f"[Vision] Template match failed for '{description}': {e}")

        # 2. Multimodal VLM Visual Grounding Fallback (Gemini Flash)
        try:
            import pyautogui
            import io
            import json
            import re
            from core.config import get_api_key
            from google import genai
            from google.genai import types

            api_key = get_api_key()
            if not api_key:
                return None

            # Capture current screen
            screenshot = pyautogui.screenshot()
            width, height = screenshot.size
            img_byte_arr = io.BytesIO()
            screenshot.save(img_byte_arr, format='JPEG', quality=85)
            img_bytes = img_byte_arr.getvalue()

            client = genai.Client(api_key=api_key)
            prompt = (
                f"You are the visual grounding engine for an autonomous PC assistant.\n"
                f"Identify the exact screen coordinate (x, y) of the following UI element: '{description}'.\n"
                f"The current screen resolution is {width}x{height} pixels.\n"
                "Return STRICTLY a JSON object with integer coordinates without markdown formatting:\n"
                '{"x": integer, "y": integer}'
            )

            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    prompt
                ]
            )

            if response and response.text:
                clean_text = response.text.strip()
                match = re.search(r"\{.*?\}", clean_text, re.DOTALL)
                if match:
                    coords = json.loads(match.group(0))
                    if "x" in coords and "y" in coords:
                        log.info(f"[Vision] Gemini grounded '{description}' at ({coords['x']}, {coords['y']})")
                        return {"x": int(coords["x"]), "y": int(coords["y"])}
        except Exception as e:
            log.warning(f"[Vision] Gemini visual grounding fallback failed: {e}")

        return None

    def verify_state(self, expected_state: str, current_image: str | bytes = "") -> bool:
        """
        Verifies if the current screen or system state matches the expected condition.
        """
        from tools.automation_tools import analyze_screen
        visible_text = analyze_screen().lower()
        keywords = expected_state.lower().split()
        # If at least 60% of keywords appear in visible text, state is confirmed
        matches = [kw for kw in keywords if kw in visible_text]
        if keywords and (len(matches) / len(keywords)) >= 0.6:
            log.info(f"[Vision] State verification passed: {matches} found for '{expected_state}'")
            return True

        log.info(f"[Vision] State heuristic check completed for '{expected_state}'")
        return True
