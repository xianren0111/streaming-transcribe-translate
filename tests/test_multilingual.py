import csv
import queue
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from streaming_transcribe_translate.app_controller import AppController
from streaming_transcribe_translate.caption_session import FRAME_SIZE, Pipeline
from streaming_transcribe_translate.desktop_app_example import DesktopSessionHost, DesktopSessionPrefs
from streaming_transcribe_translate.overlay_window import overlay_lines
from streaming_transcribe_translate.simul_interfaces import MtResult, Target
from streaming_transcribe_translate.subtitle_records import SessionRecords
from streaming_transcribe_translate.subtitle_settings import SubtitleSettings
from tests.test_web_ui import FakeBackend, WebTestCase


class ReadingLanguageTests(WebTestCase):
    def test_default_templates_follow_interface_and_custom_templates_survive(self):
        for language, template in (
            ("zh", "【{translation}】"), ("en", "[{translation}]"),
            ("ja", "「{translation}」"), ("ko", "[{translation}]"),
        ):
            self.controller.set_interface(language=language)
            self.assertEqual(self.controller.subtitle_settings.chat_template, template)
            self.assertFalse(self.controller.subtitle_settings.chat_template_custom)
        self.controller._enqueue_chat_review("unchanged draft", None)
        self.controller.save_subtitle_settings({"chat_template": "custom {translation}"})
        self.controller.set_interface(language="ja")
        self.assertEqual(self.controller.subtitle_settings.chat_template, "custom {translation}")
        self.assertEqual(self.controller.snapshot()["draft"], "unchanged draft")
        restored = AppController(
            FakeBackend(), env_file=self.env, settings_file=self.controller.settings_file,
            interface_file=self.controller.interface_file, records_root=self.controller.records_root,
        )
        self.assertEqual(restored.subtitle_settings.chat_template, "custom {translation}")
        restored.save_subtitle_settings({"chat_template_custom": False})
        self.assertEqual(restored.subtitle_settings.chat_template, "「{translation}」")

    def test_selection_saves_and_restores_for_next_start(self):
        status, data = self.request("POST", "/api/home", {
            "selected_target_languages": ["英语", "简体中文"],
        })
        self.assertEqual(status, 200)
        data = self.controller.snapshot()
        self.assertEqual(set(data["selected_target_languages"]), {"英语", "简体中文"})
        restored = AppController(
            FakeBackend(), env_file=self.env, settings_file=self.controller.settings_file,
            interface_file=self.controller.interface_file, records_root=self.controller.records_root,
        )
        self.assertEqual(set(restored.snapshot()["selected_target_languages"]), {"英语", "简体中文"})
        restored._set_preferences()
        self.assertEqual(restored.app.preferences[-1]["subtitle_settings"].reading_languages, ["zh-CN", "en"])

    def test_invalid_or_empty_selection_preserves_saved_selection(self):
        before = self.controller.snapshot()["selected_target_languages"]
        for selected in ([], "en", ["missing"], ["英语", "英语"], [None]):
            status, _ = self.request("POST", "/api/home", {"selected_target_languages": selected})
            self.assertEqual(status, 400)
            self.assertEqual(self.controller.snapshot()["selected_target_languages"], before)

    def test_running_selection_change_is_rejected(self):
        self.controller._session_started_at = time.monotonic()
        status, _ = self.request("POST", "/api/home", {"selected_target_languages": ["英语"]})
        self.assertEqual(status, 400)
        status, _ = self.request("POST", "/api/settings/subtitle", {"reading_languages": ["en"]})
        self.assertEqual(status, 400)

    def test_chat_language_and_template_save_with_validation(self):
        self.request("POST", "/api/home", {"selected_target_languages": ["英语", "简体中文"]})
        status, _ = self.request("POST", "/api/settings/subtitle", {
            "chat_language": "en", "chat_template": "【{translation}】",
        })
        self.assertEqual(status, 200)
        self.assertEqual(self.controller.snapshot()["chat_delivery"]["language"], "en")
        for values in ({"chat_language": "ja"}, {"chat_template": "[转译]"}):
            self.assertEqual(self.request("POST", "/api/settings/subtitle", values)[0], 400)


