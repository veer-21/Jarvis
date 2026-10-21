"""
JARVIS Voice Manager — Continuous Voice Mode (Phase 1 V2)
Runs in a background thread, listens for the wake word, routes commands
through the local IntentClassifier for zero-latency execution, and falls
back to the Brain for complex queries.

Upgrades:
  - Supports `interrupt_event` to abort TTS and LLM streams (Barge-in)
  - Active Conversation Session Memory (preserves short-term context)
  - Latency instrumentation broadcast to WebSocket
"""

import threading
import time
import asyncio
from typing import Optional, List

from core.logger import log, error_log
from core.voice import VoiceInterface
from core.brain.intent_classifier import IntentClassifier

class ContinuousVoiceManager:
    """
    Runs in a background thread, constantly listening for the wake word
    and routing transcribed voice commands optimally:
      1. Local IntentClassifier (instant) for simple commands
      2. Brain (LLM) for complex queries
    """
    def __init__(self, brain=None):
        self.brain = brain
        self.voice = VoiceInterface()
        self.intent_classifier = IntentClassifier()
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        
        # Interruption support
        self.interrupt_event = threading.Event()
        self.active_session_id: Optional[str] = None  # Tracks owning session for voice playback

        # Active Conversation Session Memory
        self.recent_commands = []

        # Performance stats
        self._stats = {
            "wake_hits": 0,
            "wake_misses": 0,
            "local_commands": 0,
            "llm_routes": 0,
        }

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        log.info("[VoiceManager] Continuous Voice Mode started in background.")

    def stop(self):
        self.is_running = False
        self.interrupt_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.voice.cleanup()
        log.info(f"[VoiceManager] Stopped. Stats: {self._stats}")

    def stop_speaking_for_session(self, session_id: Optional[str] = None) -> bool:
        """
        Voice Playback Owner Policy:
        Stops active voice playback only if:
        1. An authenticated session initiates the call, AND
        2. Either no specific session is bound to playback (global continuous voice),
           OR the caller's session matches self.active_session_id.
        Unrelated or unauthenticated sessions are unauthorized to stop voice playback.
        """
        if not session_id:
            return False
        if self.active_session_id is not None and self.active_session_id != session_id:
            log.warning(f"[VoiceManager] Session {session_id} attempted unauthorized voice stop for active session {self.active_session_id}")
            return False
        try:
            self.voice.stop_speaking()
            self.active_session_id = None
            return True
        except Exception as e:
            log.debug(f"[VoiceManager] Voice stop speaking notice: {e}")
            return False

    def _broadcast_metrics(self, metrics: dict):
        """Broadcast latency metrics to the WebSocket UI."""
        try:
            from api.ws_manager import ws_manager
            payload = {"type": "latency_metrics", "metrics": metrics}
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(ws_manager.broadcast(payload))
            else:
                asyncio.run(ws_manager.broadcast(payload))
        except Exception:
            pass

    def _set_ui_status(self, status_text: str):
        try:
            from api.ws_manager import ws_manager
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(ws_manager.broadcast({"status": status_text}))
            else:
                asyncio.run(ws_manager.broadcast({"status": status_text}))
        except Exception:
            pass

    def _listen_loop(self):
        """The main continuous loop."""
        while self.is_running:
            try:
                self.interrupt_event.clear()
                
                # ── 1. Listen for Wake Word ──────────────────────────────────
                self._set_ui_status("ONLINE")

                triggered = self.voice.listen_for_wake_word()

                if not triggered:
                    self._stats["wake_misses"] += 1
                    continue
                    
                self._stats["wake_hits"] += 1

                # Wake word detected!
                print("\a")  # terminal beep
                
                t_pipeline_start = time.perf_counter()

                # ── 2. Listen for actual command ─────────────────────────────
                self._set_ui_status("LISTENING")
                if self.brain and self.recent_commands:
                    self.brain.context.start_prefetch(self.recent_commands[-1])

                command = self.voice.listen(wait_for_wake_word=False, interrupt_event=self.interrupt_event)

                if not command:
                    continue
                    
                # Save to active session memory
                self.recent_commands.append(command)
                if len(self.recent_commands) > 5:
                    self.recent_commands.pop(0)

                # Broadcast partial metrics
                metrics = {}
                if 'wakeword_detection_latency' in self.voice.last_metrics:
                    metrics['wakeword_detection_latency'] = self.voice.last_metrics['wakeword_detection_latency']
                if 'vad_detect_to_stt_complete' in self.voice.last_metrics:
                    metrics['vad_detect_to_stt_complete'] = self.voice.last_metrics['vad_detect_to_stt_complete']
                
                self._broadcast_metrics(metrics)

                # ── 3. Route via Central Assistant Core (AssistantOrchestrator) ──
                self._set_ui_status("THINKING")
                self._stats["llm_routes"] += 1

                if self.brain:
                    t_llm = time.perf_counter()
                    # Unified streaming cognitive pipeline
                    response_generator = self.brain.process_input_stream(command, interrupt_event=self.interrupt_event)
                    self._set_ui_status("SPEAKING")
                    
                    # Wrap the async generator to measure llm_time_to_first_token
                    async def metrics_wrapped_generator(gen):
                        first_token = True
                        async for chunk in gen:
                            if first_token:
                                llm_ms = (time.perf_counter() - t_llm) * 1000
                                metrics['llm_time_to_first_token'] = llm_ms
                                
                                # Estimate TTS time
                                tts_t0 = time.perf_counter()
                                
                                yield chunk
                                
                                tts_ms = (time.perf_counter() - tts_t0) * 1000
                                metrics['tts_time_to_first_audio'] = tts_ms
                                
                                metrics['total_request_latency'] = metrics.get('vad_detect_to_stt_complete', 0) + llm_ms + tts_ms
                                self._broadcast_metrics(metrics)
                                
                                first_token = False
                            else:
                                yield chunk

                    # Stream the response directly to audio output, aborts instantly if interrupt_event is set
                    self.voice.speak_stream(metrics_wrapped_generator(response_generator), self.interrupt_event)

            except Exception as e:
                error_log.error(f"[VoiceManager] Loop Error: {e}")
                time.sleep(1)  # Prevent tight crash loops
