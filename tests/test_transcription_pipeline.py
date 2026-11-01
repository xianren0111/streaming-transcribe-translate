import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from streaming_transcribe_translate.caption_session import FRAME_SIZE, SAMPLE_RATE, Pipeline, Segmenter, is_sound_only
from streaming_transcribe_translate.desktop_app_example import DesktopSessionHost, DesktopSessionPrefs
from streaming_transcribe_translate.simul_interfaces import MtResult
from streaming_transcribe_translate.simul_streaming_adapter import StreamingProjectAsr


class SegmenterTests(unittest.TestCase):
    def setUp(self):
        self.models = Mock()
        self.models.vad_prob.side_effect = lambda samples: 1.0 if samples[0] else 0.0
        self.segmenter = Segmenter(self.models)

    def feed(self, frames, speech=True):
        segments = []
        for _ in range(frames):
            # Decoder read times may be identical for a burst of buffered audio.
            segments.extend(self.segmenter.process_frame(
                [0.1 if speech else 0.0] * FRAME_SIZE, 0
            ))
        return segments

    def test_draft_arrives_during_speech_in_704_ms(self):
        self.assertEqual(FRAME_SIZE * 1000 / SAMPLE_RATE, 32)
        self.assertEqual(self.feed(21), [])
        draft = self.feed(1)
        self.assertEqual(len(draft), 1)
        self.assertFalse(draft[0][2])
        self.assertEqual(len(draft[0][1]) * 1000 / SAMPLE_RATE, 704)

    def test_final_after_416_ms_silence_without_duplicate_drafts(self):
        self.feed(22)
        self.assertEqual(self.feed(12, speech=False), [])
        final = self.feed(1, speech=False)
        self.assertEqual(len(final), 1)
        self.assertTrue(final[0][2])
        self.assertEqual(self.feed(25, speech=False), [])

    def test_continuous_speech_is_bounded_at_seven_seconds(self):
        segments = self.feed(219)
        finals = [segment for segment in segments if segment[2]]
        self.assertEqual(len(finals), 1)
        self.assertEqual(len(finals[0][1]) * 1000 / SAMPLE_RATE, 7008)
        self.assertEqual(self.segmenter.segment_id, 1)

    def test_pause_samples_and_preroll_are_preserved(self):
        self.feed(5, speech=False)
        self.feed(22)
        final = self.feed(13, speech=False)[0]
        self.assertEqual(len(final[1]), (5 + 22 + 13) * FRAME_SIZE)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.host = DesktopSessionHost(DesktopSessionPrefs())
        self.events = queue.Queue()
        self.host.set_transcription_callback(
            lambda *args: self.events.put(("asr", args))
        )
        self.host.set_chat_review_callback(
            lambda *args: self.events.put(("review", args))
        )
        self.sender = Mock()
        self.sender.can_send.return_value = True
        self.pipeline = Pipeline(self.host, self.sender, "manual")
        self.pipeline.models = SimpleNamespace(asr=Mock())
        self.pipeline.models.asr.recognize.return_value = "original speech"

    def test_asr_is_visible_before_slow_translation_and_review_keeps_original(self):
        translation_started, release_translation = threading.Event(), threading.Event()

        def translate(text):
            translation_started.set()
            release_translation.wait(3)
            return MtResult("translated speech")

        self.pipeline.setup = SimpleNamespace(mt=SimpleNamespace(translate=translate))
        self.pipeline.add_audio_segment(3, [0.1] * FRAME_SIZE, True, 0)
        self.pipeline.start()
        try:
            self.assertTrue(translation_started.wait(2))
            kind, args = self.events.get(timeout=1)
            self.assertEqual(kind, "asr")
            self.assertEqual(args[:3], (3, "original speech", True))
            release_translation.set()
            kind, args = self.events.get(timeout=2)
            self.assertEqual(kind, "review")
            self.assertIn("translated speech", args[0])
            self.assertIs(args[1], self.sender)
            self.assertEqual(args[2], "original speech")
            self.sender.send.assert_not_called()
        finally:
            release_translation.set()
            self.pipeline.stop()

    def test_backlogged_drafts_do_not_prevent_final_job(self):
        self.pipeline.add_audio_segment(1, [0.1], False, 0)
        self.pipeline.add_audio_segment(1, [0.1] * 2, False, 0)
        self.pipeline.add_audio_segment(1, [0.1] * 3, True, 0)
        self.assertEqual(self.pipeline.asr_queue.qsize(), 1)
        self.assertTrue(self.pipeline.asr_queue.get_nowait()["is_final"])

    def test_sound_only_finals_skip_translation_review_and_automatic_send(self):
        for mode in ("manual", "automatic"):
            with self.subTest(mode=mode):
                self.setUp()
                self.pipeline.chat_mode = mode
                self.pipeline.models.asr.recognize.return_value = "哈哈哈！"
                translator = Mock()
                self.pipeline.setup = SimpleNamespace(mt=translator)
                self.pipeline.add_audio_segment(1, [0.1] * FRAME_SIZE, True, 0)
                self.pipeline.start()
                try:
                    self.assertEqual(self.pipeline.drain(timeout=2), 0)
                    self.assertEqual(self.pipeline.pending_final_jobs, 0)
                    translator.translate.assert_not_called()
                    self.sender.send.assert_not_called()
                    self.assertTrue(self.events.empty())
                finally:
                    self.pipeline.stop()

    def test_disabled_sound_filter_and_mixed_speech_are_translated(self):
        for text, enabled in (("哈哈哈！", False), ("哈哈，今天真开心", True)):
            with self.subTest(text=text, enabled=enabled):
                self.setUp()
                self.pipeline.options.ignore_onomatopoeia = enabled
                self.host.prefs.subtitle_settings.ignore_onomatopoeia = enabled
                self.pipeline.models.asr.recognize.return_value = text
                translator = Mock()
                translator.translate.return_value = MtResult("translated speech")
                self.pipeline.setup = SimpleNamespace(mt=translator)
                self.pipeline.add_audio_segment(1, [0.1] * FRAME_SIZE, True, 0)
                self.pipeline.start()
                try:
                    self.assertEqual(self.pipeline.drain(timeout=2), 0)
                    translator.translate.assert_called_once_with(text)
                finally:
                    self.pipeline.stop()


