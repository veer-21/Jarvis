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

class BasicVisionMock(ScreenUnderstanding):
    """
    A basic placeholder implementation until a VLM is fully integrated.
    Relies on OS accessibility APIs or simple OCR heuristics.
    """
    def parse_screen(self, image_path_or_bytes: str | bytes) -> Dict[str, Any]:
        log.warning("[Vision] BasicVisionMock parsing screen (noop).")
        return {"elements": []}
        
    def find_element(self, description: str, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, int]]:
        log.warning(f"[Vision] BasicVisionMock cannot find element: {description}")
        return None
        
    def verify_state(self, expected_state: str, current_image: str | bytes) -> bool:
        log.warning(f"[Vision] BasicVisionMock assuming state verified: {expected_state}")
        return True
