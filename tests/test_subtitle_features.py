import csv
import json
import queue
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from streaming_transcribe_translate.caption_session import FRAME_SIZE, Pipeline, Segmenter, remove_repeated_text
from streaming_transcribe_translate.desktop_app import TranslationApp
from streaming_transcribe_translate.desktop_app_example import DesktopSessionHost, DesktopSessionPrefs, StreamingLiveTranslationApp
from streaming_transcribe_translate.simul_interfaces import Caption, Lang, MtResult, Target, Timing
from streaming_transcribe_translate.simul_streaming_adapter import StreamingProjectTranslator
from streaming_transcribe_translate.subtitle_decisions import DecisionsClient
from streaming_transcribe_translate.subtitle_records import SessionRecords, recording_clock
from streaming_transcribe_translate.subtitle_settings import SubtitleSettings
from streaming_transcribe_translate.interface_preferences import InterfacePreferences


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = SessionRecords(
            self.root, platform="bilibili", room="12", audio_source="microphone"
        )

    def test_actual_sent_text_and_receipt_clock_survive_restart_and_export(self):
        start = recording_clock("2026-10-31T23:00:00+08:00")
        caption = self.store.caption(1, start + 1234, start + 3000, 1766, "original", "translation")
        self.store.success(caption, "edited message", start + 20000)
        restored = SessionRecords.restore(self.store.directory)
        srt, csv_path = restored.export(self.root / "export", start)
        self.assertIn("00:00:01,234 --> 00:00:03,000", srt.read_text(encoding="utf-8"))
        self.assertIn("edited message", srt.read_text(encoding="utf-8"))
        self.assertNotIn("translation", srt.read_text(encoding="utf-8"))
        with csv_path.open(encoding="utf-8-sig", newline="") as source:
            row = next(csv.DictReader(source))
        self.assertEqual(row["audio_received_epoch_ms"], str(start + 1234))
        self.assertEqual(row["recording_offset_ms"], "1234")
        self.assertEqual(row["actual_sent_message"], "edited message")
        self.assertEqual(row["original"], "original")
        self.assertEqual(row["translated"], "translation")
        self.assertNotEqual(row["audio_received_clock"], row["sent_clock"])

    def test_automatic_session_clock_survives_restart_and_late_export(self):
        start = recording_clock("2026-11-01T12:34:55.985+08:00")
        with patch("streaming_transcribe_translate.subtitle_records.time.time", return_value=start / 1000):
            store = SessionRecords(self.root)
        self.assertEqual(store.started_at_ms, start)
        caption = store.caption(1, start + 1500, start + 3500, 2000, "source", "translation")
        store.success(caption, "edited", start + 9000)
        restored = SessionRecords.restore(store.directory)
        self.assertEqual(restored.started_at_ms, start)
        srt, csv_path = restored.export(self.root / "automatic")
        self.assertIn("00:00:01,500 --> 00:00:03,500", srt.read_text(encoding="utf-8"))
        with csv_path.open(encoding="utf-8-sig", newline="") as source:
            self.assertEqual(next(csv.DictReader(source))["recording_offset_ms"], "1500")

    def test_legacy_session_uses_creation_time_not_export_time(self):
        start = recording_clock("2026-11-01 12:00:00")
        store = SessionRecords(self.root, started_at_ms=start)
        store.session_id = "20261101-120000-legacy"
        store.directory = self.root / store.session_id
        caption = store.caption(1, start + 1000, start + 2000, 1000, "a", "b")
        store.success(caption, "b", start + 3000)
        (store.directory / "session.json").unlink()
        restored = SessionRecords.restore(store.directory)
        self.assertEqual(restored.started_at_ms, start)
        srt, _ = restored.export(self.root / "legacy")
        self.assertIn("00:00:01,000", srt.read_text(encoding="utf-8"))

    def test_corrupt_session_clock_is_reported(self):
        store = SessionRecords(self.root)
        caption = store.caption(1, 1000, 2000, 1000, "a", "b")
        store.success(caption, "b", 3000)
        (store.directory / "session.json").write_text('{"started_at_ms": false}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "开始时间无效"):
            SessionRecords.restore(store.directory)

    def test_unsent_captions_do_not_enter_success_export(self):
        self.store.caption(1, 10000, 12000, 2000, "original", "translation")
        with self.assertRaisesRegex(ValueError, "没有成功发送"):
            self.store.export(self.root / "export", 0)
        self.assertFalse(self.store.directory.exists())
        self.assertFalse((self.store.directory / "sent_messages.jsonl").exists())

    def test_clock_rollover_negative_offsets_and_overlaps(self):
        start = recording_clock("2026-11-01T00:00:00+08:00")
        for index, (begin, end, text) in enumerate([
            (-1000, 500, "cross midnight"), (200, 3000, "second"), (1000, 4000, "third")
        ]):
            caption = self.store.caption(index, start + begin, start + end, end - begin, text, text)
            self.store.success(caption, text, start + 10000)
        srt, _ = self.store.export(self.root / "export", start)
        content = srt.read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:00,200", content)
        self.assertIn("00:00:00,200 --> 00:00:01,000", content)
        self.assertIn("00:00:01,000 --> 00:00:04,000", content)

    def test_captions_and_diagnostics_are_independent(self):
        store = SessionRecords(self.root, save_captions=False, diagnostics=False)
        caption = store.caption(1, 10000, 12000, 2000, "original", "translated")
        store.event("asr", text="not saved")
        self.assertFalse(store.directory.exists())
        store.success(caption, "sent", 14000)
        self.assertTrue((store.directory / "sent_messages.jsonl").is_file())
        self.assertFalse((store.directory / "captions.txt").exists())
        self.assertFalse((store.directory / "diagnostics.jsonl").exists())

    def test_same_start_cues_and_empty_exports_have_valid_shape(self):
        for index in (1, 2):
            caption = self.store.caption(index, 10000, 12000, 2000, "original", "translated")
            self.store.success(caption, f"message {index}", 15000)
        srt, _ = self.store.export(self.root / "export", 9000)
        content = srt.read_text(encoding="utf-8")
        self.assertEqual(content.count(" --> "), 1)
        self.assertIn("message 1\nmessage 2", content)
        with self.assertRaisesRegex(ValueError, "录像开始之前"):
            self.store.export(self.root / "late", 20000)

    def test_recording_clock_requires_date_and_time(self):
        for invalid in ("2026-10-31", "23:00:00", "2026-02-30 12:00:00"):
            with self.assertRaises(ValueError):
                recording_clock(invalid)
        self.assertEqual(
            recording_clock("2026-10-31 23:00:00.123+08:00"),
            recording_clock("2026-10-31T15:00:00.123Z"),
        )

    def test_disk_error_preserves_acknowledged_message_for_immediate_export(self):
        caption = self.store.caption(1, 10000, 12000, 2000, "original", "translation")
        with patch.object(self.store, "_append", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.success(caption, "already sent", 15000)
        srt, _ = self.store.export(self.root / "export", 9000)
        self.assertIn("already sent", srt.read_text(encoding="utf-8"))

    def test_corrupt_saved_message_is_reported_not_silently_discarded(self):
        self.store.directory.mkdir()
        (self.store.directory / "sent_messages.jsonl").write_text("{broken\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            SessionRecords.restore(self.store.directory)


class SettingsTests(unittest.TestCase):
    def test_modes_default_and_old_saved_selections_migrate_without_text_loss(self):
        self.assertEqual(list(SubtitleSettings().presets), ["主播模式", "对话模式"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for old, expected in (
                ("B站 VTuber 直播", "主播模式"),
                ("YouTube 直播", "主播模式"),
                ("一般对话", "对话模式"),
            ):
                path.write_text(json.dumps({
                    "preset": old,
                    "presets": {old: {"background": "edited background", "glossary": "edited glossary"}},
                }), encoding="utf-8")
                settings = SubtitleSettings.load(path)
                self.assertEqual(settings.preset, expected)
                self.assertEqual(settings.presets[expected]["background"], "edited background")
                self.assertEqual(settings.presets[old]["glossary"], "edited glossary")
                settings.save(path)
                self.assertEqual(SubtitleSettings.load(path), settings)

    def test_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings = SubtitleSettings(
                smart_segmentation=True, check_translation=True,
                diagnostics=True, opacity=0.75, retained_sentences=8,
            )
            settings.presets["My stream"] = {"background": "topic", "glossary": "term: word"}
            settings.preset = "My stream"
            settings.save(path)
            restored = SubtitleSettings.load(path)
            self.assertEqual(restored.preset, "主播模式")
            self.assertEqual(restored.presets["主播模式"], settings.presets["My stream"])
            self.assertEqual(restored.presets["My stream"], settings.presets["My stream"])
            self.assertEqual(restored.opacity, settings.opacity)
            self.assertNotIn("key", json.loads(path.read_text(encoding="utf-8")))
            restored.font_size = 99
            with self.assertRaises(ValueError):
                restored.save(path)

    def test_legacy_decision_provider_is_migrated_to_fixed_opencode_zen(self):
        settings = SubtitleSettings(
            smart_segmentation=True, jev_provider="自定义",
            jev_url="https://user:secret@example.invalid", jev_model="test",
        )
        settings.validate()
        self.assertEqual(settings.jev_provider, "OpenCode Zen（免费，不用 key）")
        self.assertEqual(settings.jev_url, "")
        self.assertEqual(settings.jev_model, "")
        client = DecisionsClient(settings, key="unused-test-key")
        self.assertEqual(client.url, "https://opencode.ai/zen/v1/systemone")
        self.assertEqual(client.model, "jev-1.13-free")
        self.assertEqual(client.key, "")

    def test_malformed_saved_settings_raise_explicit_validation_errors(self):
        for settings in (
            SubtitleSettings(palette=[]), SubtitleSettings(opacity=True),
            SubtitleSettings(recording_start=False),
        ):
            with self.assertRaises(ValueError):
                settings.validate()

    def test_repeat_removal_does_not_remove_other_sentences(self):
        self.assertEqual(remove_repeated_text("good morning good morning everyone"), "good morning everyone")
        self.assertEqual(remove_repeated_text("这是测试。 这是测试。"), "这是测试。")
        self.assertEqual(remove_repeated_text("one two three"), "one two three")

    def test_translator_background_glossary_context_are_real_request_messages(self):
        translator = StreamingProjectTranslator(
            Lang.EN, Target.ZH_CN, base_url="https://example.invalid/v1",
            background="stream topic", glossary="term: translation",
        )
        translator.history = [("prior original", "prior translation")]
        translator._thinking_cache[(translator.base_url, translator.model)] = "thinking"
        response = Mock(status_code=200)
        response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"translated"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]
        with patch("requests.post", return_value=response) as post:
            self.assertEqual(translator.translate("current").text, "translated")
        messages = post.call_args.kwargs["json"]["messages"]
        self.assertIn("stream topic", messages[0]["content"])
        self.assertIn("term: translation", messages[0]["content"])
        self.assertIn("prior original", messages[1]["content"])
        self.assertIn("current", messages[1]["content"])
        self.assertNotIn("prior translation", messages[1]["content"])
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["max_tokens"], 160)
        self.assertTrue(body["stream"])


class DecisionsTests(unittest.TestCase):
    def test_keyless_request_shape_and_typed_answers(self):
        notify = Mock()
        client = DecisionsClient(SubtitleSettings(), "must-not-send-key", notify)
        response = Mock(status_code=200)
        response.json.return_value = {"answers": {"x": {"noul": 0.9}}}
        with patch("requests.post", return_value=response) as post:
            self.assertTrue(client.unfinished("unfinished words"))
        self.assertEqual(post.call_args.kwargs["headers"], {})
        self.assertEqual(post.call_args.kwargs["timeout"], 1)
        self.assertEqual(post.call_args.kwargs["json"]["questions"]["x"]["type"], "noul")
        notify.assert_not_called()

    def test_invalid_decision_is_reported_and_not_used(self):
        notify = Mock()
        client = DecisionsClient(SubtitleSettings(), notify=notify)
        response = Mock(status_code=200)
        response.json.return_value = {"answers": {"x": {"noul": "true"}}}
        with patch("requests.post", return_value=response):
            self.assertIsNone(client.unfinished("source"))
        notify.assert_called_once()

    def test_rate_limit_backoff_does_not_stop_subtitles(self):
        notify = Mock()
        client = DecisionsClient(SubtitleSettings(), notify=notify)
        response = Mock(status_code=429, headers={"Retry-After": "60"})
        with patch("requests.post", return_value=response) as post:
            self.assertIsNone(client.unfinished("source"))
            self.assertIsNone(client.unfinished("source"))
        post.assert_called_once()
        notify.assert_called_once()

    def test_malformed_quality_answer_is_reported_without_worker_failure(self):
        notify = Mock()
        client = DecisionsClient(SubtitleSettings(), notify=notify)
        response = Mock(status_code=200)
        response.json.return_value = {"answers": {"x": {"choice": []}}}
        with patch("requests.post", return_value=response):
            self.assertIsNone(client.translation_problem("source", "translation"))
        notify.assert_called_once()

    def test_a_new_pause_invalidates_an_old_decision(self):
        host = DesktopSessionHost(DesktopSessionPrefs())
        host._prefs.subtitle_settings.smart_segmentation = True
        pipeline = Pipeline(host)
        generation = pipeline.reset_hint(1)
        entered, release = threading.Event(), threading.Event()

        def unfinished(_):
            entered.set()
            release.wait(2)
            return True

        pipeline.decisions = Mock()
        pipeline.decisions.unfinished.side_effect = unfinished
        pipeline.models = SimpleNamespace(asr=Mock(recognize=Mock(return_value="unfinished")))
        pipeline.options.display_mode = "说完再出"
        pipeline.add_audio_segment(1, [0.1] * 512, False, 12000, 10000, True, generation)
        pipeline.running = True
        worker = threading.Thread(target=pipeline._asr_worker)
        pipeline.asr_thread = worker
        worker.start()
        self.assertTrue(entered.wait(2))
        pipeline.reset_hint(1)
        release.set()
        pipeline.stop()
        self.assertIsNone(pipeline.hold_hint(1))

    def test_smart_pause_holds_but_is_bounded(self):
        model = Mock()
        model.vad_prob.side_effect = lambda samples: 1 if samples[0] else 0
        segmenter = Segmenter(model, hold_hint=lambda _: True)
        emitted = []
        for index in range(22):
            emitted += segmenter.process_frame([0.1] * FRAME_SIZE, 10000 + index * 32)
        for index in range(13):
            emitted += segmenter.process_frame([0.0] * FRAME_SIZE, 11000 + index * 32)
        self.assertFalse(any(final for _, _, final in emitted))
        for index in range(34):
            emitted += segmenter.process_frame([0.0] * FRAME_SIZE, 12000 + index * 32)
        self.assertTrue(any(final for _, _, final in emitted))

    def test_received_clock_preserves_first_preroll_frame_not_asr_time(self):
        model = Mock()
        model.vad_prob.side_effect = lambda samples: 1 if samples[0] else 0
        segmenter = Segmenter(model)
        for index in range(5):
            segmenter.process_frame([0.0] * FRAME_SIZE, 10000 + index * 32)
        for index in range(22):
            segmenter.process_frame([0.1] * FRAME_SIZE, 11000 + index * 32)
        for index in range(13):
            segmenter.process_frame([0.0] * FRAME_SIZE, 12000 + index * 32)
        self.assertEqual(segmenter.emitted_times[0][0], 10000)
        self.assertEqual(segmenter.emitted_times[0][1], 12384)


class IntegratedRecordingTests(unittest.TestCase):
    def test_unified_feed_does_not_duplicate_current_or_queued_caption(self):
        self.ui._enqueue_chat_review("translation", None, "source", self.caption)
        next_caption = self.store.caption(2, 20000, 22000, 2000, "next source", "next translation")
        self.ui._enqueue_chat_review("next translation", None, "next source", next_caption)
        self.ui._show_captions([
            {"segment_id": 1, "original": "source", "translated": "translation", "is_final": True},
            {"segment_id": 2, "original": "next source", "translated": "next translation", "is_final": True},
        ], None)
        text = self.ui.caption_text.get("1.0", "end-1c")
        self.assertEqual(text.count("next translation"), 1)
        self.assertNotIn("译文：translation", text)
        self.assertEqual(self.ui.pending_chat_text.get("1.0", "end-1c"), "translation")

    def setUp(self):
        language_patch = patch(
            "streaming_transcribe_translate.desktop_app.InterfacePreferences.load",
            return_value=InterfacePreferences(language="zh"),
        )
        language_patch.start()
        self.addCleanup(language_patch.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        app = StreamingLiveTranslationApp.__new__(StreamingLiveTranslationApp)
        app.prefs = DesktopSessionPrefs()
        app.host = DesktopSessionHost(app.prefs)
        app.session = None
        app.chat_sender = None
        app.chat_mode = "off"
        with (
            patch.object(TranslationApp, "_read_api_config", return_value={}),
            patch("streaming_transcribe_translate.desktop_app.SUBTITLE_SETTINGS_FILE", Path(self.temporary.name) / "settings.json"),
        ):
            self.ui = TranslationApp(self.root, app)
        self.store = SessionRecords(Path(self.temporary.name))
        self.ui._record_stores[self.store.session_id] = self.store
        app.host.records = self.store
        self.caption = self.store.caption(1, 10000, 12000, 2000, "source", "translation")

    def test_successful_manual_send_records_edited_text_only_once(self):
        sender = Mock()
        sender.send.return_value = (True, "")
        self.ui._enqueue_chat_review("translation", sender, "source", self.caption)
        self.ui.pending_chat_text.delete("1.0", "end")
        self.ui.pending_chat_text.insert("1.0", "edited text")
        self.ui._send_pending_chat()
        deadline = time.monotonic() + 3
        while self.ui._sending_manual_chat and time.monotonic() < deadline:
            try:
                self.ui.ui_queue.get(timeout=0.1)()
            except queue.Empty:
                continue
        self.assertFalse(self.ui._sending_manual_chat)
        sender.send.assert_called_once_with("edited text")
        self.assertEqual(self.store.sent[0].message, "edited text")
        self.assertEqual(self.store.sent[0].caption.received_at_ms, 10000)
        self.assertEqual(len(self.store.sent), 1)

    def test_failed_send_and_skip_are_not_recorded(self):
        sender = Mock()
        sender.send.return_value = (False, "failed")
        pipeline = Pipeline(self.ui.app.host, sender, "automatic")
        pipeline._send_chat("message", "source", self.caption)
        self.assertEqual(self.store.sent, [])
        self.ui._enqueue_chat_review("message", sender, "source", self.caption)
        self.ui._skip_pending_chat()
        self.assertEqual(self.store.sent, [])

    def test_automatic_success_records_audio_receipt_not_send_time(self):
        sender = Mock()
        sender.send.return_value = (True, "")
        pipeline = Pipeline(self.ui.app.host, sender, "automatic")
        with patch("streaming_transcribe_translate.caption_session.time.time", return_value=30):
            pipeline._send_chat("actual message", "source", self.caption)
        self.assertEqual(self.store.sent[0].caption.received_at_ms, 10000)
        self.assertEqual(self.store.sent[0].sent_at_ms, 30000)

    def test_manual_send_exception_restores_editor_for_retry(self):
        sender = Mock(send=Mock(side_effect=RuntimeError("failed")))
        self.ui._enqueue_chat_review("message", sender, "source", self.caption)
        self.ui._send_pending_chat()
        deadline = time.monotonic() + 3
        while self.ui._sending_manual_chat and time.monotonic() < deadline:
            try:
                self.ui.ui_queue.get(timeout=0.1)()
            except queue.Empty:
                continue
        self.assertFalse(self.ui._sending_manual_chat)
        self.assertEqual(len(self.ui._pending_chat), 1)
        self.assertEqual(self.store.sent, [])

    def test_settings_save_and_overlay_use_real_values(self):
        self.ui.show_settings()
        self.assertEqual(tuple(self.ui.preset_selector.cget("values")), ("主播模式", "对话模式"))
        self.ui._option_vars["font_size"].set(22)
        self.ui._option_vars["opacity"].set(0.8)
        self.ui._option_vars["show_original"].set(False)
        self.ui._option_vars["smart_segmentation"].set(True)
        path = Path(self.temporary.name) / "settings.json"
        with patch("streaming_transcribe_translate.desktop_app.SUBTITLE_SETTINGS_FILE", path), patch("streaming_transcribe_translate.desktop_app.messagebox.showinfo"):
            self.assertTrue(self.ui._save_subtitle_settings())
        self.assertEqual(SubtitleSettings.load(path).font_size, 22)
        self.ui.open_overlay()
        self.assertAlmostEqual(self.ui.overlay.attributes("-alpha"), 0.8, places=1)
        self.assertIn("22", self.ui.overlay_text.cget("font"))
        self.ui.show_home()
        self.assertTrue(self.ui.overlay.winfo_exists())

    def test_draft_display_switch_and_timing_switch_work(self):
        self.ui.subtitle_settings.display_mode = "说完再出"
        self.ui.subtitle_settings.show_stats = False
        self.ui.subtitle_settings.show_original = False
        self.ui._show_captions([
            {"original": "hidden source", "translated": "draft", "is_final": False},
            {"original": "hidden source", "translated": "final", "is_final": True},
        ], None)
        text = self.ui.caption_text.get("1.0", "end-1c")
        self.assertNotIn("draft", text)
        self.assertNotIn("hidden source", text)
        self.assertNotIn("ASR", text)
        self.assertIn("final", text)


class ContextPipelineTests(unittest.TestCase):
    def test_fifty_long_captions_are_retained_by_count_not_character_limit(self):
        host = DesktopSessionHost(DesktopSessionPrefs())
        pipeline = Pipeline(host)
        for index in range(51):
            pipeline.board.add(Caption(
                segment_id=index, revision=1, is_final=True,
                original="source", translated="x" * 50000,
                timing=Timing(0, 0, 0, 0, 0, 0, 0), audio_end_at_ms=10000,
            ))
        self.assertEqual(len(pipeline.board.captions), 50)
        self.assertEqual(pipeline.board.captions[0].segment_id, 1)

    def test_manual_pipeline_queues_final_translation_without_sender(self):
        host = DesktopSessionHost(DesktopSessionPrefs())
        host.queue_chat_review = Mock()
        pipeline = Pipeline(host, None, "manual")
        pipeline.setup = SimpleNamespace(mt=Mock(translate=Mock(return_value=MtResult("translation"))))
        pipeline.mt_queue.put({
            "seg_id": 1, "text": "source", "is_final": True,
            "audio_end_ms": 12000, "received_at_ms": 10000, "audio_ms": 2000,
            "asr_latency_ms": 50, "queue_at_ms": round(time.time() * 1000),
        })
        pipeline.running = True
        worker = threading.Thread(target=pipeline._mt_worker)
        worker.start()
        deadline = time.monotonic() + 2
        while not host.queue_chat_review.called and time.monotonic() < deadline:
            time.sleep(0.01)
        pipeline.running = False
        worker.join(2)
        host.queue_chat_review.assert_called_once()
        self.assertIsNone(host.queue_chat_review.call_args.args[1])

    def test_context_contains_final_sentences_only_and_quality_check_retries_once(self):
        host = DesktopSessionHost(DesktopSessionPrefs())
        host._prefs.subtitle_settings.use_context = True
        host._prefs.subtitle_settings.previous_sentences = 2
        host._prefs.subtitle_settings.check_translation = True
        pipeline = Pipeline(host)
        translator = Mock(history=[], correction="", last_messages=[])
        translator.translate.side_effect = [MtResult("wrong"), MtResult("correct")]
        pipeline.setup = SimpleNamespace(mt=translator)
        pipeline.decisions = Mock()
        pipeline.decisions.translation_problem.side_effect = ["reversal", "ok"]
        pipeline.previous.extend([("first", "one"), ("second", "two"), ("third", "three")])
        pipeline.mt_queue.put({
            "seg_id": 1, "text": "current", "is_final": True,
            "audio_end_ms": 12000, "received_at_ms": 10000, "audio_ms": 2000,
            "asr_latency_ms": 50, "queue_at_ms": round(time.time() * 1000),
        })
        pipeline.running = True
        worker = threading.Thread(target=pipeline._mt_worker)
        worker.start()
        deadline = time.monotonic() + 2
        while not pipeline.board.captions and time.monotonic() < deadline:
            time.sleep(0.01)
        pipeline.running = False
        worker.join(2)
        self.assertEqual(translator.history, [("second", "two"), ("third", "three")])
        self.assertEqual(translator.translate.call_count, 2)
        self.assertEqual(pipeline.board.captions[0].translated, "correct")
        self.assertEqual(pipeline.previous[-1], ("current", "correct"))

    def test_unverified_correction_requires_manual_review_even_in_automatic_mode(self):
        host = DesktopSessionHost(DesktopSessionPrefs())
        host._prefs.subtitle_settings.check_translation = True
        host.queue_chat_review = Mock()
        sender = Mock(can_send=Mock(return_value=True))
        pipeline = Pipeline(host, sender, "automatic")
        translator = Mock(history=[], correction="", last_messages=[])
        translator.translate.side_effect = [MtResult("wrong"), MtResult("unverified")]
        pipeline.setup = SimpleNamespace(mt=translator)
        pipeline.decisions = Mock()
        pipeline.decisions.translation_problem.side_effect = ["reversal", None]
        pipeline.mt_queue.put({
            "seg_id": 1, "text": "current", "is_final": True,
            "audio_end_ms": 12000, "received_at_ms": 10000, "audio_ms": 2000,
            "asr_latency_ms": 50, "queue_at_ms": round(time.time() * 1000),
        })
        pipeline.running = True
        worker = threading.Thread(target=pipeline._mt_worker)
        worker.start()
        deadline = time.monotonic() + 2
        while not host.queue_chat_review.called and time.monotonic() < deadline:
            time.sleep(0.01)
        pipeline.running = False
        worker.join(2)
        host.queue_chat_review.assert_called_once()
        sender.send.assert_not_called()
