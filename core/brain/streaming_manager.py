"""
JARVIS Brain — Streaming Manager
Handles real-time token streaming, SSE event formatting,
and WebSocket message framing for live UI updates.
"""

import json
import asyncio
from typing import AsyncIterator, Optional
from core.logger import log, error_log


class StreamingManager:
    """
    Manages real-time streaming of LLM responses.
    Provides token streaming with SSE formatting and WebSocket support.
    """

    def __init__(self, reasoning_engine=None, memory_manager=None):
        self._reasoning_engine = reasoning_engine
        self._memory_manager   = memory_manager
        log.info("StreamingManager initialized.")

    def set_reasoning_engine(self, engine) -> None:
        """Attach the reasoning engine for streaming calls."""
        self._reasoning_engine = engine

    def set_memory_manager(self, manager) -> None:
        """Attach memory manager for storing streamed responses."""
        self._memory_manager = manager

    # ─── Token Streaming ──────────────────────────────────────────────────────

    async def stream_response(
        self,
        user_input: str,
        enriched_prompt: str,
        system_prompt: str,
        interrupt_event = None,
        store_memory: bool = True,
        context = None,
    ) -> AsyncIterator[str]:
        """
        Stream the LLM response token by token asynchronously.
        Monitors the interrupt_event to immediately break and cancel.
        Broadcasts THINKING and SPEAKING states to the frontend via WebSocket.

        Args:
            user_input:      Original user message (for memory storage).
            enriched_prompt: The full enriched prompt to send.
            system_prompt:   System prompt for the streaming call.
            interrupt_event: Threading/async event to monitor for barge-in interruption.
            store_memory:    Controls whether exchange is persisted to memory.
            context:         Optional ExecutionContext instance.

        Yields:
            String chunks of the response.
        """
        if not self._reasoning_engine:
            if context:
                context.stream_error = "No reasoning engine attached"
            yield "[Error: No reasoning engine attached]"
            return

        from api.ws_manager import ws_manager
        session_id = getattr(context, "session_id", None) if context else None

        # Deliver THINKING state strictly to the owning session if authenticated
        if session_id:
            await ws_manager.send_status_to_session(session_id, "THINKING")

        full_response = ""
        first_token = True
        stream_interrupted = False
        stream_failed = False
        
        try:
            loop = asyncio.get_running_loop()
            
            # ReasoningEngine.stream_message is synchronous, so we run it in an executor/thread pool
            # to prevent it from blocking the async event loop.
            def run_stream():
                uid = getattr(context, "user_id", None) if context else None
                try:
                    return self._reasoning_engine.stream_message(
                        enriched_prompt, system_prompt, raw_message=user_input, session_id=session_id, user_id=uid
                    )
                except TypeError:
                    return self._reasoning_engine.stream_message(
                        enriched_prompt, system_prompt, raw_message=user_input
                    )
            
            gen = await loop.run_in_executor(None, run_stream)
            
            def get_next_token():
                try:
                    return next(gen)
                except StopIteration:
                    return None

            while True:
                # Interrupt Awareness: Check if user has barged in
                is_barge_in = (
                    (interrupt_event and interrupt_event.is_set())
                    or (context and hasattr(context, "cancellation_token") and context.cancellation_token and context.cancellation_token.is_set())
                )
                if is_barge_in:
                    log.info("[🎙️ Barge-In]: Interrupt detected during LLM generation. Aborting stream.")
                    stream_interrupted = True
                    if context:
                        context.is_interrupted = True
                    if session_id:
                        await ws_manager.send_status_to_session(session_id, "IDLE")
                        await ws_manager.send_chunk_to_session(session_id, "\n[Interrupted]")
                    break

                # Fetch next chunk in a non-blocking executor thread
                chunk = await loop.run_in_executor(None, get_next_token)
                if chunk is None:
                    break

                # State Delivery: Transition from THINKING to SPEAKING on first token
                if first_token:
                    if session_id:
                        await ws_manager.send_status_to_session(session_id, "SPEAKING")
                    first_token = False

                full_response += chunk
                
                # Send token strictly to the owning WebSocket session (never broadcast private chunks)
                if session_id:
                    await ws_manager.send_chunk_to_session(session_id, chunk)
                yield chunk

            if not stream_interrupted and not stream_failed:
                if context:
                    context.stream_completed = True

        except Exception as e:
            error_log.error(f"Streaming error: {e}")
            stream_failed = True
            if context:
                context.stream_error = str(e)
            yield f"\n[Stream Error: {str(e)}]"
        finally:
            # Revert to IDLE state once stream completes or is terminated (only to session)
            if session_id:
                await ws_manager.send_status_to_session(session_id, "IDLE")

    @staticmethod
    async def buffer_and_flush_sentences(token_generator, interrupt_event=None) -> AsyncIterator[str]:
        """
        Accumulates raw tokens into sentence-level chunks using punctuation boundaries
        to flush larger logical pieces for speech synthesis or optimized processing.
        """
        buffer = ""
        
        async for token in token_generator:
            if interrupt_event and interrupt_event.is_set():
                break
            buffer += token
            # Check if we hit a punctuation boundary
            if any(p in buffer for p in ('. ', '! ', '? ', '\n')):
                yield buffer.strip()
                buffer = ""
                
        if buffer.strip() and not (interrupt_event and interrupt_event.is_set()):
            yield buffer.strip()

    # ─── SSE Formatting ──────────────────────────────────────────────────────

    async def stream_as_sse(
        self,
        user_input: str,
        enriched_prompt: str,
        system_prompt: str,
        interrupt_event = None,
        store_memory: bool = True,
        context = None,
    ) -> AsyncIterator[str]:
        """
        Stream response formatted as Server-Sent Events.
        """
        try:
            async for chunk in self.stream_response(
                user_input, enriched_prompt, system_prompt, interrupt_event,
                store_memory=store_memory, context=context
            ):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    # ─── WebSocket Helpers ────────────────────────────────────────────────────

    async def stream_chunks_list(
        self,
        user_input: str,
        enriched_prompt: str,
        system_prompt: str,
        interrupt_event = None,
        store_memory: bool = True,
        context = None,
    ) -> AsyncIterator[dict]:
        """
        Stream response as dicts suitable for WebSocket JSON messages.
        """
        try:
            async for chunk in self.stream_response(
                user_input, enriched_prompt, system_prompt, interrupt_event,
                store_memory=store_memory, context=context
            ):
                yield {"chunk": chunk}
            yield {"done": True}
        except Exception as e:
            yield {"error": str(e)}

    # ─── Execution Event Streaming ────────────────────────────────────────────

    @staticmethod
    def format_execution_event(event, as_sse: bool = False):
        """
        Format an ExecutionEvent as an SSE message string or a dictionary for WebSockets.
        """
        data = {
            "type":       "execution_update",
            "event_type": event.event_type,
            "step_index": event.step_index,
            "data":       event.data,
            "timestamp":  event.timestamp,
        }
        if as_sse:
            return f"data: {json.dumps(data)}\n\n"
        return data
