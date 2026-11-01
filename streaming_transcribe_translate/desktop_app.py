"""Simple Chinese-language desktop UI for live transcription and translation."""

from __future__ import annotations

import base64
import logging
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse
from dataclasses import asdict
import os

from dotenv import dotenv_values, set_key

from .desktop_app_example import StreamingLiveTranslationApp, desktop_app_integration
from . import secret_store
from .simul_interfaces import ChatSender, Lang, Target
from .simul_streaming_adapter import MicrophoneAudioSource, StreamingProjectTranslator, list_models
from .subtitle_settings import PALETTES, SubtitleSettings, default_presets
from .subtitle_records import CaptionRecord, SessionRecords, clock_text, recording_clock
from .paths import ROOT, LOG_FILE, LOGS_ROOT
from .ui_widgets import RoundedCard
from .platforms import PLATFORMS, PLATFORM_IDS, platform_key, detect_platform, missevan_room_id
from .streaming_bridge import YouTubeChannel
from .interface_preferences import InterfacePreferences, LANGUAGES
from .env_preferences import normalize_env_choices
from .ui_localization import (
    Translator, LocalizedLabel, LocalizedButton, LocalizedCheckbutton, LocalizedCombobox,
)
from dataclasses import replace
from .chat_delivery import send_recorded, LANGUAGE_NAMES, DEFAULT_CHAT_TEMPLATES


ENV_FILE = ROOT / ".env"
SUBTITLE_SETTINGS_FILE = ROOT / "subtitle_settings.json"
RECORDS_ROOT = ROOT / "records"
INTERFACE_PREFERENCES_FILE = ROOT / "interface_preferences.json"
BG = "#f4f4f6"
CARD = "#ffffff"
TEXT = "#1c1c21"
SECONDARY = "#4b4b53"
MUTED = "#85858d"
LINE = "#e3e3e8"
PILL = "#f1f1f4"
BRAND_SOFT = "#eeedfd"
BRAND = "#4f46e5"
OK = "#189a58"
WARN = "#b45309"
ERROR = "#d64545"
LIGHT_COLORS = {
    "BG": BG, "CARD": CARD, "TEXT": TEXT, "SECONDARY": SECONDARY,
    "MUTED": MUTED, "LINE": LINE, "PILL": PILL, "BRAND_SOFT": BRAND_SOFT,
    "BRAND": BRAND, "OK": OK, "WARN": WARN, "ERROR": ERROR,
}
DARK_COLORS = {
    "BG": "#1a1a1e", "CARD": "#232327", "TEXT": "#ededf1",
    "SECONDARY": "#b9b9c1", "MUTED": "#8b8b94", "LINE": "#333339",
    "PILL": "#2d2d33", "BRAND_SOFT": "#2b2c47", "BRAND": "#a5b4fc",
    "OK": "#6fd99b", "WARN": "#f2b544", "ERROR": "#f28b82",
}

SOURCE_LANGUAGES = {"日语": "ja", "英语": "en", "中文": "zh", "自动识别": ""}
TARGET_LANGUAGES = {
    "简体中文": "zh-CN",
    "繁體中文": "zh-TW",
    "英语": "en",
    "日语": "ja",
    "韩语": "ko",
}

log = logging.getLogger(__name__)


