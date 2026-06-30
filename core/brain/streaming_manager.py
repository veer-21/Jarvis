"""
JARVIS Brain — Streaming Manager
Handles real-time token streaming, SSE event formatting,
and WebSocket message framing for live UI updates.
"""

import json
from typing import Iterator, Optional, Callable

from core.logger import log, error_log


class StreamingManager:
    """
    Manages real-time streaming of LLM responses.
    Provides token streaming with SSE formatting and WebSocket support.
    """

    def __init__(self):
        self._reasoning_engine = None
        self._memory_manager   = None
        log.info("StreamingManager initialized.")

    def set_reasoning_engine(self, engine) -> None:
        """Attach the reasoning engine for streaming calls."""
        self._reasoning_engine = engine

    def set_memory_manager(self, manager) -> None:
        """Attach memory manager for storing streamed responses."""
        self._memory_manager = manager

    # ─── Token Streaming ──────────────────────────────────────────────────────

    def stream_response(
        self,
        user_input: str,
        enriched_prompt: str,
        system_prompt: str,
    ) -> Iterator[str]:
        """
        Stream the LLM response token by token.

        Args:
            user_input:      Original user message (for memory storage).
            enriched_prompt: The full enriched prompt to send.
            system_prompt:   System prompt for the streaming call.

        Yields:
            String chunks of the response.
        """
        if not self._reasoning_engine:
            yield "[Error: No reasoning engine attached]"
            return

        full_response = ""
        try:
            for chunk in self._reasoning_engine.stream_message(enriched_prompt, system_prompt, raw_message=user_input):
                full_response += chunk
                yield chunk

            # Store in memory after full stream completes
            if self._memory_manager and full_response:
                try:
                    self._memory_manager.store_exchange(user_input, full_response)
                except Exception as e:
                    error_log.error(f"Memory store (stream) failed: {e}")

        except Exception as e:
            error_log.error(f"Streaming error: {e}")
            yield f"\n[Stream Error: {str(e)}]"

    # ─── SSE Formatting ──────────────────────────────────────────────────────

    def stream_as_sse(
        self,
        user_input: str,
        enriched_prompt: str,
        system_prompt: str,
    ) -> Iterator[str]:
        """
        Stream response formatted as Server-Sent Events.

        Yields SSE-formatted strings:
          data: {"chunk": "text"}\n\n
          data: {"done": true}\n\n

        Args:
            user_input:      Original user message.
            enriched_prompt: Enriched prompt to send.
            system_prompt:   System prompt.
        """
        try:
            for chunk in self.stream_response(user_input, enriched_prompt, system_prompt):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    # ─── WebSocket Helpers ────────────────────────────────────────────────────

    def stream_chunks_list(
        self,
        user_input: str,
        enriched_prompt: str,
        system_prompt: str,
    ) -> Iterator[dict]:
        """
        Stream response as dicts suitable for WebSocket JSON messages.

        Yields:
            Dicts: {"chunk": "text"} or {"done": True} or {"error": "msg"}
        """
        try:
            for chunk in self.stream_response(user_input, enriched_prompt, system_prompt):
                yield {"chunk": chunk}
            yield {"done": True}
        except Exception as e:
            yield {"error": str(e)}

    # ─── Execution Event Streaming ────────────────────────────────────────────

    @staticmethod
    def format_execution_event(event) -> str:
        """
        Format an ExecutionEvent as an SSE message.

        Args:
            event: ExecutionEvent object.

        Returns:
            SSE-formatted string.
        """
        data = {
            "type":       event.event_type,
            "step_index": event.step_index,
            "data":       event.data,
            "timestamp":  event.timestamp,
        }
        return f"data: {json.dumps(data)}\n\n"
