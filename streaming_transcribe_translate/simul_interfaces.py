"""
Streaming Live Translation - Simul Subtitle-style interfaces.

Architecture inspired by Simul Subtitle (https://github.com/KorenKrita/simul-subtitle).
Defines the contract between components similar to Kotlin interfaces in the original.

MIT License

Copyright (c) 2026 KorenKrita
Copyright (c) 2026 Contributors
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any, Tuple
import logging

log = logging.getLogger(__name__)


# ============================================================================
# Enums and Data Classes (matching simul-subtitle's style)
# ============================================================================

class Lang(Enum):
    """Source language (speech audio)."""
    JA = "ja"  # Japanese
    EN = "en"  # English
    ZH = "zh"  # Chinese


class Target(Enum):
    """Target language (translation output)."""
    ZH_CN = "zh-CN"      # Simplified Chinese
    ZH_TW = "zh-TW"      # Traditional Chinese
    EN = "en"            # English
    JA = "ja"            # Japanese
    KO = "ko"            # Korean


class Platform(Enum):
    """Streaming platform."""
    YOUTUBE = "youtube"
    BILIBILI = "bilibili"
    MISSEVAN = "missevan"


@dataclass
class Timing:
    """Latency breakdown for a caption (matching simul-subtitle's Timing class)."""
    audio_ms: int          # Audio segment duration
    segment_wait_ms: int   # Segmenter: end-of-speech wait
    asr_queue_ms: int      # ASR queue time
    asr_ms: int            # ASR processing time
    mt_queue_ms: int       # MT (Machine Translation) queue time
    mt_ms: int             # MT processing time
    mt_done_ms: int        # Total time from audio end to MT finish
    check_ms: int = 0      # Jev (translation quality check) time


@dataclass
class Caption:
    """One caption line on screen (matching simul-subtitle's CaptionLine)."""
    segment_id: int
    revision: int
    is_final: bool
    original: str          # Source language (e.g., Japanese)
    translated: str        # Target language (e.g., Chinese)
    timing: Timing
    audio_end_at_ms: int = 0  # Capture timestamp
    time_estimated: bool = False
    audio_received_at_ms: int = 0
    target_language: str = ""
    speaker_id: int | None = None


@dataclass
class MtResult:
    """Translation result from the MT service."""
    text: str
    http_status: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None


# ============================================================================
# Core Service Interfaces (inspired by simul-subtitle's design)
# ============================================================================

class SessionPrefs(ABC):
    """Settings a session reads and needs to access.
    
    Similar to simul-subtitle's SessionPrefs interface - the contract
    between the session and platform-specific preferences.
    """
    
    @property
    @abstractmethod
    def show_original(self) -> bool:
        """Include original text in captions."""
        pass
    
    @property
    @abstractmethod
    def show_stats(self) -> bool:
        """Show timing statistics."""
        pass
    
    @property
    @abstractmethod
    def keep_log(self) -> bool:
        """Keep session log for debugging."""
        pass
    
    @property
    @abstractmethod
    def source_lang(self) -> Optional[Lang]:
        """Source language (None = auto-detect)."""
        pass
    
    @property
    @abstractmethod
    def target_lang(self) -> Target:
        """Target language for translation."""
        pass
    
    @property
    @abstractmethod
    def scene(self) -> str:
        """Scenario/context (e.g., 'VTuber', 'Gaming')."""
        pass
    
    @property
    @abstractmethod
    def whisper_model(self) -> str:
        """Whisper model size: 'tiny', 'base', 'small'."""
        pass

    @property
    @abstractmethod
    def translation_model(self) -> str:
        """Model name for the configured translation service."""
        pass

    @abstractmethod
    def get_translation_key(self, service: str) -> Optional[str]:
        """Get API key for translation service."""
        pass
    
    @abstractmethod
    def get_translation_base_url(self) -> Optional[str]:
        """Get base URL for OpenAI-compatible translation service."""
        pass


class AudioSource(ABC):
    """System audio input, 16 kHz mono.
    
    Similar to simul-subtitle's AudioSource - opened, read and closed
    by the session thread. Blocking interface.
    """
    
    @abstractmethod
    def read(self, frame: list[float]) -> int:
        """
        Fill frame with audio samples (blocking).
        
        Args:
            frame: Float array to fill with audio data
            
        Returns:
            Timestamp (ms) when last sample was captured, or -1 if cancelled/ended
        """
        pass
    
    @property
    @abstractmethod
    def estimated(self) -> bool:
        """Whether read timestamp is estimated (read time) vs actual capture time."""
        pass
    
    @abstractmethod
    def end_reason(self) -> Optional[str]:
        """Why audio ended (error message for user), or None if normal end."""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Session thread: release audio resources."""
        pass
    
    @abstractmethod
    def cancel(self) -> None:
        """Any thread: stop audio capture; read() returns -1 soon."""
        pass


class Asr(ABC):
    """Automatic Speech Recognition engine.
    
    Similar to simul-subtitle's Asr interface - local speech-to-text.
    """
    
    @abstractmethod
    def recognize(self, samples: list[float]) -> str:
        """
        Recognize speech from audio samples.
        
        Args:
            samples: 16kHz mono audio samples
            
        Returns:
            Recognized text
        """
        pass
    
    def recognize_timed(self, samples: list[float]) -> Tuple[str, Optional[List[Tuple[str, float]]]]:
        """
        Recognize with timing information.
        
        Returns:
            (text, [(piece_text, start_time_s), ...]) or (text, None) if no timing
        """
        return self.recognize(samples), None


class Mt(ABC):
    """Machine Translation service.
    
    Similar to simul-subtitle's Mt interface - translates complete prompts.
    """
    
    @abstractmethod
    def translate(self, prompt: str) -> Optional[MtResult]:
        """
        Translate text.
        
        Args:
            prompt: Text to translate (can include context)
            
        Returns:
            MtResult with translation or error, None if cancelled
        """
        pass
    
    @abstractmethod
    def cancel(self) -> None:
        """Cancel any in-flight translation request."""
        pass


class Judge(ABC):
    """Translation quality checker (Jev).
    
    Similar to simul-subtitle's Judge interface - verifies translations
    and can flag issues for retranslation.
    """
    
    @abstractmethod
    def check(self, original: str, translated: str) -> bool:
        """
        Check if translation is acceptable.
        
        Returns:
            True if translation is good, False if retranslation needed
        """
        pass
    
    def paused(self) -> bool:
        """Whether judge is paused (rate limited)."""
        return False
    
    def last_limit(self) -> Optional[float]:
        """When rate limit expires (seconds), if paused."""
        return None


class SpeechModels(ABC):
    """Speech recognition models (ASR + VAD).
    
    Similar to simul-subtitle's SpeechModels - encapsulates recognition
    and voice activity detection. Released when session ends.
    """
    
    @property
    @abstractmethod
    def asr(self) -> Asr:
        """ASR engine."""
        pass
    
    @abstractmethod
    def vad_prob(self, frame: list[float]) -> float:
        """
        Voice Activity Detection: probability that frame contains speech.
        
        Args:
            frame: Audio frame (typically 512 samples at 16kHz)
            
        Returns:
            Probability [0.0, 1.0]
        """
        pass
    
    @abstractmethod
    def release(self) -> None:
        """Release model resources."""
        pass


class SessionHost(ABC):
    """Platform host for a CaptionSession.
    
    Similar to simul-subtitle's SessionHost - the platform's contract to
    provide UI, audio, models, and logging services.
    """
    
    @property
    @abstractmethod
    def prefs(self) -> SessionPrefs:
        """User preferences."""
        pass
    
    @abstractmethod
    def post(self, runnable: Callable[[], None]) -> None:
        """Run callable on UI thread."""
        pass
    
    @abstractmethod
    def post_delayed(self, runnable: Callable[[], None], ms: int) -> Callable[[], None]:
        """
        Run callable on UI thread after delay.
        
        Returns:
            Cancellation callable
        """
        pass
    
    @abstractmethod
    def load_models(self, asr_threads: int = 1) -> SpeechModels:
        """
        Load ASR and VAD models (slow).
        
        Args:
            asr_threads: Number of parallel ASR threads
            
        Returns:
            Loaded models
        """
        pass
    
    @abstractmethod
    def open_audio(self) -> AudioSource:
        """
        Start system audio capture.
        
        Returns:
            Audio source interface
            
        Raises:
            RuntimeError: If audio cannot be opened
        """
        pass
    
    @abstractmethod
    def show(
        self,
        captions: List[Caption],
        stats: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Show captions on screen.
        
        Args:
            captions: List of recent caption lines
            stats: Optional timing statistics
            error: Optional error message
        """
        pass
    
    @abstractmethod
    def on_session_ended(self) -> None:
        """Session ended; captions remain until user closes."""
        pass
    
    @abstractmethod
    def on_session_finished(self) -> None:
        """Session ended with no output; auto-close."""
        pass


class Setup:
    """Translation setup for a segment (immutable).
    
    Similar to simul-subtitle's Setup - encapsulates translator, judge,
    and configuration that a segment uses from start to finish.
    """
    
    def __init__(
        self,
        mt: Mt,
        source: Optional[Lang] = Lang.JA,
        target: Target = Target.ZH_CN,
        judge: Optional[Judge] = None,
        scene: str = "general",
        previous_sentences: int = 0,
        version: int = 0,
    ):
        self.mt = mt
        self.source = source
        self.target = target
        self.judge = judge
        self.scene = scene
        self.previous_sentences = previous_sentences
        self.version = version


# ============================================================================
# Chat Integration Interfaces
# ============================================================================

class ChatSender(ABC):
    """Sends translated captions to platform chat.
    
    Extends simul-subtitle's model with multi-platform chat support.
    """
    
    @abstractmethod
    def send(self, message: str, original: Optional[str] = None) -> Tuple[bool, str]:
        """
        Send message to chat.
        
        Returns:
            (success, message or error)
        """
        pass
    
    @abstractmethod
    def can_send(self) -> bool:
        """Whether chat is available and authenticated."""
        pass


class SessionLog:
    """Logs session events for debugging and replay.
    
    Similar to simul-subtitle's SessionLog - structured logging
    for debugging and post-session analysis.
    """
    
    def __init__(self, path: Path):
        self.path = path
        self.entries: List[Dict[str, Any]] = []
    
    def add_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Log an event."""
        self.entries.append({
            "type": event_type,
            "time_ms": int(self.__class__._mono_ms()),
            **data,
        })
    
    def save(self) -> None:
        """Write log to file."""
        import json
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)
    
    @staticmethod
    def _mono_ms() -> float:
        """Monotonic milliseconds (like simul-subtitle's monoMs())."""
        import time
        return time.monotonic() * 1000


# ============================================================================
# Caption Board (visual state)
# ============================================================================

class CaptionBoard:
    """Holds the current captions displayed.
    
    Similar to simul-subtitle's CaptionBoard - maintains recent
    captions with configurable history limits.
    """
    
    def __init__(self, max_sentences: int = 10, max_chars: Optional[int] = 1000):
        self.max_sentences = max_sentences
        self.max_chars = max_chars
        self.captions: List[Caption] = []
    
    def add(self, caption: Caption) -> None:
        """Add or update a caption."""
        # Update existing segment or add new
        for i, c in enumerate(self.captions):
            if (c.segment_id, c.target_language) == (caption.segment_id, caption.target_language):
                self.captions[i] = caption
                return
        self.captions.append(caption)
        self._trim()
    
    def _trim(self) -> None:
        """Remove old captions beyond limits."""
        while len(self.captions) > self.max_sentences:
            self.captions.pop(0)
        
        total_chars = sum(len(c.translated) for c in self.captions)
        while self.max_chars is not None and total_chars > self.max_chars and self.captions:
            total_chars -= len(self.captions[0].translated)
            self.captions.pop(0)
    
    def get_display_captions(self, limit: int = 3) -> List[Caption]:
        """Get the most recent captions for display."""
        return self.captions[-limit:] if self.captions else []
