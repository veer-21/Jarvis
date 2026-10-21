"""
JARVIS Voice Interface (Phase 1 V2 Refactored)
Handles streaming speech-to-text (STT), text-to-speech (TTS), and wake word detection.

Upgrades:
  - faster-whisper optimized with beam_size=1 and vad_filter=True
  - silero-vad for instant end-of-speech detection
  - edge-tts native async pipeline streaming into mpv (no subprocess overhead for generation)
  - ElevenLabs streaming playback
  - Push-to-Talk (PTT) support
  - Interruption (Barge-in) support
  - Thread-safe PyAudio resource management
"""

import os
import re
import threading
import time
import struct
import numpy as np
import subprocess
import asyncio
import tempfile
import wave
from typing import Optional, List, Dict, Any

from core.logger import log, error_log
from core.config import get_voice_engine, get_voice_profile, get_wake_words

HAS_FASTER_WHISPER = False
try:
    from faster_whisper import WhisperModel  # type: ignore
    HAS_FASTER_WHISPER = True
except (ImportError, OSError, Exception):
    pass

HAS_PORCUPINE = False
try:
    import pvporcupine
    import pyaudio
    HAS_PORCUPINE = True
except (ImportError, OSError, Exception):
    pass

HAS_ELEVENLABS = False
try:
    from elevenlabs.client import ElevenLabs
    HAS_ELEVENLABS = True
except (ImportError, OSError, Exception):
    pass


