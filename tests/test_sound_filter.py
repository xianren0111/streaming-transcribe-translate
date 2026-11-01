import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from streaming_transcribe_translate.sound_filter import SemanticSoundFilter
from streaming_transcribe_translate.caption_session import Pipeline
from streaming_transcribe_translate.desktop_app_example import DesktopSessionHost, DesktopSessionPrefs
from streaming_transcribe_translate.simul_interfaces import MtResult


class SemanticSoundTests(unittest.TestCase):
    def test_cache_is_bounded(self):
        client = SemanticSoundFilter("https://example.invalid/v1", "model", None, Mock())
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.json.return_value = {"choices": [{"message": {"content": "SPEECH"}}]}
        with patch("streaming_transcribe_translate.sound_filter.requests.post", return_value=response):
            for index in range(257):
                self.assertFalse(client.should_skip(str(index)))
        self.assertEqual(len(client.cache), 256)
        self.assertNotIn("0", client.cache)

    def test_strict_classification_cache_and_request_shape(self):
        notify = Mock()
        client = SemanticSoundFilter("https://example.invalid/v1/", "model", "test", notify)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.json.side_effect = [
            {"choices": [{"message": {"content": "SOUND"}}]},
            {"choices": [{"message": {"content": "SPEECH"}}]},
        ]
        with patch("streaming_transcribe_translate.sound_filter.requests.post", return_value=response) as post:
            self.assertTrue(client.should_skip("unknown sound"))
            self.assertTrue(client.should_skip("unknown sound"))
            self.assertFalse(client.should_skip("sound plus meaningful speech"))
            self.assertEqual(post.call_count, 2)
            self.assertEqual(post.call_args.args[0], "https://example.invalid/v1/chat/completions")
            self.assertEqual(post.call_args.kwargs["timeout"], (3, 5))
            self.assertEqual(post.call_args.kwargs["json"]["model"], "model")
            self.assertEqual(post.call_args.kwargs["json"]["messages"][1]["content"], "sound plus meaningful speech")
        notify.assert_not_called()

    def test_failure_preserves_text_notifies_and_pauses(self):
        for failure in (requests.Timeout(), requests.HTTPError(), ValueError()):
            notify = Mock()
            client = SemanticSoundFilter("https://example.invalid/v1", "model", None, notify)
            with patch("streaming_transcribe_translate.sound_filter.requests.post", side_effect=failure) as post:
                self.assertFalse(client.should_skip("unknown"))
                self.assertFalse(client.should_skip("other"))
                post.assert_called_once()
                notify.assert_called_once()
                self.assertFalse(client.cache)

    def test_invalid_response_is_not_treated_as_sound(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        for value in ("sound", "SOUND because...", None, True):
            notify = Mock()
            client = SemanticSoundFilter("https://example.invalid/v1", "model", None, notify)
            response.json.return_value = {"choices": [{"message": {"content": value}}]}
            with patch("streaming_transcribe_translate.sound_filter.requests.post", return_value=response):
                self.assertFalse(client.should_skip("unknown"))
                notify.assert_called_once()

    def test_pipeline_filters_once_before_translation_and_no_request_when_disabled(self):
        for enabled, sound in ((True, True), (True, False), (False, True)):
            with self.subTest(enabled=enabled, sound=sound):
                host = DesktopSessionHost(DesktopSessionPrefs())
                host.prefs.subtitle_settings.semantic_sound_filter = enabled
                host.prefs.get_translation_base_url = Mock(return_value="https://example.invalid/v1")
                translator = Mock()
                translator.translate.return_value = MtResult("translation")
                pipeline = Pipeline(host, chat_mode="off")
                pipeline.models = SimpleNamespace(asr=Mock(recognize=Mock(return_value="unknown utterance")))
                pipeline.setup = SimpleNamespace(mt=translator)
                with patch("streaming_transcribe_translate.sound_filter.SemanticSoundFilter") as factory:
                    factory.return_value.should_skip.return_value = sound
                    pipeline.add_audio_segment(1, [0.1] * 16000, True, 3000, 2000)
                    pipeline.start()
                    try:
                        self.assertEqual(pipeline.drain(timeout=2), 0)
                        if enabled:
                            factory.return_value.should_skip.assert_called_once_with("unknown utterance")
                        else:
                            factory.assert_not_called()
                        if enabled and sound:
                            translator.translate.assert_not_called()
                        else:
                            translator.translate.assert_called_once_with("unknown utterance")
                    finally:
                        pipeline.stop()
