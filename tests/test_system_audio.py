import threading
import time
import unittest

import numpy as np

from streaming_transcribe_translate import app_controller, system_audio
from streaming_transcribe_translate.system_audio import LoopbackAudioSource, PausableAudioSource


class FakeSpeaker:
    def __init__(self, ident):
        self.id = ident
        self.name = f"Speaker {ident}"


class FakeRecorder:
    def __init__(self, backend, rate, channels):
        self.backend = backend
        self.rate = rate
        self.channels = channels

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def record(self, numframes):
        time.sleep(0.005)
        if self.backend.silent:
            return np.zeros((0, self.channels), dtype=np.float32)
        data = np.full((numframes, self.channels), 0.5, dtype=np.float32)
        if self.channels == 2:
            data[:, 1] = -0.1
        return data


class FakeMicrophone:
    def __init__(self, backend):
        self.backend = backend

    def recorder(self, samplerate, channels=2, blocksize=None):
        if self.backend.only_48k and samplerate != 48000:
            raise RuntimeError("unsupported rate")
        return FakeRecorder(self.backend, samplerate, channels)


class FakeBackend:
    def __init__(self, silent=False, only_48k=False, broken=False):
        self.silent = silent
        self.only_48k = only_48k
        self.broken = broken
        self.speaker = FakeSpeaker("a")
        self.opened = []

    def default_speaker(self):
        return self.speaker

    def get_microphone(self, id, include_loopback=False):
        if self.broken:
            raise RuntimeError("no device")
        assert include_loopback
        self.opened.append(id)
        return FakeMicrophone(self)


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class LoopbackSourceTests(unittest.TestCase):
    def make(self, backend, **kwargs):
        source = LoopbackAudioSource(backend, **kwargs)
        self.addCleanup(source.close)
        return source

    def test_reads_512_sample_mono_frames_with_receipt_time(self):
        source = self.make(FakeBackend())
        frame = [0.0] * system_audio.FRAME_SAMPLES
        result = source.read(frame)
        self.assertGreater(result, 0)
        self.assertEqual(len(frame), 512)
        self.assertAlmostEqual(frame[0], 0.5, places=4)
        self.assertGreater(source.received_at_ms, 0)
        self.assertTrue(source.estimated)
        self.assertEqual(source.device_name, "Speaker a")

    def test_48k_stereo_fallback_is_downmixed_and_resampled(self):
        backend = FakeBackend(only_48k=True)
        source = self.make(backend)
        frame = [0.0] * 512
        self.assertGreater(source.read(frame), 0)
        self.assertAlmostEqual(frame[100], 0.2, places=4)

    def test_helpers(self):
        self.assertEqual(system_audio.to_mono(np.ones((4, 2))).shape, (4,))
        self.assertEqual(len(system_audio.resample(np.zeros(4800), 48000)), 1600)
        self.assertEqual(len(system_audio.resample(np.zeros(512), 16000)), 512)

    def test_silence_feeds_zeros_instead_of_blocking(self):
        source = self.make(FakeBackend(silent=True), silence_after=0.05)
        frame = [1.0] * 512
        started = time.monotonic()
        result = source.read(frame)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertGreater(result, 0)
        self.assertEqual(set(frame), {0.0})
        self.assertGreater(source.received_at_ms, 0)

    def test_default_device_change_reopens_capture(self):
        backend = FakeBackend()
        source = self.make(backend, device_check_interval=0.02)
        self.assertTrue(wait_for(lambda: backend.opened))
        backend.speaker = FakeSpeaker("b")
        self.assertTrue(wait_for(lambda: source.reopen_count >= 1))
        self.assertEqual(backend.opened[-1], "b")
        self.assertTrue(wait_for(lambda: source.device_name == "Speaker b"))

    def test_open_failure_ends_with_friendly_reason(self):
        source = self.make(FakeBackend(broken=True), max_open_failures=1, silence_after=5)
        frame = [0.0] * 512
        self.assertEqual(source.read(frame), -1)
        self.assertEqual(source.end_reason(), system_audio.OPEN_FAILED)

    def test_close_stops_reads(self):
        source = self.make(FakeBackend(silent=True), silence_after=5)
        source.close()
        self.assertEqual(source.read([0.0] * 512), -1)


class FakeSource:
    received_at_ms = 42
    estimated = False
    closed = False

    def read(self, frame):
        frame[:] = [0.3] * len(frame)
        return 1000

    def end_reason(self):
        return None

    def close(self):
        self.closed = True

    def cancel(self):
        self.close()


class PausableTests(unittest.TestCase):
    def test_paused_frames_are_silent_and_attributes_delegate(self):
        paused = threading.Event()
        inner = FakeSource()
        source = PausableAudioSource(inner, paused)
        frame = [0.0] * 4
        self.assertEqual(source.read(frame), 1000)
        self.assertEqual(frame, [0.3] * 4)
        paused.set()
        self.assertEqual(source.read(frame), 1000)
        self.assertEqual(frame, [0.0] * 4)
        self.assertEqual(source.received_at_ms, 42)
        self.assertFalse(source.estimated)
        source.close()
        self.assertTrue(inner.closed)


class ControllerAudioInputTests(unittest.TestCase):
    def test_computer_sound_is_a_local_audio_input(self):
        self.assertIn("电脑声音", app_controller.AUDIO_INPUTS)
        self.assertIn("电脑声音", app_controller.LOCAL_AUDIO_INPUTS)
        self.assertIn("麦克风", app_controller.LOCAL_AUDIO_INPUTS)


if __name__ == "__main__":
    unittest.main()
