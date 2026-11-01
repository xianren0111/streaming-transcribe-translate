"""
Streaming Live Translation - Integrated platform for real-time transcription and translation.

Combines transcription/translation from Streaming project with multi-platform streaming support.
Follows the architecture of Simul Subtitle (https://github.com/KorenKrita/simul-subtitle).

MIT License

Copyright (c) 2026 KorenKrita
Copyright (c) 2026 Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin

log = logging.getLogger(__name__)


class Platform(Enum):
    """Supported streaming platforms."""
    YOUTUBE = "youtube"
    BILIBILI = "bilibili"
    MISSEVAN = "missevan"


class SessionStatus(Enum):
    """Session lifecycle states."""
    IDLE = "idle"
    INITIALIZING = "initializing"
    CAPTURING = "capturing"
    TRANSCRIBING = "transcribing"
    TRANSLATING = "translating"
    SENDING = "sending"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class TranscriptionResult:
    """Output from transcription module."""
    text: str
    language: str
    confidence: float
    timestamp: float
    is_partial: bool = False


@dataclass
class TranslationResult:
    """Output from translation module."""
    original_text: str
    translated_text: str
    source_language: str
    target_language: str
    timestamp: float


@dataclass
class SessionConfig:
    """Configuration for a translation session."""
    platform: Platform
    stream_url: str
    room_id: str
    source_language: str = "ja"  # Japanese
    target_language: str = "zh-CN"  # Simplified Chinese
    
    # Optional
    youtube_api_key: Optional[str] = None
    bilibili_cookies: Optional[dict] = None
    missevan_cookies: Optional[dict] = None
    
    # Transcription settings
    whisper_model_size: str = "base"  # tiny, base, small
    segment_duration: int = 8  # seconds
    
    # Translation settings
    openai_api_base: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4"
    
    # Message formatting
    prefix: str = "[转译]"  # "[Translation]"
    include_original: bool = False
    max_message_length: int = 500
    
    # Other
    debug: bool = False
    dry_run: bool = False  # Don't actually send messages


@dataclass
class SessionMetrics:
    """Metrics for monitoring session performance."""
    start_time: float = field(default_factory=time.time)
    audio_chunks_received: int = 0
    transcriptions_completed: int = 0
    translations_completed: int = 0
    messages_sent: int = 0
    errors: int = 0
    last_transcript: str = ""
    last_translation: str = ""
    avg_transcription_latency_ms: float = 0.0
    avg_translation_latency_ms: float = 0.0
    
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time
    
    def to_dict(self) -> dict:
        return {
            "uptime_seconds": self.uptime_seconds(),
            "audio_chunks": self.audio_chunks_received,
            "transcriptions": self.transcriptions_completed,
            "translations": self.translations_completed,
            "messages_sent": self.messages_sent,
            "errors": self.errors,
            "avg_transcription_latency_ms": self.avg_transcription_latency_ms,
            "avg_translation_latency_ms": self.avg_translation_latency_ms,
        }


class AudioStreamCapture:
    """Captures audio from streaming platform sources."""
    
    def __init__(self, config: SessionConfig):
        self.config = config
        self.audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self.process: Optional[subprocess.Popen] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        
    def _get_audio_url(self) -> str:
        """Resolve stream URL to audio-only URL based on platform."""
        if self.config.platform == Platform.YOUTUBE:
            return self._youtube_audio_url()
        elif self.config.platform == Platform.BILIBILI:
            return self._bilibili_audio_url()
        elif self.config.platform == Platform.MISSEVAN:
            return self._missevan_audio_url()
        raise ValueError(f"Unsupported platform: {self.config.platform}")
    
    def _youtube_audio_url(self) -> str:
        """Extract audio URL from YouTube stream."""
        try:
            from src.transcription import resolve_youtube_audio_source
            result = resolve_youtube_audio_source(self.config.stream_url)
            return result["url"]
        except Exception as e:
            log.error(f"Failed to resolve YouTube audio: {e}")
            raise
    
    def _bilibili_audio_url(self) -> str:
        """Extract audio URL from Bilibili stream."""
        try:
            from src.transcription import extract_bilibili_audio_url
            # Room ID should be parseable from room_id or stream_url
            # This requires fetching room info first
            # Simplified - assumes stream_url is a Bilibili stream info
            return extract_bilibili_audio_url(json.loads(self.config.stream_url))
        except Exception as e:
            log.error(f"Failed to resolve Bilibili audio: {e}")
            raise
    
    def _missevan_audio_url(self) -> str:
        """Extract audio URL from Missevan stream."""
        # Missevan uses WebSocket, will need special handling
        # For now, return the stream URL
        return self.config.stream_url
    
    def start(self) -> None:
        """Start capturing audio in background thread."""
        if self.running:
            log.warning("Audio capture already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        log.info(f"Audio capture started for {self.config.platform.value}")
    
    def stop(self) -> None:
        """Stop capturing audio and wait for thread to finish."""
        if not self.running:
            return
        
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        
        if self.thread:
            self.thread.join(timeout=5)
        log.info("Audio capture stopped")
    
    def _capture_loop(self) -> None:
        """Background thread: continuously capture audio chunks."""
        try:
            audio_url = self._get_audio_url()
            
            # FFmpeg command to capture and segment audio
            # Convert to 16kHz mono PCM for faster-whisper
            cmd = [
                "ffmpeg",
                "-i", audio_url,
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                "-f", "s16",
                "-bufsize", "32k",
                "pipe:1",
            ]
            
            log.debug(f"FFmpeg command: {' '.join(cmd)}")
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=4096,
            )
            
            # Read audio in chunks
            chunk_size = 16000 * 2 * self.config.segment_duration  # 16kHz * 2 bytes * duration
            
            while self.running and self.process.poll() is None:
                try:
                    chunk = self.process.stdout.read(chunk_size)
                    if not chunk:
                        break
                    
                    self.audio_queue.put(chunk, timeout=1)
                except queue.Full:
                    log.warning("Audio queue full, dropping oldest chunk")
                    try:
                        self.audio_queue.get_nowait()
                        self.audio_queue.put(chunk, timeout=1)
                    except queue.Full:
                        pass
                except Exception as e:
                    log.error(f"Error reading audio: {e}")
                    break
            
            if self.process.stderr:
                stderr = self.process.stderr.read().decode("utf-8", errors="ignore")
                if "error" in stderr.lower():
                    log.warning(f"FFmpeg stderr: {stderr}")
        
        except Exception as e:
            log.error(f"Audio capture loop failed: {e}", exc_info=True)
    
    def get_audio_chunk(self, timeout: float = 1.0) -> Optional[bytes]:
        """Get next audio chunk, blocking up to timeout."""
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None


class TranscriptionEngine:
    """Handles speech-to-text using faster-whisper."""
    
    def __init__(self, config: SessionConfig):
        self.config = config
        self.model = None
        self._load_model()
    
    def _load_model(self) -> None:
        """Load Whisper model."""
        try:
            from faster_whisper import WhisperModel
            log.info(f"Loading Whisper model: {self.config.whisper_model_size}")
            self.model = WhisperModel(
                self.config.whisper_model_size,
                device="cuda" if self._has_gpu() else "cpu",
                compute_type="float16" if self._has_gpu() else "float32",
            )
            log.info("Whisper model loaded")
        except ImportError:
            log.error("faster-whisper not installed. Install with: pip install faster-whisper")
            raise
        except Exception as e:
            log.error(f"Failed to load Whisper model: {e}")
            raise
    
    @staticmethod
    def _has_gpu() -> bool:
        """Check if CUDA/GPU is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
    
    def transcribe(self, audio_bytes: bytes) -> Optional[TranscriptionResult]:
        """Transcribe audio bytes to text."""
        if not self.model:
            return None
        
        try:
            import io
            import numpy as np
            from scipy import signal
            
            # Convert bytes to numpy array
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Skip silence detection (optional)
            # ...
            
            start_time = time.time()
            segments, info = self.model.transcribe(
                audio_array,
                language=self._whisper_language_code(self.config.source_language),
                beam_size=5,
                best_of=5,
            )
            
            # Combine segments
            text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
            latency_ms = (time.time() - start_time) * 1000
            
            if not text:
                return None
            
            result = TranscriptionResult(
                text=text,
                language=info.language,
                confidence=0.95,  # Whisper doesn't provide per-segment confidence
                timestamp=time.time(),
            )
            
            log.debug(f"Transcribed: {text} (latency: {latency_ms:.0f}ms)")
            return result
        
        except Exception as e:
            log.error(f"Transcription failed: {e}", exc_info=True)
            return None
    
    @staticmethod
    def _whisper_language_code(lang: str) -> Optional[str]:
        """Convert language code to Whisper format."""
        mapping = {
            "ja": "ja",
            "en": "en",
            "zh": "zh",
            "zh-CN": "zh",
            "zh-TW": "zh",
            "ko": "ko",
        }
        return mapping.get(lang)


