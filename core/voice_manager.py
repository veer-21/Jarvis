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
        
        def _barge_in_watcher():
            while self.is_running:
                if self.voice._speaking:
                    # If Porcupine triggers during speech, it's a barge-in!
                    if self.voice.listen_for_wake_word():
                        log.info("[🔔 Barge-in Detected!] Interrupting TTS.")
                        self.interrupt_event.set()
                        # Wait for speaking to stop before resetting
                        time.sleep(0.5) 
                        self.interrupt_event.clear()
                else:
                    time.sleep(0.1)
                    
        barge_in_thread = threading.Thread(target=_barge_in_watcher, daemon=True)
        barge_in_thread.start()

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

                # ── 3. Try local intent classification FIRST ─────────────────
                self._set_ui_status("THINKING")

                local_match = self.intent_classifier.classify(command)
                if local_match:
                    tool_name, tool_args = local_match
                    self._stats["local_commands"] += 1

                    # Check for built-in local functions (time, date, etc.)
                    local_result = IntentClassifier.execute_local(tool_name, tool_args)
                    if local_result is not None:
                        t_total = (time.perf_counter() - t_pipeline_start) * 1000
                        log.info(f"[VOICE] LOCAL BUILTIN: {t_total:.0f}ms | \"{command}\" → {tool_name}")
                        self._set_ui_status("SPEAKING")
                        
                        # Use new stream API even for local strings
                        def str_gen(text): yield text
                        self.voice.speak_stream(str_gen(local_result), self.interrupt_event)
                        continue

                    # Execute via Brain's ToolRouter
                    if self.brain:
                        t_exec = time.perf_counter()
                        result = self.brain.tools.execute_tool(
                            tool_name, tool_args, interactive=False
                        )
                        t_exec_ms = (time.perf_counter() - t_exec) * 1000

                        if result["success"]:
                            response = str(result["result"])
                        else:
                            response = f"Command failed: {result.get('error', 'Unknown')}"

                        t_total = (time.perf_counter() - t_pipeline_start) * 1000
                        log.info(f"[VOICE] LOCAL TOOL: exec={t_exec_ms:.0f}ms total={t_total:.0f}ms | \"{command}\" → {tool_name}")
                        
                        self._set_ui_status("SPEAKING")
                        def str_gen(text): yield text
                        self.voice.speak_stream(str_gen(response), self.interrupt_event)
                    continue

                # ── 4. Route to Brain (LLM) for complex queries ──────────────
                self._stats["llm_routes"] += 1

                if self.brain:
                    # Inject short term memory context
                    context_prefix = ""
                    if len(self.recent_commands) > 1:
                        context_prefix = f"[Active Conversation Memory: You just asked: '{self.recent_commands[-2]}']\n"
                    
                    full_command = context_prefix + command
                    
                    t_llm = time.perf_counter()
                    
                    # We get a generator back
                    response_generator = self.brain.process_input_stream(full_command)
                    
                    self._set_ui_status("SPEAKING")
                    
                    # Wrap the generator to measure llm_time_to_first_token
                    def metrics_wrapped_generator(gen):
                        first_token = True
                        for chunk in gen:
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
