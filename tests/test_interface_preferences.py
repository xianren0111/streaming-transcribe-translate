import json
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from streaming_transcribe_translate.desktop_app import TranslationApp, DARK_COLORS, LIGHT_COLORS
from streaming_transcribe_translate.desktop_app_example import (
    DesktopSessionHost, DesktopSessionPrefs, StreamingLiveTranslationApp,
)
from streaming_transcribe_translate.interface_preferences import InterfacePreferences, LANGUAGES, system_language
from streaming_transcribe_translate.ui_localization import LocalizedCombobox, Translator
from streaming_transcribe_translate.ui_translations import TRANSLATIONS


class InterfacePreferenceTests(unittest.TestCase):
    def test_system_language_is_default_and_saved_selection_overrides_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interface.json"
            for system in LANGUAGES:
                with patch("streaming_transcribe_translate.interface_preferences.system_language", return_value=system):
                    self.assertEqual(InterfacePreferences.load(path).resolved_language, system)
            InterfacePreferences(theme="dark", language="ja").save(path)
            with patch("streaming_transcribe_translate.interface_preferences.system_language", return_value="ko"):
                restored = InterfacePreferences.load(path)
            self.assertEqual(restored.theme, "dark")
            self.assertEqual(restored.resolved_language, "ja")
            self.assertEqual(set(json.loads(path.read_text())), {"theme", "language"})

    def test_os_locale_detection_accepts_all_four_and_defaults_to_english(self):
        with patch("streaming_transcribe_translate.interface_preferences.sys.platform", "linux"):
            for locale_name, expected in (
                ("ja_JP", "ja"), ("zh_TW", "zh"), ("en_US", "en"),
                ("ko_KR", "ko"), ("fr_FR", "en"), (None, "en"),
            ):
                with patch("locale.getlocale", return_value=(locale_name, None)):
                    self.assertEqual(system_language(), expected)

    def test_invalid_preferences_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interface.json"
            for data in (
                {"theme": "blue"}, {"language": "de"}, {"unexpected": True}, [],
            ):
                path.write_text(json.dumps(data))
                with self.assertRaises((ValueError, TypeError)):
                    InterfacePreferences.load(path)

    def test_catalog_covers_each_target_language_and_fragments_do_not_retranslate(self):
        for source, translations in TRANSLATIONS.items():
            self.assertEqual(set(translations), {"en", "ja", "ko"}, source)
            for text in translations.values():
                self.assertTrue(text)
        translator = Translator("ja")
        self.assertEqual(translator("实时原文："), "リアルタイム原文：")
        translator.language = "en"
        self.assertEqual(translator("实时字幕 / 待处理 · 12 条待处理"), "Live subtitles / Review · 12 pending")


class InterfaceWidgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "interface.json"
        self.root = tk.Tk()
        self.root.withdraw()
        app = StreamingLiveTranslationApp.__new__(StreamingLiveTranslationApp)
        app.prefs = DesktopSessionPrefs()
        app.host = DesktopSessionHost(app.prefs)
        app.session = None
        app.chat_sender = None
        app.chat_mode = "manual"
        self.preferences_patch = patch(
            "streaming_transcribe_translate.desktop_app.INTERFACE_PREFERENCES_FILE", self.path
        )
        self.preferences_patch.start()
        self.addCleanup(self.preferences_patch.stop)
        with (
            patch.object(TranslationApp, "_read_api_config", return_value={}),
            patch("streaming_transcribe_translate.interface_preferences.system_language", return_value="zh"),
            patch("streaming_transcribe_translate.desktop_app.SUBTITLE_SETTINGS_FILE", Path(self.directory.name) / "subtitles.json"),
        ):
            self.ui = TranslationApp(self.root, app)

    def tearDown(self):
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.root.destroy()

    def test_theme_switch_changes_palette_without_rebuilding_or_losing_edit(self):
        self.ui._enqueue_chat_review("original translation", None, "source")
        editor = self.ui.pending_chat_text
        editor.delete("1.0", "end")
        editor.insert("1.0", "edited text")
        self.ui._change_interface(theme="dark")
        self.assertEqual(self.root.cget("background"), DARK_COLORS["BG"])
        self.assertEqual(editor.cget("background"), DARK_COLORS["PILL"])
        self.assertEqual(self.ui.review_card._fill, DARK_COLORS["CARD"])
        self.assertEqual(self.ui.review_card._surface.cget("background"), DARK_COLORS["BG"])
        self.assertIs(editor, self.ui.pending_chat_text)
        self.assertEqual(editor.get("1.0", "end-1c"), "edited text")
        self.ui._change_interface(theme="light")
        self.assertEqual(editor.cget("background"), LIGHT_COLORS["PILL"])
        self.assertEqual(InterfacePreferences.load(self.path).theme, "light")

    def test_language_switch_translates_ui_not_speech_or_internal_option_values(self):
        self.ui._show_transcription(1, "设置：这是原始发言", False, 120)
        self.ui._enqueue_chat_review("设置：这是发送内容", None, "这是原文")
        for language, word in (("en", "Send to chat"), ("ja", "チャットに送信"), ("ko", "채팅으로 전송"), ("zh", "发送到直播间")):
            self.ui._change_interface(language=language)
            self.assertEqual(self.ui.send_chat_button.cget("text"), word)
            self.assertEqual(self.ui.source_language.get(), "自动识别")
            self.assertEqual(self.ui.audio_input_var.get(), "直播间声音")
            self.assertIn("设置：这是原始发言", self.ui.transcription_label.cget("text"))
            self.assertEqual(self.ui.pending_chat_text.get("1.0", "end-1c"), "设置：这是发送内容")
            self.assertEqual(self.ui.original_chat_text.get("1.0", "end-1c"), "这是原文")
        self.assertEqual(tuple(self.ui._language_selectors[0].cget("values")), tuple(LANGUAGES.values()))

    def test_localized_dropdown_selection_updates_canonical_value(self):
        self.ui._change_interface(language="en")
        selector = self.ui.audio_input_selector
        self.assertIsInstance(selector, LocalizedCombobox)
        self.assertEqual(tuple(selector.cget("values")), ("Stream audio", "Microphone", "Computer sound"))
        selector.current(1)
        selector.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(self.ui.audio_input_var.get(), "麦克风")
        self.ui._change_interface(language="ja")
        self.assertEqual(selector.get(), "マイク")
        self.assertEqual(self.ui.audio_input_var.get(), "麦克风")

    def test_settings_drafts_and_palette_survive_theme_and_language_switch(self):
        self.ui.show_settings()
        self.ui.base_var.set("https://unsaved.example/v1")
        self.ui.key_var.set("unsaved-test-key")
        self.ui._option_vars["retained_sentences"].set(73)
        self.ui._change_interface(theme="dark", language="ko")
        self.assertEqual(self.ui.base_var.get(), "https://unsaved.example/v1")
        self.assertEqual(self.ui.key_var.get(), "unsaved-test-key")
        self.assertEqual(self.ui._option_vars["retained_sentences"].get(), 73)
        self.assertEqual(self.ui.preset_selector.get(), "스트리머 모드")
        self.assertEqual(self.ui.preset_selector.cget("values"), ("스트리머 모드", "대화 모드"))
        self.assertEqual(self.ui.subtitle_settings.palette, "黑白")
        self.ui.show_home()
        self.assertEqual(self.root.cget("background"), DARK_COLORS["BG"])

    def test_home_settings_login_and_overlay_have_complete_translations(self):
        for language in ("en", "ja", "ko"):
            self.ui._change_interface(language=language)
            self.ui.show_settings()
            self.ui.show_home()
            self.ui.open_login_dialog()
            self.ui.open_overlay()
            self.assertEqual(self.ui.tr._missing, set())
            for widget in self.root.winfo_children():
                if isinstance(widget, tk.Toplevel):
                    widget.destroy()

    def test_failed_preference_save_preserves_current_ui_and_reports_error(self):
        with (
            patch.object(InterfacePreferences, "save", side_effect=OSError("disk full")),
            patch("streaming_transcribe_translate.desktop_app.messagebox.showerror") as error,
        ):
            self.ui._change_interface(theme="dark", language="en")
        error.assert_called_once()
        self.assertEqual(self.ui.interface_preferences.theme, "light")
        self.assertEqual(self.ui.tr.language, "zh")

    def test_overlay_palette_and_user_text_are_independent_of_interface_theme(self):
        self.ui.open_overlay()
        self.ui._show_captions([{
            "segment_id": 1, "original": "设置：原始发言",
            "translated": "设置：翻译内容", "is_final": True,
        }], None)
        background = self.ui.overlay_text.cget("background")
        self.ui._change_interface(theme="dark", language="en")
        self.assertEqual(self.ui.overlay_text.cget("background"), background)
        text = self.ui.overlay_text.get("1.0", "end-1c")
        self.assertIn("设置：原始发言", text)
        self.assertIn("设置：翻译内容", text)

    def test_narrow_toolbar_keeps_both_controls_visible(self):
        self.ui._change_interface(language="en")
        self.root.deiconify()
        self.root.geometry("540x700")
        self.root.update()
        for widget in self.ui._theme_buttons + self.ui._language_selectors:
            self.assertGreater(widget.winfo_width(), 10)
            self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), widget.master.winfo_width())

    def test_settings_use_bounded_content_and_theme_aware_numeric_controls(self):
        self.ui._change_interface(theme="dark")
        self.ui.show_settings()
        self.root.deiconify()
        self.root.geometry("1080x820")
        self.root.update()
        content = self.ui.settings_contents["字幕"]
        self.assertLessEqual(content.winfo_width(), 760)
        widgets = []
        def collect(widget):
            widgets.append(widget)
            for child in widget.winfo_children():
                collect(child)
        collect(content)
        self.assertFalse(any(type(widget) is tk.Scale for widget in widgets))
        scales = [widget for widget in widgets if isinstance(widget, ttk.Scale)]
        entries = [widget for widget in widgets if isinstance(widget, ttk.Spinbox)]
        self.assertEqual(len(scales), 5)
        self.assertEqual(len(entries), 5)
        scales[0].set(22.7)
        self.assertEqual(self.ui._option_vars["font_size"].get(), 23)
        self.ui._option_vars["font_size"].set(18)
        self.assertEqual(scales[0].get(), 18)
        self.ui._option_vars["opacity"].set(0.73)
        self.assertEqual(scales[1].get(), 0.73)
        style = ttk.Style(self.root)
        self.assertEqual(style.lookup("TSpinbox", "foreground"), DARK_COLORS["TEXT"])
        self.root.geometry("540x700")
        self.root.update()
        self.assertLess(content.winfo_width(), 540)
        self.assertEqual(self.ui._option_vars["font_size"].get(), 18)
