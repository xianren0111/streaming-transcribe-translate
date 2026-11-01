import unittest
from unittest.mock import Mock, patch

import numpy as np

from streaming_transcribe_translate.desktop_app_example import DesktopSessionHost, DesktopSessionPrefs, StreamingLiveTranslationApp
from streaming_transcribe_translate.simul_streaming_adapter import MicrophoneAudioSource


class MicrophoneTests(unittest.TestCase):
    def setUp(self):
        self.stream = Mock(active=True)
        self.settings = patch("sounddevice.check_input_settings").start()
        self.factory = patch("sounddevice.InputStream", return_value=self.stream).start()
        self.addCleanup(patch.stopall)

    def test_local_capture_format_and_release(self):
        source = MicrophoneAudioSource(device=7)
        self.addCleanup(source.close)
        self.assertEqual(self.factory.call_args.kwargs["samplerate"], 16000)
        self.assertEqual(self.factory.call_args.kwargs["blocksize"], 512)
        self.assertEqual(self.factory.call_args.kwargs["channels"], 1)
        self.assertEqual(self.factory.call_args.kwargs["device"], 7)
        data = np.full((512, 1), 0.25, dtype=np.float32)
        source._capture(data, 512, None, False)
        frame = [0.0] * 512
        self.assertGreater(source.read(frame), 0)
        self.assertEqual(frame, [0.25] * 512)
        source.cancel()
        self.assertEqual(source.read(frame), -1)
        self.stream.abort.assert_called_once()
        self.stream.close.assert_called_once()

    def test_capture_error_is_visible_and_stops_reads(self):
        source = MicrophoneAudioSource()
        self.addCleanup(source.close)
        source._capture(np.zeros((512, 1)), 512, None, "input overflow")
        self.assertEqual(source.read([0.0] * 512), -1)
        self.assertTrue(source.end_reason())

    def test_receipt_timestamp_is_captured_before_queued_audio_is_read(self):
        source = MicrophoneAudioSource()
        self.addCleanup(source.close)
        with patch("time.time", return_value=10000):
            source._capture(np.zeros((512, 1)), 512, None, False)
        with patch("time.time", return_value=10030):
            self.assertEqual(source.read([0.0] * 512), 10030000)
        self.assertEqual(source.received_at_ms, 10000000)

    def test_open_failure_releases_stream(self):
        self.stream.start.side_effect = RuntimeError("device unavailable")
        with self.assertRaises(RuntimeError):
            MicrophoneAudioSource()
        self.stream.close.assert_called_once()

    def test_disconnected_device_reports_error(self):
        self.stream.active = False
        source = MicrophoneAudioSource()
        self.addCleanup(source.close)
        self.assertEqual(source.read([0.0] * 512), -1)
        self.assertTrue(source.end_reason())

    def test_device_discovery_filters_output_only_devices(self):
        with patch("sounddevice.query_devices", return_value=[
            {"name": "speaker", "max_input_channels": 0},
            {"name": "mic", "max_input_channels": 1},
        ]):
            self.assertEqual(MicrophoneAudioSource.devices(), {"1: mic": 1})

    def test_microphone_overrides_audio_but_preserves_chat_destination(self):
        app = StreamingLiveTranslationApp.__new__(StreamingLiveTranslationApp)
        app.host = DesktopSessionHost(DesktopSessionPrefs())
        app.chat_sender = Mock()
        app.chat_mode = "manual"
        sender = app.chat_sender
        app.configure_microphone(7)
        with patch("streaming_transcribe_translate.desktop_app_example.MicrophoneAudioSource") as factory:
            app.host.open_audio()
        factory.assert_called_once_with(7)
        self.assertIs(app.chat_sender, sender)
        self.assertEqual(app.chat_mode, "manual")
