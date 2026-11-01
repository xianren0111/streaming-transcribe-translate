import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from streaming_transcribe_translate.caption_session import FRAME_SIZE, SAMPLE_RATE, Pipeline, Segmenter
from streaming_transcribe_translate.desktop_app_example import DesktopSessionHost, DesktopSessionPrefs
from streaming_transcribe_translate.simul_interfaces import MtResult


class SegmenterParityTests(unittest.TestCase):
    def setUp(self):
        self.models = Mock()
        self.models.vad_prob.side_effect = lambda samples: 1.0 if samples[0] else 0.0

    def feed(self, segmenter, frames, speech):
        result = []
        for _ in range(frames):
            result.extend(segmenter.process_frame([0.1 if speech else 0.0] * FRAME_SIZE, 0))
        return result

    def test_reference_defaults_and_short_fragment_hold(self):
        segmenter = Segmenter(self.models)
        self.assertEqual(segmenter.threshold, 0.5)
        self.assertEqual(segmenter.silence_ms, 400)
        self.assertEqual(segmenter.draft_every_ms, 700)
        self.assertEqual(segmenter.min_draft_ms, 600)
        self.assertEqual(segmenter.max_utterance_ms, 7000)
        self.assertEqual(segmenter.pre_roll_ms, 200)
        self.assertEqual(segmenter.max_hold_silence_ms, 1500)
        self.feed(segmenter, 1, True)
        self.assertEqual(self.feed(segmenter, 46, False), [])
        final = self.feed(segmenter, 1, False)
        self.assertEqual(len(final), 1)
        self.assertTrue(final[0][2])

    def test_short_fragment_continuation_stays_in_same_segment(self):
        segmenter = Segmenter(self.models)
        self.feed(segmenter, 1, True)
        self.feed(segmenter, 20, False)
        self.feed(segmenter, 12, True)
        final = self.feed(segmenter, 13, False)
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0][0], 0)

    def test_forced_cut_uses_pause_and_preserves_every_sample(self):
        segmenter = Segmenter(self.models)
        segmenter.early_cut_after_ms = 0
        emitted = []
        for index in range(219):
            speech = not 135 <= index < 145
            emitted.extend(segmenter.process_frame([0.1 if speech else 0.0] * FRAME_SIZE, index * 32))
        finals = [job for job in emitted if job[2]]
        self.assertEqual(len(finals), 1)
        self.assertLess(len(finals[0][1]), 219 * FRAME_SIZE)
        self.assertEqual(len(finals[0][1]) + len(segmenter.buffered_samples), 219 * FRAME_SIZE)
        self.assertEqual(segmenter.segment_id, 1)

    def test_decision_wait_is_one_second_and_unfinished_forced_cut_doubles_limit(self):
        waiting = Segmenter(self.models, hold_hint=lambda _segment: None, reset_hint=lambda _segment: 1)
        self.feed(waiting, 20, True)
        candidate = self.feed(waiting, 7, False)
        self.assertEqual(len(candidate), 1)
        self.assertFalse(candidate[0][2])
        self.assertEqual(self.feed(waiting, 6, False), [])
        self.assertEqual(self.feed(waiting, 18, False), [])
        self.assertEqual(self.feed(waiting, 7, False), [])
        self.assertTrue(self.feed(waiting, 1, False)[0][2])

        held = Segmenter(self.models, hold_hint=lambda _segment: True, reset_hint=lambda _segment: 1,
                         max_utterance_ms=5000)
        first = self.feed(held, 157, True)
        self.assertFalse(any(job[2] for job in first))
        self.assertEqual(len(held.buffered_samples), 157 * FRAME_SIZE)
        final = self.feed(held, 156, True)
        self.assertTrue(any(job[2] for job in final))
        forced_final = next(job for job in final if job[2])
        self.assertEqual(len(forced_final[1]), 157 * FRAME_SIZE)
        self.assertEqual(len(held.buffered_samples), 156 * FRAME_SIZE)

    def test_long_sentence_uses_192_ms_pause_without_decisions(self):
        segmenter = Segmenter(self.models)
        self.feed(segmenter, 100, True)
        self.assertEqual(self.feed(segmenter, 5, False), [])
        final = self.feed(segmenter, 1, False)
        self.assertEqual(len(final), 1)
        self.assertTrue(final[0][2])


