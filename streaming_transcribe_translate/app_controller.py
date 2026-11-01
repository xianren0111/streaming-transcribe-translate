"""UI-agnostic application state and logic shared by browser (and future) front ends.

The controller mirrors the behaviour of the Tkinter ``TranslationApp`` (room/platform
routing, review queue, login state, settings and exports) but never touches a widget.
Front ends call its methods and receive JSON-serialisable events through ``subscribe``.
Secrets (API key, cookies) stay inside the controller and never appear in a snapshot.
"""

from __future__ import annotations

import base64
import itertools
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from dotenv import dotenv_values

from . import secret_store
from . import streaming_bridge as bridge
from .interface_preferences import InterfacePreferences, LANGUAGES
from .env_preferences import AUDIO_INPUTS, CHAT_MODES, normalize_env_choices, overlay_position
from .paths import ROOT
from .platforms import PLATFORMS, PLATFORM_IDS, platform_key, detect_platform, missevan_room_id
from .simul_interfaces import ChatSender, Lang, Target
from .simul_streaming_adapter import (
    MicrophoneAudioSource, StreamingProjectTranslator, list_models,
)
from .subtitle_records import CaptionRecord, SessionRecords, clock_text, recording_clock
from .subtitle_settings import PALETTES, SubtitleSettings, default_presets
from .chat_delivery import CHAT_LIMITS, DEFAULT_CHAT_TEMPLATES, send_recorded

log = logging.getLogger(__name__)

ENV_FILE = ROOT / ".env"
SUBTITLE_SETTINGS_FILE = ROOT / "subtitle_settings.json"
RECORDS_ROOT = ROOT / "records"
INTERFACE_PREFERENCES_FILE = ROOT / "interface_preferences.json"

SOURCE_LANGUAGES = {"日语": "ja", "英语": "en", "中文": "zh", "自动识别": ""}
TARGET_LANGUAGES = {
    "简体中文": "zh-CN",
    "繁體中文": "zh-TW",
    "英语": "en",
    "日语": "ja",
    "韩语": "ko",
}
LOCAL_AUDIO_INPUTS = ("麦克风", "电脑声音")
RECORDS_OFF_TITLE = "记录未开启"
RECORDS_OFF_MESSAGE = "请先在「设置 → 记录」打开「保存字幕和发送记录（用于导出时间轴）」并保存；从下次开始字幕起会保存记录。"
DEFAULT_MICROPHONE = "系统默认麦克风"
API_CONFIG_KEYS = (
    "OPENAI_API_BASE", "OPENAI_MODEL", "OPENAI_API_KEY", "BILIBILI_ROOM_URL",
    "YOUTUBE_ROOM_URL", "MISSEVAN_ROOM_URL", "LIVE_ROOM_URL", "LIVE_PLATFORM",
    "CHAT_MODE", "AUDIO_INPUT", "JEV_API_KEY",
    "SOURCE_LANGUAGE",
)
STATUS_TITLES = {
    "ready": "可以开始了",
    "running": "字幕正在运行",
    "warn": "还需要设置",
    "error": "暂时无法继续",
    "stopped": "字幕已停止",
}


class UserError(Exception):
    """A friendly, translatable error meant to be shown to the user."""

    def __init__(self, title: str, message: str, action: str = "") -> None:
        super().__init__(message)
        self.title = title
        self.message = message
        self.action = action

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "message": self.message, "action": self.action}


@dataclass
class PendingChat:
    message: str
    sender: Optional[ChatSender]
    original: str
    record: Optional[CaptionRecord]
    id: int


def friendly_error(error: str) -> str:
    if "拒绝访问" in error or "Unauthorized" in error:
        return "翻译服务无法访问，请打开「设置」检查 API Key 和服务地址。"
    if "HTTP 429" in error:
        return "翻译服务暂时限流，请稍后再试或检查账户额度。"
    if "Stream" in error or "ffmpeg" in error.lower():
        return "连接直播间失败，请确认直播正在播放，然后再试一次。"
    return error


def validate_bilibili_url(room_url: str) -> None:
    if room_url.isdecimal():
        return
    parsed = urlparse(room_url)
    if parsed.hostname not in ("live.bilibili.com", "www.bilibili.com"):
        raise ValueError("请输入有效的哔哩哔哩直播间链接或房间号。")
    room_id = parsed.path.strip("/").split("/", 1)[0]
    if not room_id.isdecimal():
        raise ValueError("直播间链接中没有有效的房间号。")


def youtube_video_id(room_url: str) -> str:
    parsed = urlparse(room_url)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if not video_id:
            match = re.match(r"^/(?:live|shorts|embed)/([^/?]+)", parsed.path)
            video_id = match.group(1) if match else ""
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_id):
        raise ValueError(
            "请输入 YouTube 直播链接，例如 youtube.com/watch?v=… 或 youtube.com/live/…。"
        )
    return video_id