class VoiceInterface:
    def __init__(self):
        log.info("Initializing New Voice Pipeline (Phase 1 V2)...")
        
        self.engine_type = get_voice_engine()
        self.profile = get_voice_profile()
        self.wake_words = get_wake_words()
        
        # Performance Tracking
        self.last_metrics = {}
        
        # 1. Setup VAD (Silero)
        try:
            import torch
            from silero_vad import load_silero_vad
            self.vad_model = load_silero_vad()
            self.has_vad = True
            log.info("[🎙️ VAD]: Silero VAD enabled.")
        except Exception as e:
            log.warning(f"[⚠️ VAD Error]: {e}. Fallback to basic energy thresholding.")
            self.has_vad = False
            
        # 2. Setup STT (Faster-Whisper Multilingual Small)
        if HAS_FASTER_WHISPER:
            log.info("[🎙️ STT]: Loading faster-whisper small model...")
            # Optimize model initialization for CPU with cpu_threads=4
            self.stt_model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4)
            log.info("[🎙️ STT]: faster-whisper loaded.")
        else:
            log.warning("[⚠️ STT]: faster-whisper not installed.")
            self.stt_model = None

        # 3. Setup Wake Word (Porcupine fallback)
        self.porcupine_api_key = os.getenv("PICOVOICE_API_KEY") or os.getenv("PORCUPINE_ACCESS_KEY")
        self.wake_word_engine = None
        
        try:
            import pyaudio
            self.pa = pyaudio.PyAudio()
        except Exception as e:
            self.pa = None
            log.warning(f"[⚠️ Voice]: PyAudio failed to initialize: {e}. Running in audio fallback mode.")
            self._broadcast_hardware_fallback("audio_input", str(e))
        
        if HAS_PORCUPINE and self.pa and self.porcupine_api_key:
            try:
                # Use the primary configured wake word, fallback to jarvis
                keyword = "jarvis"
                if "travis" in self.wake_words:
                    keyword = "travis"
                self.wake_word_engine = pvporcupine.create(
                    access_key=self.porcupine_api_key, 
                    keywords=[keyword]
                )
                log.info("[🎙️ Wake Word]: Porcupine enabled.")
            except Exception as e:
                log.error(f"[⚠️ Porcupine Error]: {e}")
                
        # 4. Setup Push-to-Talk
        self.ptt_hotkey = "f9"
        try:
            import keyboard
            self.has_keyboard = True
        except ImportError:
            self.has_keyboard = False

        self._tts_lock = threading.Lock()
        self._audio_lock = threading.Lock()  # Mutex lock for shared PyAudio instance
        self._speaking = False

    def _broadcast_hardware_fallback(self, hardware_type: str, details: str) -> None:
        """Broadcast a hardware fallback notification to telemetry and logs."""
        log.warning(f"[Voice Hardware Fallback] {hardware_type}: {details}")
        try:
            from api.ws_manager import ws_manager
            import asyncio
            msg = {
                "type": "hardware_fallback",
                "hardware": hardware_type,
                "error": details,
                "timestamp": time.time()
            }
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    asyncio.create_task(ws_manager.broadcast_event(msg))
            except RuntimeError:
                pass
        except Exception:
            pass

    def _get_best_input_device_index(self):
        """
        Dynamically finds the best audio input device index (Microphone).
        Prioritizes user-specified env, default system input, or active mic array.
        Avoids hardcoding index=1 which breaks on different hardware setups.
        """
        env_idx = os.getenv("AUDIO_INPUT_INDEX")
        if env_idx is not None and env_idx.strip() != "":
            try:
                return int(env_idx)
            except ValueError:
                pass

        if not self.pa:
            return None

        # 1. Try PyAudio default input device
        try:
            default_dev = self.pa.get_default_input_device_info()
            if default_dev and default_dev.get("maxInputChannels", 0) > 0:
                dev_idx = int(default_dev.get("index", 0))
                dev_name = default_dev.get("name", "Default")
                log.info(f"[🎙️ Mic Discovery]: Using default system input device [{dev_idx}]: {dev_name}")
                return dev_idx
        except Exception as e:
            log.debug(f"Could not get default input device: {e}")

        # 2. Iterate host API 0 devices and find primary Microphone
        try:
            device_count = self.pa.get_device_count()
            fallback_idx = None
            for i in range(device_count):
                try:
                    info = self.pa.get_device_info_by_index(i)
                    if info.get("maxInputChannels", 0) > 0:
                        name = info.get("name", "").lower()
                        # Prefer physical microphone array / microphone over virtual mappers
                        if "microphone" in name or "mic" in name or "array" in name:
                            log.info(f"[🎙️ Mic Discovery]: Selected microphone [{i}]: {info.get('name')}")
                            return i
                        if fallback_idx is None:
                            fallback_idx = i
                except Exception:
                    continue
            if fallback_idx is not None:
                return fallback_idx
        except Exception as e:
            log.warning(f"Error enumerating input devices: {e}")

        return None


    def listen_for_wake_word(self) -> bool:
        """Blocks until the wake word is detected."""
        time.sleep(0.05)
        if not self.wake_word_engine or not self.pa:
            # Fallback if Porcupine isn't setup - wait for PTT only
            print(f"\n[🎙️ JARVIS is sleeping... Press {self.ptt_hotkey.upper()} to wake]")
            t_start = time.perf_counter()
            while True:
                if self.has_keyboard:
                    import keyboard
                    if keyboard.is_pressed(self.ptt_hotkey):
                        print("\n[🔔 PTT Triggered!]")
                        self.last_metrics['wakeword_detection_latency'] = (time.perf_counter() - t_start) * 1000
                        return True
                time.sleep(0.1)

        t_start = time.perf_counter()
        audio_stream = None
        dev_idx = self._get_best_input_device_index()
        try:
            with self._audio_lock:
                stream_kwargs = {
                    "rate": 44100,
                    "channels": 1,
                    "format": pyaudio.paInt16,
                    "input": True,
                    "frames_per_buffer": 1411
                }
                if dev_idx is not None:
                    stream_kwargs["input_device_index"] = dev_idx

                try:
                    audio_stream = self.pa.open(**stream_kwargs)
                except Exception as stream_err:
                    log.warning(f"Failed to open wake word stream ({stream_err}). Resetting PyAudio instance.")
                    try:
                        self.pa.terminate()
                    except Exception:
                        pass
                    self.pa = pyaudio.PyAudio()
                    audio_stream = self.pa.open(**stream_kwargs)
                print(f"\n[🎙️ JARVIS is sleeping... Say '{self.wake_words[0]}' or press {self.ptt_hotkey.upper()} to wake]")

                import keyboard
                while True:
                    if self.has_keyboard and keyboard.is_pressed(self.ptt_hotkey):
                        print("\n[🔔 PTT Triggered!]")
                        self.last_metrics['wakeword_detection_latency'] = (time.perf_counter() - t_start) * 1000
                        return True

                    if self.wake_word_engine is not None:
                        pcm_44100 = audio_stream.read(1411, exception_on_overflow=False)
                        audio_data = np.frombuffer(pcm_44100, dtype=np.int16)
                        num_samples = self.wake_word_engine.frame_length
                        resampled = np.interp(
                            np.linspace(0, len(audio_data), num_samples, endpoint=False),
                            np.arange(len(audio_data)),
                            audio_data
                        ).astype(np.int16)
                        pcm = resampled.tolist()
                        keyword_index = self.wake_word_engine.process(pcm)

                        if keyword_index >= 0:
                            print("\n[🔔 Wake Word Detected!]")
                            self.last_metrics['wakeword_detection_latency'] = (time.perf_counter() - t_start) * 1000
                            return True
                    else:
                        # Offline wake word engine is not configured; rely on Push-to-Talk (F9)
                        time.sleep(0.1)
        except Exception as e:
            print(f"[⚠️ Wake Word Listening Error]: {e}")
            self._broadcast_hardware_fallback("audio_input", str(e))
            return False
        finally:
            if audio_stream:
                try:
                    audio_stream.close()
                except Exception:
                    pass

    def listen(self, wait_for_wake_word: bool = False, interrupt_event: threading.Event = None) -> str:
        """
        Listens until speech is detected, then records until silence via VAD.
        Returns the transcription.
        """
        if wait_for_wake_word:
            self.listen_for_wake_word()

        time.sleep(0.05)
        import pyaudio
        import torch
        
        if not self.pa:
            try:
                self.pa = pyaudio.PyAudio()
            except Exception as e:
                log.error(f"Cannot initialize PyAudio: {e}")
                self._broadcast_hardware_fallback("audio_input", str(e))
                return ""
        
        frames = []
        is_speaking = False
        silence_counter = 0
        stream = None
        
        import keyboard
        print("\n[🎙️ JARVIS is listening... Speak now]")
        
        dev_idx = self._get_best_input_device_index()
        try:
            with self._audio_lock:
                stream_kwargs = {
                    "format": pyaudio.paInt16,
                    "channels": 1,
                    "rate": 44100,
                    "input": True,
                    "frames_per_buffer": 1411
                }
                if dev_idx is not None:
                    stream_kwargs["input_device_index"] = dev_idx

                try:
                    stream = self.pa.open(**stream_kwargs)
                except Exception as stream_err:
                    log.warning(f"Failed to open recording stream ({stream_err}). Resetting PyAudio instance.")
                    try:
                        self.pa.terminate()
                    except Exception:
                        pass
                    self.pa = pyaudio.PyAudio()
                    stream = self.pa.open(**stream_kwargs)
                
                while True:
                    # Check for global interruption
                    if interrupt_event and interrupt_event.is_set():
                        return ""
                        
                    data_44100 = stream.read(1411, exception_on_overflow=False)
                    
                    # Resample dynamically from 44100 to 16000
                    audio_data = np.frombuffer(data_44100, dtype=np.int16)
                    num_samples = 512
                    resampled_audio = np.interp(
                        np.linspace(0, len(audio_data), num_samples, endpoint=False),
                        np.arange(len(audio_data)),
                        audio_data
                    ).astype(np.int16)
                    data = resampled_audio.tobytes()
                    
                    # Check Push-To-Talk
                    ptt_active = False
                    if self.has_keyboard and keyboard.is_pressed(self.ptt_hotkey):
                        ptt_active = True
                        
                    if self.has_vad:
                        audio_int16 = resampled_audio
                        audio_float32 = audio_int16.astype(np.float32) / 32768.0
                        vad_prob = self.vad_model(torch.from_numpy(audio_float32), 16000).item()
                    else:
                        vad_prob = 0.0 # fallback
                        
                    speech_detected = vad_prob > 0.45 or ptt_active
                    
                    if speech_detected:
                        if not is_speaking:
                            is_speaking = True
                            frames = [] # clear buffer
                        frames.append(data)
                        silence_counter = 0
                    elif is_speaking:
                        frames.append(data)
                        silence_counter += 1
                        # ~18 frames * 32ms = ~570ms silence for snappy response without cutting user off
                        if silence_counter > 18 and not ptt_active:
                            break

        except Exception as e:
            log.error(f"Error during audio recording: {e}")
            self._broadcast_hardware_fallback("audio_input", str(e))
            return ""
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            
        if len(frames) < 15:
            return ""
            
        # Transcribe with faster-whisper
        t0 = time.perf_counter()
        
        audio_data = b''.join(frames)
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        
        if self.stt_model:
            # Optimize Whisper with beam_size=1 and C++ level VAD filtering
            segments, info = self.stt_model.transcribe(audio_np, beam_size=1, vad_filter=True)
            text = "".join([segment.text for segment in segments]).strip()
        else:
            # Fallback to speech_recognition if faster-whisper is not available
            import speech_recognition as sr
            r = sr.Recognizer()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name
            
            with wave.open(temp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(self.pa.get_sample_size(pyaudio.paInt16))
                wf.setframerate(16000)
                wf.writeframes(audio_data)
            try:
                with sr.AudioFile(temp_path) as source:
                    audio = r.record(source)
                text = r.recognize_google(audio)
            except Exception:
                text = ""
            finally:
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass
            
        stt_ms = (time.perf_counter() - t0) * 1000
        self.last_metrics['vad_detect_to_stt_complete'] = stt_ms
        
        if text:
            print(f"USER (Voice): {text}")
            log.info(f"[PERF] STT: {stt_ms:.0f}ms | \"{text}\"")
            
        return text

    def speak(self, text: str, interrupt_event: Optional[threading.Event] = None) -> None:
        """
        Speaks a string of text directly via TTS.
        """
        if not text or not text.strip():
            return
        if interrupt_event is None:
            class DummyEvent:
                def is_set(self): return False
            interrupt_event = DummyEvent()
        self.speak_stream([text], interrupt_event)

    def speak_stream(self, text_generator, interrupt_event: threading.Event):
        """
        Streams text from the LLM directly to the audio output.
        """

        self._speaking = True
        try:
            if self.engine_type == "elevenlabs" and HAS_ELEVENLABS:
                self._speak_elevenlabs_stream(text_generator, interrupt_event)
            else:
                self._speak_edge_tts_stream(text_generator, interrupt_event)
        finally:
            self._speaking = False

    def _speak_elevenlabs_stream(self, text_generator, interrupt_event):
        el_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
        # ElevenLabs streaming using direct native playback
        audio_stream = el_client.generate(
            text=text_generator,
            voice="Adam",
            model="eleven_multilingual_v2",
            stream=True
        )
        
        # Accumulate all chunks of the stream
        audio_data = bytearray()
        try:
            for chunk in audio_stream:
                if interrupt_event.is_set():
                    break
                if chunk:
                    audio_data.extend(chunk)
        except Exception as e:
            error_log.error(f"ElevenLabs stream generation failed: {e}")
            return
            
        if audio_data and not interrupt_event.is_set():
            self._play_raw_audio(bytes(audio_data), "mp3", interrupt_event)

    def _play_raw_audio(self, audio_data: bytes, format: str = "mp3", interrupt_event = None) -> None:
        """
        Plays raw audio bytes natively in Python.
        First tries pydub + PyAudio. Falls back to sounddevice. Lastly falls back to mpv.
        """
        if not audio_data:
            return
            
        if interrupt_event is None:
            class DummyEvent:
                def is_set(self): return False
            interrupt_event = DummyEvent()

        # 1. Primary: pydub + PyAudio (Active thread-safe hardware stream)
        try:
            import io
            from pydub import AudioSegment
            audio = AudioSegment.from_file(io.BytesIO(audio_data), format=format)
            
            with self._audio_lock:
                if not self.pa:
                    import pyaudio
                    self.pa = pyaudio.PyAudio()
                    
                out_stream = self.pa.open(
                    format=self.pa.get_format_from_width(audio.sample_width),
                    channels=audio.channels,
                    rate=audio.frame_rate,
                    output=True
                )
            
            chunk_size = 1024
            raw_pcm = audio.raw_data
            data_len = len(raw_pcm)
            
            self._speaking = True
            for i in range(0, data_len, chunk_size):
                if interrupt_event.is_set():
                    break
                chunk_bytes = raw_pcm[i:i+chunk_size]
                out_stream.write(chunk_bytes)
                
            out_stream.stop_stream()
            out_stream.close()
            self._speaking = False
            return
            
        except Exception as play_err:
            log.debug(f"Native PyAudio playback failed ({play_err}). Trying sounddevice.")
            
        # 2. Fallback: pydub + sounddevice
        try:
            import io
            from pydub import AudioSegment
            import sounddevice as sd
            import numpy as np
            
            audio = AudioSegment.from_file(io.BytesIO(audio_data), format=format)
            samples = np.array(audio.get_array_of_samples())
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
                
            sd.play(samples, samplerate=audio.frame_rate)
            
            total_sleep = len(samples) / audio.frame_rate
            sleep_step = 0.05
            slept = 0.0
            
            self._speaking = True
            while slept < total_sleep:
                if interrupt_event.is_set():
                    sd.stop()
                    break
                time.sleep(sleep_step)
                slept += sleep_step
            self._speaking = False
            return
        except Exception as sd_err:
            log.debug(f"Sounddevice fallback failed ({sd_err}). Trying external mpv fallback.")

        # 3. Fallback: Spawning external mpv (compatibility layer)
        try:
            process = subprocess.Popen(
                ["mpv", "--no-cache", "--no-terminal", "--", "fd://0"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            process.stdin.write(audio_data)
            process.stdin.flush()
            process.stdin.close()
            
            self._speaking = True
            while process.poll() is None:
                if interrupt_event.is_set():
                    try:
                        subprocess.run(f"taskkill /F /T /PID {process.pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        process.terminate()
                    break
                time.sleep(0.05)
            self._speaking = False
            return
        except Exception as mpv_err:
            log.error(f"All audio playback pipelines failed: {mpv_err}")
            self._broadcast_hardware_fallback("audio_output", f"All audio pipelines failed: {mpv_err}")

    def _speak_edge_tts_stream(self, text_generator, interrupt_event):
        """
        Edge-TTS streaming playback using native edge-tts async generator.
        Runs the async event loop to stream chunks from the API.
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._async_speak_edge_tts(text_generator, interrupt_event), loop
            )
            future.result()
        else:
            loop.run_until_complete(self._async_speak_edge_tts(text_generator, interrupt_event))

    async def _async_speak_edge_tts(self, text_generator, interrupt_event):
        voice = "en-US-AriaNeural"
        if self.profile == "Jarvis Classic":
            voice = "en-GB-RyanNeural"
        elif self.profile == "Female Assistant":
            voice = "en-US-JennyNeural"
        elif self.profile == "Professional":
            voice = "en-US-GuyNeural"
        elif self.profile == "Minimal":
            voice = "en-US-AnaNeural"

        buffer = ""
        try:
            is_async_gen = hasattr(text_generator, "__anext__")

            if is_async_gen:
                async for chunk in text_generator:
                    if interrupt_event.is_set():
                        break
                    buffer += chunk
                    if any(p in buffer for p in ['. ', '! ', '? ', '\n']):
                        await self._play_sentence_audio(buffer.strip(), voice, interrupt_event)
                        buffer = ""
            else:
                for chunk in text_generator:
                    if interrupt_event.is_set():
                        break
                    buffer += chunk
                    if any(p in buffer for p in ['. ', '! ', '? ', '\n']):
                        await self._play_sentence_audio(buffer.strip(), voice, interrupt_event)
                        buffer = ""

            if buffer.strip() and not interrupt_event.is_set():
                await self._play_sentence_audio(buffer.strip(), voice, interrupt_event)

        except Exception as e:
            error_log.error(f"[🎙️ Voice TTS Stream Error]: {e}")

    async def _play_sentence_audio(self, sentence: str, voice: str, interrupt_event):
        if not sentence:
            return
        print(f"JARVIS: {sentence}")
        
        audio_data = bytearray()
        try:
            import edge_tts
            communicate = edge_tts.Communicate(sentence, voice)
            async for chunk in communicate.stream():
                if interrupt_event.is_set():
                    break
                if chunk["type"] == "audio":
                    audio_data.extend(chunk["data"])
        except Exception as e:
            error_log.error(f"[🎙️ Voice TTS Chunk Error]: {e}")
            return
            
        if audio_data and not interrupt_event.is_set():
            loop = asyncio.get_running_loop()
            # Play natively in background executor thread so the FastAPI async loop remains unblocked
            await loop.run_in_executor(None, self._play_raw_audio, bytes(audio_data), "mp3", interrupt_event)

    def cleanup(self):
        if self.wake_word_engine:
            try:
                self.wake_word_engine.delete()
            except Exception:
                pass
        if self.pa:
            try:
                self.pa.terminate()
            except Exception:
                pass