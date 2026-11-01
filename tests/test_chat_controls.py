import queue
import threading
import time
import tempfile
from pathlib import Path
import tkinter as tk
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

from streaming_transcribe_translate.desktop_app import TranslationApp
from streaming_transcribe_translate.desktop_app_example import (
    DesktopSessionHost,
    DesktopSessionPrefs,
    StreamingLiveTranslationApp,
)
from streaming_transcribe_translate.streaming_bridge import BilibiliQrLogin, LoginError
from streaming_transcribe_translate.interface_preferences import InterfacePreferences


class ChatEditorTests(unittest.TestCase):
    def test_youtube_start_button_runs_session_and_surfaces_startup_failure(self):
        self.ui.room_url_var.set("https://www.youtube.com/watch?v=NCycSRKpZUw")
        self.ui.api_config.update({"OPENAI_API_BASE": "http://127.0.0.1:1/v1", "OPENAI_MODEL": "test"})
        self.ui._cookies["youtube"] = {"SAPISID": "test"}
        callback_errors = []
        self.root.report_callback_exception = lambda *error: callback_errors.append(error)
        with (
            patch.object(self.ui, "_persist_home_preferences"),
            patch.object(self.ui.app.host, "load_models", side_effect=RuntimeError("test model startup failure")) as models,
            patch("streaming_transcribe_translate.desktop_app.messagebox.showerror") as error_dialog,
        ):
            self.ui.start_button.invoke()
            deadline = time.monotonic() + 3
            while not self.ui._reported_error and time.monotonic() < deadline:
                try:
                    self.ui.ui_queue.get(timeout=0.1)()
                except queue.Empty:
                    continue
        self.assertEqual(callback_errors, [])
        models.assert_called_once()
        self.assertIn("test model startup failure", self.ui.status_detail.cget("text"))
        error_dialog.assert_called_once()

    def test_cookie_import_preselects_current_channel_and_waits_for_confirmation(self):
        from tkinter import ttk
        cookies = {"SAPISID": "test"}
        channel = {"name": "Current brand", "handle": "@brand", "page_id": "brand-id", "selected": True}
        self.ui.room_url_var.set("https://youtube.com/live/abc123def45")
        for method in ("text", "firefox"):
            with self.subTest(method=method):
                dialog = tk.Toplevel(self.root)
                label = tk.Label(dialog)
                button = tk.Button(dialog)
                field = tk.Text(dialog)
                field.insert("1.0", "test cookie")
                with (
                    patch("streaming_transcribe_translate.streaming_bridge.verify_login", return_value="Main account"),
                    patch("streaming_transcribe_translate.streaming_bridge.parse_cookie_text", return_value=cookies),
                    patch("streaming_transcribe_translate.streaming_bridge.read_firefox_cookies", return_value=cookies),
                    patch("streaming_transcribe_translate.streaming_bridge.list_youtube_channels", return_value=[channel]) as current,
                ):
                    if method == "text":
                        self.ui._login_from_text("youtube", dialog, label, field)
                    else:
                        self.ui._login_from_firefox("youtube", dialog, label, button)
                    self.ui.ui_queue.get(timeout=3)()
                current.assert_called_once_with(cookies)
                chooser = next(widget for widget in dialog.winfo_children() if isinstance(widget, tk.Toplevel))
                combo = next(widget for widget in chooser.winfo_children() if isinstance(widget, ttk.Combobox))
                self.assertEqual(combo.current(), 0)
                if method == "text":
                    self.assertNotIn("youtube", self.ui._cookies)
                confirm = next(widget for widget in chooser.winfo_children() if isinstance(widget, tk.Button))
                confirm.invoke()
                self.assertEqual(self.ui._youtube_page_id, "brand-id")
                self.assertIn("Current brand", self.ui.login_status.cget("text"))

    def test_discovery_failure_preserves_existing_login_and_reports_error(self):
        dialog = tk.Toplevel(self.root)
        label, button = tk.Label(dialog), tk.Button(dialog)
        self.ui._cookies["youtube"] = {"SAPISID": "old"}
        self.ui._youtube_page_id = "old-brand"
        with (
            patch("streaming_transcribe_translate.streaming_bridge.read_firefox_cookies", return_value={"SAPISID": "new"}),
            patch("streaming_transcribe_translate.streaming_bridge.verify_login", return_value="New"),
            patch("streaming_transcribe_translate.streaming_bridge.list_youtube_channels", side_effect=LoginError("Cannot list accounts")),
        ):
            self.ui._login_from_firefox("youtube", dialog, label, button)
            self.ui.ui_queue.get(timeout=3)()
        self.assertIn("Cannot list accounts", label.cget("text"))
        self.assertEqual(self.ui._cookies["youtube"], {"SAPISID": "old"})
        self.assertEqual(self.ui._youtube_page_id, "old-brand")
        self.assertEqual(button.cget("state"), "normal")

    def test_youtube_picker_discovers_and_applies_selected_channel(self):
        from tkinter import ttk
        self.ui._cookies["youtube"] = {"SAPISID": "test"}
        self.ui.room_url_var.set("https://youtube.com/live/abc123def45")
        channels = [
            {"name": "Main account", "handle": "@main", "page_id": "", "selected": True},
            {"name": "Brand channel", "handle": "@brand", "page_id": "brand-id", "selected": False},
        ]
        parent = tk.Toplevel(self.root)
        self.ui._complete_cookie_import("youtube", {"SAPISID": "new"}, "New", parent, channels)
        dialog = next(widget for widget in parent.winfo_children() if isinstance(widget, tk.Toplevel))
        combo = next(widget for widget in dialog.winfo_children() if isinstance(widget, ttk.Combobox))
        combo.current(1)
        button = next(widget for widget in dialog.winfo_children() if isinstance(widget, tk.Button))
        button.invoke()
        self.assertEqual(self.ui._youtube_page_id, "brand-id")
        self.assertIn("Brand channel", self.ui.login_status.cget("text"))
        self.assertEqual(self.ui._cookies["youtube"], {"SAPISID": "new"})
        self.assertFalse(dialog.winfo_exists())

    def test_new_youtube_login_resets_selected_channel(self):
        self.ui._youtube_page_id = "old-brand"
        dialog = tk.Toplevel(self.root)
        self.ui._activate_login("youtube", {"SAPISID": "new-login"}, "New account", dialog)
        self.assertEqual(self.ui._youtube_page_id, "")
        self.assertEqual(self.ui._login_names["youtube"], "New account")

    def test_youtube_account_selection_updates_pending_and_future_senders(self):
        from streaming_transcribe_translate.simul_streaming_adapter import YouTubeChatSender
        cookies = {"SAPISID": "test"}
        self.ui._cookies["youtube"] = cookies
        self.ui.room_url_var.set("https://youtube.com/live/abc123def45")
        self.assertFalse(hasattr(self.ui, "youtube_account_button"))
        sender = YouTubeChatSender("abc123def45", cookies)
        self.ui.app.chat_sender = sender
        self.ui._enqueue_chat_review("translation", sender, "original")
        cookies = {"SAPISID": "reimported"}
        self.ui._activate_login("youtube", cookies, "Brand channel", tk.Toplevel(self.root), "brand-id")
        self.assertEqual(sender.page_id, "brand-id")
        self.assertEqual(sender.cookies, cookies)
        self.assertIn("Brand channel", self.ui.login_status.cget("text"))
        with (
            patch.object(self.ui, "_api_ready", return_value=True),
            patch.object(self.ui, "_persist_home_preferences"),
            patch.object(self.ui.app, "start_session"),
        ):
            self.ui.start_session()
        self.assertEqual(self.ui.app.chat_sender.page_id, "brand-id")
        self.assertEqual(self.ui.login_button.cget("state"), "disabled")

    def test_reimport_activation_is_blocked_during_send(self):
        self.ui._cookies["youtube"] = {"SAPISID": "test"}
        self.ui.room_url_var.set("https://youtube.com/live/abc123def45")
        self.assertFalse(hasattr(self.ui, "youtube_account_button"))
        self.ui._sending_manual_chat = True
        dialog = tk.Toplevel(self.root)
        with patch("streaming_transcribe_translate.desktop_app.messagebox.showwarning") as info:
            self.ui._activate_login("youtube", {"SAPISID": "new"}, "New", dialog, "new-brand")
        info.assert_called_once()
        self.assertEqual(self.ui._cookies["youtube"], {"SAPISID": "test"})

    def test_cancelled_import_keeps_existing_account(self):
        self.ui._cookies["youtube"] = {"SAPISID": "old"}
        self.ui._youtube_page_id = "old-brand"
        parent = tk.Toplevel(self.root)
        self.ui._complete_cookie_import("youtube", {"SAPISID": "new"}, "New", parent, [
            {"name": "New", "handle": "", "page_id": "new-brand", "selected": True},
        ])
        parent.destroy()
        self.assertEqual(self.ui._cookies["youtube"], {"SAPISID": "old"})
        self.assertEqual(self.ui._youtube_page_id, "old-brand")

    def test_ambiguous_import_requires_explicit_account_choice(self):
        from tkinter import ttk
        parent = tk.Toplevel(self.root)
        self.ui._complete_cookie_import("youtube", {"SAPISID": "new"}, "New", parent, [
            {"name": "Main", "handle": "", "page_id": "", "selected": False},
            {"name": "Brand", "handle": "", "page_id": "brand", "selected": False},
        ])
        dialog = next(widget for widget in parent.winfo_children() if isinstance(widget, tk.Toplevel))
        combo = next(widget for widget in dialog.winfo_children() if isinstance(widget, ttk.Combobox))
        self.assertEqual(combo.current(), -1)
        button = next(widget for widget in dialog.winfo_children() if isinstance(widget, tk.Button))
        button.invoke()
        self.assertNotIn("youtube", self.ui._cookies)
        combo.current(1)
        button.invoke()
        self.assertEqual(self.ui._youtube_page_id, "brand")

    def test_login_controls_identify_selected_site_and_keep_accounts_separate(self):
        self.ui._login_names.update({"bilibili": "Bilibili user", "missevan": "MissEvan user"})
        for url, site, name in (
            ("https://fm.missevan.com/live/869215180", "猫耳FM", "MissEvan user"),
            ("https://live.bilibili.com/25760587", "哔哩哔哩", "Bilibili user"),
            ("https://youtube.com/live/abc123def45", "YouTube", None),
        ):
            with self.subTest(site=site):
                self.ui.room_url_var.set(url)
                self.assertEqual(
                    self.ui.login_status.cget("text"),
                    site + " · " + ("聊天账号：" + name if name else "聊天账号：未登录"),
                )
                self.assertEqual(self.ui.login_button.cget("text"), site + " · 登录 / 导入 Cookie")
        self.ui.tr.language = "en"
        self.ui.login_status.refresh_language()
        self.ui.login_button.refresh_language()
        self.assertEqual(self.ui.login_status.cget("text"), "YouTube · Chat account: not signed in")
        self.assertEqual(self.ui.login_button.cget("text"), "YouTube · Sign in / Import cookies")
        self.ui.show_settings()
        self.ui.show_home()
        self.assertEqual(self.ui.login_button.cget("text"), "YouTube · Sign in / Import cookies")

    def test_detect_models_fills_dropdown_and_keeps_manual_choice(self):
        self.ui.show_settings()
        self.ui.base_var.set("http://localhost:11434/v1")
        self.ui.model_var.set("")
        with patch(
            "streaming_transcribe_translate.desktop_app.list_models",
            return_value=["gemma4:12b", "qwen3:8b"],
        ) as detect:
            self.ui.detect_models()
            callback = self.ui.ui_queue.get(timeout=5)
        detect.assert_called_once_with("http://localhost:11434/v1", self.ui.api_config.get("OPENAI_API_KEY", ""))
        callback()
        self.assertEqual(list(self.ui.model_combo.cget("values")), ["gemma4:12b", "qwen3:8b"])
        self.assertEqual(self.ui.model_var.get(), "gemma4:12b")
        self.assertIn("模型数量：2", self.ui.settings_result.cget("text"))
        self.ui.model_var.set("qwen3:8b")
        self.ui._show_detected_models(["gemma4:12b", "qwen3:8b"], None)
        self.assertEqual(self.ui.model_var.get(), "qwen3:8b")
        self.ui._show_detected_models([], "API Key 无效或没有权限读取模型列表。")
        self.assertIn("检测失败", self.ui.settings_result.cget("text"))
        self.assertEqual(self.ui.model_var.get(), "qwen3:8b")
        self.assertEqual(str(self.ui.detect_models_button.cget("state")), "normal")

    def test_missevan_link_selects_missevan_and_never_opens_bilibili_qr(self):
        self.ui.room_url_var.set("https://fm.missevan.com/live/869215180")
        self.assertEqual(self.ui._platform_key(), "missevan")
        self.ui.open_login_dialog()
        dialogs = [widget for widget in self.root.winfo_children() if isinstance(widget, tk.Toplevel)]
        self.assertTrue(dialogs)
        self.assertIn("猫耳FM", dialogs[-1].title())
        widgets = []
        def collect(widget):
            widgets.append(widget)
            for child in widget.winfo_children():
                collect(child)
        collect(dialogs[-1])
        self.assertFalse(any(
            isinstance(widget, tk.Button) and "哔哩哔哩" in widget.cget("text")
            for widget in widgets
        ))

    def test_unknown_room_host_is_rejected_before_login(self):
        self.ui.room_url_var.set("https://example.com/live/869215180")
        self.ui.chat_mode_var.set("自动发送")
        with (
            patch.object(self.ui, "_api_ready", return_value=True),
            patch.object(self.ui, "open_login_dialog") as login,
            patch("streaming_transcribe_translate.desktop_app.messagebox.showerror") as error,
        ):
            self.ui.start_session()
        login.assert_not_called()
        error.assert_called_once()

    def test_missevan_manual_start_without_login_uses_missevan_audio(self):
        self.ui.room_url_var.set("https://fm.missevan.com/live/869215180")
        self.ui._cookies["bilibili"] = {"SESSDATA": "bilibili-only", "bili_jct": "csrf"}
        with (
            patch.object(self.ui, "_api_ready", return_value=True),
            patch.object(self.ui, "_persist_home_preferences"),
            patch.object(self.ui.app, "start_session") as start,
            patch.object(self.ui, "open_login_dialog") as login,
        ):
            self.ui.start_session()
        start.assert_called_once()
        login.assert_not_called()
        self.assertEqual(self.ui.app.host.open_audio().platform, "missevan")
        self.assertIsNone(self.ui.app.chat_sender)
        self.assertEqual(self.ui.app.host.records.platform, "missevan")

    def test_missevan_auto_send_requires_missevan_login_even_with_bilibili_cookies(self):
        self.ui.room_url_var.set("https://fm.missevan.com/live/869215180")
        self.ui.chat_mode_var.set("自动发送")
        self.ui._cookies["bilibili"] = {"SESSDATA": "bilibili-only", "bili_jct": "csrf"}
        with (
            patch.object(self.ui, "_api_ready", return_value=True),
            patch.object(self.ui, "open_login_dialog") as login,
            patch("streaming_transcribe_translate.desktop_app.messagebox.showinfo"),
            patch.object(self.ui.app, "start_session") as start,
        ):
            self.ui.start_session()
        login.assert_called_once()
        start.assert_not_called()
        self.assertEqual(self.ui._platform_key(), "missevan")

    def test_switching_platform_preserves_separate_room_urls(self):
        self.ui.room_url_var.set("https://fm.missevan.com/live/869215180")
        self.ui.platform_var.set("YouTube")
        self.ui._on_platform_changed()
        self.ui.room_url_var.set("https://youtube.com/live/abc123def45")
        self.ui.platform_var.set("MissEvan")
        self.ui._on_platform_changed()
        self.assertEqual(self.ui.room_url_var.get(), "https://fm.missevan.com/live/869215180")

    def test_missevan_room_preferences_save_to_single_room_key(self):
        self.ui.room_url_var.set("https://fm.missevan.com/live/869215180")
        with patch.object(self.ui, "_write_env") as write:
            self.ui._persist_home_preferences(self.ui.room_url_var.get())
        values = write.call_args.args[0]
        self.assertEqual(values["LIVE_ROOM_URL"], self.ui.room_url_var.get())
        self.assertNotIn("MISSEVAN_ROOM_URL", values)
        self.assertEqual(values["LIVE_PLATFORM"], "MissEvan")
        self.assertNotIn("YOUTUBE_ROOM_URL", values)
        self.assertNotIn("BILIBILI_ROOM_URL", values)

    def test_home_layout_adapts_without_recreating_editor(self):
        editor = self.ui.pending_chat_text
        self.ui._enqueue_chat_review("current message", None, "original")
        self.edit("my edit")
        self.root.deiconify()
        self.root.geometry("1080x820")
        self.root.update()
        self.assertEqual(self.ui.review_card.grid_info()["column"], 1)
        self.assertEqual(self.ui.review_card.grid_info()["row"], 0)
        self.assertGreater(self.ui.review_card.winfo_width(), self.ui.connection_card.winfo_width())
        self.root.geometry("540x700")
        self.root.update()
        self.assertEqual(self.ui.review_card.grid_info()["column"], 0)
        self.assertEqual(self.ui.review_card.grid_info()["row"], 1)
        self.assertLessEqual(
            self.ui.review_card.winfo_x() + self.ui.review_card.winfo_width(),
            self.ui.home_columns.winfo_width(),
        )
        self.assertIs(self.ui.pending_chat_text, editor)
        self.assertEqual(self.text(), "my edit")

    def test_rounded_cards_redraw_and_settings_keep_working(self):
        self.root.update_idletasks()
        self.assertTrue(self.ui.review_card._surface.find_withtag("surface"))
        self.ui.show_settings()
        self.root.update_idletasks()
        self.assertIn("retained_sentences", self.ui._option_vars)
        self.ui.show_home()
        self.root.update_idletasks()
        self.assertTrue(self.ui.connection_card._surface.find_withtag("surface"))

    def test_home_has_one_settings_button_auto_language_and_two_state_toggle(self):
        self.assertEqual(self.ui.source_language.get(), "自动识别")
        self.assertIsInstance(self.ui.chat_mode_selector, tk.Checkbutton)
        self.assertEqual(self.ui.chat_mode_var.get(), "手动确认")
        self.assertEqual(self.ui.chat_mode_selector.cget("text"), "手动发送")
        self.ui.chat_mode_selector.invoke()
        self.assertEqual(self.ui.chat_mode_var.get(), "自动发送")
        self.assertEqual(self.ui.chat_mode_selector.cget("text"), "自动发送")
        self.ui.chat_mode_selector.invoke()
        self.assertEqual(self.ui.chat_mode_var.get(), "手动确认")
        self.assertEqual(self.ui.chat_mode_selector.cget("text"), "手动发送")
        widgets = []

        def collect(widget):
            widgets.append(widget)
            for child in widget.winfo_children():
                collect(child)

        collect(self.root)
        settings = [
            widget for widget in widgets
            if isinstance(widget, tk.Button) and widget.cget("text").startswith("设置")
        ]
        self.assertEqual(len(settings), 1)
        self.assertIs(self.ui.caption_text, self.ui.review_queue_text)

    def test_sending_mode_label_survives_rebuild_and_language_switch(self):
        self.ui.chat_mode_var.set("自动发送")
        self.assertEqual(self.ui.chat_mode_selector.cget("text"), "自动发送")
        self.ui.show_settings()
        self.ui.show_home()
        self.assertEqual(self.ui.chat_mode_selector.cget("text"), "自动发送")
        self.ui.tr.language = "en"
        self.ui.chat_mode_selector.refresh_language()
        self.assertEqual(self.ui.chat_mode_selector.cget("text"), "Auto-send")
        self.ui.chat_mode_var.set("手动确认")
        self.assertEqual(self.ui.chat_mode_selector.cget("text"), "Manual-send")
        self.ui.tr.language = "ja"
        self.ui.chat_mode_selector.refresh_language()
        self.assertEqual(self.ui.chat_mode_selector.cget("text"), "手動送信")
        self.ui.tr.language = "ko"
        self.ui.chat_mode_var.set("自动发送")
        self.assertEqual(self.ui.chat_mode_selector.cget("text"), "자동 전송")

    def test_local_review_has_edit_and_skip_but_no_send(self):
        self.ui._enqueue_chat_review("local translation", None, "original")
        self.assertEqual(self.ui.pending_chat_text.cget("state"), "normal")
        self.assertEqual(self.ui.send_chat_button.cget("state"), "disabled")
        self.assertEqual(self.ui.skip_chat_button.cget("state"), "normal")
        self.edit("edited locally")
        self.ui._send_pending_chat()
        self.assertEqual(self.text(), "edited locally")
        self.ui._skip_pending_chat()
        self.assertEqual(self.ui._pending_chat, [])

    def test_pending_limit_defaults_to_fifty_and_expires_oldest_item(self):
        self.assertEqual(self.ui.subtitle_settings.retained_sentences, 50)
        for index in range(51):
            self.ui._enqueue_chat_review(f"translation-{index}", None, f"original-{index}")
        self.assertEqual(len(self.ui._pending_chat), 50)
        self.assertEqual(self.text(), "translation-1")
        self.assertEqual(self.ui._pending_chat[-1][0], "translation-50")
        self.assertIn("移除", self.ui.chat_status.cget("text"))

    def test_live_area_lists_entire_review_queue_after_history(self):
        self.ui._last_captions = [
            {"segment_id": f"old-{index}", "original": f"old-o-{index}", "translated": f"old-t-{index}"}
            for index in range(60)
        ]
        for index in range(5):
            self.ui._enqueue_chat_review(f"queued-{index}", None, f"source-{index}")
        content = self.ui.caption_text.get("1.0", "end")
        self.assertIn("待发送队列 · 4", content)
        self.assertNotIn("source-0", content)
        for index in range(1, 5):
            self.assertIn(f"queued-{index}", content)
            self.assertIn(f"source-{index}", content)
        self.assertLess(content.index("old-t-59"), content.index("待发送队列"))
        self.assertNotIn("old-t-9\n", content)

    def test_retention_protects_in_flight_send_identity(self):
        self.ui.subtitle_settings.retained_sentences = 2
        self.ui._enqueue_chat_review("first", self.sender)
        self.ui._enqueue_chat_review("second", self.sender)
        self.ui._sending_manual_chat = True
        self.ui._enqueue_chat_review("third", self.sender)
        self.assertEqual([entry[0] for entry in self.ui._pending_chat], ["first", "third"])
        self.ui._finish_manual_send("first", (True, "sent"))
        self.assertEqual(self.text(), "third")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings_patch = patch(
            "streaming_transcribe_translate.desktop_app.SUBTITLE_SETTINGS_FILE",
            Path(temporary.name) / "settings.json",
        )
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        self.language_patch = patch(
            "streaming_transcribe_translate.desktop_app.InterfacePreferences.load",
            return_value=InterfacePreferences(language="zh"),
        )
        self.language_patch.start()
        self.addCleanup(self.language_patch.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        app = StreamingLiveTranslationApp.__new__(StreamingLiveTranslationApp)
        app.prefs = DesktopSessionPrefs()
        app.host = DesktopSessionHost(app.prefs)
        app.session = None
        app.chat_sender = None
        app.chat_mode = "off"
        with patch.object(TranslationApp, "_read_api_config", return_value={}):
            self.ui = TranslationApp(self.root, app)
        self.sender = Mock()
        self.sender.send.return_value = (True, "")

    def tearDown(self):
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.root.destroy()

    def edit(self, text):
        self.ui.pending_chat_text.delete("1.0", "end")
        self.ui.pending_chat_text.insert("1.0", text)

    def text(self):
        return self.ui.pending_chat_text.get("1.0", "end-1c")

    def finish_send(self):
        deadline = time.monotonic() + 2
        while self.ui._sending_manual_chat and time.monotonic() < deadline:
            try:
                self.ui.ui_queue.get(timeout=0.1)()
            except queue.Empty:
                continue
        self.assertFalse(self.ui._sending_manual_chat)

    def test_new_caption_does_not_overwrite_edits_and_skip_advances(self):
        self.ui._enqueue_chat_review("first", self.sender)
        self.edit("edited first")
        self.ui._enqueue_chat_review("second", self.sender)
        self.assertEqual(self.text(), "edited first")
        self.ui._skip_pending_chat()
        self.assertEqual(self.text(), "second")
        self.sender.send.assert_not_called()
        self.ui._skip_pending_chat()
        self.assertEqual(self.text(), "")
        self.assertEqual(self.ui.send_chat_button.cget("state"), "disabled")

    def test_queue_and_original_reference_follow_send_and_skip(self):
        self.ui._enqueue_chat_review("first", self.sender, "original first")
        self.edit("edited first")
        self.ui._enqueue_chat_review("second", self.sender, "original second")
        self.ui._enqueue_chat_review("third", self.sender, "original third")
        preview = self.ui.review_queue_text.get("1.0", "end-1c")
        self.assertIn("original second", preview)
        self.assertIn("second", preview)
        self.assertIn("original third", preview)
        self.assertNotIn("original first", preview)
        self.assertEqual(self.ui.original_chat_text.get("1.0", "end-1c"), "original first")
        self.assertEqual(self.ui.review_queue_text.cget("state"), "disabled")
        self.assertEqual(self.text(), "edited first")
        self.ui._send_pending_chat()
        self.finish_send()
        self.assertEqual(self.ui.original_chat_text.get("1.0", "end-1c"), "original second")
        self.ui._skip_pending_chat()
        self.assertEqual(self.text(), "third")
        self.assertEqual(self.ui.original_chat_text.get("1.0", "end-1c"), "original third")

    def test_live_original_is_displayed_without_a_translation(self):
        self.ui.subtitle_settings.display_mode = "边听边出"
        self.ui.app.host.show_transcription(1, "recognized immediately", False, 120)
        self.assertIn("recognized immediately", self.ui.transcription_label.cget("text"))
        self.assertIn("120 ms", self.ui.asr_timing_label.cget("text"))
        self.assertEqual(self.ui._last_captions, [])

    def test_microphone_without_chat_needs_no_room_or_login(self):
        self.ui.audio_input_var.set("\u9ea6\u514b\u98ce")
        self.ui.chat_mode_var.set("\u624b\u52a8\u786e\u8ba4")
        self.ui.room_url_var.set("")
        app = self.ui.app
        with (
            patch.object(self.ui, "_api_ready", return_value=True),
            patch.object(self.ui, "_persist_home_preferences"),
            patch.object(app, "start_session") as start,
            patch.object(app, "configure_microphone") as configure,
            patch("streaming_transcribe_translate.desktop_app.messagebox.showinfo") as info,
        ):
            self.ui.start_session()
        start.assert_called_once()
        configure.assert_called_once_with(None)
        info.assert_not_called()
        self.assertIsNone(app.chat_sender)
        self.assertEqual(app.chat_mode, "manual")

    def test_microphone_can_keep_authenticated_chat_destination(self):
        self.ui.audio_input_var.set("\u9ea6\u514b\u98ce")
        self.ui.chat_mode_var.set("\u624b\u52a8\u786e\u8ba4")
        self.ui.room_url_var.set("25760587")
        self.ui._cookies["bilibili"] = {"SESSDATA": "test", "bili_jct": "csrf"}
        with (
            patch.object(self.ui, "_api_ready", return_value=True),
            patch.object(self.ui, "_persist_home_preferences"),
            patch.object(self.ui.app, "start_session") as start,
        ):
            self.ui.start_session()
        self.assertIsNotNone(self.ui.app.chat_sender)
        self.assertEqual(self.ui.app.chat_mode, "manual")
        with patch("streaming_transcribe_translate.desktop_app_example.MicrophoneAudioSource") as microphone:
            self.ui.app.host.open_audio()
        microphone.assert_called_once_with(None)
        start.assert_called_once()

    def test_send_uses_edited_text_and_advances(self):
        self.ui._enqueue_chat_review("first", self.sender)
        self.ui._enqueue_chat_review("second", self.sender)
        self.edit("corrected translation")
        self.ui._send_pending_chat()
        self.finish_send()
        self.sender.send.assert_called_once_with("corrected translation")
        self.assertEqual(self.text(), "second")

    def test_failure_keeps_edit_for_retry(self):
        self.sender.send.return_value = (False, "send failed")
        self.ui._enqueue_chat_review("first", self.sender)
        self.ui._enqueue_chat_review("second", self.sender)
        self.edit("corrected")
        self.ui._send_pending_chat()
        self.finish_send()
        self.assertEqual(self.text(), "corrected")
        self.assertEqual(len(self.ui._pending_chat), 2)
        self.assertEqual(self.ui.chat_status.cget("text"), "send failed")
        self.assertEqual(self.ui.pending_chat_text.cget("state"), "normal")

    def test_empty_text_requires_send_or_skip_decision(self):
        self.ui._enqueue_chat_review("first", self.sender)
        self.edit("  ")
        self.ui._send_pending_chat()
        self.sender.send.assert_not_called()
        self.assertEqual(len(self.ui._pending_chat), 1)
        self.assertTrue(self.ui.chat_status.cget("text"))

    def test_edits_survive_settings_navigation(self):
        self.ui._enqueue_chat_review("first", self.sender)
        self.edit("draft")
        self.ui.show_settings()
        self.ui._enqueue_chat_review("second", self.sender)
        self.ui.show_home()
        self.assertEqual(self.text(), "draft")

    def test_send_locks_editor_and_skip_until_complete(self):
        release = threading.Event()

        def send(message):
            if not release.wait(2):
                return False, "timeout"
            return True, ""

        self.sender.send.side_effect = send
        self.ui._enqueue_chat_review("first", self.sender)
        self.ui._enqueue_chat_review("second", self.sender)
        try:
            self.ui._send_pending_chat()
            self.assertEqual(self.ui.pending_chat_text.cget("state"), "disabled")
            self.ui._skip_pending_chat()
            self.assertEqual(len(self.ui._pending_chat), 2)
        finally:
            release.set()
            self.finish_send()
        self.assertEqual(self.text(), "second")

    def test_qr_login_activates_verified_cookies(self):
        import qrcode

        output = BytesIO()
        qrcode.make("https://example.invalid/test").save(output, format="PNG")
        qr = Mock()
        qr.generate.return_value = output.getvalue()
        cookies = {"SESSDATA": "test", "bili_jct": "csrf"}
        qr.poll.return_value = ("done", cookies)
        parent = tk.Toplevel(self.root)
        with (
            patch("streaming_transcribe_translate.streaming_bridge.BilibiliQrLogin", return_value=qr),
            patch("streaming_transcribe_translate.streaming_bridge.verify_login", return_value="Test account"),
        ):
            self.ui.open_qr_login(parent)
            deadline = time.monotonic() + 2
            while "bilibili" not in self.ui._cookies and time.monotonic() < deadline:
                try:
                    self.ui.ui_queue.get(timeout=0.1)()
                except queue.Empty:
                    continue
        self.assertEqual(self.ui._cookies["bilibili"], cookies)
        self.assertFalse(parent.winfo_exists())
        qr.close.assert_called_once()

    def test_closing_qr_window_does_not_activate_late_login_result(self):
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        qr = Mock()
        qr.generate.return_value = b"unused after cancellation"

        def poll():
            entered.set()
            release.wait(2)
            return "done", {"SESSDATA": "test", "bili_jct": "csrf"}

        qr.poll.side_effect = poll
        qr.close.side_effect = closed.set
        parent = tk.Toplevel(self.root)
        with (
            patch("streaming_transcribe_translate.streaming_bridge.BilibiliQrLogin", return_value=qr),
            patch("streaming_transcribe_translate.streaming_bridge.verify_login", return_value="Test account") as verify,
        ):
            self.ui.open_qr_login(parent)
            try:
                self.assertTrue(entered.wait(2))
                parent.destroy()
            finally:
                release.set()
                self.assertTrue(closed.wait(2))
            while not self.ui.ui_queue.empty():
                self.ui.ui_queue.get_nowait()()
            verify.assert_not_called()
        self.assertNotIn("bilibili", self.ui._cookies)


class QrLoginTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.session.cookies.get_dict.return_value = {}
        with patch("streaming_transcribe_translate.streaming_bridge.requests.Session", return_value=self.session):
            self.qr = BilibiliQrLogin()

    def tearDown(self):
        self.qr.close()
        self.session.close.assert_called_once()

    def respond(self, data):
        self.session.get.return_value.json.return_value = {"code": 0, "data": data}

    def test_generates_png_in_memory(self):
        self.respond({
            "qrcode_key": "test-token",
            "url": "https://example.invalid/test-qr",
        })
        self.assertTrue(self.qr.generate().startswith(b"\x89PNG"))
        self.assertEqual(self.qr.key, "test-token")

    def test_poll_states_and_cookie_result(self):
        self.qr.key = "test-token"
        for code, state in ((86101, "scan"), (86090, "confirm"), (86038, "expired")):
            self.respond({"code": code})
            self.assertEqual(self.qr.poll(), (state, {}))
        self.respond({
            "code": 0,
            "url": "https://example.invalid/?SESSDATA=test%2Cvalue&bili_jct=csrf&DedeUserID=123",
        })
        state, cookies = self.qr.poll()
        self.assertEqual(state, "done")
        self.assertEqual(cookies, {
            "SESSDATA": "test%2Cvalue", "bili_jct": "csrf", "DedeUserID": "123"
        })

    def test_rejects_missing_credentials_unknown_status_and_network_error(self):
        self.qr.key = "test-token"
        for data in ({"code": 0}, {"code": 12345}):
            self.respond(data)
            with self.assertRaises(LoginError):
                self.qr.poll()
        import requests

        self.session.get.side_effect = requests.Timeout("private-token")
        with self.assertRaises(LoginError) as error:
            self.qr.poll()
        self.assertNotIn("private-token", str(error.exception))


if __name__ == "__main__":
    unittest.main()