class TranslationEngine:
    """Handles text translation using Streaming project's translate module."""
    
    def __init__(self, config: SessionConfig):
        self.config = config
        self._setup_translation()
    
    def _setup_translation(self) -> None:
        """Initialize translation provider."""
        try:
            from src import translate as translate_module
            from src.config import TRANSLATION_PROVIDER
            
            log.info(f"Translation provider: {TRANSLATION_PROVIDER}")
            # The translate module handles provider selection automatically
        except Exception as e:
            log.error(f"Failed to setup translation: {e}")
    
    def translate(self, text: str) -> Optional[TranslationResult]:
        """Translate text to target language."""
        if not text.strip():
            return None
        
        try:
            from src import translate as translate_module
            
            start_time = time.time()
            
            # Get translation from the Streaming project's module
            # It returns (translated_text, source_language) or caches results
            translated, source_lang = translate_module.get_translation(
                text,
                self.config.target_language
            )
            
            if not translated:
                log.debug("Translation pending or failed")
                return None
            
            latency_ms = (time.time() - start_time) * 1000
            
            result = TranslationResult(
                original_text=text,
                translated_text=translated,
                source_language=source_lang or self.config.source_language,
                target_language=self.config.target_language,
                timestamp=time.time(),
            )
            
            log.debug(f"Translated: '{text}' -> '{translated}' (latency: {latency_ms:.0f}ms)")
            return result
        
        except Exception as e:
            log.error(f"Translation failed: {e}", exc_info=True)
            return None


