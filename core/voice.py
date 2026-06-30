"""
JARVIS Voice Interface (Phase 1 V2)
Handles streaming speech-to-text (STT), text-to-speech (TTS), and wake word detection.

Upgrades:
  - faster-whisper for fast local transcription
  - silero-vad for instant end-of-speech detection
  - edge-tts / elevenlabs streaming playback
  - Push-to-Talk (PTT) support
  - Interruption (Barge-in) support
"""

import os
import re
import threading
import time
import struct
import numpy as np
import subprocess
import asyncio

from core.logger import log, error_log
from core.config import get_voice_engine, get_voice_profile, get_wake_words

HAS_FASTER_WHISPER = False
try:
    from faster_whisper import WhisperModel
    HAS_FASTER_WHISPER = True
except ImportError:
    pass

HAS_PORCUPINE = False
try:
    import pvporcupine
    import pyaudio
    HAS_PORCUPINE = True
except ImportError:
    pass

HAS_ELEVENLABS = False
try:
    from elevenlabs.client import ElevenLabs
    HAS_ELEVENLABS = True
except ImportError:
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
            self.stt_model = WhisperModel("small", device="cpu", compute_type="int8")
            log.info("[🎙️ STT]: faster-whisper loaded.")
        else:
            log.warning("[⚠️ STT]: faster-whisper not installed.")
            self.stt_model = None

        # 3. Setup Wake Word (Porcupine fallback)
        self.porcupine_api_key = os.getenv("PICOVOICE_API_KEY") or os.getenv("PORCUPINE_ACCESS_KEY")
        self.wake_word_engine = None
        self.pa = pyaudio.PyAudio() if HAS_PORCUPINE else None
        
        if HAS_PORCUPINE and self.porcupine_api_key:
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
        self._speaking = False

    def listen_for_wake_word(self) -> bool:
        """Blocks until the wake word is detected."""
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
        try:
            audio_stream = self.pa.open(
                rate=self.wake_word_engine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.wake_word_engine.frame_length
            )
            print(f"\n[🎙️ JARVIS is sleeping... Say '{self.wake_words[0]}' or press {self.ptt_hotkey.upper()} to wake]")

            import keyboard
            while True:
                if self.has_keyboard and keyboard.is_pressed(self.ptt_hotkey):
                    print("\n[🔔 PTT Triggered!]")
                    self.last_metrics['wakeword_detection_latency'] = (time.perf_counter() - t_start) * 1000
                    return True

                pcm = audio_stream.read(self.wake_word_engine.frame_length, exception_on_overflow=False)
                pcm = struct.unpack_from("h" * self.wake_word_engine.frame_length, pcm)
                keyword_index = self.wake_word_engine.process(pcm)

                if keyword_index >= 0:
                    print("\n[🔔 Wake Word Detected!]")
                    self.last_metrics['wakeword_detection_latency'] = (time.perf_counter() - t_start) * 1000
                    return True
        except Exception as e:
            print(f"[⚠️ Wake Word Listening Error]: {e}")
            return False
        finally:
            if audio_stream:
                audio_stream.close()

    def listen(self, wait_for_wake_word: bool = False, interrupt_event: threading.Event = None) -> str:
        """
        Listens until speech is detected, then records until silence via VAD.
        Returns the transcription.
        """
        if wait_for_wake_word:
            self.listen_for_wake_word()

        import pyaudio
        import torch
        
        pa = pyaudio.PyAudio()
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=512)
        
        frames = []
        is_speaking = False
        silence_counter = 0
        
        import keyboard
        print("\n[🎙️ JARVIS is listening... Speak now]")
        
        try:
            while True:
                # Check for global interruption
                if interrupt_event and interrupt_event.is_set():
                    return ""
                    
                data = stream.read(512, exception_on_overflow=False)
                
                # Check Push-To-Talk
                ptt_active = False
                if self.has_keyboard and keyboard.is_pressed(self.ptt_hotkey):
                    ptt_active = True
                    
                if self.has_vad:
                    audio_int16 = np.frombuffer(data, dtype=np.int16)
                    audio_float32 = audio_int16.astype(np.float32) / 32768.0
                    vad_prob = self.vad_model(torch.from_numpy(audio_float32), 16000).item()
                else:
                    vad_prob = 0.0 # fallback
                    
                speech_detected = vad_prob > 0.5 or ptt_active
                
                if speech_detected:
                    if not is_speaking:
                        is_speaking = True
                        frames = [] # clear buffer
                    frames.append(data)
                    silence_counter = 0
                elif is_speaking:
                    frames.append(data)
                    silence_counter += 1
                    # 16000 rate / 512 frames = 31.25 buffers per second
                    # 1.0 seconds of silence = 31 buffers
                    if silence_counter > 30 and not ptt_active:
                        break
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
            
        if len(frames) < 15:
            return ""
            
        # Transcribe with faster-whisper
        t0 = time.perf_counter()
        
        audio_data = b''.join(frames)
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        
        if self.stt_model:
            segments, info = self.stt_model.transcribe(audio_np, beam_size=5)
            text = "".join([segment.text for segment in segments]).strip()
        else:
            # Fallback to normal speech_recognition if faster-whisper not available
            import speech_recognition as sr
            r = sr.Recognizer()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name
            import wave
            with wave.open(temp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
                wf.setframerate(16000)
                wf.writeframes(audio_data)
            try:
                with sr.AudioFile(temp_path) as source:
                    audio = r.record(source)
                text = r.recognize_google(audio)
            except Exception:
                text = ""
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            
        stt_ms = (time.perf_counter() - t0) * 1000
        self.last_metrics['vad_detect_to_stt_complete'] = stt_ms
        
        if text:
            print(f"USER (Voice): {text}")
            log.info(f"[PERF] STT: {stt_ms:.0f}ms | \"{text}\"")
            
        return text

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
        
        # ElevenLabs streaming using direct playback via subprocess
        # We buffer to mpv to ensure it plays immediately while generating
        audio_stream = el_client.generate(
            text=text_generator,
            voice="Adam",
            model="eleven_multilingual_v2",
            stream=True
        )
        
        process = subprocess.Popen(
            ["mpv", "--no-cache", "--no-terminal", "--", "fd://0"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        
        try:
            for chunk in audio_stream:
                if interrupt_event.is_set():
                    break
                if chunk:
                    process.stdin.write(chunk)
                    process.stdin.flush()
        except Exception as e:
            pass
        finally:
            process.stdin.close()
            process.terminate()

    def _speak_edge_tts_stream(self, text_generator, interrupt_event):
        """
        Edge-TTS streaming playback. Buffers sentences and plays them sequentially.
        """
        buffer = ""
        for chunk in text_generator:
            if interrupt_event.is_set():
                break
            buffer += chunk
            if any(p in buffer for p in ['. ', '! ', '? ', '\n']):
                self._play_edge_sentence(buffer.strip(), interrupt_event)
                buffer = ""
        
        if buffer.strip() and not interrupt_event.is_set():
            self._play_edge_sentence(buffer.strip(), interrupt_event)

    def _play_edge_sentence(self, sentence: str, interrupt_event):
        if not sentence: return
        
        print(f"JARVIS: {sentence}")
        
        # Resolve voice profile
        voice = "en-US-AriaNeural"
        if self.profile == "Jarvis Classic":
            voice = "en-GB-RyanNeural"
        elif self.profile == "Female Assistant":
            voice = "en-US-JennyNeural"
        elif self.profile == "Professional":
            voice = "en-US-GuyNeural"
        elif self.profile == "Minimal":
            voice = "en-US-AnaNeural"
            
        process = subprocess.Popen(
            f'edge-tts --voice {voice} --text "{sentence}" --play',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        while process.poll() is None:
            if interrupt_event.is_set():
                # Force kill the edge-tts process and any child media players
                subprocess.run(f"taskkill /F /T /PID {process.pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            time.sleep(0.05)

    def cleanup(self):
        if self.wake_word_engine:
            self.wake_word_engine.delete()
        if self.pa:
            self.pa.terminate()