class AppController:
    def __init__(
        self,
        backend: Any = None,
        *,
        env_file: Path = ENV_FILE,
        settings_file: Path = SUBTITLE_SETTINGS_FILE,
        interface_file: Path = INTERFACE_PREFERENCES_FILE,
        records_root: Path = RECORDS_ROOT,
    ) -> None:
        if backend is None:
            from .desktop_app_example import desktop_app_integration
            backend = desktop_app_integration()
        self.app = backend
        self.env_file = Path(env_file)
        self.settings_file = Path(settings_file)
        self.interface_file = Path(interface_file)
        self.records_root = Path(records_root)
        self.default_records_root = self.records_root
        self._lock = threading.RLock()
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._ids = itertools.count(1)
        self.startup_notices: list[dict[str, str]] = []

        try:
            self.interface_preferences = InterfacePreferences.load(self.interface_file, env_file=self.env_file)
        except (OSError, ValueError, TypeError) as error:
            log.error("Interface preferences load failed: %s", type(error).__name__)
            self.interface_preferences = InterfacePreferences()
            self.startup_notices.append({
                "title": "界面设置加载失败",
                "message": "界面设置或 env 默认值无效；本次使用系统语言和浅色主题，请检查配置。",
            })
        self.api_config = self._read_api_config()
        try:
            self.subtitle_settings = SubtitleSettings.load(self.settings_file, env_file=self.env_file)
        except (ValueError, TypeError, OSError) as error:
            log.error("Subtitle settings could not be loaded: %s", type(error).__name__)
            self.startup_notices.append({
                "title": "字幕设置加载失败",
                "message": "字幕设置或 env 默认值无效；本次使用默认设置，请检查配置后重新保存。",
            })
            self.subtitle_settings = SubtitleSettings()

        self.overlay_position = None
        if not self.settings_file.with_name("overlay_window.json").exists():
            try:
                self.overlay_position = overlay_position(self.env_file)
            except (OSError, ValueError) as error:
                log.error("Overlay env position invalid: %s", type(error).__name__)
                self.startup_notices.append({
                    "title": "悬浮窗位置设置无效",
                    "message": "请将 OVERLAY_X 和 OVERLAY_Y 同时设为整数；本次使用默认位置。",
                })
        if not self.subtitle_settings.chat_template_custom:
            self.subtitle_settings = replace(
                self.subtitle_settings,
                chat_template=DEFAULT_CHAT_TEMPLATES[self.interface_preferences.resolved_language],
            )
        self.records_root = self.subtitle_settings.record_directory(self.default_records_root)
        self._record_stores: dict[str, SessionRecords] = {}
        platform = platform_key(self.api_config.get("LIVE_PLATFORM", "")) or "bilibili"
        self._room_urls = {
            "bilibili": self.api_config.get("BILIBILI_ROOM_URL") or "https://live.bilibili.com/25760587",
            "youtube": self.api_config.get("YOUTUBE_ROOM_URL") or "",
            "missevan": self.api_config.get("MISSEVAN_ROOM_URL") or "",
        }
        saved_room = self.api_config.get("LIVE_ROOM_URL")
        if saved_room:
            try:
                detected = detect_platform(saved_room)
            except ValueError:
                detected = None
            if detected:
                platform = detected
            self._room_urls[platform] = saved_room
        self.platform = platform
        self._last_platform = platform
        self.room_url = self._room_urls[platform]
        self.room_url_text = self.room_url
        source_code = self.api_config.get("SOURCE_LANGUAGE", "")
        if source_code not in SOURCE_LANGUAGES.values():
            log.warning("Unsupported SOURCE_LANGUAGE; using automatic detection.")
        self.source_language = next(
            (name for name, code in SOURCE_LANGUAGES.items() if code == source_code), "自动识别",
        )
        self.target_language = self._target_name()
        audio_input = self.api_config.get("AUDIO_INPUT") or AUDIO_INPUTS[0]
        self.audio_input = audio_input if audio_input in AUDIO_INPUTS else AUDIO_INPUTS[0]
        self.microphone = DEFAULT_MICROPHONE
        self._microphone_devices: dict[str, Optional[int]] = {DEFAULT_MICROPHONE: None}
        chat_mode = self.api_config.get("CHAT_MODE") or CHAT_MODES[0]
        self.chat_mode = chat_mode if chat_mode in CHAT_MODES else CHAT_MODES[0]

        self._cookies: dict[str, dict[str, str]] = {}
        self._login_names: dict[str, str] = {}
        self._youtube_page_id = ""
        self._pending_import: Optional[dict[str, Any]] = None
        self._qr: Optional[dict[str, Any]] = None

        self._pending_chat: list[PendingChat] = []
        self._chat_draft: Optional[str] = None
        self._sending_manual_chat = False
        self._send_thread: Optional[threading.Thread] = None
        self._chat_status: dict[str, Any] = {"success": True, "message": "", "seq": 0}
        self._latest_transcription = ""
        self._asr_latency_ms: Optional[int] = None
        self._session_started_at: Optional[float] = None
        self._reported_error = False
        self._stopping = False
        self._last_captions: list[dict[str, Any]] = []
        self._status = ("ready", "")
        self._monitor: Optional[threading.Thread] = None
        self._closed = threading.Event()
        self._paused = threading.Event()
        self._overlay_state: dict[str, bool] = {"available": False, "open": False, "locked": False}
        self._set_ui_callback()
        self._set_status_for_home()

    # ------------------------------------------------------------------ events

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def _emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                log.exception("Event subscriber failed")

    def _emit_state(self) -> None:
        self._emit({"type": "state", "state": self.snapshot()})

    def _emit_error(self, title: str, message: str) -> None:
        self._emit({"type": "error", "title": title, "message": message})

    # ---------------------------------------------------------------- snapshot

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            options = self.subtitle_settings
            running = self._session_started_at is not None
            session_id = self.app.host.records.session_id if self.app.host.records else None
            pending_ids = {
                (item.record.segment_id, item.record.target_language) for item in self._pending_chat
                if item.record and item.record.session_id == session_id
            }
            history = [
                caption for caption in self._last_captions
                if (caption.get("segment_id"), caption.get("target_language", "")) not in pending_ids
                and not (options.display_mode == "说完再出" and not caption.get("is_final", True))
            ]
            history = history[-options.retained_sentences:] if options.retained_sentences else []
            head = self._pending_chat[0] if self._pending_chat else None
            pending = [self._pending_view(item) for item in self._pending_chat]
            settings = asdict(options)
            return {
                "running": running,
                "paused": running and self._paused.is_set(),
                "desktop_overlay": dict(self._overlay_state),
                "stopping": self._stopping,
                "busy": self._stopping or (running and self._reported_error),
                "status": {
                    "kind": self._status[0],
                    "title": STATUS_TITLES.get(self._status[0], "字幕状态"),
                    "detail": self._status[1],
                },
                "api": {
                    "base": self.api_config.get("OPENAI_API_BASE", ""),
                    "model": self.api_config.get("OPENAI_MODEL", ""),
                    "key_saved": bool(self.api_config.get("OPENAI_API_KEY")),
                    "ready": self._api_ready(),
                    "summary": self._api_summary(),
                },
                "room": {
                    "url": self.room_url_text,
                    "platform": self.platform,
                    "platforms": dict(PLATFORMS),
                },
                "audio_input": self.audio_input,
                "audio_inputs": list(AUDIO_INPUTS),
                "microphone": self.microphone,
                "microphones": list(self._microphone_devices),
                "source_language": self.source_language,
                "source_languages": list(SOURCE_LANGUAGES),
                "target_language": self.target_language,
                "selected_target_languages": self.selected_target_languages(),
                "target_languages": list(TARGET_LANGUAGES),
                "chat_mode": self.chat_mode,
                "chat_modes": list(CHAT_MODES),
                "chat_delivery": {
                    "language": self.subtitle_settings.chat_language or TARGET_LANGUAGES[self.selected_target_languages()[0]],
                    "max_length": CHAT_LIMITS[self.platform][0],
                    "interval": CHAT_LIMITS[self.platform][1],
                },
                "login": {key: self._login_names.get(key, "") for key in PLATFORMS},
                "history": history,
                "captions": self._last_captions[-options.retained_sentences * len(self.selected_target_languages()):],
                "pending": pending,
                "draft": (
                    self._chat_draft if self._chat_draft is not None
                    else (head.message if head else "")
                ),
                "sending": self._sending_manual_chat,
                "chat_status": dict(self._chat_status),
                "transcription": {
                    "text": self._latest_transcription,
                    "latency_ms": self._asr_latency_ms,
                },
                "subtitle_settings": settings,
                "records_folder": str(self.records_root),
                "palettes": {name: list(colors) for name, colors in PALETTES.items()},
                "interface": {
                    "theme": self.interface_preferences.theme,
                    "language": self.interface_preferences.language,
                    "resolved_language": self.interface_preferences.resolved_language,
                    "languages": dict(LANGUAGES),
                },
            }

    @staticmethod
    def _pending_view(item: PendingChat) -> dict[str, Any]:
        return {
            "id": item.id,
            "message": item.message,
            "original": item.original,
            "received_at": clock_text(item.record.received_at_ms) if item.record else "",
            "can_send": item.sender is not None,
            "target_language": item.record.target_language if item.record else "",
        }

    # ------------------------------------------------------------------ config

    def _read_api_config(self) -> dict[str, str]:
        values = dotenv_values(self.env_file) if self.env_file.exists() else {}
        config = {key: str(values.get(key) or "") for key in API_CONFIG_KEYS}
        secrets, failed = secret_store.load_secrets(self.env_file, values)
        config.update(secrets)
        if "OPENAI_API_KEY" in failed:
            self.startup_notices.append({
                "title": secret_store.DECRYPT_FAILED_TITLE,
                "message": secret_store.DECRYPT_FAILED_MESSAGE,
            })
        return normalize_env_choices(config)

    def _write_env(self, values: dict[str, str]) -> None:
        secret_store.write_env(self.env_file, values)

    def _api_ready(self) -> bool:
        return bool(self.api_config.get("OPENAI_API_BASE") and self.api_config.get("OPENAI_MODEL"))

    def _api_summary(self) -> str:
        if not self._api_ready():
            return "翻译：还没设置翻译服务"
        base = urlparse(self.api_config["OPENAI_API_BASE"]).hostname or "自定义服务"
        return f"翻译：{self.api_config['OPENAI_MODEL']} · {base}"

    def _target_name(self) -> str:
        if self.subtitle_settings.reading_languages:
            return next(name for name, code in TARGET_LANGUAGES.items()
                        if code == self.subtitle_settings.reading_languages[0])
        target = self.app.prefs.target_lang
        return next(
            (name for name, code in TARGET_LANGUAGES.items() if code == target.value),
            "简体中文",
        )

    def selected_target_languages(self) -> list[str]:
        codes = self.subtitle_settings.reading_languages
        return [name for name, code in TARGET_LANGUAGES.items() if code in codes] or [self.target_language]

    def _set_ui_callback(self) -> None:
        host = self.app.host
        host.set_ui_callback(self._run_ui)
        host.set_caption_callback(self._show_captions)
        host.set_chat_review_callback(self._enqueue_chat_review)
        host.set_chat_status_callback(self._show_chat_status)
        host.set_transcription_callback(self._show_transcription)
        host.set_notice_callback(lambda text: self._show_chat_status(False, text))

    @staticmethod
    def _run_ui(task: Callable[[], None]) -> None:
        try:
            task()
        except Exception:
            log.exception("Could not update the application state")

    # ------------------------------------------------------------------ status

    def _set_status(self, detail: str, kind: str) -> None:
        self._status = (kind, detail)

    def _set_status_for_home(self) -> None:
        if not self._api_ready():
            self._set_status("请先设置翻译服务地址和模型 ID。API Key 按服务要求填写。", "warn")
        elif self._session_started_at is not None:
            self._set_status("正在连接直播并加载语音识别。保持此窗口打开即可。", "running")
        else:
            self._set_status("准备好了。点下面的按钮开始翻译直播。", "ready")

    def _show_chat_status(self, success: bool, message: str) -> None:
        with self._lock:
            self._chat_status = {
                "success": success,
                "message": message or ("发送成功" if success else "发送失败"),
                "seq": self._chat_status["seq"] + 1,
            }
        self._emit_state()

    # ----------------------------------------------------- home / room routing

    def update_home(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            running = self._session_started_at is not None
            if "target_language" in values and "selected_target_languages" not in values:
                values = {**values, "selected_target_languages": [values["target_language"]]}
            if "selected_target_languages" in values:
                selected = values["selected_target_languages"]
                if (
                    not isinstance(selected, list) or not selected
                    or any(not isinstance(name, str) or name not in TARGET_LANGUAGES for name in selected)
                    or len(set(selected)) != len(selected)
                ):
                    raise UserError("选项不正确", "请至少选择一种字幕语言。")
                if running and set(selected) != set(self.selected_target_languages()):
                    raise UserError("请先停止字幕", "停止当前字幕后再修改阅读语言。")
                codes = [code for name, code in TARGET_LANGUAGES.items() if name in selected]
                if codes != self.subtitle_settings.reading_languages:
                    self.save_subtitle_settings({
                        "reading_languages": codes,
                        "chat_language": self.subtitle_settings.chat_language if self.subtitle_settings.chat_language in codes else codes[0],
                    })
                self.target_language = next(name for name, code in TARGET_LANGUAGES.items() if code == codes[0])
            for key, allowed in (("source_language", SOURCE_LANGUAGES), ("target_language", TARGET_LANGUAGES)):
                if key in values:
                    if values[key] not in allowed:
                        raise UserError("选项不正确", "请从列表中选择语言。")
                    setattr(self, key, values[key])
            if not running:
                if "platform" in values:
                    platform = values["platform"]
                    platform = platform_key(platform)
                    if platform is None:
                        raise UserError("选项不正确", "请从列表中选择直播平台。")
                    if platform != self.platform:
                        self._on_platform_changed(platform)
                if "room_url" in values:
                    self.room_url_text = str(values["room_url"])
                    self._on_room_url_changed()
                if "audio_input" in values:
                    if values["audio_input"] not in AUDIO_INPUTS:
                        raise UserError("选项不正确", "请从列表中选择声音来源。")
                    self.audio_input = values["audio_input"]
                if "microphone" in values:
                    name = values["microphone"]
                    self.microphone = name if name in self._microphone_devices else DEFAULT_MICROPHONE
                if "chat_mode" in values:
                    if values["chat_mode"] not in CHAT_MODES:
                        raise UserError("选项不正确", "请选择发送方式。")
                    self.chat_mode = values["chat_mode"]
        self._emit_state()
        return self.snapshot()

    def _on_room_url_changed(self) -> None:
        if self._session_started_at is not None:
            return
        try:
            platform = detect_platform(self.room_url_text)
        except ValueError:
            return  # Pasted/typed URLs are validated before login or starting.
        if platform and platform != self.platform:
            self.platform = platform
            self._last_platform = platform
            self._room_urls[platform] = self.room_url_text.strip()

    def _on_platform_changed(self, platform: str) -> None:
        self._room_urls[self._last_platform] = self.room_url_text.strip()
        self.platform = self._last_platform = platform
        self.room_url_text = self._room_urls.get(platform, "")

    def resolve_room_platform(self) -> str:
        with self._lock:
            try:
                platform = detect_platform(self.room_url_text)
                if platform:
                    self.platform = self._last_platform = platform
                    self._room_urls[platform] = self.room_url_text.strip()
                platform = self.platform
                room_url = self.room_url_text.strip()
                if room_url:
                    if platform == "missevan":
                        missevan_room_id(room_url)
                    elif platform == "youtube":
                        youtube_video_id(room_url)
                    else:
                        validate_bilibili_url(room_url)
            except ValueError as error:
                raise UserError("直播间地址不正确", str(error)) from error
            return platform

    def refresh_microphones(self) -> dict[str, Any]:
        try:
            devices = MicrophoneAudioSource.devices()
        except Exception as error:
            log.error("Could not list microphones: %s", type(error).__name__)
            raise UserError("无法读取麦克风", "无法读取录音设备，请检查设备连接和麦克风权限。") from error
        with self._lock:
            self._microphone_devices = {DEFAULT_MICROPHONE: None, **devices}
            if self.microphone not in self._microphone_devices:
                self.microphone = DEFAULT_MICROPHONE
        self._emit_state()
        warning = None
        if not devices:
            warning = {"title": "没有麦克风", "message": "没有找到录音设备，请连接麦克风后刷新。"}
        return {"microphones": list(self._microphone_devices), "warning": warning}

    # --------------------------------------------------------------- sessions

    def _set_preferences(self) -> None:
        self.app.set_preferences({
            "source_language": SOURCE_LANGUAGES[self.source_language],
            "target_language": TARGET_LANGUAGES[self.target_language],
            "whisper_model": self.app.prefs.whisper_model,
            "translation_model": self.api_config.get("OPENAI_MODEL", ""),
            "api_keys": {
                "openai": self.api_config.get("OPENAI_API_KEY", ""),
                "jev": self.api_config.get("JEV_API_KEY", ""),
            },
            "subtitle_settings": self.subtitle_settings,
            "translation_base_url": self.api_config.get("OPENAI_API_BASE", ""),
        })

    def _persist_home_preferences(self, room_url: str) -> Optional[dict[str, str]]:
        values = {
            "SOURCE_LANGUAGE": SOURCE_LANGUAGES[self.source_language],
            "TARGET_LANGUAGE": TARGET_LANGUAGES[self.target_language],
            "LIVE_ROOM_URL": room_url,
            "LIVE_PLATFORM": PLATFORM_IDS[self.platform],
            "CHAT_MODE": self.chat_mode,
            "AUDIO_INPUT": self.audio_input,
        }
        self._room_urls[self.platform] = room_url
        try:
            self._write_env(values)
        except OSError as error:
            log.error("Could not save language or room preferences: %s", error)
            return {
                "title": "设置未能保存",
                "message": "本次仍会开始翻译，但直播间和语言选择无法保存到下次使用。",
            }
        return None

    def start_session(
        self, values: Optional[dict[str, Any]] = None, confirm_auto: bool = False
    ) -> dict[str, Any]:
        with self._lock:
            if values:
                self.update_home(values)
            if self._stopping:
                return self.snapshot()
            if self._session_started_at is not None:
                return self.stop_session()
            if not self._api_ready():
                raise UserError(
                    "还不能开始",
                    "请先点「设置」，填写翻译服务地址和模型 ID。API Key 按服务要求填写。",
                    "settings",
                )
            room_url = self.room_url_text.strip()
            microphone = self.audio_input == "麦克风"
            system_audio = self.audio_input == "电脑声音"
            local_audio = microphone or system_audio
            platform = self.resolve_room_platform()
            automatic = self.chat_mode == "自动发送"
            chat_mode = "automatic" if automatic else "manual"
            cookies = self._cookies.get(platform)
            if not room_url and (not local_audio or automatic):
                raise UserError("需要直播间地址", "收听直播或发送弹幕时，请填写直播间链接。", "room_url")
            if automatic and not cookies:
                raise UserError(
                    "需要登录",
                    "发送翻译弹幕前，需要先登录当前直播平台。Cookie 只会保存在本次运行中。",
                    "login",
                )
            if automatic and not confirm_auto:
                raise UserError(
                    "确认自动发送", "每条完成的翻译都会直接发送到直播间聊天。确定继续吗？", "confirm_auto"
                )
            try:
                if local_audio and (not cookies or not room_url):
                    self.app.chat_sender = None
                    self.app.chat_mode = "manual"
                elif platform == "youtube":
                    self.app.configure_youtube_stream(
                        room_url, youtube_video_id(room_url), cookies=cookies,
                        chat_mode=chat_mode, page_id=self._youtube_page_id,
                    )
                elif platform == "missevan":
                    self.app.configure_missevan_stream(room_url, cookies=cookies, chat_mode=chat_mode)
                else:
                    validate_bilibili_url(room_url)
                    self.app.configure_bilibili_stream(room_url, cookies=cookies, chat_mode=chat_mode)
                if microphone:
                    self.app.configure_microphone(self._microphone_devices[self.microphone])
                elif system_audio:
                    self.app.configure_system_audio()
                self._wrap_pausable_audio()
                self._set_preferences()
            except ValueError as error:
                raise UserError("直播间地址不正确", str(error), "room_url") from error

            self.room_url = room_url
            warning = self._persist_home_preferences(room_url)
            self._session_started_at = time.monotonic()
            self._reported_error = False
            self._last_captions.clear()
            self._latest_transcription = ""
            self._asr_latency_ms = None
            self._paused.clear()
            self._set_status(
                "正在加载语音识别并打开麦克风。就绪后直接说话即可。" if microphone
                else "正在加载语音识别并捕获电脑声音。电脑播放的声音会被识别和翻译。" if system_audio
                else "正在连接直播并加载语音识别。保持此窗口打开即可。",
                "running",
            )
            try:
                options = self.subtitle_settings
                store = SessionRecords(
                    self.records_root, options.save_captions, options.diagnostics,
                    platform=self.platform, room=room_url,
                    audio_source="microphone" if microphone else "system" if system_audio else "stream",
                    enabled=options.save_records,
                )
                self._record_stores[store.session_id] = store
                self.app.host.records = store
                self.app.start_session()
            except Exception as error:
                self._session_started_at = None
                message = friendly_error(str(error))
                self._set_status(message, "error")
                self._emit_state()
                self._emit_error("暂时无法继续", message)
                return self.snapshot()
        if warning:
            self._emit({"type": "notice", **warning})
        self._emit_state()
        return self.snapshot()

    def toggle_pause(self) -> dict[str, Any]:
        """Pause/resume subtitles: while paused no audio reaches speech recognition."""
        with self._lock:
            if self._session_started_at is None:
                raise UserError("字幕未运行", "开始字幕后才能暂停。")
            if self._paused.is_set():
                self._paused.clear()
                self._set_status("字幕已继续。", "running")
            else:
                self._paused.set()
                self._set_status("字幕已暂停，点「继续字幕」恢复。", "running")
        self._emit_state()
        return self.snapshot()

    def set_overlay_state(self, available: bool, open: bool, locked: bool) -> None:
        with self._lock:
            state = {"available": bool(available), "open": bool(open), "locked": bool(locked)}
            if state == self._overlay_state:
                return
            self._overlay_state = state
        self._emit_state()

    def _wrap_pausable_audio(self) -> None:
        host = self.app.host
        try:
            factory = getattr(host, "_audio_source_factory", None)
        except AttributeError:
            factory = None
        if factory is None or getattr(factory, "pausable", False):
            return
        from .system_audio import PausableAudioSource

        paused = self._paused

        def pausable() -> Any:
            return PausableAudioSource(factory(), paused)

        pausable.pausable = True  # type: ignore[attr-defined]
        host.set_audio_source_factory(pausable)

    def stop_session(self) -> dict[str, Any]:
        with self._lock:
            if self._session_started_at is None or self._stopping:
                return self.snapshot()
            self._stopping = True
            self._set_status("正在停止字幕…", "stopped")

        def stop() -> None:
            try:
                self.app.stop_session()
            except Exception:
                log.exception("Stopping the session failed")
            finally:
                with self._lock:
                    self._stopping = False
                    self._session_started_at = None
                    self._set_status("字幕已停止，可以重新开始。", "stopped")
                self._emit_state()

        threading.Thread(target=stop, daemon=True).start()
        self._emit_state()
        return self.snapshot()

    def poll_session(self) -> None:
        with self._lock:
            session = self.app.session
            running = bool(session and session.running)
            changed = False
            if self._stopping and session is None:
                self._stopping = False
                self._session_started_at = None
                self._set_status("字幕已停止，可以重新开始。", "stopped")
                changed = True
            elif self._session_started_at is not None and not running and not self._stopping:
                self._session_started_at = None
                if not self._reported_error:
                    self._set_status("直播连接已结束，可以重新开始。", "stopped")
                changed = True
        if changed:
            self._emit_state()

    def start_monitor(self) -> None:
        if self._monitor is not None:
            return

        def loop() -> None:
            while not self._closed.wait(0.5):
                try:
                    self.poll_session()
                except Exception:
                    log.exception("Session monitor failed")

        self._monitor = threading.Thread(target=loop, daemon=True)
        self._monitor.start()

    def close(self) -> None:
        self._closed.set()
        self.cancel_qr_login()
        session = self.app.session
        if session and session.running:
            self.app.stop_session()

    # ------------------------------------------------- captions / transcription

    def _show_transcription(self, segment_id: int, text: str, is_final: bool, latency_ms: int) -> None:
        with self._lock:
            if self.subtitle_settings.display_mode == "说完再出" and not is_final:
                return
            self._latest_transcription = text
            self._asr_latency_ms = latency_ms
        self._emit({"type": "transcription", "text": text, "latency_ms": latency_ms})

    def _show_captions(self, captions: list[dict[str, Any]], error: Optional[str]) -> None:
        notice = None
        with self._lock:
            self._last_captions = list(captions[-self.subtitle_settings.retained_sentences * len(self.selected_target_languages()):])
            if error:
                self._reported_error = True
                notice = friendly_error(error)
                self._set_status(notice, "error")
        self._emit_state()
        if notice:
            self._emit_error("暂时无法继续", notice)

    # ----------------------------------------------------------- review queue

    def _enqueue_chat_review(
        self, message: str, sender: Optional[ChatSender], original: str = "",
        record: Optional[CaptionRecord] = None,
    ) -> None:
        with self._lock:
            self._pending_chat.append(PendingChat(message, sender, original, record, next(self._ids)))
            self._trim_pending_chat()
        self._emit_state()

    def _trim_pending_chat(self) -> None:
        removed = 0
        while len(self._pending_chat) > self.subtitle_settings.retained_sentences:
            index = 1 if self._sending_manual_chat else 0
            self._pending_chat.pop(index)
            if index == 0:
                self._chat_draft = None
            removed += 1
        if removed:
            log.info("Removed %s pending translations at configured retention limit", removed)
            self._chat_status = {
                "success": False,
                "message": f"已按保留数量移除 {removed} 条最早待处理翻译。",
                "seq": self._chat_status["seq"] + 1,
            }

    def set_draft(self, text: str) -> None:
        with self._lock:
            if self._pending_chat and not self._sending_manual_chat:
                self._chat_draft = str(text)

    def skip_pending_chat(self, message: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            if self._pending_chat and not self._sending_manual_chat:
                head = self._pending_chat[0]
                if message is None:
                    message = self._chat_draft if self._chat_draft is not None else head.message
                self._chat_draft = message
                if head.record:
                    store = self._record_stores.get(head.record.session_id)
                    try:
                        if store is None:
                            raise ValueError("missing recording session")
                        store.skip(head.record, message, round(time.time() * 1000))
                    except (OSError, ValueError) as error:
                        log.error("Skipped caption record could not be saved: %s", type(error).__name__)
                        raise UserError("记录未保存", "跳过记录保存失败；已保留当前内容，请检查磁盘空间后重试。") from error
                self._pending_chat.pop(0)
                abandon = getattr(head.sender, "abandon_partial", None)
                if callable(abandon):
                    abandon()
                self._chat_draft = None
                self._chat_status = {
                    "success": True, "message": "已跳过", "seq": self._chat_status["seq"] + 1,
                }
        self._emit_state()
        return self.snapshot()

    def send_pending_chat(self, message: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            if not self._pending_chat or self._sending_manual_chat:
                return self.snapshot()
            head = self._pending_chat[0]
            queued_message, sender, record = head.message, head.sender, head.record
            if sender is None:
                self._show_chat_status(False, "未登录发送账号；可编辑或跳过，登录后重新开始字幕即可发送。")
                return self.snapshot()
            if message is None:
                message = self._chat_draft if self._chat_draft is not None else queued_message
            message = message.strip()
            if not message:
                self._show_chat_status(False, "请输入要发送的文字，或点击「跳过」。")
                return self.snapshot()
            self._chat_draft = message
            self._sending_manual_chat = True

        def send() -> None:
            try:
                store = self._record_stores.get(record.session_id) if record else None
                result = send_recorded(sender, message, None, store, record)
            except Exception as error:
                log.error("Manual chat send failed: %s", type(error).__name__)
                result = (False, "发送失败，请检查登录状态和直播间权限。")
            self._finish_manual_send(queued_message, result)

        self._send_thread = threading.Thread(target=send, daemon=True)
        self._send_thread.start()
        self._emit_state()
        return self.snapshot()

    def _finish_manual_send(self, message: str, result: tuple[bool, str]) -> None:
        with self._lock:
            self._sending_manual_chat = False
            if result[0] and self._pending_chat and self._pending_chat[0].message == message:
                self._pending_chat.pop(0)
                self._chat_draft = None
        self._show_chat_status(*result)

    # ----------------------------------------------------------------- logins

    def _activate_login(
        self, platform: str, cookies: dict[str, str], name: str, page_id: str = ""
    ) -> None:
        with self._lock:
            if self._session_started_at is not None or self._sending_manual_chat:
                raise UserError(
                    "切换 YouTube 账号", "请先停止字幕并等待发送完成，再切换账号。"
                )
            self._cookies[platform] = cookies
            if platform == "youtube":
                self._select_youtube_account(page_id, name, cookies)
            self._login_names[platform] = name
        self._show_chat_status(True, f"{name} 已登录；Cookie 仅保存在内存中")

    def _select_youtube_account(self, page_id: str, name: str, cookies: dict[str, str]) -> None:
        from .simul_streaming_adapter import YouTubeChatSender
        self._youtube_page_id = page_id
        self._login_names["youtube"] = name
        senders = [self.app.chat_sender] + [item.sender for item in self._pending_chat]
        for sender in senders:
            if isinstance(sender, YouTubeChatSender):
                sender.cookies = dict(cookies)
                sender.page_id = page_id

    @staticmethod
    def _login_platform(platform: str) -> str:
        if platform not in PLATFORMS:
            raise UserError("直播间地址不正确", "请选择有效的直播平台。")
        return platform

    def login_with_cookies(
        self, platform: str, text: str = "", firefox: bool = False
    ) -> dict[str, Any]:
        """Verify pasted or Firefox cookies; YouTube then waits for an explicit channel choice."""
        platform = self._login_platform(platform)
        if not firefox and not text.strip():
            raise UserError("无法登录", "请先粘贴 Cookie 内容。")
        try:
            cookies = (
                bridge.read_firefox_cookies(platform) if firefox
                else bridge.parse_cookie_text(text.strip(), platform)
            )
            name = bridge.verify_login(platform, cookies)
            channels = bridge.list_youtube_channels(cookies) if platform == "youtube" else []
        except Exception as error:
            log.warning("Cookie login failed: %s", type(error).__name__)
            raise UserError("无法登录", f"读取或验证失败：{error}") from error
        if platform != "youtube":
            self._activate_login(platform, cookies, name)
            return {"stage": "done", "name": name}
        labels = []
        for number, channel in enumerate(channels, 1):
            label = channel["name"].strip()
            handle = channel["handle"].strip()
            labels.append((label + (f" ({handle})" if handle and handle != label else "")) or f"YouTube #{number}")
        selected = [i for i, channel in enumerate(channels) if channel["selected"]]
        preselect = selected[0] if len(selected) == 1 else (0 if len(channels) == 1 else None)
        import_id = uuid.uuid4().hex
        with self._lock:
            self._pending_import = {
                "id": import_id, "cookies": cookies, "channels": channels, "labels": labels,
            }
        return {
            "stage": "choose", "import_id": import_id, "name": name,
            "channels": labels, "preselect": preselect,
        }

    def confirm_youtube_account(self, import_id: str, index: Any) -> dict[str, Any]:
        with self._lock:
            pending = self._pending_import
            if not pending or pending["id"] != import_id:
                raise UserError("无法登录", "登录已过期，请重新导入 Cookie。")
            if type(index) is not int or not 0 <= index < len(pending["channels"]):
                raise UserError("无法登录", "选择用于发送聊天的 YouTube 账号或频道。")
            self._activate_login(
                "youtube", pending["cookies"], pending["labels"][index],
                pending["channels"][index]["page_id"],
            )
            self._pending_import = None
        self._emit_state()
        return {"stage": "done", "name": self._login_names["youtube"]}

    def cancel_youtube_import(self) -> None:
        with self._lock:
            self._pending_import = None

    def start_qr_login(self) -> dict[str, Any]:
        self.cancel_qr_login()
        qr = bridge.BilibiliQrLogin()
        try:
            image = qr.generate()
        except Exception as error:
            qr.close()
            log.warning("QR login failed: %s", type(error).__name__)
            raise UserError("无法登录", "扫码登录失败，请关闭此窗口重试或使用 Cookie 登录。") from error
        state = {
            "id": uuid.uuid4().hex, "state": "waiting",
            "message": "请使用哔哩哔哩手机 App 扫码，并在手机上确认登录。",
            "cancel": threading.Event(),
        }
        with self._lock:
            self._qr = state
        threading.Thread(target=self._qr_worker, args=(qr, state), daemon=True).start()
        return {
            "id": state["id"], "message": state["message"],
            "image": "data:image/png;base64," + base64.b64encode(image).decode("ascii"),
        }

    def _qr_worker(self, qr: Any, state: dict[str, Any]) -> None:
        cancelled = state["cancel"]
        try:
            deadline = time.monotonic() + 180
            while not cancelled.is_set() and time.monotonic() < deadline:
                result, cookies = qr.poll()
                if cancelled.is_set():
                    return
                if result == "done":
                    name = bridge.verify_login("bilibili", cookies)
                    self._activate_login("bilibili", cookies, name)
                    state.update(state="done", message=name)
                    self._emit_state()
                    return
                if result == "expired":
                    break
                if result == "confirm":
                    state.update(state="confirm", message="已扫码，请在手机上确认登录。")
                if cancelled.wait(2):
                    return
            state.update(state="expired", message="二维码已过期，请关闭此窗口后重新扫码。")
        except UserError as error:
            state.update(state="failed", message=error.message)
        except Exception as error:
            log.warning("QR login failed: %s", type(error).__name__)
            state.update(state="failed", message="扫码登录失败，请关闭此窗口重试或使用 Cookie 登录。")
        finally:
            qr.close()

    def qr_status(self, qr_id: str) -> dict[str, str]:
        with self._lock:
            state = self._qr
            if not state or state["id"] != qr_id:
                return {"state": "failed", "message": "二维码已过期，请关闭此窗口后重新扫码。"}
            return {"state": state["state"], "message": state["message"]}

    def cancel_qr_login(self) -> None:
        with self._lock:
            if self._qr:
                self._qr["cancel"].set()
            self._qr = None

    # ---------------------------------------------------------- API settings

    def _config_values(self, base: str, model: str, key: str) -> tuple[str, str, str]:
        base = str(base).strip().rstrip("/")
        model = str(model).strip()
        key = str(key).strip() or self.api_config.get("OPENAI_API_KEY", "")
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("请填写有效的服务地址，例如 https://api.openai.com/v1。")
        if not model or any(char.isspace() for char in model):
            raise ValueError("请填写正确的模型 ID。")
        return base, model, key

    def save_api_settings(self, base: str, model: str, key: str = "") -> dict[str, Any]:
        with self._lock:
            try:
                base, model, key = self._config_values(base, model, key)
                room_url = self.room_url_text.strip() or self.room_url
                values = {
                    "OPENAI_API_BASE": base,
                    "OPENAI_MODEL": model,
                    "OPENAI_API_KEY": key,
                    "SOURCE_LANGUAGE": SOURCE_LANGUAGES[self.source_language],
                    "TARGET_LANGUAGE": TARGET_LANGUAGES[self.target_language],
                    "LIVE_ROOM_URL": room_url,
                    "LIVE_PLATFORM": PLATFORM_IDS[self.platform],
                    "CHAT_MODE": self.chat_mode,
                    "AUDIO_INPUT": self.audio_input,
                }
                self._room_urls[self.platform] = room_url
                self._write_env(values)
            except (ValueError, OSError) as error:
                raise UserError("无法保存", str(error)) from error
            self.api_config.update(values)
            self.room_url = room_url
            self._set_preferences()
            if self._session_started_at is None:
                self._set_status_for_home()
        self._emit_state()
        return self.snapshot()

    def clear_saved_key(self) -> dict[str, Any]:
        with self._lock:
            if self.api_config.get("OPENAI_API_KEY"):
                try:
                    self._write_env({"OPENAI_API_KEY": ""})
                except OSError as error:
                    raise UserError("无法清除", str(error)) from error
                self.api_config["OPENAI_API_KEY"] = ""
        self._emit_state()
        return self.snapshot()

    def detect_models(self, base: str, key: str = "") -> list[str]:
        key = str(key).strip() or self.api_config.get("OPENAI_API_KEY", "")
        try:
            return list_models(str(base).strip(), key)
        except ValueError as error:
            raise UserError("检测失败", str(error)) from error
        except Exception as error:
            log.exception("Model detection failed")
            raise UserError("检测失败", "读取模型列表失败。") from error

    def test_connection(self, base: str, model: str, key: str = "") -> dict[str, Any]:
        self.save_api_settings(base, model, key)
        config = self.api_config
        source = Lang.EN if self.source_language == "英语" else Lang.JA
        target = Target(TARGET_LANGUAGES[self.target_language])
        try:
            result = StreamingProjectTranslator(
                source, target, api_key=config.get("OPENAI_API_KEY", ""),
                base_url=config["OPENAI_API_BASE"], model=config["OPENAI_MODEL"],
            ).translate("こんにちは")
            error = result.error
        except Exception as failure:
            log.error("Connection test failed: %s", type(failure).__name__)
            error = "无法连接翻译服务，请检查服务地址和网络。"
        return {"connected": not error, "error": error or ""}

    # ----------------------------------------------------- subtitle settings

    def save_subtitle_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        values = dict(values)
        confirmed = values.pop("confirm_speaker_download", False)
        if values.get("distinguish_speakers") is True:
            from .speaker_tracking import model_ready, download_model

            with self._lock:
                if self._session_started_at is not None:
                    raise UserError("无法保存字幕设置", "请先停止字幕再修改说话人设置。")
            if not model_ready():
                if confirmed is not True:
                    raise UserError("下载说话人模型", "首次开启需确认下载约 28 MB 本机声纹模型。")
                try:
                    download_model()
                except (OSError, RuntimeError) as error:
                    log.error("Speaker model download failed: %s", type(error).__name__)
                    raise UserError("下载说话人模型失败", str(error)) from error
        with self._lock:
            merged = asdict(self.subtitle_settings)
            if "chat_template" in values:
                merged["chat_template_custom"] = True
            for name, value in values.items():
                if name not in merged:
                    raise UserError("无法保存字幕设置", "字幕设置格式无效。")
                if isinstance(merged[name], int) and not isinstance(merged[name], bool):
                    if isinstance(value, float) and value.is_integer():
                        value = int(value)
                merged[name] = value
            if not merged["chat_template_custom"]:
                merged["chat_template"] = DEFAULT_CHAT_TEMPLATES[self.interface_preferences.resolved_language]
            try:
                settings = SubtitleSettings(**merged)
                settings.validate()
                if (self._session_started_at is not None
                        and settings.distinguish_speakers != self.subtitle_settings.distinguish_speakers):
                    raise ValueError("请先停止字幕再修改说话人设置。")
                if settings.chat_language and settings.chat_language not in (
                    settings.reading_languages or [TARGET_LANGUAGES[self.target_language]]
                ):
                    raise ValueError("发送语言必须包含在阅读语言中。")
                if (self._session_started_at is not None
                        and (settings.reading_languages != self.subtitle_settings.reading_languages
                             or settings.chat_language != self.subtitle_settings.chat_language)):
                    raise ValueError("停止当前字幕后再修改阅读语言。")
                if settings.records_folder != self.subtitle_settings.records_folder and settings.records_folder:
                    import tempfile

                    folder = Path(settings.records_folder)
                    if not folder.is_dir():
                        raise ValueError("请选择有效的记录文件夹。")
                    with tempfile.TemporaryFile(dir=folder):
                        pass
                if settings.recording_start.strip():
                    recording_clock(settings.recording_start)
                settings.save(self.settings_file)
            except (ValueError, OSError, TypeError) as error:
                log.error("Subtitle settings save failed: %s", type(error).__name__)
                raise UserError("无法保存字幕设置", str(error)) from error
            self.subtitle_settings = settings
            self.records_root = settings.record_directory(getattr(self, "default_records_root", self.records_root))
            self.app.prefs.subtitle_settings = settings
            store = self.app.host.records
            if store is not None:
                store.enabled = settings.save_records
                store.save_captions = settings.save_captions
                store.diagnostics = settings.diagnostics
            self._last_captions = self._last_captions[-settings.retained_sentences * len(self.selected_target_languages()):]
            self._trim_pending_chat()
        self._emit_state()
        return self.snapshot()

    def default_presets(self) -> dict[str, dict[str, str]]:
        return default_presets()

    # --------------------------------------------------------------- records

    def open_records(self) -> None:
        if not self.records_root.exists():
            if not self.subtitle_settings.save_records:
                raise UserError(RECORDS_OFF_TITLE, RECORDS_OFF_MESSAGE)
            raise UserError("没有记录", "开始字幕并保存文本或成功发送消息后，这里会出现记录。")
        try:
            os.startfile(self.records_root)  # type: ignore[attr-defined]
        except (OSError, AttributeError) as error:
            log.error("Could not open records folder: %s", type(error).__name__)
            raise UserError("无法打开记录", "请手动打开本应用的 records 文件夹。") from error

    def export_sessions(self) -> dict[str, Any]:
        sessions: dict[str, Any] = {
            name: store for name, store in self._record_stores.items()
            if (store.sent or store.reviewed) and store.enabled
        }
        roots = {self.records_root, getattr(self, "default_records_root", self.records_root)}
        roots.update(store.directory.parent for store in self._record_stores.values())
        for root in roots:
            if not root.exists():
                continue
            for directory in sorted(root.iterdir()):
                if any((directory / name).is_file() for name in ("sent_messages.jsonl", "captions.jsonl")):
                    sessions.setdefault(directory.name, directory)
        return dict(sorted(sessions.items()))

    def list_export_sessions(self) -> list[str]:
        return list(self.export_sessions())

    def records_hint(self) -> dict[str, Any]:
        """Tell the UI whether records are off so it can explain empty exports."""
        return {
            "enabled": self.subtitle_settings.save_records,
            "title": RECORDS_OFF_TITLE,
            "message": RECORDS_OFF_MESSAGE,
        }

    def export_sent(self, session: str) -> dict[str, str]:
        try:
            selected = self.export_sessions().get(session)
            if selected is None and not self.subtitle_settings.save_records:
                raise UserError(RECORDS_OFF_TITLE, RECORDS_OFF_MESSAGE)
            if selected is None:
                raise ValueError("请选择有已发送或已跳过字幕的会话。")
            store = SessionRecords.restore(selected) if isinstance(selected, Path) else selected
            folder = self.records_root / "exports"
            srt, csv_path = store.export(folder, include_skipped=True)
        except (OSError, ValueError, TypeError, KeyError) as error:
            log.error("Sent subtitle export failed: %s", type(error).__name__)
            raise UserError("导出失败", str(error)) from error
        return {"srt": str(srt), "csv": str(csv_path), "folder": str(folder)}

    # ------------------------------------------------------------- interface

    def set_interface(self, theme: Optional[str] = None, language: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            preferences = replace(
                self.interface_preferences,
                theme=theme or self.interface_preferences.theme,
                language=language or self.interface_preferences.language,
            )
            try:
                preferences.save(self.interface_file)
            except (OSError, ValueError) as error:
                log.error("Interface preferences save failed: %s", type(error).__name__)
                raise UserError("界面设置未保存", "无法保存界面设置，请检查文件权限和磁盘空间。") from error
            self.interface_preferences = preferences
            if not self.subtitle_settings.chat_template_custom:
                self.subtitle_settings = replace(
                    self.subtitle_settings, chat_template=DEFAULT_CHAT_TEMPLATES[preferences.resolved_language],
                )
                self.app.prefs.subtitle_settings = self.subtitle_settings
        self._emit_state()
        return self.snapshot()
