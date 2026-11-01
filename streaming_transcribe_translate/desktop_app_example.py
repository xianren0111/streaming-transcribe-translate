"""
Desktop Implementation Example - PySide6 GUI for Streaming Live Translation.

Implements SessionHost interface for desktop deployment.
Shows how to integrate with simul_interfaces and caption_session.

MIT License (inherited from Simul Subtitle)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from .simul_interfaces import (
    SessionHost, SessionPrefs, Caption, Lang, Target, ChatSender,
    SpeechModels, AudioSource,
)
from .caption_session import CaptionSession
from .subtitle_records import CaptionRecord, SessionRecords
from .subtitle_settings import SubtitleSettings
from .paths import ROOT, LOG_FILE, LOGS_ROOT
from .platforms import missevan_room_id
from .simul_streaming_adapter import (
    StreamingSpeechModels, StreamingProjectTranslator, SystemAudioSource,
    StreamAudioSource, MicrophoneAudioSource,
    BilibiliChatSender, YouTubeChatSender, MissevanChatSender,
)

log = logging.getLogger(__name__)


# ============================================================================
# Configuration & Preferences
# ============================================================================

class DesktopSessionPrefs(SessionPrefs):
    """Desktop application preferences."""
    
    def __init__(self):
        self._show_original = True
        self._show_stats = True
        self._keep_log = True
        self._source_lang = Lang.JA
        self._target_lang = Target.ZH_CN
        self._scene = "vtuber"
        self._whisper_model = "base"
        self._translation_model = "gpt-4o-mini"
        self._api_keys: Dict[str, str] = {}
        self._translation_url: Optional[str] = None
        self.subtitle_settings = SubtitleSettings()
    
    @property
    def show_original(self) -> bool:
        return self._show_original
    
    @property
    def show_stats(self) -> bool:
        return self._show_stats
    
    @property
    def keep_log(self) -> bool:
        return self._keep_log
    
    @property
    def source_lang(self) -> Optional[Lang]:
        return self._source_lang
    
    @property
    def target_lang(self) -> Target:
        return self._target_lang

    @property
    def target_langs(self) -> tuple[Target, ...]:
        return tuple(Target(code) for code in self.subtitle_settings.reading_languages) or (self.target_lang,)
    
    @property
    def scene(self) -> str:
        return self._scene
    
    @property
    def whisper_model(self) -> str:
        return self._whisper_model

    @property
    def translation_model(self) -> str:
        return self._translation_model
    
    def get_translation_key(self, service: str) -> Optional[str]:
        return self._api_keys.get(service)
    
    def get_translation_base_url(self) -> Optional[str]:
        return self._translation_url
    
    def load_from_dict(self, config: Dict[str, Any]) -> None:
        """Load preferences from configuration dict."""
        self._show_original = config.get("show_original", True)
        self._show_stats = config.get("show_stats", True)
        self._keep_log = config.get("keep_log", True)
        
        source = config.get("source_language", "ja")
        self._source_lang = Lang(source) if source else None
        
        target = config.get("target_language", "zh-CN")
        self._target_lang = Target(target) if target else Target.ZH_CN
        
        self._scene = config.get("scene", "vtuber")
        self._whisper_model = config.get("whisper_model", "base")
        self._translation_model = config.get("translation_model", "gpt-4o-mini")
        self._api_keys = config.get("api_keys", {})
        self._translation_url = config.get("translation_base_url")
        if "subtitle_settings" in config:
            self.subtitle_settings = config["subtitle_settings"]


class DesktopSessionHost(SessionHost):
    """
    Desktop UI host for caption sessions.
    
    Implements SessionHost interface for PySide6/Tkinter desktop apps.
    Manages UI thread communication, audio capture, and model loading.
    """
    
    def __init__(self, prefs: Optional[DesktopSessionPrefs] = None):
        self._prefs = prefs or DesktopSessionPrefs()
        self._ui_callback: Optional[Callable] = None
        self._ui_thread_id: Optional[int] = None
        self._pending_tasks: List[Callable] = []
        self._running = False
        self._audio_source_factory: Optional[Callable[[], AudioSource]] = None
        self._caption_callback: Optional[
            Callable[[List[Dict[str, Any]], Optional[str]], None]
        ] = None
        self._chat_review_callback: Optional[
            Callable[[str, Optional[ChatSender], str, Optional[CaptionRecord]], None]
        ] = None
        self._chat_status_callback: Optional[Callable[[bool, str], None]] = None
        self._transcription_callback: Optional[Callable[[int, str, bool, int], None]] = None
        self.records: Optional[SessionRecords] = None
        self._notice_callback: Optional[Callable[[str], None]] = None
    
    @property
    def prefs(self) -> SessionPrefs:
        return self._prefs
    
    def set_ui_callback(self, callback: Callable) -> None:
        """
        Set callback for UI updates (e.g., Qt signal emitter).
        
        Callback should accept (captions: List[Caption], stats: Dict, error: str)
        """
        self._ui_callback = callback
    
    def post(self, runnable: Callable[[], None]) -> None:
        """Run on UI thread."""
        if self._ui_callback:
            self._ui_callback(runnable)
        else:
            # Fallback: run immediately
            try:
                runnable()
            except Exception as e:
                log.error(f"UI runnable failed: {e}")
    
    def post_delayed(self, runnable: Callable[[], None], ms: int) -> Callable[[], None]:
        """Run on UI thread after delay."""
        import threading
        
        timer = threading.Timer(ms / 1000, lambda: self.post(runnable))
        timer.start()
        return timer.cancel
    
    def load_models(self, asr_threads: int = 1) -> SpeechModels:
        """Load speech models."""
        log.info("Loading speech models...")
        from .reazon_asr import create_asr

        language = self._prefs.source_lang.value if self._prefs.source_lang else None
        models = StreamingSpeechModels(asr=create_asr(language))
        log.info("Speech models loaded")
        return models
    
    def open_audio(self) -> Any:
        """Open configured audio input, falling back to system audio."""
        log.info("Opening audio...")
        audio = (
            self._audio_source_factory()
            if self._audio_source_factory
            else SystemAudioSource(platform="windows")
        )
        log.info("Audio opened")
        return audio

    def set_audio_source_factory(self, factory: Callable[[], AudioSource]) -> None:
        """Set a factory so each session receives a fresh audio source."""
        self._audio_source_factory = factory

    def set_caption_callback(
        self,
        callback: Callable[[List[Dict[str, Any]], Optional[str]], None],
    ) -> None:
        """Receive caption and session-error updates on the host's UI thread."""
        self._caption_callback = callback

    def set_chat_review_callback(
        self, callback: Callable[[str, Optional[ChatSender], str, Optional[CaptionRecord]], None]
    ) -> None:
        self._chat_review_callback = callback

    def set_chat_status_callback(
        self, callback: Callable[[bool, str], None]
    ) -> None:
        self._chat_status_callback = callback

    def queue_chat_review(
        self, message: str, sender: Optional[ChatSender], original: str = "",
        record: Optional[CaptionRecord] = None,
    ) -> None:
        if self._chat_review_callback:
            self._chat_review_callback(message, sender, original, record)

    def set_notice_callback(self, callback: Callable[[str], None]) -> None:
        self._notice_callback = callback

    def notice(self, message: str) -> None:
        log.warning("%s", message)
        if self._notice_callback:
            self.post(lambda: self._notice_callback(message))

    def set_transcription_callback(
        self, callback: Callable[[int, str, bool, int], None]
    ) -> None:
        self._transcription_callback = callback

    def show_transcription(
        self, segment_id: int, text: str, is_final: bool, latency_ms: int
    ) -> None:
        if self._transcription_callback:
            self._transcription_callback(segment_id, text, is_final, latency_ms)

    def report_chat_status(self, success: bool, message: str) -> None:
        if self._chat_status_callback:
            self.post(lambda: self._chat_status_callback(success, message))
    
    def show(
        self,
        captions: List[Caption],
        stats: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Display captions."""
        caption_data = [
            {
                "segment_id": c.segment_id,
                "target_language": c.target_language,
                "original": c.original,
                "translated": (f"[Speaker {c.speaker_id}] " if c.speaker_id else "") + c.translated,
                "speaker_id": c.speaker_id,
                "is_final": c.is_final,
                "received_at_ms": c.audio_received_at_ms,
                "timing": {
                    "asr_ms": c.timing.asr_ms,
                    "mt_ms": c.timing.mt_ms,
                    "total_ms": c.timing.mt_done_ms,
                },
            }
            for c in captions
        ]
        
        if error:
            log.error("Session error: %s", error)
        if self._caption_callback:
            self._caption_callback(caption_data, error)
    
    def on_session_ended(self) -> None:
        """Session ended."""
        log.info("Session ended")
    
    def on_session_finished(self) -> None:
        """Session finished without output."""
        log.info("Session finished")


# ============================================================================
# Desktop Application Example
# ============================================================================

class StreamingLiveTranslationApp:
    """Main application class."""
    
    def __init__(self):
        self.prefs = DesktopSessionPrefs()
        self.host = DesktopSessionHost(self.prefs)
        self.session: Optional[CaptionSession] = None
        self.chat_sender: Optional[ChatSender] = None
        self.chat_mode = "off"
        self._setup_logging()

    def configure_youtube(
        self, video_id: str, cookies: Optional[Dict[str, str]] = None
    ) -> None:
        """Configure the legacy YouTube chat integration."""
        self.chat_mode = "automatic"
        self.chat_sender = YouTubeChatSender(
            video_id, cookies, status_callback=self.host.report_chat_status
        )

    def configure_bilibili(
        self, room_id: str, cookies: Optional[Dict[str, str]] = None
    ) -> None:
        """Configure the legacy Bilibili chat integration."""
        self.chat_mode = "automatic"
        self.chat_sender = BilibiliChatSender(
            room_id, cookies, status_callback=self.host.report_chat_status
        )
    
    def _setup_logging(self) -> None:
        """Configure logging."""
        LOGS_ROOT.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            handlers=[
                logging.FileHandler(LOG_FILE, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )
    
    def configure_bilibili_stream(
        self,
        room_id: str,
        cookies: Optional[Dict[str, str]] = None,
        chat_mode: str = "off",
    ) -> None:
        """Configure Bilibili stream audio and optional authenticated chat."""
        room_id = room_id.strip().rstrip("/").rsplit("/", 1)[-1]
        if not room_id.isdecimal():
            raise ValueError("Bilibili room ID must be numeric")

        stream_url = f"https://live.bilibili.com/{room_id}"
        self.host.set_audio_source_factory(
            lambda: StreamAudioSource(stream_url, platform="bilibili")
        )
        self.chat_mode = chat_mode
        self.chat_sender = (
            BilibiliChatSender(
                room_id, cookies, status_callback=self.host.report_chat_status
            )
            if chat_mode != "off" and cookies
            else None
        )

    def configure_youtube_stream(
        self,
        stream_url: str,
        video_id: str,
        cookies: Optional[Dict[str, str]] = None,
        chat_mode: str = "off",
        page_id: str = "",
    ) -> None:
        """Configure YouTube stream audio and optional authenticated chat."""
        self.host.set_audio_source_factory(
            lambda: StreamAudioSource(stream_url, platform="youtube")
        )
        self.chat_mode = chat_mode
        self.chat_sender = (
            YouTubeChatSender(
                video_id, cookies, status_callback=self.host.report_chat_status, page_id=page_id
            )
            if chat_mode != "off" and cookies
            else None
        )
    
    def configure_missevan(
        self, room_id: str, cookies: Optional[Dict[str, str]] = None,
    ) -> None:
        """Configure the legacy Missevan chat integration with explicit cookies."""
        self.chat_sender = MissevanChatSender(
            missevan_room_id(room_id), cookies, status_callback=self.host.report_chat_status
        )
        self.chat_mode = "automatic"

    def configure_missevan_stream(
        self, room_url: str, cookies: Optional[Dict[str, str]] = None,
        chat_mode: str = "off",
    ) -> None:
        room_id = missevan_room_id(room_url)
        self.host.set_audio_source_factory(
            lambda: StreamAudioSource(f"https://fm.missevan.com/live/{room_id}", platform="missevan")
        )
        self.chat_mode = chat_mode
        self.chat_sender = (
            MissevanChatSender(room_id, cookies, status_callback=self.host.report_chat_status)
            if chat_mode != "off" and cookies else None
        )

    def configure_microphone(self, device: Optional[int] = None) -> None:
        """Use microphone audio, preserving any explicitly configured chat sender."""
        self.host.set_audio_source_factory(lambda: MicrophoneAudioSource(device))

    def configure_system_audio(self) -> None:
        """Capture what the default playback device plays (WASAPI loopback)."""
        from .system_audio import LoopbackAudioSource

        self.host.set_audio_source_factory(LoopbackAudioSource)
    
    def set_preferences(self, config: Dict[str, Any]) -> None:
        """Load preferences."""
        self.prefs.load_from_dict(config)
    
    def start_session(self) -> None:
        """Start translation session."""
        if self.session and self.session.running:
            log.warning("Session already running")
            return
        
        log.info("Starting session...")
        self.session = CaptionSession(self.host, self.chat_sender, self.chat_mode)
        self.session.start()
    
    def stop_session(self) -> None:
        """Stop translation session."""
        if not self.session:
            return
        
        log.info("Stopping session...")
        self.session.stop()
        self.session = None
    
    def is_running(self) -> bool:
        """Check if session is active."""
        return self.session is not None and self.session.running


# ============================================================================
# Quick Start Examples
# ============================================================================

def example_youtube():
    """Example: YouTube live translation."""
    app = StreamingLiveTranslationApp()
    
    # Configure
    app.set_preferences({
        "source_language": "ja",
        "target_language": "zh-CN",
        "whisper_model": "base",
        "show_original": True,
        "show_stats": True,
    })
    
    # Set YouTube room
    app.configure_youtube("video_id_here")
    
    # Start
    app.start_session()
    
    # Keep running...
    try:
        import time
        while app.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        app.stop_session()


def example_bilibili():
    """Example: Bilibili live translation."""
    app = StreamingLiveTranslationApp()
    
    app.set_preferences({
        "source_language": "en",
        "target_language": "zh-CN",
        "whisper_model": "small",
    })
    
    app.configure_bilibili("12345678")  # Room ID
    app.start_session()
    
    try:
        import time
        while app.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop_session()


# ============================================================================
# CLI Integration with desktop_app.py style
# ============================================================================

def desktop_app_integration():
    """
    Integration point with E:\\Workspaces\\Streaming\\desktop_app.py
    
    Shows how to extend the existing desktop_app with translation features.
    """
    
    # This would integrate with the existing PySide6 desktop app
    # The StreamingLiveTranslationApp becomes a "worker" component
    # with the desktop_app.py providing the UI layer.
    
    app = StreamingLiveTranslationApp()
    
    # Read from existing streaming config
    from pathlib import Path
    config_path = ROOT / ".env"
    
    if config_path.exists():
        import dotenv
        config = dotenv.dotenv_values(config_path)
        from .secret_store import load_secrets
        secrets, _failed = load_secrets(config_path, config)
        
        app.set_preferences({
            "source_language": config.get("SOURCE_LANGUAGE", "ja"),
            "target_language": config.get("TARGET_LANGUAGE", "zh-CN"),
            "whisper_model": config.get("WHISPER_MODEL", "base"),
            "translation_model": config.get("OPENAI_MODEL", "gpt-4o-mini"),
            "api_keys": {
                "openai": secrets.get("OPENAI_API_KEY", ""),
            },
            "translation_base_url": config.get("OPENAI_API_BASE"),
        })
    
    return app


if __name__ == "__main__":
    # Example: Run Bilibili translation
    example_bilibili()
