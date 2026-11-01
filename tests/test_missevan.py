from contextlib import contextmanager, nullcontext
import unittest
from unittest.mock import Mock, patch

from streaming_transcribe_translate import streaming_bridge
from streaming_transcribe_translate.desktop_app_example import (
    DesktopSessionHost, DesktopSessionPrefs, StreamingLiveTranslationApp,
)
from streaming_transcribe_translate.platforms import detect_platform, missevan_room_id
from streaming_transcribe_translate.simul_streaming_adapter import MissevanChatSender, StreamAudioSource


class PlatformRoutingTests(unittest.TestCase):
    def test_domain_detection_and_numeric_ids(self):
        for url, expected in (
            ("https://fm.missevan.com/live/869215180", "missevan"),
            ("fm.missevan.com/live/869215180", "missevan"),
            ("https://www.missevan.com/live/869215180?source=test", "missevan"),
            ("https://live.bilibili.com/25760587", "bilibili"),
            ("https://youtu.be/abc123def45", "youtube"),
            ("https://www.youtube.com/live/abc123def45", "youtube"),
            ("869215180", None), ("", None),
        ):
            with self.subTest(url=url):
                self.assertEqual(detect_platform(url), expected)
        for url in (
            "https://fm.missevan.com.evil.test/live/869215180",
            "https://missevan.com@evil.test/live/869215180",
            "https://user:pass@fm.missevan.com/live/869215180",
            "file://fm.missevan.com/live/869215180",
        ):
            with self.assertRaises(ValueError):
                detect_platform(url)

    def test_missevan_room_parser_accepts_only_live_urls_and_ids(self):
        for url in ("869215180", "fm.missevan.com/live/869215180", "https://fm.missevan.com/live/869215180/?a=1"):
            self.assertEqual(missevan_room_id(url), "869215180")
        for url in ("https://fm.missevan.com/sound/123", "https://live.bilibili.com/123", "abc123def45"):
            with self.assertRaises(ValueError):
                missevan_room_id(url)


class MissevanBridgeTests(unittest.TestCase):
    def setUp(self):
        self.browser = Mock()
        self.login = Mock()
        self.login.using.side_effect = lambda values: nullcontext()
        self.bilibili = Mock()
        self.youtube = Mock()
        self.missevan = Mock()
        modules = patch.object(streaming_bridge, "_modules", return_value=(
            self.browser, self.login, self.bilibili, self.youtube,
        ))
        modules.start()
        self.addCleanup(modules.stop)
        missevan = patch.object(streaming_bridge, "_missevan_module", return_value=self.missevan)
        missevan.start()
        self.addCleanup(missevan.stop)

    def test_cookie_imports_target_missevan_domain_not_bilibili(self):
        self.browser.read_cookies.return_value = {"token": "missevan-only"}
        self.browser.parse_cookie_text.return_value = {"token": "missevan-only"}
        streaming_bridge.read_firefox_cookies("missevan")
        self.browser.read_cookies.assert_called_once_with("firefox", "missevan.com")
        streaming_bridge.parse_cookie_text("token=test", "missevan")
        self.browser.parse_cookie_text.assert_called_once_with("token=test", "missevan.com")

    def test_login_is_verified_by_missevan_with_username(self):
        cookies = {"token": "missevan-only"}
        self.missevan.verify_login.return_value = {"is_login": True, "username": "Missevan user"}
        self.assertEqual(streaming_bridge.verify_login("missevan", cookies), "Missevan user")
        self.missevan.verify_login.assert_called_once_with(cookies)
        self.browser.verify_bilibili_login.assert_not_called()
        self.youtube.verify_login.assert_not_called()

    def test_failed_login_and_unknown_platform_are_not_accepted(self):
        self.missevan.verify_login.return_value = {"is_login": False}
        with self.assertRaises(streaming_bridge.LoginError):
            streaming_bridge.verify_login("missevan", {"token": "invalid"})
        for call in (
            lambda: streaming_bridge.verify_login("unknown", {}),
            lambda: streaming_bridge.read_firefox_cookies("unknown"),
            lambda: streaming_bridge.parse_cookie_text("token=test", "unknown"),
        ):
            with self.assertRaises(streaming_bridge.LoginError):
                call()

    def test_send_has_isolated_cookie_context_and_does_not_expose_response_body(self):
        active = {}
        @contextmanager
        def using(values):
            active.update(values)
            try:
                yield
            finally:
                active.clear()
        self.login.using.side_effect = using
        def send(room, message):
            self.assertEqual(active, {"missevan": {"token": "missevan-only"}})
            return True, "server message id"
        self.missevan.send_message.side_effect = send
        self.assertEqual(streaming_bridge.send_missevan_message(
            "869215180", "edited translation", {"token": "missevan-only"},
        ), (True, "发送成功"))
        self.missevan.send_message.assert_called_once_with("869215180", "edited translation")
        self.assertEqual(active, {})
        self.bilibili.send_danmaku.assert_not_called()

    def test_failed_send_reports_platform_specific_error_without_secret_details(self):
        self.missevan.send_message.return_value = (False, "URL with private cookie")
        success, detail = streaming_bridge.send_missevan_message("123", "message", {"token": "test"})
        self.assertFalse(success)
        self.assertIn("MissEvan", detail)
        self.assertNotIn("private cookie", detail)

    def test_audio_resolution_errors_are_explicit_and_do_not_expose_urls(self):
        self.missevan.get_live_audio_url.side_effect = RuntimeError("private signed URL")
        with self.assertRaisesRegex(RuntimeError, "MissEvan") as raised:
            streaming_bridge.resolve_missevan_audio("123")
        self.assertNotIn("private signed URL", str(raised.exception))

    def test_missing_cookies_never_send(self):
        self.assertFalse(streaming_bridge.send_missevan_message("123", "message", {})[0])
        self.missevan.send_message.assert_not_called()