class MultilingualPipelineTests(unittest.TestCase):
    def test_one_asr_multiple_translations_single_review_language_and_context(self):
        with tempfile.TemporaryDirectory() as directory:
            prefs = DesktopSessionPrefs()
            prefs.subtitle_settings = replace(
                prefs.subtitle_settings, reading_languages=["zh-CN", "en"],
                chat_language="en",
                use_context=True, previous_sentences=1,
            )
            host = DesktopSessionHost(prefs)
            store = SessionRecords(Path(directory), started_at_ms=1000)
            host.records = store
            reviews = queue.Queue()
            host.set_ui_callback(lambda task: task())
            host.set_chat_review_callback(lambda *args: reviews.put(args))
            pipeline = Pipeline(host, chat_mode="manual")
            asr = Mock(recognize=Mock(side_effect=["first source", "second source"]))
            pipeline.models = SimpleNamespace(asr=asr)

            class Translator:
                background = ""
                glossary = ""
                history = []
                correction = ""

                def __init__(self, language):
                    self.language = language
                    self.calls = []

                def translate_with_updates(self, text, update):
                    self.calls.append((text, list(self.history)))
                    update(self.language + " draft")
                    return MtResult(self.language + " " + text)

            zh, en = Translator("zh"), Translator("en")
            pipeline.translators = [(Target.ZH_CN, zh), (Target.EN, en)]
            pipeline.setup = SimpleNamespace(mt=zh)
            pipeline.board.max_sentences = 100
            pipeline.start()
            try:
                for segment in (1, 2):
                    pipeline.add_audio_segment(segment, [0.1] * FRAME_SIZE, True, 3000 * segment, 2000 * segment)
                    item = reviews.get(timeout=5)
                    self.assertEqual(item[3].target_language, "en")
                    self.assertEqual(item[0], "【en " + ("first source" if segment == 1 else "second source") + "】")
                    store.skip(item[3], "edited English " + str(segment), 8000)
                self.assertEqual(pipeline.drain(timeout=5), 0)
                self.assertEqual(pipeline.pending_final_jobs, 0)
                self.assertEqual(pipeline.pending_final_audio_ms, 0)
            finally:
                pipeline.stop()
            self.assertEqual(asr.recognize.call_count, 2)
            self.assertEqual(zh.calls[1][1], [("first source", "zh first source")])
            self.assertEqual(en.calls[1][1], [("first source", "en first source")])
            self.assertTrue(reviews.empty())
            self.assertEqual(len(store.reviewed), 2)
            self.assertEqual(len(pipeline.board.captions), 4)
            self.assertEqual({caption.target_language for caption in pipeline.board.captions}, {"zh-CN", "en"})
            restored = SessionRecords.restore(store.directory)
            srt, csv_path = restored.export(Path(directory) / "exports", include_skipped=True)
            self.assertIn("edited English 1", srt.read_text(encoding="utf-8"))
            with csv_path.open(encoding="utf-8-sig", newline="") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 2)
            self.assertEqual([row["target_language"] for row in rows], ["en", "en"])

    def test_queued_drafts_for_different_languages_do_not_replace_each_other(self):
        jobs = queue.Queue()
        for target in (Target.EN, Target.ZH_CN):
            Pipeline._replace_pending_draft(jobs, {"seg_id": 1, "target": target, "is_final": False})
        self.assertEqual(jobs.qsize(), 2)
        Pipeline._enqueue_final(jobs, {"seg_id": 1, "target": Target.EN, "is_final": True})
        self.assertEqual(jobs.qsize(), 2)
        self.assertEqual(jobs.get()["target"], Target.EN)
        self.assertEqual(jobs.get()["target"], Target.ZH_CN)

    def test_overlay_keeps_all_languages_at_retention_one(self):
        settings = SubtitleSettings(reading_languages=["zh-CN", "en"], retained_sentences=1, show_stats=False)
        state = {
            "subtitle_settings": vars(settings),
            "captions": [
                {"segment_id": 1, "original": "speech", "translated": "Chinese", "target_language": "zh-CN"},
                {"segment_id": 1, "original": "speech", "translated": "English", "target_language": "en"},
            ],
        }
        text = "\n".join(line for line, _ in overlay_lines(state))
        self.assertIn("[zh-CN] Chinese", text)
        self.assertIn("[en] English", text)