class ChatMessageSender:
    """Sends translated messages to streaming platform chat."""
    
    def __init__(self, config: SessionConfig):
        self.config = config
        self.last_message_time = 0
        self.min_message_interval = 1  # seconds between messages
    
    def send(self, text: str, original_text: Optional[str] = None) -> bool:
        """Send message to streaming room, respecting rate limits."""
        if self.config.dry_run:
            log.info(f"[DRY RUN] Would send: {text}")
            return True
        
        # Rate limiting
        now = time.time()
        if now - self.last_message_time < self.min_message_interval:
            time.sleep(self.min_message_interval - (now - self.last_message_time))
        
        try:
            success = False
            
            if self.config.platform == Platform.YOUTUBE:
                success = self._send_youtube(text)
            elif self.config.platform == Platform.BILIBILI:
                success = self._send_bilibili(text)
            elif self.config.platform == Platform.MISSEVAN:
                success = self._send_missevan(text)
            
            if success:
                self.last_message_time = time.time()
                log.info(f"Message sent to {self.config.platform.value}: {text}")
            
            return success
        
        except Exception as e:
            log.error(f"Failed to send message: {e}", exc_info=True)
            return False
    
    def _send_youtube(self, text: str) -> bool:
        """Send message to YouTube live chat."""
        try:
            from src import youtube, youtube_web
            
            # Try direct API first, fallback to web
            if self.config.youtube_api_key:
                # Need live_chat_id - would require additional setup
                log.warning("YouTube API requires additional setup for live_chat_id")
            
            # Web method (no API key needed if logged in)
            success, msg = youtube_web.send_message(self.config.room_id, text)
            return success
        
        except Exception as e:
            log.error(f"YouTube send failed: {e}")
            return False
    
    def _send_bilibili(self, text: str) -> bool:
        """Send message to Bilibili live chat."""
        try:
            from src import bilibili
            
            # Requires authentication cookies
            if not bilibili.has_login_credentials():
                log.error("Bilibili requires login credentials")
                return False
            
            success, msg = bilibili.send_comment(self.config.room_id, text)
            return success
        
        except Exception as e:
            log.error(f"Bilibili send failed: {e}")
            return False
    
    def _send_missevan(self, text: str) -> bool:
        """Send message to Missevan live chat."""
        try:
            from src import missevan
            
            success, msg = missevan.send_message(self.config.room_id, text)
            return success
        
        except Exception as e:
            log.error(f"Missevan send failed: {e}")
            return False