class TranslationApp:
    def __init__(self, root: tk.Tk, app: StreamingLiveTranslationApp) -> None:
        self.root = root
        self.app = app
        self.ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        try:
            self.interface_preferences = InterfacePreferences.load(INTERFACE_PREFERENCES_FILE, env_file=ENV_FILE)
        except (OSError, ValueError, TypeError) as error:
            log.error("Interface preferences load failed: %s", type(error).__name__)
            self.interface_preferences = InterfacePreferences()
            translator = Translator(self.interface_preferences.resolved_language)
            self._dialog('showerror', 
                translator("界面设置加载失败"),
                translator("界面设置或 env 默认值无效；本次使用系统语言和浅色主题，请检查配置。"),
                parent=root,
            )
        self.tr = Translator(self.interface_preferences.resolved_language)
        self.colors = dict(DARK_COLORS if self.interface_preferences.theme == "dark" else LIGHT_COLORS)
        self._theme_buttons = []
        self._language_selectors = []
        self.api_config = self._read_api_config()
        try:
            self.subtitle_settings = SubtitleSettings.load(SUBTITLE_SETTINGS_FILE, env_file=ENV_FILE)
        except (ValueError, TypeError, OSError) as error:
            log.error("Subtitle settings could not be loaded: %s", type(error).__name__)
            self._dialog('showerror', "字幕设置加载失败", "字幕设置或 env 默认值无效；本次使用默认设置，请检查配置后重新保存。", parent=root)
            self.subtitle_settings = SubtitleSettings()
        self._record_stores: dict[str, SessionRecords] = {}
        self.overlay: Optional[tk.Toplevel] = None
        self._option_vars: dict[str, tk.Variable] = {}
        self.platform_var = tk.StringVar(
            value=PLATFORMS[platform_key(self.api_config.get("LIVE_PLATFORM", "")) or "bilibili"]
        )
        if self.platform_var.get() not in PLATFORMS.values():
            self.platform_var.set(PLATFORMS["bilibili"])
        selected_platform = self._platform_key()
        self._room_urls = {
            "bilibili": self.api_config.get("BILIBILI_ROOM_URL")
            or "https://live.bilibili.com/25760587",
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
                selected_platform = detected
                self.platform_var.set(PLATFORMS[detected])
            self._room_urls[selected_platform] = saved_room
        self.room_url = self._room_urls[selected_platform]
        source_code = self.api_config.get("SOURCE_LANGUAGE", "")
        if source_code not in SOURCE_LANGUAGES.values():
            log.warning("Unsupported SOURCE_LANGUAGE; using automatic detection.")
        self.source_language = tk.StringVar(value=next(
            (name for name, code in SOURCE_LANGUAGES.items() if code == source_code), "自动识别",
        ))
        self.target_language = tk.StringVar(value=self._target_name())
        if not self.subtitle_settings.chat_template_custom:
            self.subtitle_settings = replace(
                self.subtitle_settings, chat_template=DEFAULT_CHAT_TEMPLATES[self.interface_preferences.resolved_language],
            )
        codes = self.subtitle_settings.reading_languages or [TARGET_LANGUAGES[self.target_language.get()]]
        self.reading_language_vars = {
            name: tk.BooleanVar(value=code in codes) for name, code in TARGET_LANGUAGES.items()
        }
        self.reading_language_buttons: list[tk.Checkbutton] = []
        self.target_language.set(next(name for name, code in TARGET_LANGUAGES.items() if code in codes))
        self.room_url_var = tk.StringVar(value=self.room_url)
        self._last_platform_key = selected_platform
        self._syncing_room_platform = False
        self.room_url_var.trace_add("write", self._on_room_url_changed)
        self._on_room_url_changed()
        self.audio_input_var = tk.StringVar(
            value=self.api_config.get("AUDIO_INPUT") or "直播间声音"
        )
        if self.audio_input_var.get() not in ("直播间声音", "麦克风", "电脑声音"):
            self.audio_input_var.set("直播间声音")
        self.microphone_var = tk.StringVar(value="系统默认麦克风")
        self._microphone_devices: dict[str, Optional[int]] = {"系统默认麦克风": None}
        self.chat_mode_var = tk.StringVar(
            value=self.api_config.get("CHAT_MODE") or "手动确认"
        )
        if self.chat_mode_var.get() not in ("手动确认", "自动发送"):
            self.chat_mode_var.set("手动确认")
        self.chat_mode_var.trace_add("write", self._update_chat_mode_label)
        self._cookies: dict[str, dict[str, str]] = {}
        self._login_names: dict[str, str] = {}
        self._youtube_page_id = ""
        self._pending_chat: list[tuple[str, Optional[ChatSender], str, Optional[CaptionRecord]]] = []
        self._chat_draft: Optional[str] = None
        self._latest_transcription = ""
        self._asr_latency_ms: Optional[int] = None
        self._sending_manual_chat = False
        self._session_started_at: Optional[float] = None
        self._reported_error = False
        self._stopping = False
        self._last_captions: list[dict[str, Any]] = []
        self._set_ui_callback()

        self.root.title(self.tr("同传字幕"))
        if self.overlay and self.overlay.winfo_exists():
            self.overlay.title(self.tr("字幕窗口 · 可在 OBS 中捕获"))
        self.root.configure(bg=self.colors['BG'])
        width = min(1080, max(540, self.root.winfo_screenwidth() - 80))
        height = min(820, max(700, self.root.winfo_screenheight() - 100))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(540, 700)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_theme()
        self.show_home()
        self.root.after(80, self._drain_ui_queue)
        self.root.after(500, self._poll_session)

    def _configure_theme(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground=self.colors['PILL'],
            background=self.colors['PILL'],
            foreground=self.colors['TEXT'],
            borderwidth=0,
            bordercolor=self.colors["LINE"],
            lightcolor=self.colors["PILL"],
            darkcolor=self.colors["PILL"],
            arrowcolor=self.colors["SECONDARY"],
            padding=(10, 6),
            arrowsize=12,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.colors['PILL'])],
            selectbackground=[("readonly", self.colors['PILL'])],
            selectforeground=[("readonly", self.colors['TEXT'])],
        )
        style.configure("TNotebook", background=self.colors['BG'], borderwidth=0, tabmargins=(0, 8, 0, 8))
        style.configure("TNotebook.Tab", padding=(16, 9), background=self.colors['PILL'], foreground=self.colors['SECONDARY'])
        style.map(
            "TNotebook.Tab", background=[("selected", self.colors['CARD'])],
            foreground=[("selected", self.colors['BRAND'])],
        )
        style.configure("Vertical.TScrollbar", background=self.colors['LINE'], troughcolor=self.colors['BG'], borderwidth=0, arrowsize=10)
        style.configure("TSeparator", background=self.colors["LINE"])
        style.configure(
            "Horizontal.TScale", background=self.colors["BRAND"],
            troughcolor=self.colors["PILL"], bordercolor=self.colors["LINE"],
            lightcolor=self.colors["LINE"], darkcolor=self.colors["LINE"],
        )
        style.configure(
            "TSpinbox", fieldbackground=self.colors["PILL"], foreground=self.colors["TEXT"],
            background=self.colors["PILL"], arrowcolor=self.colors["SECONDARY"],
            bordercolor=self.colors["LINE"], lightcolor=self.colors["PILL"],
            darkcolor=self.colors["PILL"], padding=(8, 5),
        )
        style.configure(
            "TCheckbutton", background=self.colors["CARD"], foreground=self.colors["TEXT"],
            indicatorbackground=self.colors["PILL"], indicatorforeground=self.colors["BRAND"],
        )
        style.configure(
            "TNotebook.Tab", bordercolor=self.colors["BG"],
            lightcolor=self.colors["BG"], darkcolor=self.colors["BG"],
        )
        style.configure("TNotebook", bordercolor=self.colors["BG"], lightcolor=self.colors["BG"], darkcolor=self.colors["BG"])
        style.layout("Pills.TNotebook.Tab", [])
        style.configure(
            "Pills.TNotebook", background=self.colors["BG"], borderwidth=0,
            tabmargins=0, bordercolor=self.colors["BG"],
            lightcolor=self.colors["BG"], darkcolor=self.colors["BG"],
        )
        if getattr(self, "_refresh_settings_tabs", None):
            self._refresh_settings_tabs()
        style.map("Horizontal.TScale", background=[("active", self.colors["BRAND"])])

    def _button(self, parent, **kwargs):
        kwargs.setdefault("fg", self.colors["TEXT"])
        kwargs.setdefault("activeforeground", self.colors["TEXT"])
        kwargs.setdefault("activebackground", self.colors["BRAND_SOFT"])
        kwargs.setdefault("cursor", "hand2")
        kwargs.setdefault("padx", 12)
        kwargs.setdefault("pady", 7)
        if kwargs.get("bg") == self.colors["BRAND"] and kwargs.get("fg") == "#ffffff":
            kwargs["fg"] = "#14142a" if self.interface_preferences.theme == "dark" else "#ffffff"
            if self.interface_preferences.theme == "dark":
                kwargs["activebackground"] = self.colors["BRAND"]
                kwargs["activeforeground"] = "#14142a"
        return LocalizedButton(parent, translator=self.tr, **kwargs)

    def _checkbutton(self, parent, **kwargs):
        kwargs.setdefault("selectcolor", self.colors["PILL"])
        kwargs.setdefault("activeforeground", self.colors["TEXT"])
        return LocalizedCheckbutton(parent, translator=self.tr, **kwargs)

    def _combobox(self, parent, **kwargs):
        return LocalizedCombobox(parent, translator=self.tr, **kwargs)

    def _make_label(self, parent, **kwargs):
        return LocalizedLabel(parent, translator=self.tr, **kwargs)

    def _dialog(self, method, title, message, **kwargs):
        return getattr(messagebox, method)(self.tr(title), self.tr(message), **kwargs)

    def _interface_controls(self, header):
        language = ttk.Combobox(
            header, values=list(LANGUAGES.values()), state="readonly", width=8,
            font=("Microsoft YaHei UI", 9),
        )
        language.set(LANGUAGES[self.tr.language])
        language.bind(
            "<<ComboboxSelected>>",
            lambda _: self._change_interface(language=next(
                code for code, label in LANGUAGES.items() if label == language.get()
            )),
        )
        language.pack(side="right", padx=(6, 0))
        self._language_selectors.append(language)
        theme = self._button(
            header, text="深色" if self.interface_preferences.theme == "light" else "浅色",
            command=lambda: self._change_interface(
                theme="dark" if self.interface_preferences.theme == "light" else "light"
            ),
            bg=self.colors["PILL"], fg=self.colors["TEXT"], activebackground=self.colors["BRAND_SOFT"],
            relief="flat", padx=10, pady=7, cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        )
        theme.pack(side="right", padx=(6, 0))
        self._theme_buttons.append(theme)

    def _change_interface(self, *, theme=None, language=None):
        preferences = replace(
            self.interface_preferences,
            theme=theme or self.interface_preferences.theme,
            language=language or self.interface_preferences.language,
        )
        try:
            preferences.save(INTERFACE_PREFERENCES_FILE)
        except (OSError, ValueError) as error:
            log.error("Interface preferences save failed: %s", type(error).__name__)
            self._dialog(
                "showerror", "界面设置未保存", "无法保存界面设置，请检查文件权限和磁盘空间。",
                parent=self.root,
            )
            for selector in self._language_selectors:
                if selector.winfo_exists():
                    selector.set(LANGUAGES[self.tr.language])
            return
        previous = dict(self.colors)
        self.interface_preferences = preferences
        if not self.subtitle_settings.chat_template_custom:
            self.subtitle_settings = replace(
                self.subtitle_settings, chat_template=DEFAULT_CHAT_TEMPLATES[preferences.resolved_language],
            )
            self.app.prefs.subtitle_settings = self.subtitle_settings
            if hasattr(self, "chat_template_var"):
                self.chat_template_var.set(self.subtitle_settings.chat_template)
        self.colors = dict(DARK_COLORS if preferences.theme == "dark" else LIGHT_COLORS)
        self.tr.language = preferences.resolved_language
        replacements = {previous[name]: value for name, value in self.colors.items()}
        replacements["#4338ca"] = self.colors["BRAND_SOFT"] if preferences.theme == "dark" else "#4338ca"

        def refresh(widget):
            if widget is self.overlay:
                return
            primary = (
                "background" in widget.keys() and widget.cget("background") == previous["BRAND"]
            )
            for option in (
                "background", "foreground", "activebackground", "activeforeground",
                "highlightbackground", "highlightcolor", "insertbackground", "selectcolor",
                "selectbackground", "selectforeground",
            ):
                if option in widget.keys():
                    value = widget.cget(option)
                    if value in replacements:
                        widget.configure(**{option: replacements[value]})
            if isinstance(widget, RoundedCard):
                widget._fill = self.colors["CARD"]
                widget._edge = self.colors["LINE"]
                widget._surface.configure(bg=self.colors["BG"])
                widget._draw(type("Size", (), {"width": widget.winfo_width(), "height": widget.winfo_height()})())
            if widget is self.status_dot:
                for item in widget.find_all():
                    fill = widget.itemcget(item, "fill")
                    if fill in replacements:
                        widget.itemconfigure(item, fill=replacements[fill])
            if hasattr(widget, "refresh_language"):
                widget.refresh_language()
            if primary and "foreground" in widget.keys():
                widget.configure(foreground="#14142a" if preferences.theme == "dark" else "#ffffff")
            if isinstance(widget, ttk.Notebook):
                for tab, name in zip(widget.tabs(), ("字幕", "翻译", "页面", "记录", "关于")):
                    widget.tab(tab, text=self.tr(name))
            for child in widget.winfo_children():
                refresh(child)

        refresh(self.root)
        self._configure_theme()
        for button in self._theme_buttons:
            if button.winfo_exists():
                button.configure(text="深色" if preferences.theme == "light" else "浅色")
        for selector in self._language_selectors:
            if selector.winfo_exists():
                selector.set(LANGUAGES[self.tr.language])
        self.root.title(self.tr("同传字幕"))
        if self.overlay and self.overlay.winfo_exists():
            self.overlay.title(self.tr("字幕窗口 · 可在 OBS 中捕获"))
        self._render_pending_chat()
        self._render_transcription()
        self._render_overlay()

    def _read_api_config(self) -> dict[str, str]:
        values = dotenv_values(ENV_FILE)
        config = {
            key: str(values.get(key) or "")
            for key in (
                "OPENAI_API_BASE",
                "OPENAI_MODEL",
                "OPENAI_API_KEY",
                "BILIBILI_ROOM_URL",
                "YOUTUBE_ROOM_URL",
                "MISSEVAN_ROOM_URL",
                "LIVE_ROOM_URL",
                "LIVE_PLATFORM",
                "CHAT_MODE",
                "AUDIO_INPUT",
                "JEV_API_KEY",
                "SOURCE_LANGUAGE",
            )
        }
        secrets, failed = secret_store.load_secrets(ENV_FILE, values)
        config.update(secrets)
        if "OPENAI_API_KEY" in failed:
            self.root.after(500, lambda: self._dialog(
                'showwarning', secret_store.DECRYPT_FAILED_TITLE,
                secret_store.DECRYPT_FAILED_MESSAGE, parent=self.root,
            ))
        return normalize_env_choices(config)

    def _source_name(self) -> str:
        source = self.app.prefs.source_lang
        if source is None:
            return "自动识别"
        return next(
            (name for name, code in SOURCE_LANGUAGES.items() if code == source.value),
            "自动识别",
        )

    def _target_name(self) -> str:
        target = self.app.prefs.target_lang
        return next(
            (name for name, code in TARGET_LANGUAGES.items() if code == target.value),
            "简体中文",
        )

    def _set_ui_callback(self) -> None:
        self.app.host.set_ui_callback(self.ui_queue.put)
        self.app.host.set_caption_callback(self._show_captions)
        self.app.host.set_chat_review_callback(self._enqueue_chat_review)
        self.app.host.set_chat_status_callback(self._show_chat_status)
        self.app.host.set_transcription_callback(self._show_transcription)
        self.app.host.set_notice_callback(lambda text: self._show_chat_status(False, text))

    def _show_transcription(
        self, segment_id: int, text: str, is_final: bool, latency_ms: int
    ) -> None:
        if self.subtitle_settings.display_mode == "说完再出" and not is_final:
            return
        self._latest_transcription = text
        self._asr_latency_ms = latency_ms
        self._render_transcription()

    def _render_transcription(self) -> None:
        if self.transcription_label and self.transcription_label.winfo_exists():
            self.transcription_label.configure(
                text=lambda tr: tr("实时原文：") + (
                    self._latest_transcription or tr("等待语音…")
                )
            )
            if self.subtitle_settings.show_original:
                self.transcription_label.pack(fill="x", padx=14, pady=(4, 0))
            else:
                self.transcription_label.pack_forget()
        if (
            self.asr_timing_label and self.asr_timing_label.winfo_exists()
        ):
            self.asr_timing_label.configure(
                text=f"识别耗时 {self._asr_latency_ms} ms（不含直播/分句/翻译等待）"
                if self._asr_latency_ms is not None else "识别耗时：等待语音…"
            )
            if self.subtitle_settings.show_stats:
                self.asr_timing_label.pack(fill="x", padx=14, pady=(0, 4))
            else:
                self.asr_timing_label.pack_forget()

    def open_overlay(self) -> None:
        if self.overlay and self.overlay.winfo_exists():
            self.overlay.lift()
            return
        self.overlay = tk.Toplevel(self.root)
        self.overlay.title(self.tr("字幕窗口 · 可在 OBS 中捕获"))
        self.overlay.attributes("-topmost", True)
        self.overlay_text = tk.Text(
            self.overlay, wrap="word", relief="flat", padx=12, pady=8, state="disabled"
        )
        self.overlay_text.pack(fill="both", expand=True)
        self._render_overlay()

    def _render_overlay(self) -> None:
        if not self.overlay or not self.overlay.winfo_exists():
            return
        options = self.subtitle_settings
        foreground, background = PALETTES[options.palette]
        self.overlay.attributes("-alpha", options.opacity)
        width = round(self.root.winfo_screenwidth() * options.width_percent / 100)
        height = round(self.root.winfo_screenheight() * options.height_percent / 100)
        self.overlay.geometry(f"{width}x{height}")
        self.overlay_text.configure(
            state="normal", bg=background, fg=foreground,
            font=("Microsoft YaHei UI", options.font_size),
        )
        self.overlay_text.delete("1.0", "end")
        if not self._last_captions:
            self.overlay_text.insert("end", self.tr("字幕预览：识别和翻译后会显示在这里。"))
        self.overlay_text.tag_configure("draft", foreground="#aaaab0")
        for caption in self._last_captions[-options.retained_sentences * max(1, len(options.reading_languages)):]:
            final = caption.get("is_final", True)
            if not final and options.display_mode == "说完再出":
                continue
            tag = () if final else ("draft",)
            if options.show_original:
                self.overlay_text.insert("end", caption["original"] + "\n", tag)
            language = "[" + caption["target_language"] + "] " if caption.get("target_language") else ""
            self.overlay_text.insert("end", language + caption["translated"] + "\n", tag)
            if options.show_stats:
                timing = caption.get("timing", {})
                self.overlay_text.insert(
                    "end", f"ASR {timing.get('asr_ms', 0)} ms · MT {timing.get('mt_ms', 0)} ms\n", tag
                )
        self.overlay_text.configure(state="disabled")
        self.overlay_text.see("end")

    def _drain_ui_queue(self) -> None:
        for _ in range(50):
            try:
                task = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                task()
            except tk.TclError:
                return
            except Exception:
                log.exception("Could not update the application window")
        self.root.after(80, self._drain_ui_queue)

    def _poll_session(self) -> None:
        session = self.app.session
        running = bool(session and session.running)
        if self._stopping and session is None:
            self._stopping = False
            self._session_started_at = None
            self._set_status("字幕已停止，可以重新开始。", self.colors['MUTED'])
            self._set_start_button(False)
        elif self._session_started_at is not None and not running and not self._stopping:
            self._session_started_at = None
            if not self._reported_error:
                self._set_status("直播连接已结束，可以重新开始。", self.colors['MUTED'])
            self._set_start_button(False)
        self.root.after(500, self._poll_session)

    def _show_captions(
        self,
        captions: list[dict[str, Any]],
        error: Optional[str],
    ) -> None:
        self._last_captions = captions[-self.subtitle_settings.retained_sentences * max(1, len(self.subtitle_settings.reading_languages)):]
        self._render_captions()
        if error:
            self._reported_error = True
            if self.start_button and self.start_button.winfo_exists():
                self.start_button.configure(
                    state="disabled",
                    text="正在结束…",
                    bg=self.colors['PILL'],
                    fg=self.colors['MUTED'],
                )
            self._set_status(self._friendly_error(error), self.colors['ERROR'])
            self._dialog("showerror", "暂时无法继续", self._friendly_error(error), parent=self.root)

    @staticmethod
    def _friendly_error(error: str) -> str:
        if "拒绝访问" in error or "Unauthorized" in error:
            return "翻译服务无法访问，请打开「设置」检查 API Key 和服务地址。"
        if "HTTP 429" in error:
            return "翻译服务暂时限流，请稍后再试或检查账户额度。"
        if "Stream" in error or "ffmpeg" in error.lower():
            return "连接直播间失败，请确认直播正在播放，然后再试一次。"
        return error

    def _render_captions(self) -> None:
        if not self.caption_text or not self.caption_text.winfo_exists():
            return
        self.caption_text.configure(state="normal")
        self.caption_text.tag_configure("original", foreground=self.colors["MUTED"])
        self.caption_text.tag_configure("translated", foreground=self.colors["TEXT"])
        self.caption_text.tag_configure("queue_heading", foreground=self.colors["BRAND"], font=("Microsoft YaHei UI", 10, "bold"))
        self.caption_text.delete("1.0", "end")
        options = self.subtitle_settings
        pending_ids = {
            (record.segment_id, record.target_language) for _, _, _, record in self._pending_chat
            if record and self.app.host.records and record.session_id == self.app.host.records.session_id
        }
        history = [
            caption for caption in self._last_captions
            if (caption.get("segment_id"), caption.get("target_language", "")) not in pending_ids
            and not (
                options.display_mode == "说完再出" and not caption.get("is_final", True)
            )
        ]
        for caption in history[-options.retained_sentences * max(1, len(options.reading_languages)):] if options.retained_sentences else []:
            if options.display_mode == "说完再出" and not caption.get("is_final", True):
                continue
            if options.show_original:
                self.caption_text.insert("end", caption["original"] + "\n", "original")
            language = "[" + caption["target_language"] + "] " if caption.get("target_language") else ""
            self.caption_text.insert("end", language + caption["translated"] + "\n\n", "translated")
            if options.show_stats:
                timing = caption.get("timing", {})
                self.caption_text.insert(
                    "end", ('ASR ' + str(timing.get('asr_ms', 0)) + self.tr(' ms · 翻译 ') + str(timing.get('mt_ms', 0)) + ' ms\n'), "original"
                )
        queue_start = None
        upcoming = self._pending_chat[1:]
        if upcoming:
            queue_start = self.caption_text.index("end-1c")
            self.caption_text.insert(
                "end", self.tr("待发送队列") + f" · {len(upcoming)}\n", "queue_heading"
            )
            for index, (message, _sender, original, record) in enumerate(upcoming, 1):
                timing = f" [{clock_text(record.received_at_ms)}]" if record else ""
                self.caption_text.insert("end", f"{index}.{timing}{self.tr(' 原文：')}{original}\n", "original")
                language = "[" + record.target_language + "] " if record and record.target_language else ""
                self.caption_text.insert("end", f"{language}{self.tr('译文：')}{message}\n\n", "translated")
        self.caption_text.configure(state="disabled")
        if queue_start:
            self.caption_text.yview(queue_start)
        else:
            self.caption_text.see("end")
        self._render_overlay()

    def _platform_key(self) -> str:
        key = platform_key(self.platform_var.get())
        if key is None:
            raise ValueError("请从列表中选择直播平台。")
        return key

    def _update_chat_mode_label(self, *_args) -> None:
        selector = getattr(self, "chat_mode_selector", None)
        if selector and selector.winfo_exists():
            selector.configure(text="自动发送" if self.chat_mode_var.get() == "自动发送" else "手动发送")

    def _on_room_url_changed(self, *_args) -> None:
        if self._syncing_room_platform or getattr(self, "_session_started_at", None) is not None:
            return
        try:
            platform = detect_platform(self.room_url_var.get())
        except ValueError:
            return  # Pasted/typed URLs are validated before login or starting.
        if platform and platform != self._platform_key():
            self.platform_var.set(PLATFORMS[platform])
            self._last_platform_key = platform
            self._room_urls[platform] = self.room_url_var.get().strip()
            self._update_login_status()

    def _resolve_room_platform(self) -> Optional[str]:
        try:
            platform = detect_platform(self.room_url_var.get())
            if platform:
                self.platform_var.set(PLATFORMS[platform])
                self._last_platform_key = platform
                self._room_urls[platform] = self.room_url_var.get().strip()
            platform = self._platform_key()
            room_url = self.room_url_var.get().strip()
            if room_url:
                if platform == "missevan":
                    missevan_room_id(room_url)
                elif platform == "youtube":
                    self._youtube_video_id(room_url)
                else:
                    self._validate_bilibili_url(room_url)
        except ValueError as error:
            self._dialog("showerror", "直播间地址不正确", str(error), parent=self.root)
            return None
        self._update_login_status()
        return platform

    def _on_platform_changed(self, _event: Any = None) -> None:
        self._syncing_room_platform = True
        try:
            self._room_urls[self._last_platform_key] = self.room_url_var.get().strip()
            self._last_platform_key = self._platform_key()
            self.room_url_var.set(self._room_urls.get(self._last_platform_key, ""))
        finally:
            self._syncing_room_platform = False
        self._update_login_status()

    def _refresh_microphones(self) -> None:
        try:
            devices = MicrophoneAudioSource.devices()
        except Exception as error:
            log.error("Could not list microphones: %s", type(error).__name__)
            self._dialog('showerror', 
                "无法读取麦克风", "无法读取录音设备，请检查设备连接和麦克风权限。",
                parent=self.root,
            )
            return
        self._microphone_devices = {"系统默认麦克风": None, **devices}
        self.microphone_selector.configure(values=list(self._microphone_devices))
        if self.microphone_var.get() not in self._microphone_devices:
            self.microphone_var.set("系统默认麦克风")
        if not devices:
            self._dialog('showwarning', 
                "没有麦克风", "没有找到录音设备，请连接麦克风后刷新。", parent=self.root
            )

    def _update_login_status(self) -> None:
        if not getattr(self, "login_status", None) or not self.login_status.winfo_exists():
            return
        platform = self._platform_key()
        site_name = PLATFORMS[platform]
        name = self._login_names.get(platform)
        self.login_status.configure(
            text=lambda tr: site_name + " · " + (
                tr("聊天账号：") + name if name else tr("聊天账号：未登录")
            ),
            fg=self.colors['OK'] if name else self.colors['MUTED'],
        )
        if getattr(self, "login_button", None) and self.login_button.winfo_exists():
            self.login_button.configure(
                text=lambda tr: site_name + " · " + tr("登录 / 导入 Cookie"),
            )
    def _complete_cookie_import(
        self, platform: str, cookies: dict[str, str], name: str,
        parent: tk.Toplevel, channels: list[YouTubeChannel],
    ) -> None:
        if not parent.winfo_exists():
            return
        if platform != "youtube":
            self._activate_login(platform, cookies, name, parent)
            return
        dialog = tk.Toplevel(parent)
        dialog.title(self.tr("切换 YouTube 账号"))
        dialog.configure(bg=self.colors['BG'])
        dialog.transient(parent)
        dialog.grab_set()
        status = self._label(dialog, "选择用于发送聊天的 YouTube 账号或频道。", wraplength=420)
        status.pack(fill="x", padx=16, pady=16)
        labels = []
        for number, channel in enumerate(channels, 1):
            label = channel["name"].strip()
            handle = channel["handle"].strip()
            labels.append((label + (f" ({handle})" if handle and handle != label else "")) or f"YouTube #{number}")
        combo = ttk.Combobox(dialog, values=labels, state="readonly", width=42)
        combo.pack(fill="x", padx=16, pady=(0, 12))
        selected = [i for i, channel in enumerate(channels) if channel["selected"]]
        if len(selected) == 1:
            combo.current(selected[0])
        elif len(channels) == 1:
            combo.current(0)

        def choose() -> None:
            index = combo.current()
            if index < 0:
                status.configure(fg=self.colors['ERROR'])
                return
            self._activate_login("youtube", cookies, labels[index], parent, channels[index]["page_id"])

        self._button(dialog, text="使用此账号", command=choose).pack(padx=16, pady=(0, 16))

    def _select_youtube_account(self, page_id: str, name: str, cookies: dict[str, str]) -> None:
        from .simul_streaming_adapter import YouTubeChatSender
        self._youtube_page_id = page_id
        self._login_names["youtube"] = name
        senders = [self.app.chat_sender] + [item[1] for item in self._pending_chat]
        for sender in senders:
            if isinstance(sender, YouTubeChatSender):
                sender.cookies = dict(cookies)
                sender.page_id = page_id
        self._update_login_status()

    def _enqueue_chat_review(
        self, message: str, sender: Optional[ChatSender], original: str = "",
        record: Optional[CaptionRecord] = None,
    ) -> None:
        self._pending_chat.append((message, sender, original, record))
        self._trim_pending_chat()
        self._render_pending_chat()

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
            self._show_chat_status(False, f"已按保留数量移除 {removed} 条最早待处理翻译。")

    def _render_pending_chat(self) -> None:
        self._render_captions()
        if self.review_queue_title and self.review_queue_title.winfo_exists():
            self.review_queue_title.configure(
                text=f"实时字幕 / 待处理 · {max(0, len(self._pending_chat) - 1)} 条待处理"
            )
        if self.original_chat_text and self.original_chat_text.winfo_exists():
            self.original_chat_text.configure(state="normal")
            self.original_chat_text.delete("1.0", "end")
            self.original_chat_text.insert(
                "1.0",
                (
                    f"[音频接收 {clock_text(self._pending_chat[0][3].received_at_ms)}]\n"
                    if self._pending_chat and self._pending_chat[0][3] else ""
                ) + (self._pending_chat[0][2] if self._pending_chat else "等待翻译…"),
            )
            self.original_chat_text.configure(state="disabled")
        if not self.pending_chat_text or not self.pending_chat_text.winfo_exists():
            return
        self.pending_chat_text.configure(
            state="disabled" if self._sending_manual_chat else "normal"
        )
        if not self._pending_chat:
            self.pending_chat_text.delete("1.0", "end")
            self.pending_chat_text.configure(state="disabled")
            self._chat_draft = None
            self.send_chat_button.configure(state="disabled")
            self.skip_chat_button.configure(state="disabled")
            return
        if self._chat_draft is None:
            self._chat_draft = self._pending_chat[0][0]
            self.pending_chat_text.configure(state="normal")
            self.pending_chat_text.delete("1.0", "end")
            self.pending_chat_text.insert("1.0", self._chat_draft)
            self.pending_chat_text.configure(
                state="disabled" if self._sending_manual_chat else "normal"
            )
        state = "disabled" if self._sending_manual_chat else "normal"
        self.send_chat_button.configure(state=state if self._pending_chat[0][1] else "disabled")
        self.skip_chat_button.configure(state=state)

    def _show_chat_status(self, success: bool, message: str) -> None:
        if self.chat_status and self.chat_status.winfo_exists():
            self.chat_status.configure(
                text=message or ("发送成功" if success else "发送失败"),
                fg=self.colors['OK'] if success else self.colors['ERROR'],
            )

    def _skip_pending_chat(self) -> None:
        if self._pending_chat and not self._sending_manual_chat:
            _, sender, _, record = self._pending_chat[0]
            if record:
                try:
                    store = self._record_stores.get(record.session_id)
                    if store is None:
                        raise ValueError("missing recording session")
                    store.skip(record, self.pending_chat_text.get("1.0", "end-1c"), round(time.time() * 1000))
                except (OSError, ValueError) as error:
                    log.error("Skipped caption record could not be saved: %s", type(error).__name__)
                    self._dialog(
                        'showerror', "记录未保存",
                        "跳过记录保存失败；已保留当前内容，请检查磁盘空间后重试。", parent=self.root,
                    )
                    return
            self._pending_chat.pop(0)
            abandon = getattr(type(sender), "abandon_partial", None)
            if callable(abandon):
                sender.abandon_partial()
            self._chat_draft = None
            self._show_chat_status(True, "已跳过")
            self._render_pending_chat()

    def _send_pending_chat(self) -> None:
        if not self._pending_chat or self._sending_manual_chat:
            return
        queued_message, sender, _original, record = self._pending_chat[0]
        if sender is None:
            self._show_chat_status(False, "未登录发送账号；可编辑或跳过，登录后重新开始字幕即可发送。")
            return
        message = self.pending_chat_text.get("1.0", "end-1c").strip()
        if not message:
            self._show_chat_status(False, "请输入要发送的文字，或点击「跳过」。")
            return
        self._chat_draft = message
        self._sending_manual_chat = True
        self._render_pending_chat()
        self.send_chat_button.configure(text="正在发送…")

        def send() -> None:
            try:
                store = self._record_stores.get(record.session_id) if record else None
                result = send_recorded(sender, message, None, store, record)
            except Exception as error:
                log.error("Manual chat send failed: %s", type(error).__name__)
                result = (False, "发送失败，请检查登录状态和直播间权限。")
            self.ui_queue.put(lambda: self._finish_manual_send(queued_message, result))

        threading.Thread(target=send, daemon=True).start()

    def _finish_manual_send(
        self, message: str, result: tuple[bool, str]
    ) -> None:
        self._sending_manual_chat = False
        if result[0] and self._pending_chat and self._pending_chat[0][0] == message:
            self._pending_chat.pop(0)
            self._chat_draft = None
        self._show_chat_status(*result)
        if self.send_chat_button and self.send_chat_button.winfo_exists():
            self.send_chat_button.configure(text="发送到直播间")
        self._render_pending_chat()

    def open_login_dialog(self) -> None:
        platform = self._resolve_room_platform()
        if platform is None:
            return
        site_name = PLATFORMS[platform]
        dialog = tk.Toplevel(self.root)
        dialog.title(f"{site_name} {self.tr('登录')}")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg=self.colors['BG'])
        dialog.geometry("500x490")
        content = self._card(dialog)
        content.pack(fill="both", expand=True, padx=16, pady=16)
        inner = tk.Frame(content, bg=self.colors['CARD'])
        inner.pack(fill="both", expand=True, padx=16, pady=14)
        self._label(inner, f"连接 {site_name} 聊天账号", size=15, weight="bold").pack(
            anchor="w"
        )
        self._label(
            inner,
            "Cookie 相当于登录凭证。只在本次运行中保存在内存，不会写入配置文件或日志。请勿发送给他人。",
            size=9,
            color=self.colors['SECONDARY'],
            wraplength=430,
        ).pack(anchor="w", fill="x", pady=(6, 12))
        result_label = self._label(inner, "", size=9, color=self.colors['SECONDARY'], wraplength=430)
        result_label.pack(fill="x", pady=(0, 6))
        if platform == "bilibili":
            self._button(
                inner,
                text="使用哔哩哔哩手机 App 扫码登录",
                command=lambda: self.open_qr_login(dialog),
                bg=self.colors['PILL'],
                fg=self.colors['TEXT'],
                relief="flat",
                font=("Microsoft YaHei UI", 9),
                pady=7,
            ).pack(fill="x", pady=(0, 8))
        cookie_input = tk.Text(
            inner,
            height=10,
            wrap="word",
            bg=self.colors['PILL'],
            fg=self.colors['TEXT'],
            relief="flat",
            padx=8,
            pady=8,
            font=("Consolas", 9),
        )
        cookie_input.pack(fill="both", expand=True)
        self._label(
            inner,
            "可以粘贴 Cookie 请求头、Netscape 导出或 JSON 格式。",
            size=9,
            color=self.colors['MUTED'],
        ).pack(anchor="w", pady=(5, 10))
        buttons = tk.Frame(inner, bg=self.colors['CARD'])
        buttons.pack(fill="x")
        firefox_button = self._button(
            buttons,
            text="从 Firefox 读取并验证",
            command=lambda: self._login_from_firefox(
                platform, dialog, result_label, firefox_button
            ),
            bg=self.colors['PILL'],
            fg=self.colors['TEXT'],
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
            padx=10,
            pady=7,
        )
        firefox_button.pack(side="left")
        self._button(
            buttons,
            text="验证并使用",
            command=lambda: self._login_from_text(
                platform, dialog, result_label, cookie_input
            ),
            bg=self.colors['BRAND'],
            fg="#ffffff",
            activebackground="#4338ca",
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=12,
            pady=7,
        ).pack(side="right")

    def open_qr_login(self, login_dialog: tk.Toplevel) -> None:
        dialog = tk.Toplevel(login_dialog)
        dialog.title(self.tr("哔哩哔哩扫码登录"))
        dialog.transient(login_dialog)
        dialog.configure(bg=self.colors['CARD'])
        cancelled = threading.Event()
        dialog.bind(
            "<Destroy>",
            lambda event: cancelled.set() if event.widget == dialog else None,
        )
        status = self._label(
            dialog, "正在生成二维码…", wraplength=360, size=10
        )
        status.pack(padx=16, pady=12)
        image_label = self._make_label(dialog, bg=self.colors['CARD'])
        image_label.pack(padx=16, pady=(0, 16))
        qr_image: Optional[tk.PhotoImage] = None

        def update_status(message: str) -> None:
            if not cancelled.is_set():
                status.configure(text=message)

        def display_image(data: bytes) -> None:
            nonlocal qr_image
            if not cancelled.is_set():
                qr_image = tk.PhotoImage(data=base64.b64encode(data).decode("ascii"))
                image_label.configure(image=qr_image)
                update_status("请使用哔哩哔哩手机 App 扫码，并在手机上确认登录。")

        def activate(cookies: dict[str, str], name: str) -> None:
            if not cancelled.is_set():
                self._activate_login("bilibili", cookies, name, login_dialog)

        def login() -> None:
            qr = None
            try:
                from .streaming_bridge import BilibiliQrLogin, verify_login

                qr = BilibiliQrLogin()
                image = qr.generate()
                self.ui_queue.put(lambda: display_image(image))
                deadline = time.monotonic() + 180
                while not cancelled.is_set() and time.monotonic() < deadline:
                    state, cookies = qr.poll()
                    if cancelled.is_set():
                        return
                    if state == "done":
                        name = verify_login("bilibili", cookies)
                        self.ui_queue.put(lambda: activate(cookies, name))
                        return
                    if state == "expired":
                        break
                    if state == "confirm":
                        self.ui_queue.put(
                            lambda: update_status("已扫码，请在手机上确认登录。")
                        )
                    if cancelled.wait(2):
                        return
                self.ui_queue.put(
                    lambda: update_status("二维码已过期，请关闭此窗口后重新扫码。")
                )
            except Exception as error:
                log.warning("QR login failed: %s", type(error).__name__)
                self.ui_queue.put(
                    lambda: update_status("扫码登录失败，请关闭此窗口重试或使用 Cookie 登录。")
                )
            finally:
                if qr is not None:
                    qr.close()

        threading.Thread(target=login, daemon=True).start()

    def _login_from_firefox(
        self,
        platform: str,
        dialog: tk.Toplevel,
        result_label: tk.Label,
        button: tk.Button,
    ) -> None:
        button.configure(state="disabled", text="正在读取…")
        result_label.configure(
            text="请稍候，正在读取 Firefox Cookie 并验证登录…", fg=self.colors['SECONDARY']
        )

        def verify() -> None:
            try:
                from .streaming_bridge import read_firefox_cookies, verify_login

                cookies = read_firefox_cookies(platform)
                name = verify_login(platform, cookies)
                channels = self._import_channels(platform, cookies)
            except Exception as error:
                log.warning("Firefox login failed: %s", type(error).__name__)
                failure = f"读取或验证失败：{error}"
                self.ui_queue.put(
                    lambda message=failure: self._login_failed(
                        result_label, button, message
                    )
                )
                return
            self.ui_queue.put(
                lambda: self._complete_cookie_import(platform, cookies, name, dialog, channels)
            )

        threading.Thread(target=verify, daemon=True).start()

    def _login_from_text(
        self,
        platform: str,
        dialog: tk.Toplevel,
        result_label: tk.Label,
        cookie_input: tk.Text,
    ) -> None:
        text = cookie_input.get("1.0", "end").strip()
        cookie_input.delete("1.0", "end")
        if not text:
            result_label.configure(text="请先粘贴 Cookie 内容。", fg=self.colors['ERROR'])
            return
        result_label.configure(text="正在验证登录…", fg=self.colors['SECONDARY'])

        def verify() -> None:
            try:
                from .streaming_bridge import parse_cookie_text, verify_login

                cookies = parse_cookie_text(text, platform)
                name = verify_login(platform, cookies)
                channels = self._import_channels(platform, cookies)
            except Exception as error:
                log.warning("Pasted-cookie login failed: %s", type(error).__name__)
                failure = f"读取或验证失败：{error}"
                self.ui_queue.put(
                    lambda message=failure: self._login_failed(
                        result_label, None, message
                    )
                )
                return
            self.ui_queue.put(
                lambda: self._complete_cookie_import(platform, cookies, name, dialog, channels)
            )

        threading.Thread(target=verify, daemon=True).start()

    @staticmethod
    def _import_channels(platform: str, cookies: dict[str, str]) -> list[YouTubeChannel]:
        if platform != "youtube":
            return []
        from .streaming_bridge import list_youtube_channels
        return list_youtube_channels(cookies)

    def _login_failed(
        self,
        result_label: tk.Label,
        button: Optional[tk.Button],
        message: str,
    ) -> None:
        if result_label.winfo_exists():
            result_label.configure(text=message, fg=self.colors['ERROR'])
        if button and button.winfo_exists():
            button.configure(state="normal", text="从 Firefox 读取并验证")

    def _activate_login(
        self,
        platform: str,
        cookies: dict[str, str],
        name: str,
        dialog: tk.Toplevel,
        page_id: str = "",
    ) -> None:
        if not dialog.winfo_exists():
            return
        if self._session_started_at is not None or self._sending_manual_chat:
            self._dialog("showwarning", "切换 YouTube 账号", "请先停止字幕并等待发送完成，再切换账号。", parent=dialog)
            return
        self._cookies[platform] = cookies
        if platform == "youtube":
            self._select_youtube_account(page_id, name, cookies)
        self._login_names[platform] = name
        self._update_login_status()
        self._show_chat_status(True, f"{name} 已登录；Cookie 仅保存在内存中")
        if dialog.winfo_exists():
            dialog.destroy()

    def _api_ready(self) -> bool:
        return bool(
            self.api_config.get("OPENAI_API_BASE")
            and self.api_config.get("OPENAI_MODEL")
        )

    def _api_summary(self) -> str:
        if not self._api_ready():
            return "翻译：还没设置翻译服务"
        base = urlparse(self.api_config["OPENAI_API_BASE"]).hostname or "自定义服务"
        return f"翻译：{self.api_config['OPENAI_MODEL']} · {base}"

    def _clear_screen(self, scrollable: bool = False) -> tk.Frame:
        self._theme_buttons = []
        self._language_selectors = []
        editor = getattr(self, "pending_chat_text", None)
        if editor and editor.winfo_exists() and self._pending_chat:
            self._chat_draft = editor.get("1.0", "end-1c")
        self.root.unbind("<MouseWheel>")
        for child in self.root.winfo_children():
            if child != self.overlay:
                child.destroy()
        for name in (
            "status_dot",
            "status_title",
            "status_detail",
            "caption_text",
            "service_label",
            "start_button",
            "room_entry",
            "audio_input_selector",
            "microphone_selector",
            "refresh_microphones_button",
            "platform_selector",
            "login_status",
            "login_button",
            "chat_status",
            "review_queue_text",
            "review_queue_title",
            "original_chat_text",
            "transcription_label",
            "asr_timing_label",
            "pending_chat_text",
            "send_chat_button",
            "skip_chat_button",
            "settings_result",
            "test_button",
            "model_combo",
            "detect_models_button",
        ):
            setattr(self, name, None)
        page = tk.Frame(self.root, bg=self.colors['BG'])
        page.pack(fill="both", expand=True)
        if scrollable:
            canvas = tk.Canvas(page, bg=self.colors['BG'], highlightthickness=0)
            scrollbar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
            scrollbar.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)
            canvas.configure(yscrollcommand=scrollbar.set)
            content = tk.Frame(canvas, bg=self.colors['BG'])
            window = canvas.create_window((0, 0), window=content, anchor="nw")
            content.bind(
                "<Configure>",
                lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
            )
            canvas.bind(
                "<Configure>", lambda event: canvas.itemconfigure(window, width=event.width)
            )
            self.root.bind(
                "<MouseWheel>",
                lambda event: canvas.yview_scroll(-int(event.delta / 120), "units")
                if event.widget.winfo_class() != "Text" else None,
            )
            return content
        return page

    def _card(self, parent: tk.Widget, **kwargs: Any) -> tk.Frame:
        return RoundedCard(parent, fill=self.colors['CARD'], edge=self.colors['LINE'], page=self.colors['BG'], **kwargs)

    def _layout_home(self, width: int) -> None:
        wide = width >= 900
        if width < 760:
            self.home_title.pack_forget()
        elif not self.home_title.winfo_manager():
            self.home_title.pack(side="left")
        self.home_columns.columnconfigure(0, weight=4 if wide else 1)
        self.home_columns.columnconfigure(1, weight=6 if wide else 0)
        self.connection_card.grid(
            row=0, column=0, sticky="new",
            padx=(0, 8) if wide else 0, pady=(0, 14),
        )
        self.review_card.grid(
            row=0 if wide else 1, column=1 if wide else 0, sticky="new",
            padx=(8, 0) if wide else 0, pady=(0, 14),
        )

    def _label(
        self,
        parent: tk.Widget,
        text: str,
        *,
        size: int = 11,
        color: Optional[str] = None,
        weight: str = "normal",
        **kwargs: Any,
    ) -> tk.Label:
        return LocalizedLabel(
            parent,
            translator=self.tr,
            text=text,
            bg=kwargs.pop("bg", self.colors['CARD']),
            fg=color or self.colors["TEXT"],
            font=("Microsoft YaHei UI", size, weight),
            anchor=kwargs.pop("anchor", "w"),
            justify=kwargs.pop("justify", "left"),
            wraplength=kwargs.pop("wraplength", 480),
            **kwargs,
        )

    def show_home(self) -> None:
        page = self._clear_screen(scrollable=True)
        header = tk.Frame(page, bg=self.colors['BG'])
        header.pack(fill="x", padx=24, pady=(20, 2))
        self.home_title = self._label(header, "同传字幕", size=20, weight="bold", bg=self.colors['BG'])
        self.home_title.pack(side="left")
        self._interface_controls(header)
        self._button(
            header,
            text="设置",
            command=self.show_settings,
            bg=self.colors['BG'],
            fg=self.colors['SECONDARY'],
            activebackground=self.colors['BG'],
            activeforeground=self.colors['TEXT'],
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 10),
            padx=12, pady=7,
        ).pack(side="right")
        self._button(
            header, text="字幕窗口", command=self.open_overlay,
            bg=self.colors['BRAND_SOFT'], fg=self.colors['BRAND'], activebackground=self.colors['PILL'], relief="flat",
            font=("Microsoft YaHei UI", 10),
            padx=12, pady=7, cursor="hand2",
        ).pack(side="right", padx=(0, 8))
        self._label(
            page,
            "听见每一句，轻松翻译与分享",
            size=10,
            color=self.colors['SECONDARY'],
            bg=self.colors['BG'],
        ).pack(anchor="w", padx=26, pady=(0, 14))

        self.home_columns = tk.Frame(page, bg=self.colors['BG'])
        self.home_columns.pack(fill="both", expand=True, padx=24)
        self.home_columns.bind("<Configure>", lambda event: self._layout_home(event.width))
        card = self.connection_card = self._card(self.home_columns)
        inner = tk.Frame(card, bg=self.colors['CARD'])
        inner.pack(fill="x", padx=18, pady=18)

        status_row = tk.Frame(inner, bg=self.colors['CARD'])
        status_row.pack(fill="x")
        self.status_dot = tk.Canvas(
            status_row, width=12, height=18, bg=self.colors['CARD'], highlightthickness=0
        )
        self.status_dot.create_oval(2, 5, 11, 14, fill=self.colors['BRAND'], outline="")
        self.status_dot.pack(side="left", padx=(0, 7))
        self.status_title = self._label(status_row, "", size=13, weight="bold")
        self.status_title.pack(side="left")
        self.status_detail = self._label(
            inner,
            "",
            size=9,
            color=self.colors['SECONDARY'],
            wraplength=480,
        )
        self.status_detail.pack(fill="x", padx=(19, 0), pady=(4, 10))
        inner.bind(
            "<Configure>",
            lambda event: self.status_detail.configure(wraplength=max(120, event.width - 19)),
        )
        ttk.Separator(inner).pack(fill="x", pady=(0, 12))

        platform_row = tk.Frame(inner, bg=self.colors['CARD'])
        platform_row.pack(fill="x", pady=(1, 6))
        self._label(platform_row, "直播平台", size=10).pack(side="left")
        self.platform_selector = self._combobox(
            platform_row,
            textvariable=self.platform_var,
            values=list(PLATFORMS.values()),
            state="readonly",
            width=12,
            font=("Microsoft YaHei UI", 10),
        )
        self.platform_selector.pack(side="right")
        self.platform_selector.bind(
            "<<ComboboxSelected>>", self._on_platform_changed, add="+"
        )

        input_row = tk.Frame(inner, bg=self.colors['CARD'])
        input_row.pack(fill="x", pady=(4, 6))
        self._label(input_row, "声音来源", size=10).pack(side="left")
        self.audio_input_selector = self._combobox(
            input_row, textvariable=self.audio_input_var,
            values=("直播间声音", "麦克风", "电脑声音"), state="readonly", width=12,
            font=("Microsoft YaHei UI", 10),
        )
        self.audio_input_selector.pack(side="right")
        microphone_row = tk.Frame(inner, bg=self.colors['CARD'])
        microphone_row.pack(fill="x", pady=(0, 6))
        self.microphone_selector = self._combobox(
            microphone_row, textvariable=self.microphone_var,
            values=list(self._microphone_devices), state="readonly",
            font=("Microsoft YaHei UI", 9),
        )
        self.microphone_selector.pack(side="left", fill="x", expand=True)
        self.refresh_microphones_button = self._button(
            microphone_row, text="刷新麦克风", command=self._refresh_microphones,
            bg=self.colors['PILL'], fg=self.colors['SECONDARY'], relief="flat", font=("Microsoft YaHei UI", 9),
        )
        self.refresh_microphones_button.pack(side="right", padx=(6, 0))
        self._label(
            inner, "麦克风和电脑声音可直接使用，无需登录。发送聊天才需要账号。",
            size=9, color=self.colors['SECONDARY'],
        ).pack(fill="x", pady=(0, 6))

        self._label(inner, "直播间链接", size=10).pack(anchor="w", pady=(8, 6))
        self.room_entry = tk.Entry(
            inner,
            textvariable=self.room_url_var,
            font=("Microsoft YaHei UI", 10),
            bg=self.colors['PILL'],
            fg=self.colors['TEXT'],
            insertbackground=self.colors['TEXT'],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.colors['PILL'],
            highlightcolor=self.colors['BRAND'],
        )
        self.room_entry.pack(fill="x", ipady=9, padx=1)
        self.room_entry.bind("<Return>", lambda _event: self.start_session())

        languages = tk.Frame(inner, bg=self.colors['CARD'])
        languages.pack(fill="x", pady=(14, 4))
        source = self._combobox(
            languages,
            textvariable=self.source_language,
            values=list(SOURCE_LANGUAGES),
            state="readonly",
            font=("Microsoft YaHei UI", 10),
        )
        source.pack(side="left", fill="x", expand=True)
        self._label(languages, "→", size=14, color=self.colors['MUTED']).pack(side="left", padx=10)
        target = tk.Frame(languages, bg=self.colors['CARD'])
        target.pack(side="left", fill="x", expand=True)
        self.reading_language_buttons = []
        for index, (name, variable) in enumerate(self.reading_language_vars.items()):
            widget = self._checkbutton(
                target, text=name, variable=variable, command=self._change_reading_languages,
                bg=self.colors['CARD'], fg=self.colors['TEXT'],
                selectcolor=self.colors['PILL'], activebackground=self.colors['CARD'],
                font=("Microsoft YaHei UI", 10),
            )
            widget.grid(row=index // 2, column=index % 2, sticky="w", padx=4, pady=2)
            self.reading_language_buttons.append(widget)
        self._label(
            inner,
            "自动识别原文语言 → 你想阅读的字幕语言",
            size=9,
            color=self.colors['SECONDARY'],
            wraplength=480,
        ).pack(fill="x", pady=(3, 8))

        chat_row = tk.Frame(inner, bg=self.colors['CARD'])
        chat_row.pack(fill="x", pady=(2, 4))
        self._label(chat_row, "发送方式", size=10).pack(side="left")
        self.chat_mode_selector = self._checkbutton(
            chat_row,
            text="自动发送" if self.chat_mode_var.get() == "自动发送" else "手动发送",
            variable=self.chat_mode_var,
            onvalue="自动发送", offvalue="手动确认",
            bg=self.colors['PILL'], fg=self.colors['SECONDARY'], activebackground=self.colors['BRAND_SOFT'],
            selectcolor=self.colors['BRAND_SOFT'], indicatoron=False,
            relief="flat", offrelief="flat", overrelief="flat",
            padx=14, pady=6, cursor="hand2",
            font=("Microsoft YaHei UI", 10),
        )
        self.chat_mode_selector.pack(side="right")
        self._label(
            inner,
            "默认手动审核；开启自动后，每条译文直接发送。",
            size=9,
            color=self.colors['SECONDARY'],
            wraplength=480,
        ).pack(fill="x", pady=(0, 5))

        login_row = tk.Frame(inner, bg=self.colors['CARD'])
        login_row.pack(fill="x", pady=(0, 8))
        self.login_status = self._label(
            login_row, "聊天账号：未登录", size=9, color=self.colors['MUTED']
        )
        self.login_status.pack(side="left", fill="x", expand=True)
        self.login_button = self._button(
            login_row,
            text="登录 / 导入 Cookie",
            command=self.open_login_dialog,
            bg=self.colors['PILL'],
            fg=self.colors['SECONDARY'],
            activebackground=self.colors['LINE'],
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
            padx=10,
            pady=6,
        )
        self.login_button.pack(side="right")

        self.start_button = self._button(
            inner,
            text="▶  开始字幕",
            command=self.start_session,
            bg=self.colors['BRAND'],
            fg="#ffffff",
            activebackground="#4338ca",
            activeforeground="#ffffff",
            disabledforeground="#ffffff",
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 12, "bold"),
            height=1, pady=10,
        )
        self.start_button.pack(fill="x", pady=(0, 10))

        service_row = tk.Frame(inner, bg=self.colors['CARD'])
        service_row.pack(fill="x")
        self.service_label = self._label(
            service_row, self._api_summary(), size=9, color=self.colors['SECONDARY']
        )
        self.service_label.pack(side="left", fill="x", expand=True)
        review_card = self.review_card = self._card(self.home_columns)
        review_inner = tk.Frame(review_card, bg=self.colors['CARD'])
        review_inner.pack(fill="x", padx=18, pady=18)
        self.review_queue_title = self._label(
            review_inner, "实时字幕 / 待处理", size=13, weight="bold"
        )
        self.review_queue_title.pack(fill="x", pady=(0, 5))
        self._label(review_inner, "审核和发送语言", size=9).pack(anchor="w")
        codes = self.subtitle_settings.reading_languages or [TARGET_LANGUAGES[self.target_language.get()]]
        self.chat_language_var = tk.StringVar(value=LANGUAGE_NAMES[self.subtitle_settings.chat_language or codes[0]])
        chat_language = self._combobox(
            review_inner, textvariable=self.chat_language_var,
            values=[LANGUAGE_NAMES[code] for code in codes], state="readonly",
        )
        chat_language.pack(fill="x")
        chat_language.bind("<<ComboboxSelected>>", lambda _event: self._save_chat_options())
        self._label(review_inner, "发送模板", size=9).pack(anchor="w")
        self.chat_template_var = tk.StringVar(value=self.subtitle_settings.chat_template)
        template = tk.Entry(review_inner, textvariable=self.chat_template_var)
        template.pack(fill="x")
        template.bind("<FocusOut>", lambda _event: self._save_chat_options())
        template.bind("<Return>", lambda _event: self._save_chat_options())
        self.transcription_label = self._label(review_inner, "", size=10, color=self.colors['SECONDARY'])
        self.transcription_label.pack(fill="x")
        self.asr_timing_label = self._label(review_inner, "", size=9, color=self.colors['MUTED'])
        self.asr_timing_label.pack(fill="x")
        queue_row = tk.Frame(review_inner, bg=self.colors['CARD'])
        queue_row.pack(fill="x", pady=(0, 10))
        self.review_queue_text = tk.Text(
            queue_row, height=10, wrap="word", bg=self.colors['CARD'], fg=self.colors['SECONDARY'],
            relief="flat", padx=10, pady=10, font=("Microsoft YaHei UI", 10),
            state="disabled",
        )
        queue_scroll = ttk.Scrollbar(
            queue_row, orient="vertical", command=self.review_queue_text.yview
        )
        queue_scroll.pack(side="right", fill="y")
        self.review_queue_text.configure(yscrollcommand=queue_scroll.set)
        self.review_queue_text.pack(side="left", fill="x", expand=True)
        self.caption_text = self.review_queue_text
        self.caption_text.tag_configure("original", foreground=self.colors['MUTED'], spacing1=8)
        self.caption_text.tag_configure("translated", foreground=self.colors['TEXT'], spacing3=12)
        self._render_transcription()
        ttk.Separator(review_inner).pack(fill="x", pady=(0, 12))
        self._label(
            review_inner, "当前原文（参考）", size=9, color=self.colors['SECONDARY']
        ).pack(fill="x")
        self.original_chat_text = tk.Text(
            review_inner, height=2, wrap="word", bg=self.colors['CARD'], fg=self.colors['SECONDARY'],
            relief="flat", padx=8, pady=4, font=("Microsoft YaHei UI", 10),
            state="disabled",
        )
        self.original_chat_text.pack(fill="x", pady=(0, 6))
        review_header = tk.Frame(review_inner, bg=self.colors['CARD'])
        review_header.pack(fill="x")
        self._label(review_header, "当前译文 · 可编辑", size=11, weight="bold").pack(
            side="left"
        )
        self.chat_status = self._label(
            review_header, "", size=9, color=self.colors['SECONDARY'], wraplength=280
        )
        self.chat_status.pack(side="right")
        self.pending_chat_text = tk.Text(
            review_inner,
            height=3,
            wrap="word",
            bg=self.colors['PILL'],
            fg=self.colors['TEXT'],
            relief="flat",
            padx=8,
            pady=6,
            font=("Microsoft YaHei UI", 10),
            highlightthickness=1, highlightbackground=self.colors['LINE'], highlightcolor=self.colors['BRAND'],
            insertbackground=self.colors['BRAND'],
        )
        if self._chat_draft is not None:
            self.pending_chat_text.insert("1.0", self._chat_draft)
        self.pending_chat_text.pack(fill="x", pady=(5, 8))
        review_buttons = tk.Frame(review_inner, bg=self.colors['CARD'])
        review_buttons.pack(fill="x")
        self.skip_chat_button = self._button(
            review_buttons,
            text="跳过",
            command=self._skip_pending_chat,
            bg=self.colors['PILL'],
            fg=self.colors['SECONDARY'],
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
            padx=14,
            pady=8,
            state="disabled",
        )
        self.skip_chat_button.pack(side="right")
        self.send_chat_button = self._button(
            review_buttons,
            text="发送到直播间",
            command=self._send_pending_chat,
            bg=self.colors['BRAND'],
            fg="#ffffff",
            activebackground="#4338ca",
            activeforeground="#ffffff",
            disabledforeground="#c7c3ff",
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=14,
            pady=8,
            state="disabled",
        )
        self.send_chat_button.pack(side="right", padx=(0, 8))
        self._update_login_status()
        self._render_pending_chat()
        self._layout_home(self.root.winfo_width())

        self._set_status_for_home()
        self._label(
            page,
            "声音在本机识别；翻译文字会发给翻译服务。只有你选择发送后，字幕才会发到直播间聊天。",
            size=9,
            color=self.colors['SECONDARY'],
            bg=self.colors['BG'],
            wraplength=520,
        ).pack(fill="x", padx=22, pady=(10, 8))

        self._render_captions()

    def _set_status_for_home(self) -> None:
        if not self._api_ready():
            self._set_status(
                "请先设置翻译服务地址和模型 ID。API Key 按服务要求填写。",
                self.colors['WARN'],
            )
        elif self._session_started_at is not None:
            self._set_status(
                "正在连接直播并加载语音识别。保持此窗口打开即可。",
                self.colors['BRAND'],
            )
        else:
            self._set_status("准备好了。点下面的按钮开始翻译直播。", self.colors['BRAND'])

    def _set_status(self, detail: str, color: str) -> None:
        if not self.status_title or not self.status_title.winfo_exists():
            return
        title = {
            self.colors['BRAND']: "可以开始了",
            self.colors['OK']: "字幕正在运行",
            self.colors['WARN']: "还需要设置",
            self.colors['ERROR']: "暂时无法继续",
            self.colors['MUTED']: "字幕已停止",
        }.get(color, "字幕状态")
        self.status_dot.delete("all")
        self.status_dot.create_oval(2, 5, 11, 14, fill=color, outline="")
        self.status_title.configure(text=title)
        self.status_detail.configure(text=detail)

    def _set_start_button(self, running: bool) -> None:
        if not self.start_button or not self.start_button.winfo_exists():
            return
        if running:
            self.start_button.configure(
                text="■  停止字幕",
                command=self.stop_session,
                bg=self.colors["CARD"],
                fg=self.colors['ERROR'],
                activebackground=self.colors['PILL'],
                activeforeground=self.colors['ERROR'],
                highlightthickness=1,
                highlightbackground=self.colors['LINE'],
            )
            self.room_entry.configure(state="disabled")
        else:
            self.start_button.configure(
                text="▶  开始字幕",
                command=self.start_session,
                bg=self.colors['BRAND'],
                fg="#14142a" if self.interface_preferences.theme == "dark" else "#ffffff",
                activebackground=self.colors["BRAND"] if self.interface_preferences.theme == "dark" else "#4338ca",
                activeforeground="#14142a" if self.interface_preferences.theme == "dark" else "#ffffff",
                highlightthickness=0,
            )
            self.room_entry.configure(state="normal")
        if self.platform_selector and self.platform_selector.winfo_exists():
            self.platform_selector.configure(state="readonly" if not running else "disabled")
        if self.chat_mode_selector and self.chat_mode_selector.winfo_exists():
            self.chat_mode_selector.configure(state="normal" if not running else "disabled")
        if self.login_button and self.login_button.winfo_exists():
            self.login_button.configure(state="disabled" if running else "normal")
        for button in self.reading_language_buttons:
            if button.winfo_exists():
                button.configure(state="disabled" if running else "normal")
        for selector in (self.audio_input_selector, self.microphone_selector):
            if selector and selector.winfo_exists():
                selector.configure(state="disabled" if running else "readonly")
        if self.refresh_microphones_button and self.refresh_microphones_button.winfo_exists():
            self.refresh_microphones_button.configure(state="disabled" if running else "normal")

    def _set_preferences(self) -> None:
        source = SOURCE_LANGUAGES[self.source_language.get()]
        target = TARGET_LANGUAGES[self.target_language.get()]
        self.app.set_preferences(
            {
                "source_language": source,
                "target_language": target,
                "whisper_model": self.app.prefs.whisper_model,
                "translation_model": self.api_config.get("OPENAI_MODEL", ""),
                "api_keys": {
                    "openai": self.api_config.get("OPENAI_API_KEY", ""),
                    "jev": self.api_config.get("JEV_API_KEY", ""),
                },
                "subtitle_settings": self.subtitle_settings,
                "translation_base_url": self.api_config.get("OPENAI_API_BASE", ""),
            }
        )

    def _change_reading_languages(self) -> None:
        codes = [TARGET_LANGUAGES[name] for name, variable in self.reading_language_vars.items() if variable.get()]
        try:
            if not codes:
                raise ValueError("请至少选择一种字幕语言。")
            if self._session_started_at is not None:
                raise ValueError("停止当前字幕后再修改阅读语言。")
            settings = replace(
                self.subtitle_settings, reading_languages=codes,
                chat_language=self.subtitle_settings.chat_language if self.subtitle_settings.chat_language in codes else codes[0],
            )
            settings.save(SUBTITLE_SETTINGS_FILE)
        except (ValueError, OSError) as error:
            log.error("Reading languages not saved: %s", type(error).__name__)
            saved = self.subtitle_settings.reading_languages or [TARGET_LANGUAGES[self.target_language.get()]]
            for name, variable in self.reading_language_vars.items():
                variable.set(TARGET_LANGUAGES[name] in saved)
            self._dialog("showerror", "无法保存字幕设置", str(error), parent=self.root)
            return
        self.subtitle_settings = settings
        self.target_language.set(next(name for name, code in TARGET_LANGUAGES.items() if code == codes[0]))
        self.show_home()

    def _save_chat_options(self) -> None:
        language = next(code for code, name in LANGUAGE_NAMES.items() if name == self.chat_language_var.get())
        try:
            current = self.subtitle_settings.chat_language or (
                self.subtitle_settings.reading_languages or [TARGET_LANGUAGES[self.target_language.get()]]
            )[0]
            if self._session_started_at is not None and language != current:
                raise ValueError("停止当前字幕后再修改阅读语言。")
            settings = replace(
                self.subtitle_settings, chat_language=language, chat_template=self.chat_template_var.get(),
                chat_template_custom=self.subtitle_settings.chat_template_custom or self.chat_template_var.get() != self.subtitle_settings.chat_template,
            )
            settings.save(SUBTITLE_SETTINGS_FILE)
        except (ValueError, OSError) as error:
            log.error("Chat options not saved: %s", type(error).__name__)
            self._dialog("showerror", "无法保存字幕设置", str(error), parent=self.root)
            return
        self.subtitle_settings = settings
        self.app.prefs.subtitle_settings = settings

    def start_session(self) -> None:
        if self._stopping:
            return
        if self._session_started_at is not None:
            self.stop_session()
            return
        if not self._api_ready():
            self._dialog('showinfo', 
                "还不能开始",
                "请先点「设置」，填写翻译服务地址和模型 ID。API Key 按服务要求填写。",
                parent=self.root,
            )
            self.show_settings()
            return

        room_url = self.room_url_var.get().strip()
        microphone = self.audio_input_var.get() == "麦克风"
        system_audio = self.audio_input_var.get() == "电脑声音"
        local_audio = microphone or system_audio
        platform = self._resolve_room_platform()
        if platform is None:
            return
        chat_mode = "automatic" if self.chat_mode_var.get() == "自动发送" else "manual"
        cookies = self._cookies.get(platform)
        if not room_url and (not local_audio or chat_mode == "automatic"):
            self._dialog('showinfo', "需要直播间地址", "收听直播或发送弹幕时，请填写直播间链接。", parent=self.root)
            self.room_entry.focus_set()
            return
        if chat_mode == "automatic" and not cookies:
            self._dialog('showinfo', 
                "需要登录",
                "发送翻译弹幕前，需要先登录当前直播平台。Cookie 只会保存在本次运行中。",
                parent=self.root,
            )
            self.open_login_dialog()
            return
        if chat_mode == "automatic" and not self._dialog('askyesno', 
            "确认自动发送",
            "每条完成的翻译都会直接发送到直播间聊天。确定继续吗？",
            parent=self.root,
        ):
            return
        try:
            if local_audio and (not cookies or not room_url):
                self.app.chat_sender = None
                self.app.chat_mode = "manual"
            elif platform == "youtube":
                video_id = self._youtube_video_id(room_url)
                self.app.configure_youtube_stream(
                    room_url, video_id, cookies=cookies, chat_mode=chat_mode,
                    page_id=self._youtube_page_id,
                )
            elif platform == "missevan":
                self.app.configure_missevan_stream(room_url, cookies=cookies, chat_mode=chat_mode)
            else:
                self._validate_bilibili_url(room_url)
                self.app.configure_bilibili_stream(
                    room_url, cookies=cookies, chat_mode=chat_mode
                )
            if microphone:
                self.app.configure_microphone(self._microphone_devices[self.microphone_var.get()])
            elif system_audio:
                self.app.configure_system_audio()
            self._set_preferences()
        except ValueError as error:
            self._dialog('showerror', "直播间地址不正确", str(error), parent=self.root)
            self.room_entry.focus_set()
            return

        self.room_url = room_url
        self._persist_home_preferences(room_url)
        self._session_started_at = time.monotonic()
        self._reported_error = False
        self._last_captions.clear()
        self._latest_transcription = ""
        self._asr_latency_ms = None
        self._render_transcription()
        self._render_captions()
        self._set_start_button(True)
        self._set_status(
            "正在加载语音识别并打开麦克风。就绪后直接说话即可。" if microphone
            else "正在加载语音识别并捕获电脑声音。电脑播放的声音会被识别和翻译。" if system_audio
            else "正在连接直播并加载语音识别。保持此窗口打开即可。",
            self.colors['BRAND'],
        )
        try:
            options = self.subtitle_settings
            store = SessionRecords(
                options.record_directory(RECORDS_ROOT), options.save_captions, options.diagnostics,
                platform=self._platform_key(), room=room_url,
                audio_source="microphone" if microphone else "system" if system_audio else "stream",
                enabled=options.save_records,
            )
            self._record_stores[store.session_id] = store
            self.app.host.records = store
            self.app.start_session()
        except Exception as error:
            self._session_started_at = None
            self._set_start_button(False)
            self._set_status(self._friendly_error(str(error)), self.colors['ERROR'])

    def stop_session(self) -> None:
        if self._session_started_at is None or self._stopping:
            return
        self._stopping = True
        self._set_status("正在停止字幕…", self.colors['MUTED'])
        if self.start_button and self.start_button.winfo_exists():
            self.start_button.configure(
                state="disabled",
                text="正在停止…",
                bg=self.colors['PILL'],
                fg=self.colors['MUTED'],
            )
        threading.Thread(target=self.app.stop_session, daemon=True).start()

    def _persist_home_preferences(self, room_url: str) -> None:
        values = {
            "SOURCE_LANGUAGE": SOURCE_LANGUAGES[self.source_language.get()],
            "TARGET_LANGUAGE": TARGET_LANGUAGES[self.target_language.get()],
            "LIVE_ROOM_URL": room_url,
            "LIVE_PLATFORM": PLATFORM_IDS[self._platform_key()],
            "CHAT_MODE": self.chat_mode_var.get(),
            "AUDIO_INPUT": self.audio_input_var.get(),
        }
        self._room_urls[self._platform_key()] = room_url
        try:
            self._write_env(values)
        except OSError as error:
            log.error("Could not save language or room preferences: %s", error)
            self._dialog('showwarning', 
                "设置未能保存",
                "本次仍会开始翻译，但直播间和语言选择无法保存到下次使用。",
                parent=self.root,
            )

    @staticmethod
    def _validate_bilibili_url(room_url: str) -> None:
        if room_url.isdecimal():
            return
        parsed = urlparse(room_url)
        if parsed.hostname not in ("live.bilibili.com", "www.bilibili.com"):
            raise ValueError("请输入有效的哔哩哔哩直播间链接或房间号。")
        room_id = parsed.path.strip("/").split("/", 1)[0]
        if not room_id.isdecimal():
            raise ValueError("直播间链接中没有有效的房间号。")

    @staticmethod
    def _youtube_video_id(room_url: str) -> str:
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

    def show_settings(self) -> None:
        page = self._clear_screen()
        header = tk.Frame(page, bg=self.colors['BG'])
        header.pack(fill="x", padx=18, pady=(16, 14))
        self._interface_controls(header)
        self._button(
            header,
            text="‹ 返回",
            command=self.show_home,
            bg=self.colors['BG'],
            fg=self.colors['SECONDARY'],
            activebackground=self.colors['BG'],
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left")
        self._label(header, "设置", size=16, weight="bold", bg=self.colors['BG']).pack(
            side="left", expand=True, padx=8
        )
        self._button(
            header, text="保存字幕设置", command=self._save_subtitle_settings,
            bg=self.colors['BRAND'], fg="#ffffff", relief="flat", font=("Microsoft YaHei UI", 9),
        ).pack(side="right", padx=8)
        tab_bar = tk.Frame(page, bg=self.colors['PILL'], padx=4, pady=4)
        tab_bar.pack(anchor="center", pady=(4, 10))
        notebook = ttk.Notebook(page, style="Pills.TNotebook")
        notebook.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        tabs = {}
        self.settings_notebook = notebook
        self.settings_canvases = {}
        self.settings_contents = {}
        tab_buttons = []
        for name in ("字幕", "翻译", "页面", "记录", "关于"):
            frame = tk.Frame(notebook, bg=self.colors['BG'])
            notebook.add(frame, text=self.tr(name))
            button = self._button(
                tab_bar, text=name, command=lambda f=frame: notebook.select(f),
                relief="flat", bd=0, font=("Microsoft YaHei UI", 10),
                padx=18, pady=6,
            )
            button.pack(side="left", padx=2)
            tab_buttons.append((str(frame), button))
            canvas = tk.Canvas(frame, bg=self.colors['BG'], highlightthickness=0)
            scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
            scrollbar.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)
            canvas.configure(yscrollcommand=scrollbar.set)
            content = tk.Frame(canvas, bg=self.colors['BG'])
            window = canvas.create_window((0, 10), window=content, anchor="nw")
            content.bind("<Configure>", lambda event, c=canvas: c.configure(scrollregion=c.bbox("all")))
            def resize(event, c=canvas, w=window):
                width = min(760, max(1, event.width - 32))
                c.itemconfigure(w, width=width)
                c.coords(w, max(0, (event.width - width) // 2), 10)
            canvas.bind("<Configure>", resize)
            self.settings_canvases[str(frame)] = canvas
            self.settings_contents[name] = content
            tabs[name] = content

        def refresh_tabs(_event=None) -> None:
            if not tab_bar.winfo_exists():
                self._refresh_settings_tabs = None
                return
            tab_bar.configure(bg=self.colors['PILL'])
            selected = notebook.select()
            for frame_name, button in tab_buttons:
                active = frame_name == selected
                button.configure(
                    bg=self.colors['CARD'] if active else self.colors['PILL'],
                    fg=self.colors['BRAND'] if active else self.colors['SECONDARY'],
                    activebackground=self.colors['CARD'],
                    activeforeground=self.colors['BRAND'],
                    font=("Microsoft YaHei UI", 10, "bold" if active else "normal"),
                )

        self._refresh_settings_tabs = refresh_tabs
        notebook.bind("<<NotebookTabChanged>>", refresh_tabs)
        refresh_tabs()

        def scroll_settings(event):
            if event.widget.winfo_class() not in ("Text", "TCombobox", "TSpinbox"):
                selected = notebook.select()
                self.settings_canvases[selected].yview_scroll(-int(event.delta / 120), "units")
        self.root.bind("<MouseWheel>", scroll_settings)
        self._build_feature_settings(tabs)
        outer = tabs["翻译"]
        self._label(outer, "LLM API", size=9, color=self.colors['MUTED'], bg=self.colors['BG']).pack(
            anchor="w", padx=8, pady=(0, 6)
        )
        card = self._card(outer)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=self.colors['CARD'])
        inner.pack(fill="x", padx=16, pady=14)
        self._label(
            inner,
            "填写一个 OpenAI 兼容的翻译服务。声音识别在本机完成，只有识别出的文字会发送给此服务。",
            size=9,
            color=self.colors['SECONDARY'],
            wraplength=480,
        ).pack(fill="x", pady=(0, 12))

        self.base_var = tk.StringVar(value=self.api_config.get("OPENAI_API_BASE", ""))
        self.model_var = tk.StringVar(value=self.api_config.get("OPENAI_MODEL", ""))
        self.key_var = tk.StringVar()
        self._setting_field(inner, "服务地址（OpenAI 兼容）", self.base_var)
        self._label(inner, "模型 ID", size=10, weight="bold").pack(
            anchor="w", pady=(10, 4)
        )
        model_row = tk.Frame(inner, bg=self.colors['CARD'])
        model_row.pack(fill="x")
        self.model_combo = ttk.Combobox(
            model_row,
            textvariable=self.model_var,
            values=[],
            font=("Microsoft YaHei UI", 10),
        )
        self.model_combo.pack(side="left", fill="x", expand=True, ipady=5, padx=(1, 8))
        self.detect_models_button = self._button(
            model_row,
            text="检测模型",
            command=self.detect_models,
            bg=self.colors['PILL'],
            fg=self.colors['SECONDARY'],
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
            padx=10,
            pady=8,
        )
        self.detect_models_button.pack(side="right")
        self._label(
            inner,
            "填好服务地址（和 API Key）后点「检测模型」，即可从列表中选择。",
            size=9,
            color=self.colors['SECONDARY'],
            wraplength=480,
        ).pack(anchor="w", pady=(4, 0))

        self._label(inner, "API Key", size=10, weight="bold").pack(
            anchor="w", pady=(12, 4)
        )
        key_row = tk.Frame(inner, bg=self.colors['CARD'])
        key_row.pack(fill="x")
        self.key_entry = tk.Entry(
            key_row,
            textvariable=self.key_var,
            show="●",
            font=("Microsoft YaHei UI", 10),
            bg=self.colors['PILL'],
            fg=self.colors['TEXT'],
            insertbackground=self.colors['TEXT'],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.colors['PILL'],
            highlightcolor=self.colors['BRAND'],
        )
        self.key_entry.pack(side="left", fill="x", expand=True, ipady=9, padx=(0, 8))
        self.key_shown = False
        self._button(
            key_row,
            text="显示",
            command=self._toggle_key_visibility,
            bg=self.colors['PILL'],
            fg=self.colors['SECONDARY'],
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
            padx=10,
            pady=8,
        ).pack(side="right")
        key_saved = bool(self.api_config.get("OPENAI_API_KEY"))
        self.key_status = self._label(
            inner,
            "已有密钥已保存；留空会继续使用。"
            if key_saved
            else "API Key 可选；无 Key 的服务可以留空。",
            size=9,
            color=self.colors['OK'] if key_saved else self.colors['WARN'],
        )
        self.key_status.pack(anchor="w", pady=(4, 2))

        self._label(
            inner,
            "服务地址示例：https://api.openai.com/v1\nAPI Key 只保存在这台电脑的配置文件中，不会发送给直播间。",
            size=9,
            color=self.colors['SECONDARY'],
            wraplength=480,
        ).pack(anchor="w", pady=(6, 12))
        self.settings_result = self._label(inner, "", size=9, color=self.colors['SECONDARY'])
        self.settings_result.pack(anchor="w", fill="x", pady=(0, 6))

        buttons = tk.Frame(inner, bg=self.colors['CARD'])
        buttons.pack(fill="x")
        self.test_button = self._button(
            buttons,
            text="测试连接",
            command=self.test_connection,
            bg=self.colors['BRAND'],
            fg="#ffffff",
            activebackground="#4338ca",
            activeforeground="#ffffff",
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=16,
            pady=8,
        )
        self.test_button.pack(side="right")
        self._button(
            buttons,
            text="清除已保存的 Key",
            command=self.clear_saved_key,
            bg=self.colors['CARD'],
            fg=self.colors['ERROR'],
            activebackground=self.colors['CARD'],
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        self._button(
            buttons,
            text="保存",
            command=self.save_settings,
            bg=self.colors['CARD'],
            fg=self.colors['TEXT'],
            activebackground=self.colors['PILL'],
            relief="solid",
            bd=1,
            cursor="hand2",
            font=("Microsoft YaHei UI", 10),
            padx=16,
            pady=7,
        ).pack(side="right", padx=(0, 8))

    def _build_feature_settings(self, tabs: dict[str, tk.Frame]) -> None:
        values = asdict(self.subtitle_settings)
        self._editing_presets = values.pop("presets")
        values.pop("reading_languages")
        self._option_vars = {}
        for name, value in values.items():
            variable = (
                tk.BooleanVar(value=value) if type(value) is bool
                else tk.IntVar(value=value) if type(value) is int
                else tk.DoubleVar(value=value) if isinstance(value, float)
                else tk.StringVar(value=value)
            )
            self._option_vars[name] = variable

        def section(tab: str, title: str) -> tk.Frame:
            card = self._card(tabs[tab])
            card.pack(fill="x", pady=(0, 16))
            inner = tk.Frame(card, bg=self.colors['CARD'])
            inner.pack(fill="x", padx=20, pady=18)
            self._label(inner, title, size=12, weight="bold").pack(fill="x", pady=(0, 12))
            return inner

        def toggle(parent: tk.Widget, name: str, text: str) -> None:
            self._checkbutton(
                parent, text=text, variable=self._option_vars[name],
                bg=self.colors['CARD'], fg=self.colors['TEXT'], activebackground=self.colors['CARD'], anchor="w",
                font=("Microsoft YaHei UI", 10), wraplength=460, justify="left",
            ).pack(fill="x", pady=3)

        def slider(parent: tk.Widget, name: str, text: str, low: float, high: float, step: float = 1) -> None:
            self._label(parent, text, size=10, color=self.colors['SECONDARY']).pack(fill="x", pady=(8, 6))
            row = tk.Frame(parent, bg=self.colors["CARD"])
            row.pack(fill="x", pady=(0, 8))
            variable = self._option_vars[name]
            scale_value = tk.DoubleVar(master=self.root, value=variable.get())
            def change(value):
                snapped = round(round(float(value) / step) * step, 2)
                variable.set(int(snapped) if step == 1 else snapped)
            scale = ttk.Scale(row, from_=low, to=high, variable=scale_value, command=change)
            scale.pack(side="left", fill="x", expand=True, padx=(0, 16), pady=4)
            entry = ttk.Spinbox(
                row, from_=low, to=high, increment=step, textvariable=variable,
                width=6, justify="center", font=("Microsoft YaHei UI", 10),
            )
            entry.pack(side="right")
            def sync(*_):
                try:
                    value = variable.get()
                except tk.TclError:
                    return  # A numeric field may be temporarily empty while being edited.
                scale_value.set(value)
            trace = variable.trace_add("write", sync)
            row.bind("<Destroy>", lambda event: variable.trace_remove("write", trace) if event.widget is row else None)

        appearance = section("字幕", "字幕外观（独立字幕窗口）")
        self._combobox(
            appearance, textvariable=self._option_vars["palette"],
            values=list(PALETTES), state="readonly",
        ).pack(fill="x", pady=5)
        slider(appearance, "font_size", "文字大小", 10, 40)
        slider(appearance, "opacity", "背景浓淡 / 窗口不透明度（0.1 到 1）", 0.1, 1, 0.01)
        self._button(
            appearance, text="保存并预览字幕窗口",
            command=lambda: self.open_overlay() if self._save_subtitle_settings() else None,
            bg=self.colors['PILL'], relief="flat",
        ).pack(fill="x", pady=5)
        display = section("字幕", "显示")
        toggle(display, "show_original", "同时显示原文（聊天审核原文仍保留）")
        toggle(display, "show_stats", "显示识别和翻译用时")
        bounds = section("字幕", "字幕大小和保留句数")
        slider(bounds, "width_percent", "字幕宽度 · 屏幕百分比", 20, 100)
        slider(bounds, "height_percent", "字幕高度 · 屏幕百分比", 5, 80)
        slider(bounds, "retained_sentences", "保留翻译数量（包括待处理；超出时移除最早条目）", 1, 200)

        content = section("翻译", "模式 / 背景与术语")
        self.preset_selector = self._combobox(
            content, textvariable=self._option_vars["preset"],
            values=list(default_presets()), state="readonly",
        )
        self.preset_selector.pack(fill="x", pady=5)
        self._button(content, text="编辑背景和术语表", command=self._edit_preset, bg=self.colors['PILL'], relief="flat").pack(side="left")
        context = section("翻译", "结合上下文翻译")
        toggle(context, "use_context", "参考之前已完成的原文和译文")
        slider(context, "previous_sentences", "参考前面几句（越多可能越慢）", 0, 8)
        behavior = section("翻译", "字幕怎么出现")
        self._combobox(
            behavior, textvariable=self._option_vars["display_mode"],
            values=("边听边出", "说完再出"), state="readonly",
        ).pack(fill="x", pady=5)
        toggle(behavior, "deduplicate", "去掉同一条识别结果内重复的字句（也可能去掉真实重复）")
        toggle(behavior, "ignore_onomatopoeia", "忽略拟声词 · 仅跳过整句笑声、叫声或常见拟声词，不翻译或发送")
        toggle(behavior, "semantic_sound_filter", "拟声词语义过滤 · 使用翻译 API 判断中日英整句拟声词及语气声，增加费用和延迟，等待整句后显示")
        toggle(behavior, "distinguish_speakers", "区分说话人 · 默认关闭，仅字幕和记录显示标签；短句或多人重叠可能分错，停止字幕后修改")
        decisions = section("翻译", "在线 Decisions 模型辅助（可选）")
        self._label(
            decisions, "开启后会把原文/译文发给 OpenCode Zen，不发送音频。网络失败会明确提示并跳过辅助。",
            size=9, color=self.colors['SECONDARY'],
        ).pack(fill="x")
        toggle(decisions, "smart_segmentation", "智能断句 · 暂停时判断是否说完，最多额外等待约 1 秒")
        toggle(decisions, "check_translation", "检查译文 · 有问题时重译一次，可能增加延迟")
        self._label(decisions, "OpenCode Zen（免费，不用 key）", color=self.colors['SECONDARY']).pack(fill="x", pady=5)

        layout = section("页面", "字幕窗口")
        self._label(
            layout, "主页的「字幕窗口」可单独显示字幕并供 OBS 捕获。颜色、字号、透明度和尺寸在「字幕」页设置；窗口可拖动和关闭。",
            size=10,
        ).pack(fill="x")
        self._label(layout, "主页保留原文、待审核队列和一个可编辑聊天框。灰色字幕是仍可能修订的草稿。", size=9, color=self.colors['SECONDARY']).pack(fill="x", pady=8)

        saving = section("记录", "字幕文本 / 使用记录")
        toggle(saving, "save_records", "保存字幕和发送记录（用于导出时间轴）")
        toggle(saving, "save_captions", "发送成功或跳过时保存原文和当前译文（下次开始字幕生效）")
        toggle(saving, "diagnostics", "记录每次使用：原文、翻译提示词、译文、Decisions 问答（不含音频或 key；下次生效）")
        self._label(
            saving, "记录默认关闭。开启后，成功发送的消息会保存到本机，用于剪辑导出；关闭时不写入任何记录文件。记录可能包含私人对话，请谨慎分享。",
            size=9, color=self.colors['SECONDARY'],
        ).pack(fill="x", pady=5)
        self._button(saving, text="打开本地记录文件夹", command=self._open_records, bg=self.colors['PILL'], relief="flat").pack(fill="x")
        self._label(saving, "记录保存文件夹", size=10, weight="bold").pack(anchor="w", pady=(10, 4))
        self.records_folder_label = self._label(
            saving, str(self.subtitle_settings.record_directory(RECORDS_ROOT)), size=9,
        )
        self.records_folder_label.pack(fill="x")
        self._button(saving, text="选择文件夹", command=self._choose_records_folder, bg=self.colors['PILL'], relief="flat").pack(fill="x")
        self._label(
            saving, "文件夹选择自动保存，从下次开始字幕生效；当前会话保留在原文件夹，不移动已有记录。",
            size=9, color=self.colors['SECONDARY'],
        ).pack(fill="x")
        export = section("记录", "Final Cut Pro / 剪映：已审核字幕导出")
        self._label(
            export, "时间轴自动从开始字幕时计时。导出已发送和已跳过字幕，使用审核后的文字；CSV 标明发送或跳过。",
            size=9, color=self.colors['SECONDARY'],
        ).pack(fill="x")
        self._export_sessions = {
            name: store for name, store in self._record_stores.items()
            if store.enabled and (store.sent or store.reviewed)
        }
        roots = {RECORDS_ROOT, self.subtitle_settings.record_directory(RECORDS_ROOT)}
        roots.update(store.directory.parent for store in self._record_stores.values())
        for folder in roots:
            if not folder.exists():
                continue
            for directory in sorted(folder.iterdir()):
                if directory.is_dir() and any(
                    (directory / name).is_file() for name in ("sent_messages.jsonl", "captions.jsonl")
                ):
                    self._export_sessions.setdefault(directory.name, directory)
        self.export_session_var = tk.StringVar(
            value=next(reversed(self._export_sessions), "")
        )
        self._combobox(
            export, textvariable=self.export_session_var,
            values=list(self._export_sessions), state="readonly",
        ).pack(fill="x", pady=5)
        self._button(
            export, text="导出已审核 SRT + CSV", command=self._export_sent,
            bg=self.colors['BRAND'], fg="#ffffff", relief="flat",
        ).pack(fill="x", pady=5)
        self.export_result = self._label(export, "", size=9, color=self.colors['SECONDARY'])
        self.export_result.pack(fill="x")
        about = section("关于", "同传字幕")
        self._label(
            about, "本机语音识别 · 自选翻译服务 · 哔哩哔哩 / YouTube / 猫耳FM聊天\n借鉴 Simul Subtitle 的使用方式，Python 实现。\n接收时间不是源网站的直播时间码：直播缓冲/网络延迟仍需在剪辑软件中校正。SRT 不包含样式。",
            size=10,
        ).pack(fill="x")

    def _feature_values(self) -> SubtitleSettings:
        values = {**asdict(self.subtitle_settings), **{name: variable.get() for name, variable in self._option_vars.items()}}
        values["presets"] = self._editing_presets
        settings = SubtitleSettings(**values)
        settings.validate()
        if settings.recording_start.strip():
            recording_clock(settings.recording_start)
        return settings

    def _save_subtitle_settings(self) -> bool:
        try:
            settings = self._feature_values()
            if (getattr(self, "_session_started_at", None) is not None
                    and settings.distinguish_speakers != self.subtitle_settings.distinguish_speakers):
                raise ValueError("请先停止字幕再修改说话人设置。")
            if settings.distinguish_speakers:
                from .speaker_tracking import model_ready, download_model

                if not model_ready():
                    if getattr(self, "_speaker_downloading", False):
                        return False
                    if not self._dialog(
                        'askyesno', "区分说话人",
                        "首次开启将下载约 28 MB 本机声纹模型。音频不上传，下载期间请等待。标签不加入弹幕。继续吗？",
                        parent=self.root,
                    ):
                        return False
                    self._speaker_downloading = True

                    def download() -> None:
                        try:
                            download_model()
                        except (OSError, RuntimeError) as error:
                            log.error("Speaker model download failed: %s", type(error).__name__)
                            def failed(message=str(error)) -> None:
                                self._speaker_downloading = False
                                self._dialog('showerror', "下载说话人模型失败", message, parent=self.root)
                            self.root.after(0, failed)
                        else:
                            def finished() -> None:
                                self._speaker_downloading = False
                                self._save_subtitle_settings()
                            self.root.after(0, finished)

                    threading.Thread(target=download, daemon=True).start()
                    return False
            settings.save(SUBTITLE_SETTINGS_FILE)
        except (ValueError, OSError, tk.TclError) as error:
            log.error("Subtitle settings save failed: %s", type(error).__name__)
            self._dialog('showerror', "无法保存字幕设置", str(error), parent=self.root)
            return False
        self.subtitle_settings = settings
        self._last_captions = self._last_captions[-settings.retained_sentences * max(1, len(settings.reading_languages)):]
        self._trim_pending_chat()
        self._render_pending_chat()
        self._render_captions()
        self._render_transcription()
        self._render_overlay()
        self._dialog('showinfo', 
            "字幕设置已保存", "外观立即生效；内容、断句、译文检查和记录开关从下次开始字幕生效。",
            parent=self.root,
        )
        return True

    def _edit_preset(self) -> None:
        name = self._option_vars["preset"].get()
        content = self._editing_presets.get(name, {"background": "", "glossary": ""})
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr(name))
        dialog.geometry("520x450")
        fields = {}
        for field, label in (("background", "背景说明"), ("glossary", "术语表（每行一个，例如 原词: 译法）")):
            self._make_label(dialog, text=label).pack(anchor="w", padx=10, pady=(8, 2))
            widget = tk.Text(dialog, height=7, wrap="word")
            widget.insert("1.0", content[field])
            widget.pack(fill="both", expand=True, padx=10)
            fields[field] = widget

        def save() -> None:
            self._editing_presets[name] = {
                field: widget.get("1.0", "end-1c") for field, widget in fields.items()
            }
            self.preset_selector.configure(values=list(default_presets()))
            self._option_vars["preset"].set(name)
            dialog.destroy()

        self._button(dialog, text="应用（再点保存字幕设置）", command=save).pack(pady=8)

    def _records_off_hint(self) -> None:
        self._dialog(
            'showinfo', "记录未开启",
            "请先在「设置 → 记录」打开「保存字幕和发送记录（用于导出时间轴）」并保存；从下次开始字幕起会保存记录。",
            parent=self.root,
        )

    def _open_records(self) -> None:
        folder = self.subtitle_settings.record_directory(RECORDS_ROOT)
        if not folder.exists():
            if not self.subtitle_settings.save_records:
                self._records_off_hint()
                return
            self._dialog('showinfo', "没有记录", "开始字幕并保存文本或成功发送消息后，这里会出现记录。", parent=self.root)
            return
        try:
            os.startfile(folder)
        except OSError as error:
            log.error("Could not open records folder: %s", type(error).__name__)
            self._dialog('showerror', "无法打开记录", "请手动打开本应用的 records 文件夹。", parent=self.root)

    def _choose_records_folder(self) -> None:
        folder = filedialog.askdirectory(
            parent=self.root, title=self.tr("选择记录保存文件夹"),
            initialdir=str(self.subtitle_settings.record_directory(RECORDS_ROOT)), mustexist=True,
        )
        if not folder:
            return
        try:
            import tempfile

            with tempfile.TemporaryFile(dir=folder):
                pass
            settings = replace(self.subtitle_settings, records_folder=folder)
            settings.save(SUBTITLE_SETTINGS_FILE)
        except (OSError, ValueError) as error:
            log.error("Record folder save failed: %s", type(error).__name__)
            self._dialog('showerror', "无法保存字幕设置", str(error), parent=self.root)
            return
        self.subtitle_settings = settings
        self._option_vars["records_folder"].set(folder)
        self.records_folder_label.configure(text=folder)

    def _export_sent(self) -> None:
        try:
            selected = self._export_sessions.get(self.export_session_var.get())
            if selected is None and not self.subtitle_settings.save_records:
                self._records_off_hint()
                return
            if selected is None:
                raise ValueError("请选择有已发送或已跳过字幕的会话。")
            store = SessionRecords.restore(selected) if isinstance(selected, Path) else selected
            directory = filedialog.askdirectory(title="选择 SRT / CSV 导出文件夹", parent=self.root)
            if not directory:
                return
            srt, csv_path = store.export(Path(directory), include_skipped=True)
        except (OSError, ValueError, TypeError, KeyError) as error:
            log.error("Sent subtitle export failed: %s", type(error).__name__)
            self._dialog('showerror', "导出失败", str(error), parent=self.root)
            return
        self.export_result.configure(text=f"已导出：{srt.name}\n{csv_path.name}", fg=self.colors['OK'])

    def _setting_field(
        self,
        parent: tk.Widget,
        label: str,
        variable: tk.StringVar,
    ) -> None:
        self._label(parent, label, size=10, weight="bold").pack(
            anchor="w", pady=(10, 4)
        )
        entry = tk.Entry(
            parent,
            textvariable=variable,
            font=("Microsoft YaHei UI", 10),
            bg=self.colors['PILL'],
            fg=self.colors['TEXT'],
            insertbackground=self.colors['TEXT'],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.colors['PILL'],
            highlightcolor=self.colors['BRAND'],
        )
        entry.pack(fill="x", ipady=9, padx=1)

    def _toggle_key_visibility(self) -> None:
        self.key_shown = not self.key_shown
        self.key_entry.configure(show="" if self.key_shown else "●")

    def _config_values(self) -> tuple[str, str, str]:
        base = self.base_var.get().strip().rstrip("/")
        model = self.model_var.get().strip()
        key = self.key_var.get().strip() or self.api_config.get("OPENAI_API_KEY", "")
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("请填写有效的服务地址，例如 https://api.openai.com/v1。")
        if not model or any(char.isspace() for char in model):
            raise ValueError("请填写正确的模型 ID。")
        return base, model, key

    def _write_env(self, values: dict[str, str]) -> None:
        secret_store.write_env(ENV_FILE, values)

    def save_settings(self) -> bool:
        try:
            base, model, key = self._config_values()
            room_url = self.room_url_var.get().strip() or self.room_url
            values = {
                "OPENAI_API_BASE": base,
                "OPENAI_MODEL": model,
                "OPENAI_API_KEY": key,
                "SOURCE_LANGUAGE": SOURCE_LANGUAGES[self.source_language.get()],
                "TARGET_LANGUAGE": TARGET_LANGUAGES[self.target_language.get()],
                "LIVE_ROOM_URL": room_url,
                "LIVE_PLATFORM": PLATFORM_IDS[self._platform_key()],
                "CHAT_MODE": self.chat_mode_var.get(),
                "AUDIO_INPUT": self.audio_input_var.get(),
            }
            self._room_urls[self._platform_key()] = room_url
            self._write_env(values)
        except (ValueError, OSError) as error:
            self._dialog('showerror', "无法保存", str(error), parent=self.root)
            return False

        self.api_config.update(values)
        self.room_url = room_url
        self.key_var.set("")
        self.key_status.configure(text="密钥已保存在这台电脑。", fg=self.colors['OK'])
        self.settings_result.configure(text="设置已保存。", fg=self.colors['OK'])
        self._set_preferences()
        if self.service_label and self.service_label.winfo_exists():
            self.service_label.configure(text=self._api_summary())
        return True

    def clear_saved_key(self) -> None:
        if not self.api_config.get("OPENAI_API_KEY"):
            self.key_status.configure(text="API Key 可选；无 Key 的服务可以留空。", fg=self.colors['MUTED'])
            return
        if not self._dialog('askyesno', 
            "清除 API Key",
            "清除这台电脑上已保存的 API Key？",
            parent=self.root,
        ):
            return
        try:
            self._write_env({"OPENAI_API_KEY": ""})
        except OSError as error:
            self._dialog('showerror', "无法清除", str(error), parent=self.root)
            return
        self.api_config["OPENAI_API_KEY"] = ""
        self.key_var.set("")
        self.key_status.configure(text="已清除保存的密钥。", fg=self.colors['WARN'])
        self.settings_result.configure(text="已清除 API Key。", fg=self.colors['SECONDARY'])

    def detect_models(self) -> None:
        base = self.base_var.get().strip()
        key = self.key_var.get().strip() or self.api_config.get("OPENAI_API_KEY", "")
        self.detect_models_button.configure(state="disabled", text="正在检测…")
        self.settings_result.configure(text="正在读取模型列表…", fg=self.colors['SECONDARY'])

        def detect() -> None:
            try:
                models, error = list_models(base, key), None
            except ValueError as failure:
                models, error = [], str(failure)
            except Exception:
                log.exception("Model detection failed")
                models, error = [], "读取模型列表失败。"
            self.ui_queue.put(lambda: self._show_detected_models(models, error))

        threading.Thread(target=detect, daemon=True).start()

    def _show_detected_models(self, models: list[str], error: Optional[str]) -> None:
        if not self.model_combo or not self.model_combo.winfo_exists():
            return
        if self.detect_models_button and self.detect_models_button.winfo_exists():
            self.detect_models_button.configure(state="normal", text="检测模型")
        if error:
            self.settings_result.configure(
                text=f"检测失败：{error}", fg=self.colors['ERROR']
            )
            return
        self.model_combo.configure(values=models)
        if self.model_var.get().strip() not in models:
            self.model_var.set(models[0])
        self.settings_result.configure(
            text=f"检测完成，可从「模型 ID」列表选择。模型数量：{len(models)}",
            fg=self.colors['OK'],
        )

    def test_connection(self) -> None:
        if not self.save_settings():
            return
        base = self.api_config["OPENAI_API_BASE"]
        model = self.api_config["OPENAI_MODEL"]
        key = self.api_config.get("OPENAI_API_KEY", "")
        self.test_button.configure(state="disabled", text="正在测试…")
        self.settings_result.configure(text="正在连接翻译服务…", fg=self.colors['SECONDARY'])
        source = Lang.EN if self.source_language.get() == "英语" else Lang.JA
        target = Target(TARGET_LANGUAGES[self.target_language.get()])

        def test() -> None:
            result = StreamingProjectTranslator(
                source,
                target,
                api_key=key,
                base_url=base,
                model=model,
            ).translate("こんにちは")
            self.ui_queue.put(lambda: self._show_test_result(result.error))

        threading.Thread(target=test, daemon=True).start()

    def _show_test_result(self, error: Optional[str]) -> None:
        if not self.settings_result or not self.settings_result.winfo_exists():
            return
        if self.test_button and self.test_button.winfo_exists():
            self.test_button.configure(state="normal", text="测试连接")
        if error:
            self.settings_result.configure(
                text=f"连接失败：{error}",
                fg=self.colors['ERROR'],
            )
        else:
            self.settings_result.configure(
                text="连接成功，翻译服务可以正常使用。",
                fg=self.colors['OK'],
            )

    def close(self) -> None:
        session = self.app.session
        if session and session.running:
            self.app.stop_session()
        self.root.destroy()


def main() -> None:
    LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    try:
        app = desktop_app_integration()
    except Exception as error:
        log.exception("Could not initialize the application")
        messagebox.showerror(
            "同传字幕无法启动",
            f"应用初始化失败：{error}",
        )
        return
    root = tk.Tk()
    TranslationApp(root, app)
    root.mainloop()


if __name__ == "__main__":
    main()
