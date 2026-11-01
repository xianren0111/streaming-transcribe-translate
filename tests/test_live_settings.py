import queue
from dataclasses import replace
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from streaming_transcribe_translate.caption_session import FRAME_SIZE, Pipeline
from streaming_transcribe_translate.desktop_app_example import DesktopSessionHost, DesktopSessionPrefs
from streaming_transcribe_translate.simul_interfaces import MtResult
from streaming_transcribe_translate.subtitle_records import SessionRecords
from tests.test_web_ui import WebTestCase


class LivePipelineSettingsTests(TestCase):
    def test_active_pipeline_updates_options_and_decisions_without_restart(self):
        host = DesktopSessionHost(DesktopSessionPrefs())
        pipeline = Pipeline(host, chat_mode="manual")
        host.prefs.subtitle_settings = replace(
            host.prefs.subtitle_settings, smart_segmentation=True,
            check_translation=True, display_mode="说完再出", retained_sentences=12,
        )
        pipeline.refresh_settings()
        self.assertTrue(pipeline.options.smart_segmentation)
        self.assertEqual(pipeline.options.display_mode, "说完再出")
        self.assertEqual(pipeline.board.max_sentences, 12)
        self.assertIsNotNone(pipeline.decisions)
        host.prefs.subtitle_settings = replace(
            host.prefs.subtitle_settings, smart_segmentation=False, check_translation=False,
        )
        pipeline.refresh_settings()
        self.assertIsNone(pipeline.decisions)

    def test_running_translator_uses_changed_background_and_glossary(self):
        host = DesktopSessionHost(DesktopSessionPrefs())
        pipeline = Pipeline(host, chat_mode="manual")
        pipeline.models = SimpleNamespace(asr=Mock(recognize=Mock(return_value="hello")))
        translated = queue.Queue()

        class Translator:
            background = ""
            glossary = ""
            history = []
            correction = ""

            def translate(self, text):
                translated.put((self.background, self.glossary))
                return MtResult("translated")

        pipeline.setup = SimpleNamespace(mt=Translator())
        pipeline.start()
        self.addCleanup(pipeline.stop)
        host.prefs.subtitle_settings = replace(
            host.prefs.subtitle_settings,
            presets={"live": {"background": "new background", "glossary": "new glossary"}},
            preset="live",
        )
        pipeline.add_audio_segment(1, [0.1] * FRAME_SIZE, True, 4000, 3000)
        self.assertEqual(translated.get(timeout=2), ("new background", "new glossary"))
        self.assertTrue(pipeline.running)


class LiveSettingsControllerTests(WebTestCase):
    def test_record_switches_change_current_store_immediately(self):
        store = SessionRecords(self.controller.records_root, enabled=False, started_at_ms=1000)
        self.controller.app.host.records = store
        self.controller._record_stores[store.session_id] = store
        status, _ = self.request("POST", "/api/settings/subtitle", {
            "save_records": True, "save_captions": True, "diagnostics": True,
        })
        self.assertEqual(status, 200)
        self.assertTrue(store.enabled)
        self.assertTrue(store.diagnostics)
        self.assertIs(self.controller.app.prefs.subtitle_settings, self.controller.subtitle_settings)
        caption = store.caption(1, 2000, 3000, 1000, "source", "translation")
        store.skip(caption, "edited", 4000)
        self.assertTrue((store.directory / "captions.jsonl").exists())
        self.request("POST", "/api/settings/subtitle", {"save_records": False})
        before = (store.directory / "captions.jsonl").read_bytes()
        store.skip(store.caption(2, 5000, 6000, 1000, "a", "b"), "b", 7000)
        self.assertEqual((store.directory / "captions.jsonl").read_bytes(), before)

    def test_browser_has_no_save_button_or_next_session_labels(self):
        status, raw = self.request("GET", "/?t=" + self.web.token)
        self.assertEqual(status, 200)
        self.assertNotIn('id="save-subtitle"', raw.decode("utf-8"))
        self.assertNotIn("下次生效", raw.decode("utf-8"))
        self.assertNotIn("（下次开始字幕生效）", raw.decode("utf-8"))
        status, raw = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn("saveOption(el)", raw.decode("utf-8"))
        self.assertNotIn('$("#save-subtitle")', raw.decode("utf-8"))