class StreamingLiveTranslationSession:
    """Main session orchestrator - coordinates all components."""
    
    def __init__(self, config: SessionConfig):
        self.config = config
        self.status = SessionStatus.IDLE
        self.metrics = SessionMetrics()
        
        self.audio_capture = AudioStreamCapture(config)
        self.transcription = TranscriptionEngine(config)
        self.translation = TranslationEngine(config)
        self.chat_sender = ChatMessageSender(config)
        
        self.running = False
        self.process_thread: Optional[threading.Thread] = None
        
        # Deque for tracking recent transcriptions (for deduplication)
        self.recent_transcriptions: deque = deque(maxlen=10)
    
    def start(self) -> None:
        """Start the translation session."""
        if self.running:
            log.warning("Session already running")
            return
        
        log.info(f"Starting translation session: {self.config.platform.value} -> {self.config.room_id}")
        self.running = True
        self.status = SessionStatus.INITIALIZING
        self.metrics = SessionMetrics()
        
        self.audio_capture.start()
        
        self.process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self.process_thread.start()
        
        self.status = SessionStatus.CAPTURING
        log.info("Session started")
    
    def stop(self) -> None:
        """Stop the translation session."""
        if not self.running:
            return
        
        log.info("Stopping translation session")
        self.running = False
        self.status = SessionStatus.STOPPED
        
        self.audio_capture.stop()
        
        if self.process_thread:
            self.process_thread.join(timeout=5)
        
        log.info(f"Session stopped. Metrics: {self.metrics.to_dict()}")
    
    def pause(self) -> None:
        """Pause the session."""
        self.status = SessionStatus.PAUSED
        log.info("Session paused")
    
    def resume(self) -> None:
        """Resume from pause."""
        if self.status == SessionStatus.PAUSED:
            self.status = SessionStatus.CAPTURING
            log.info("Session resumed")
    
    def _process_loop(self) -> None:
        """Main processing loop: capture -> transcribe -> translate -> send."""
        while self.running:
            try:
                # Get audio chunk
                audio_chunk = self.audio_capture.get_audio_chunk(timeout=2.0)
                if not audio_chunk:
                    continue
                
                self.status = SessionStatus.TRANSCRIBING
                self.metrics.audio_chunks_received += 1
                
                # Transcribe
                transcript = self.transcription.transcribe(audio_chunk)
                if not transcript or not transcript.text.strip():
                    continue
                
                self.metrics.transcriptions_completed += 1
                self.metrics.last_transcript = transcript.text
                
                # Skip duplicate transcriptions
                if transcript.text in self.recent_transcriptions:
                    log.debug("Skipping duplicate transcription")
                    continue
                
                self.recent_transcriptions.append(transcript.text)
                
                # Translate
                self.status = SessionStatus.TRANSLATING
                translation = self.translation.translate(transcript.text)
                if not translation or not translation.translated_text.strip():
                    continue
                
                self.metrics.translations_completed += 1
                self.metrics.last_translation = translation.translated_text
                
                # Format message
                message = self._format_message(translation)
                if len(message) > self.config.max_message_length:
                    message = message[:self.config.max_message_length - 3] + "..."
                
                # Send to chat
                self.status = SessionStatus.SENDING
                success = self.chat_sender.send(message, transcript.text)
                if success:
                    self.metrics.messages_sent += 1
                else:
                    self.metrics.errors += 1
            
            except Exception as e:
                log.error(f"Process loop error: {e}", exc_info=True)
                self.metrics.errors += 1
                self.status = SessionStatus.ERROR
                time.sleep(1)  # Back off on error
    
    def _format_message(self, translation: TranslationResult) -> str:
        """Format translation result as chat message."""
        if self.config.include_original:
            return f"{self.config.prefix} {translation.original_text}\n→ {translation.translated_text}"
        else:
            return f"{self.config.prefix} {translation.translated_text}"
    
    def get_status(self) -> dict:
        """Get current session status and metrics."""
        return {
            "status": self.status.value,
            "running": self.running,
            "metrics": self.metrics.to_dict(),
            "platform": self.config.platform.value,
            "room_id": self.config.room_id,
        }


# Convenience function for quick setup
def create_session(
    platform: str,
    stream_url: str,
    room_id: str,
    target_language: str = "zh-CN",
) -> StreamingLiveTranslationSession:
    """Create a translation session with minimal config."""
    config = SessionConfig(
        platform=Platform[platform.upper()],
        stream_url=stream_url,
        room_id=room_id,
        target_language=target_language,
    )
    return StreamingLiveTranslationSession(config)
