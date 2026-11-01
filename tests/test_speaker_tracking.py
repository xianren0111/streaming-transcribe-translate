import csv
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from streaming_transcribe_translate.caption_session import Pipeline
from streaming_transcribe_translate.desktop_app_example import DesktopSessionHost, DesktopSessionPrefs
from streaming_transcribe_translate.simul_interfaces import MtResult
from streaming_transcribe_translate.speaker_tracking import SpeakerTracker
from streaming_transcribe_translate.subtitle_records import SessionRecords
from streaming_transcribe_translate.subtitle_settings import SubtitleSettings
from streaming_transcribe_translate.setup_models import download_verified
from tests.test_web_ui import WebTestCase


class SpeakerTrackerTests(unittest.TestCase):
    def test_model_download_timeout_integrity_and_retry(self):
        payload = b"test model"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.onnx"
            with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")) as request:
                with self.assertRaises(TimeoutError):
                    download_verified(path, "https://example.invalid/model", len(payload), digest)
                request.assert_called_once_with("https://example.invalid/model", timeout=30)
            self.assertFalse(path.exists())
            with patch("urllib.request.urlopen", return_value=io.BytesIO(b"wrong")):
                with self.assertRaises(RuntimeError):
                    download_verified(path, "https://example.invalid/model", len(payload), digest)
            self.assertFalse(path.with_name(path.name + ".part").exists())
            with patch("urllib.request.urlopen", return_value=io.BytesIO(payload)):
                download_verified(path, "https://example.invalid/model", len(payload), digest)
            self.assertEqual(path.read_bytes(), payload)

    def tracker(self, embeddings):
        tracker = SpeakerTracker.__new__(SpeakerTracker)
        tracker.extractor = Mock()
        tracker.extractor.is_ready.return_value = True
        tracker.extractor.compute.side_effect = embeddings
        tracker.centroids = []
        tracker.counts = []
        tracker.pending_embedding = None
        return tracker

    def test_matching_new_and_returning_speakers(self):
        tracker = self.tracker([[1, 0], [0.99, 0.01], [0, 1], [0, 1], [1, 0]])
        self.assertEqual([tracker.identify([0.1] * 32000) for _ in range(5)], [1, 1, None, 2, 1])

    def test_borderline_same_voice_does_not_create_new_speaker(self):
        tracker = self.tracker([[1, 0], [0.64, 0.768375], [1, 0]])
        self.assertEqual([tracker.identify([0.1] * 32000) for _ in range(3)], [1, None, 1])
        self.assertEqual(len(tracker.centroids), 1)

    def test_single_outlier_and_short_segments_cannot_create_new_speaker(self):
        tracker = self.tracker([[1, 0], [0, 1], [1, 0], [0, 1], [0, 1]])
        self.assertEqual([tracker.identify([0.1] * 32000) for _ in range(3)], [1, None, 1])
        self.assertIsNone(tracker.identify([0.1] * 16000))
        self.assertIsNone(tracker.identify([0.1] * 32000))
        self.assertEqual(len(tracker.centroids), 1)

    def test_short_quiet_and_unready_segments_are_unlabelled(self):
        tracker = self.tracker([])
        self.assertIsNone(tracker.identify([0.1] * 100))
        self.assertIsNone(tracker.identify([0.0] * 16000))
        tracker.extractor.is_ready.return_value = False
        self.assertIsNone(tracker.identify([0.1] * 16000))
        tracker.extractor.compute.assert_not_called()

    def test_invalid_embeddings_surface_errors(self):
        for embedding in ([0, 0], [float("nan"), 1]):
            with self.subTest(embedding=embedding):
                with self.assertRaises(RuntimeError):
                    self.tracker([embedding]).identify([0.1] * 16000)

    def test_speaker_limit_does_not_force_wrong_assignment(self):
        tracker = self.tracker([[0, 1]])
        tracker.centroids = [np.array([1.0, 0.0])] * 20
        tracker.counts = [1] * 20
        self.assertIsNone(tracker.identify([0.1] * 16000))

    def test_disabled_pipeline_does_not_load_model(self):
        host = DesktopSessionHost(DesktopSessionPrefs())
        pipeline = Pipeline(host)
        with patch("streaming_transcribe_translate.speaker_tracking.SpeakerTracker") as factory:
            pipeline.start()
            pipeline.stop()
        factory.assert_not_called()
        self.assertFalse(SubtitleSettings().distinguish_speakers)

    def test_pipeline_labels_display_and_records_but_not_translation_or_chat(self):
        host = DesktopSessionHost(DesktopSessionPrefs())
        host.prefs.subtitle_settings.distinguish_speakers = True
        display = Mock()
        host.set_caption_callback(display)
        with tempfile.TemporaryDirectory() as directory:
            host.records = SessionRecords(Path(directory), enabled=False, started_at_ms=1000)
            sender = Mock()
            sender.can_send.return_value = True
            sender.send.return_value = (True, "ok")
            translator = Mock()
            translator.translate.return_value = MtResult("translated")
            pipeline = Pipeline(host, sender, "automatic")
            pipeline.models = SimpleNamespace(asr=Mock(recognize=Mock(return_value="hello")))
            pipeline.setup = SimpleNamespace(mt=translator)
            with patch("streaming_transcribe_translate.speaker_tracking.SpeakerTracker") as factory:
                factory.return_value.identify.return_value = 2
                pipeline.start()
                try:
                    pipeline.add_audio_segment(1, [0.1] * 16000, True, 3000, 2000)
                    self.assertEqual(pipeline.drain(timeout=2), 0)
                    translator.translate.assert_called_once_with("hello")
                    self.assertEqual(host.records.captions[0].speaker_id, 2)
                    self.assertTrue(any(
                        call.args[0] and call.args[0][0]["translated"] == "[Speaker 2] translated"
                        for call in display.call_args_list
                    ))
                    self.assertTrue(sender.send.called)
                    self.assertNotIn("Speaker", sender.send.call_args.args[0])
                    self.assertEqual(host.records.reviewed[0].action, "sent")
                finally:
                    pipeline.stop()

    def test_record_export_labels_without_changing_actual_message(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionRecords(Path(directory), started_at_ms=1000)
            record = store.caption(1, 2000, 3000, 1000, "hello", "translated", speaker_id=2)
            store.skip(record, "edited", 4000)
            srt_path, csv_path = store.export(Path(directory), 1000, include_skipped=True)
            with csv_path.open(encoding="utf-8-sig", newline="") as file:
                row = next(csv.DictReader(file))
            self.assertEqual(row["speaker_id"], "2")
            self.assertEqual(row["actual_reviewed_text"], "edited")
            self.assertIn("[Speaker 2] edited", srt_path.read_text(encoding="utf-8"))
            loaded = SessionRecords.restore(store.directory)
            self.assertEqual(loaded.reviewed[0].caption.speaker_id, 2)


class SpeakerSettingsTests(WebTestCase):
    def test_missing_model_requires_explicit_consent(self):
        with patch("streaming_transcribe_translate.speaker_tracking.model_ready", return_value=False), patch(
            "streaming_transcribe_translate.speaker_tracking.download_model"
        ) as download:
            status, _ = self.request("POST", "/api/settings/subtitle", {"distinguish_speakers": True})
            self.assertNotEqual(status, 200)
            download.assert_not_called()
            self.assertFalse(self.controller.subtitle_settings.distinguish_speakers)
            status, _ = self.request("POST", "/api/settings/subtitle", {
                "distinguish_speakers": True, "confirm_speaker_download": True,
            })
            self.assertEqual(status, 200)
            download.assert_called_once()
            self.assertTrue(self.controller.subtitle_settings.distinguish_speakers)

    def test_download_failure_leaves_setting_off(self):
        with patch("streaming_transcribe_translate.speaker_tracking.model_ready", return_value=False), patch(
            "streaming_transcribe_translate.speaker_tracking.download_model", side_effect=OSError("offline")
        ):
            status, _ = self.request("POST", "/api/settings/subtitle", {
                "distinguish_speakers": True, "confirm_speaker_download": True,
            })
            self.assertNotEqual(status, 200)
            self.assertFalse(self.controller.subtitle_settings.distinguish_speakers)

    def test_active_session_cannot_change_speaker_setting(self):
        self.controller._session_started_at = 1
        with patch("streaming_transcribe_translate.speaker_tracking.download_model") as download:
            status, _ = self.request("POST", "/api/settings/subtitle", {
                "distinguish_speakers": True, "confirm_speaker_download": True,
            })
            self.assertNotEqual(status, 200)
            download.assert_not_called()
