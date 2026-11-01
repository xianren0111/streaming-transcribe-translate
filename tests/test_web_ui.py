import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from streaming_transcribe_translate import app_controller, secret_store, web_server
from streaming_transcribe_translate.app_controller import AppController, UserError
from streaming_transcribe_translate.ui_translations import TRANSLATIONS
from streaming_transcribe_translate.web_server import WEB_DIR, WebApp

SECRET = "sk-test-SECRET-1234567890"


class WebPortTests(unittest.TestCase):
    def test_default_and_valid_ports(self):
        for value, expected in (
            (None, 8765), ("", 8765), (" ", 8765), ("0", 0),
            ("9000", 9000), (" 9001 ", 9001), ("1", 1), ("65535", 65535),
        ):
            with self.subTest(value=value), mock.patch.object(
                web_server, "dotenv_values", return_value={"WEB_PORT": value},
            ):
                self.assertEqual(web_server.configured_port(), expected)

    def test_invalid_ports_are_rejected(self):
        for value in ("-1", "65536", "port", "1.5", "+9000", "９０００"):
            with self.subTest(value=value), mock.patch.object(
                web_server, "dotenv_values", return_value={"WEB_PORT": value},
            ):
                with self.assertRaisesRegex(ValueError, "WEB_PORT"):
                    web_server.configured_port()

    def test_main_uses_configured_port(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.object(web_server, "_running_instance_url", return_value=None),
            mock.patch.object(web_server, "LOGS_ROOT", Path(temporary)),
            mock.patch.object(web_server, "LOG_FILE", Path(temporary) / "app.log"),
            mock.patch.object(web_server, "URL_FILE", Path(temporary) / "url.txt"),
            mock.patch.object(web_server.logging, "basicConfig"),
            mock.patch.object(web_server.logging, "FileHandler"),
            mock.patch.object(web_server, "_say"),
            mock.patch.object(web_server.webbrowser, "open"),
            mock.patch.object(web_server, "_wait_for_quit"),
            mock.patch.object(web_server, "configured_port", return_value=9000),
            mock.patch.object(web_server, "AppController"),
            mock.patch.object(web_server, "WebApp") as web,
        ):
            web.return_value.url = "http://127.0.0.1:9000/?t=test"
            web_server.main()
            self.assertEqual(web.call_args.kwargs["port"], 9000)
            web.return_value.start.assert_called_once()
            web.return_value.stop.assert_called_once()

    def test_selected_free_port_serves_http(self):
        web = WebApp(None, port=0)
        web.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", web.port, timeout=5)
            try:
                connection.request("GET", "/?t=" + web.token)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
            finally:
                connection.close()
        finally:
            web.stop()

    def test_occupied_port_falls_back_with_warning(self):
        first = WebApp(None, port=0)
        first.start()
        second = None
        try:
            with self.assertLogs(web_server.log, level="WARNING"):
                second = WebApp(None, port=first.port)
            second.start()
            self.assertNotEqual(second.port, first.port)
        finally:
            if second is not None:
                second.stop()
            first.stop()


class FakeHost:
    records = None

    def __getattr__(self, name):
        if name.startswith("set_"):
            return lambda *args, **kwargs: None
        raise AttributeError(name)


class FakeBackend:
    def __init__(self):
        self.host = FakeHost()
        self.prefs = SimpleNamespace(target_lang=SimpleNamespace(value="zh-CN"), whisper_model="base")
        self.preferences = []
        self.chat_sender = None

    def set_preferences(self, values):
        self.preferences.append(values)


class FakeSender:
    def __init__(self, result=(True, "ok")):
        self.sent = []
        self.result = result
        self.gate = threading.Event()
        self.gate.set()

    def send(self, message):
        self.gate.wait(5)
        self.sent.append(message)
        return self.result


class WebTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = root / ".env"
        self.env.write_text(
            f'OPENAI_API_BASE="https://example.test/v1"\nOPENAI_MODEL="m1"\nOPENAI_API_KEY="{SECRET}"\n',
            encoding="utf-8",
        )
        self.controller = AppController(
            FakeBackend(),
            env_file=self.env,
            settings_file=root / "subtitle_settings.json",
            interface_file=root / "interface_preferences.json",
            records_root=root / "records",
        )
        self.web = WebApp(self.controller, port=0)
        self.web.start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.web.stop)

    def request(self, method, path, body=None, token=True, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.web.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.web.port}"}
        if token:
            headers["X-Token"] = self.web.token
        data = None
        if body is not None:
            data = json.dumps(body)
            headers["Content-Type"] = "application/json"
        connection.request(method, path, data, headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        try:
            return response.status, json.loads(raw)
        except ValueError:
            return response.status, raw

    def queue(self, *messages, sender=None):
        sender = sender or FakeSender()
        for message in messages:
            self.controller._enqueue_chat_review(message, sender, f"orig {message}")
        return sender


class TokenTests(WebTestCase):
    def test_requires_token(self):
        self.assertEqual(self.request("GET", "/api/snapshot", token=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/home", {}, token=False)[0], 403)
        self.assertEqual(self.request("GET", "/api/snapshot", token=True)[0], 200)

    def test_token_in_query_works(self):
        status, _ = self.request("GET", f"/api/snapshot?t={self.web.token}", token=False)
        self.assertEqual(status, 200)
        self.assertEqual(self.request("GET", "/api/snapshot?t=wrong", token=False)[0], 403)

    def test_bad_host_rejected(self):
        self.assertEqual(self.request("GET", "/api/snapshot", host="evil.example:80")[0], 403)

    def test_static_pages_served(self):
        status, body = self.request("GET", f"/?t={self.web.token}", token=False)
        self.assertEqual(status, 200)
        self.assertIn(self.web.token.encode(), body)
        self.assertEqual(self.request("GET", f"/overlay?t={self.web.token}", token=False)[0], 200)
        self.assertEqual(self.request("GET", "/", token=False)[0], 403)


class ReviewLayoutTests(WebTestCase):
    def test_obs_link_is_only_on_home_and_redundant_tab_is_removed(self):
        status, raw = self.request("GET", "/?t=" + self.web.token)
        self.assertEqual(status, 200)
        html = raw.decode("utf-8")
        for removed in ('data-tab="页面"', 'data-panel="页面"', 'id="overlay-url-2"', 'id="copy-overlay-2"'):
            self.assertNotIn(removed, html)
        for retained in ('id="overlay-url"', 'id="copy-overlay"', 'id="open-overlay"'):
            self.assertIn(retained, html)
        status, raw = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertNotIn("overlay-url-2", raw.decode("utf-8"))
        self.assertNotIn("copy-overlay-2", raw.decode("utf-8"))

    def test_review_keeps_editor_and_queue_without_live_preview(self):
        status, raw = self.request("GET", "/?t=" + self.web.token)
        self.assertEqual(status, 200)
        html = raw.decode("utf-8")
        for removed in ("live-original", "asr-timing", "history"):
            self.assertNotIn(f'id="{removed}"', html)
        for retained in ("draft-original", "draft-text", "send-button", "skip-button", "queue-list"):
            self.assertIn(f'id="{retained}"', html)
        status, raw = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        js = raw.decode("utf-8")
        self.assertNotIn("renderTranscription", js)
        self.assertNotIn("renderCaptions", js)


class SnapshotTests(WebTestCase):
    def test_snapshot_never_contains_key(self):
        status, data = self.request("GET", "/api/snapshot")
        self.assertEqual(status, 200)
        self.assertTrue(data["api"]["key_saved"])
        self.assertNotIn(SECRET, json.dumps(data))
        self.assertNotIn(SECRET, json.dumps(self.controller.snapshot()))
        self.assertNotIn("OPENAI_API_KEY", json.dumps(data))

    def test_room_url_detects_platform(self):
        _, data = self.request("POST", "/api/home", {"room_url": "https://www.youtube.com/watch?v=abcdefghijk"})
        self.assertEqual(data["state"]["room"]["platform"], "youtube")
        _, data = self.request("POST", "/api/home", {"room_url": "https://live.bilibili.com/123"})
        self.assertEqual(data["state"]["room"]["platform"], "bilibili")

    def test_invalid_choice_is_friendly_error(self):
        status, data = self.request("POST", "/api/home", {"chat_mode": "bogus"})
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])
        self.assertTrue(data["error"]["message"])

    def test_i18n_endpoint(self):
        status, data = self.request("GET", "/api/i18n")
        self.assertEqual(status, 200)
        self.assertIn("检测模型", json.dumps(data, ensure_ascii=False))


class QueueTests(WebTestCase):
    def test_send_removes_head_and_uses_edited_text(self):
        sender = self.queue("a", "b")
        self.controller.set_draft("edited")
        self.assertEqual(self.controller.snapshot()["draft"], "edited")
        self.controller.send_pending_chat()
        self.controller._send_thread.join(5)
        self.assertEqual(sender.sent, ["edited"])
        state = self.controller.snapshot()
        self.assertEqual([item["message"] for item in state["pending"]], ["b"])
        self.assertEqual(state["draft"], "b")

    def test_skip_drops_head(self):
        self.queue("a", "b")
        self.controller.skip_pending_chat()
        self.assertEqual([i["message"] for i in self.controller.snapshot()["pending"]], ["b"])

    def test_failed_send_keeps_item(self):
        sender = FakeSender((False, "nope"))
        self.queue("a", sender=sender)
        self.controller.send_pending_chat()
        self.controller._send_thread.join(5)
        state = self.controller.snapshot()
        self.assertEqual(len(state["pending"]), 1)
        self.assertFalse(state["chat_status"]["success"])
        self.assertFalse(state["sending"])

    def test_blank_message_not_sent(self):
        sender = self.queue("a")
        self.controller.send_pending_chat("   ")
        self.assertEqual(sender.sent, [])
        self.assertEqual(len(self.controller.snapshot()["pending"]), 1)

    def test_without_login_cannot_send(self):
        self.controller._enqueue_chat_review("a", None, "o")
        state = self.controller.send_pending_chat()
        self.assertFalse(state["pending"][0]["can_send"])
        self.assertFalse(state["chat_status"]["success"])

    def test_retention_protects_in_flight_send(self):
        self.controller.subtitle_settings.retained_sentences = 2
        sender = FakeSender()
        sender.gate.clear()
        self.queue("a", "b", sender=sender)
        self.controller.send_pending_chat()
        self.controller._enqueue_chat_review("c", sender, "o")
        messages = [i["message"] for i in self.controller.snapshot()["pending"]]
        self.assertEqual(messages, ["a", "c"])
        sender.gate.set()
        self.controller._send_thread.join(5)
        self.assertEqual([i["message"] for i in self.controller.snapshot()["pending"]], ["c"])

    def test_queue_through_api(self):
        self.queue("a", "b")
        _, data = self.request("POST", "/api/draft", {"text": "changed"})
        self.assertTrue(data["ok"])
        _, data = self.request("POST", "/api/chat/skip", {})
        self.assertEqual(len(data["state"]["pending"]), 1)


class EventTests(WebTestCase):
    def test_sse_delivers_state(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.web.port, timeout=10)
        connection.request("GET", f"/api/events?t={self.web.token}", headers={"Host": f"127.0.0.1:{self.web.port}"})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn("text/event-stream", response.getheader("Content-Type"))
        first = response.fp.readline().decode()
        self.assertTrue(first.startswith("data:"))
        self.assertEqual(json.loads(first[5:])["type"], "state")
        self.queue("live")
        seen = False
        for _ in range(20):
            line = response.fp.readline().decode()
            if line.startswith("data:") and "live" in line:
                seen = True
                break
        connection.close()
        self.assertTrue(seen)

    def test_sse_requires_token(self):
        self.assertEqual(self.request("GET", "/api/events", token=False)[0], 403)


class SettingsTests(WebTestCase):
    def test_export_uses_session_clock_without_user_timestamp(self):
        from streaming_transcribe_translate.subtitle_records import SessionRecords

        store = SessionRecords(self.controller.records_root, started_at_ms=10000)
        caption = store.caption(1, 12000, 14000, 2000, "a", "b")
        store.success(caption, "edited", 16000)
        self.controller._record_stores[store.session_id] = store
        status, result = self.request("POST", "/api/records/export", {"session": store.session_id})
        self.assertEqual(status, 200)
        self.assertIn("00:00:02,000 --> 00:00:04,000", Path(result["srt"]).read_text(encoding="utf-8"))
        status, raw = self.request("GET", "/?t=" + self.web.token)
        self.assertEqual(status, 200)
        self.assertNotIn('id="opt-recording-start"', raw.decode("utf-8"))
        self.assertNotIn('id="recording-now"', raw.decode("utf-8"))

    def test_display_mode_partial_save_broadcasts_shared_value(self):
        events = []
        unsubscribe = self.controller.subscribe(events.append)
        self.addCleanup(unsubscribe)
        previous = self.controller.subtitle_settings.previous_sentences
        for mode in ("说完再出", "边听边出"):
            status, data = self.request("POST", "/api/settings/subtitle", {"display_mode": mode})
            self.assertEqual(status, 200)
            self.assertEqual(data["state"]["subtitle_settings"]["display_mode"], mode)
            self.assertEqual(events[-1]["state"]["subtitle_settings"]["display_mode"], mode)
            self.assertEqual(self.controller.subtitle_settings.previous_sentences, previous)
            stored = json.loads(self.controller.settings_file.read_text(encoding="utf-8"))
            self.assertEqual(stored["display_mode"], mode)

    def test_detect_models(self):
        with mock.patch.object(app_controller, "list_models", return_value=["x", "y"]) as patched:
            status, data = self.request("POST", "/api/models/detect", {"base": "https://example.test/v1"})
        self.assertEqual((status, data["models"]), (200, ["x", "y"]))
        self.assertEqual(patched.call_args.args[1], SECRET)

    def test_detect_models_failure_is_friendly(self):
        with mock.patch.object(app_controller, "list_models", side_effect=ValueError("bad address")):
            status, data = self.request("POST", "/api/models/detect", {"base": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["message"], "bad address")

    def test_save_api_keeps_key_when_blank(self):
        status, data = self.request(
            "POST", "/api/settings/api", {"base": "https://other.test/v1/", "model": "m2", "key": ""}
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["state"]["api"]["model"], "m2")
        self.assertEqual(data["state"]["api"]["base"], "https://other.test/v1")
        stored = self.env.read_text(encoding="utf-8")
        if secret_store.available():
            self.assertNotIn(SECRET, stored)
            secrets, failed = secret_store.read_env_secrets(self.env)
            self.assertEqual((secrets["OPENAI_API_KEY"], failed), (SECRET, []))
        else:
            self.assertIn(SECRET, stored)
        self.assertNotIn(SECRET, json.dumps(data))

    def test_save_api_validation(self):
        status, data = self.request("POST", "/api/settings/api", {"base": "not a url", "model": "m"})
        self.assertEqual(status, 400)
        status, data = self.request("POST", "/api/settings/api", {"base": "https://a.test", "model": "bad model"})
        self.assertEqual(status, 400)

    def test_clear_key(self):
        _, data = self.request("POST", "/api/settings/clear-key", {})
        self.assertFalse(data["state"]["api"]["key_saved"])
        self.assertNotIn(SECRET, self.env.read_text(encoding="utf-8"))

    def test_save_subtitle_settings_and_validation(self):
        status, data = self.request("POST", "/api/settings/subtitle", {"font_size": 40, "retained_sentences": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["state"]["subtitle_settings"]["font_size"], 40)
        status, data = self.request("POST", "/api/settings/subtitle", {"retained_sentences": 0})
        self.assertEqual(status, 400)
        status, data = self.request("POST", "/api/settings/subtitle", {"no_such_option": 1})
        self.assertEqual(status, 400)
        status, data = self.request("POST", "/api/settings/subtitle", {"recording_start": "garbage"})
        self.assertEqual(status, 400)

    def test_interface_preferences(self):
        _, data = self.request("POST", "/api/interface", {"theme": "dark", "language": "ja"})
        self.assertEqual(data["state"]["interface"]["theme"], "dark")
        self.assertEqual(data["state"]["interface"]["resolved_language"], "ja")

    def test_start_requires_login_or_settings(self):
        with self.assertRaises(UserError):
            self.controller.start_session({"room_url": "not a link"}, False)


class LoginTests(WebTestCase):
    def test_youtube_login_requires_confirmation(self):
        channels = [
            {"name": "One", "handle": "@one", "selected": False, "page_id": "p1"},
            {"name": "Two", "handle": "", "selected": False, "page_id": "p2"},
        ]
        bridge = app_controller.bridge
        with mock.patch.object(bridge, "parse_cookie_text", return_value={"SID": "1"}), \
                mock.patch.object(bridge, "verify_login", return_value="Me"), \
                mock.patch.object(bridge, "list_youtube_channels", return_value=channels):
            status, data = self.request("POST", "/api/login/cookies", {"platform": "youtube", "text": "SID=1"})
            self.assertEqual(status, 200)
            self.assertEqual(data["stage"], "choose")
            self.assertIsNone(data["preselect"])
            self.assertEqual(self.controller.snapshot()["login"]["youtube"], "")
            status, _ = self.request(
                "POST", "/api/login/youtube/confirm", {"import_id": data["import_id"], "index": None}
            )
            self.assertEqual(status, 400)
            status, done = self.request(
                "POST", "/api/login/youtube/confirm", {"import_id": data["import_id"], "index": 1}
            )
            self.assertEqual(status, 200)
            self.assertEqual(done["name"], "Two")
            self.assertEqual(self.controller.snapshot()["login"]["youtube"], "Two")

    def test_cancel_keeps_previous_login(self):
        channels = [{"name": "Solo", "handle": "", "selected": False, "page_id": "p"}]
        bridge = app_controller.bridge
        with mock.patch.object(bridge, "parse_cookie_text", return_value={"SID": "1"}), \
                mock.patch.object(bridge, "verify_login", return_value="Me"), \
                mock.patch.object(bridge, "list_youtube_channels", return_value=channels):
            data = self.controller.login_with_cookies("youtube", "SID=1")
        self.assertEqual(data["preselect"], 0)
        self.controller.cancel_youtube_import()
        with self.assertRaises(UserError):
            self.controller.confirm_youtube_account(data["import_id"], 0)
        self.assertEqual(self.controller.snapshot()["login"]["youtube"], "")


class TranslationCoverageTests(unittest.TestCase):
    CJK = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")

    def uncovered(self, text):
        for key in sorted(TRANSLATIONS, key=len, reverse=True):
            if key in text:
                text = text.replace(key, "\0")
        return self.CJK.findall(text)

    def strings(self):
        found = {}
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        for match in re.finditer(r'data-i18n[a-z-]*="([^"]+)"', html):
            found.setdefault(match.group(1).replace("\\n", "\n"), "index.html")
        for name in ("app.js", "i18n.js"):
            js = (WEB_DIR / name).read_text(encoding="utf-8")
            for match in re.finditer(r'"((?:[^"\\\n]|\\.)*)"', js):
                text = match.group(1)
                if self.CJK.search(text) and text not in found:
                    found[text.replace("\\n", "\n")] = name
        return found

    def test_all_visible_strings_translated(self):
        missing = {text: name for text, name in self.strings().items() if self.uncovered(text)}
        self.assertEqual(missing, {})

    def test_every_translation_has_all_languages(self):
        for text, values in TRANSLATIONS.items():
            for language in ("en", "ja", "ko"):
                self.assertTrue(values.get(language), (text, language))


if __name__ == "__main__":
    unittest.main()