class SoundFilterTests(unittest.TestCase):
    def test_known_whole_utterances(self):
        for text in ("哈哈哈！", "哈 哈，哈哈。", "呵呵", "喵喵！", "汪汪", "砰！",
                     "あはは！", "アハハ", "にゃーん", "ワンワン", "ドキドキ",
                     "ha ha ha!", "HAHAHA", "meow, woof!", "ㅋㅋㅋ", "하하하",
                     "ふん", "うん", "あっ", "えっ？", "アッ！", "うっ", "うっ！", "ウッ",
                     "嗯", "啊", "哦", "唔", "哼", "oh!", "uh", "hmmm"):
            with self.subTest(text=text):
                self.assertTrue(is_sound_only(text))

    def test_mixed_ambiguous_and_unknown_utterances_remain(self):
        for text in ("哈哈，今天真开心", "猫在喵喵叫", "あはは、ありがとう",
                     "ドキドキする", "うん、わかった", "あっ、見つけた", "えっ、本当？",
                     "ふん、そういうことか", "うっ、痛い", "ha ha that's funny", "bang the drum",
                     "啊，找到了", "嗯，我知道", "oh that's nice", "は", "ha", "yes", "", "！？", "123"):
            with self.subTest(text=text):
                self.assertFalse(is_sound_only(text))


class AsrBackendTests(unittest.TestCase):
    def test_cuda_does_not_depend_on_pytorch_and_is_warmed_before_capture(self):
        with (
            patch("ctranslate2.get_cuda_device_count", return_value=1),
            patch("faster_whisper.WhisperModel") as factory,
            patch.object(StreamingProjectAsr, "recognize", return_value="") as warmup,
        ):
            StreamingProjectAsr("base", "ja")
        self.assertEqual(factory.call_args.kwargs["device"], "cuda")
        self.assertEqual(factory.call_args.kwargs["compute_type"], "float16")
        warmup.assert_called_once()

    def test_cpu_uses_int8_when_no_cuda_device(self):
        with (
            patch("ctranslate2.get_cuda_device_count", return_value=0),
            patch("faster_whisper.WhisperModel") as factory,
            patch.object(StreamingProjectAsr, "recognize", return_value=""),
        ):
            StreamingProjectAsr("base", "ja")
        self.assertEqual(factory.call_args.kwargs["device"], "cpu")
        self.assertEqual(factory.call_args.kwargs["compute_type"], "int8")

    def test_fast_decode_options(self):
        asr = StreamingProjectAsr.__new__(StreamingProjectAsr)
        asr.language = "ja"
        asr.model = Mock()
        asr.model.transcribe.return_value = ([SimpleNamespace(text=" speech ")], None)
        self.assertEqual(asr.recognize([0.1] * FRAME_SIZE), "speech")
        self.assertEqual(asr.model.transcribe.call_args.kwargs["beam_size"], 1)
        self.assertFalse(asr.model.transcribe.call_args.kwargs["condition_on_previous_text"])


if __name__ == "__main__":
    unittest.main()