class MissevanAdapterTests(unittest.TestCase):
    def test_stream_configuration_keeps_audio_and_chat_on_missevan(self):
        app = StreamingLiveTranslationApp.__new__(StreamingLiveTranslationApp)
        app.host = DesktopSessionHost(DesktopSessionPrefs())
        app.configure_missevan_stream("https://fm.missevan.com/live/869215180", {"token": "test"}, "manual")
        self.assertEqual(app.chat_mode, "manual")
        self.assertIsInstance(app.chat_sender, MissevanChatSender)
        self.assertTrue(app.chat_sender.can_send())
        source = app.host.open_audio()
        self.assertEqual(source.platform, "missevan")
        self.assertEqual(source.stream_url, "https://fm.missevan.com/live/869215180")
        app.configure_missevan_stream("869215180", chat_mode="manual")
        self.assertIsNone(app.chat_sender)
        self.assertEqual(app.chat_mode, "manual")

    def test_audio_uses_signed_missevan_source_not_youtube_downloader(self):
        source = StreamAudioSource("https://fm.missevan.com/live/869215180", "missevan")
        with (
            patch("streaming_transcribe_translate.streaming_bridge.resolve_missevan_audio", return_value="https://audio.example/live.m3u8") as resolve,
            patch("subprocess.Popen") as process,
            patch("yt_dlp.YoutubeDL") as downloader,
        ):
            source._start_process()
            source._start_process()
        self.assertEqual(resolve.call_count, 2)
        resolve.assert_called_with("869215180")
        cmd = process.call_args.args[0]
        self.assertEqual(cmd[cmd.index("-i") + 1], "https://audio.example/live.m3u8")
        downloader.assert_not_called()

    def test_sender_requires_cookies_and_reports_status(self):
        callback = Mock()
        self.assertFalse(MissevanChatSender("123").can_send())
        sender = MissevanChatSender("123", {"token": "test"}, status_callback=callback)
        with patch("streaming_transcribe_translate.streaming_bridge.send_missevan_message", return_value=(True, "")) as send:
            self.assertEqual(sender.send("message"), (True, ""))
        send.assert_called_once_with("123", "message", {"token": "test"})
        callback.assert_called_once_with(True, "")