class PipelineParityTests(unittest.TestCase):
    def setUp(self):
        self.host = DesktopSessionHost(DesktopSessionPrefs())
        self.notices = []
        self.host.set_notice_callback(self.notices.append)
        self.pipeline = Pipeline(self.host, chat_mode="manual")
        self.pipeline.models = SimpleNamespace(asr=Mock())
        self.pipeline.models.asr.recognize.return_value = "same source sentence"

    def tearDown(self):
        self.pipeline.stop()

    def test_stale_drafts_collapse_and_final_is_prioritized(self):
        self.pipeline.add_audio_segment(4, [0.1] * 2, False, 0)
        self.pipeline.add_audio_segment(4, [0.2] * 3, False, 0)
        self.assertEqual(self.pipeline.asr_queue.qsize(), 1)
        self.pipeline.add_audio_segment(4, [0.3] * 4, True, 0)
        self.assertEqual(self.pipeline.asr_queue.qsize(), 1)
        final = self.pipeline.asr_queue.get_nowait()
        self.assertTrue(final["is_final"])
        self.assertEqual(final["samples"], [0.3] * 4)

    def test_pending_audio_over_30_seconds_stops_acceptance_and_reports_abandonment(self):
        self.pipeline.add_audio_segment(1, [0.0] * 480000, True, 0)
        self.assertFalse(self.pipeline.overloaded)
        self.pipeline.add_audio_segment(2, [0.0] * 16, True, 0)
        self.assertTrue(self.pipeline.overloaded)
        self.assertFalse(self.pipeline.accepting)
        self.assertTrue(self.notices)
        self.assertEqual(self.pipeline.drain(timeout=0.1), 2)
        self.assertEqual(self.pipeline.pending_final_jobs, 0)

    def test_final_stream_partials_update_caption_but_chat_gets_only_final_text(self):
        calls = []
        partials = []
        review = queue.Queue()
        self.host.set_chat_review_callback(lambda message, sender, original, record:
                                           review.put((message, original)))
        self.host.set_caption_callback(lambda captions, error:
                                       partials.extend(item["translated"] for item in captions))

        class Translator:
            history = []
            correction = ""

            @staticmethod
            def _system_message():
                return "stable system"

            def translate_with_updates(self, text, on_partial):
                calls.append(text)
                on_partial("partial translation")
                return MtResult("final translation")

            def translate(self, text):
                calls.append(text)
                return MtResult("final translation")

        self.pipeline.setup = SimpleNamespace(mt=Translator())
        self.pipeline.start()
        self.pipeline.add_audio_segment(7, [0.1] * FRAME_SIZE, False, 0)
        deadline = threading.Event()
        # Wait until the draft has been translated before adding its final revision.
        for _ in range(100):
            if calls:
                break
            deadline.wait(0.01)
        self.assertTrue(calls)
        self.pipeline.add_audio_segment(7, [0.1] * FRAME_SIZE, True, 0)
        message, original = review.get(timeout=2)
        self.assertEqual(original, "same source sentence")
        self.assertIn("final translation", message)
        self.assertTrue(any("partial translation" in item for item in partials))
        self.assertEqual(calls, ["same source sentence"])
        self.assertNotIn("partial translation", message)

    def test_final_translation_failure_is_shown_without_sending_or_stopping_pipeline(self):
        review = queue.Queue()
        shown = queue.Queue()
        self.host.set_chat_review_callback(lambda *args: review.put(args))
        self.host.set_caption_callback(lambda captions, error: shown.put((captions, error)))

        class Translator:
            history = []
            correction = ""

            @staticmethod
            def _system_message():
                return "stable system"

            @staticmethod
            def translate(_text):
                return MtResult("", error="service unavailable")

        self.pipeline.setup = SimpleNamespace(mt=Translator())
        self.pipeline.start()
        self.pipeline.add_audio_segment(11, [0.1] * FRAME_SIZE, True, 0)
        deadline = threading.Event()
        captions, error = shown.get(timeout=2)
        self.assertEqual(error, "service unavailable")
        for _ in range(100):
            captions = self.pipeline.board.get_display_captions(limit=10)
            if captions:
                break
            deadline.wait(0.01)
        self.assertEqual(captions[-1].translated, "[\u7ffb\u8bd1\u5931\u8d25] same source sentence")
        self.assertTrue(self.pipeline.running)
        self.assertTrue(review.empty())

    def test_opening_words_from_earlier_draft_are_restored(self):
        self.pipeline.latest_drafts[2] = "\u4eca\u65e5\u306f\u56f3\u66f8\u9928\u306b"
        self.assertEqual(
            self.pipeline._repair_lost_opening(2, "\u56f3\u66f8\u9928\u306b\u884c\u304d\u307e\u3057\u305f"),
            "\u4eca\u65e5\u306f\u56f3\u66f8\u9928\u306b\u884c\u304d\u307e\u3057\u305f",
        )


if __name__ == "__main__":
    unittest.main()
