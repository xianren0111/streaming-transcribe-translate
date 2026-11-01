"""Computer sound ("电脑声音") capture via WASAPI loopback of the default playback device.

Mirrors the reference app's ``sysaudio`` helper: 16 kHz mono float frames, follows
default-device changes, and keeps feeding silence when nothing is playing (WASAPI
loopback delivers no packets then) so the pipeline never blocks forever.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import warnings
from typing import Any, Callable, List, Optional

from .simul_interfaces import AudioSource

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512
FALLBACK_RATE = 48000
OPEN_FAILED = "无法捕获电脑声音，请检查播放设备（扬声器/耳机）后重新开始。"
NOT_INSTALLED = "缺少电脑声音组件，请运行 Setup Models.bat 或 pip install soundcard 后重试。"


def _load_soundcard() -> Any:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import soundcard  # type: ignore[import-not-found]
    except Exception as error:  # ImportError, or COM errors on unusual systems
        raise RuntimeError(NOT_INSTALLED) from error
    try:
        warnings.filterwarnings("ignore", category=soundcard.SoundcardRuntimeWarning)
    except AttributeError:
        pass
    return soundcard


def _co_initialize() -> None:
    """WASAPI needs COM on every capture thread."""
    try:
        import ctypes

        ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
    except (AttributeError, OSError):
        pass


def to_mono(data: Any) -> Any:
    import numpy as np

    samples = np.asarray(data, dtype=np.float32)
    if samples.ndim == 2:
        samples = samples.mean(axis=1) if samples.shape[1] > 1 else samples[:, 0]
    return samples.reshape(-1)


def resample(samples: Any, source_rate: int, target_rate: int = SAMPLE_RATE) -> Any:
    """Linear resampling; good enough for speech recognition input."""
    import numpy as np

    samples = np.asarray(samples, dtype=np.float32)
    if source_rate == target_rate or not len(samples):
        return samples
    count = max(1, round(len(samples) * target_rate / source_rate))
    positions = np.linspace(0, len(samples) - 1, count)
    return np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)


class LoopbackAudioSource(AudioSource):
    """Capture what the default speaker plays, as 16 kHz mono ``float`` frames."""

    def __init__(
        self,
        backend: Any = None,
        *,
        silence_after: float = 0.25,
        device_check_interval: float = 1.0,
        max_open_failures: int = 5,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._sc = backend if backend is not None else _load_soundcard()
        self.cancelled = threading.Event()
        self.chunks: queue.Queue = queue.Queue(maxsize=400)
        self._buffer: list[float] = []
        self._buffer_received_at = 0
        self._end_reason: Optional[str] = None
        self._fatal = threading.Event()
        self._silence_after = silence_after
        self._device_check_interval = device_check_interval
        self._max_open_failures = max_open_failures
        self._clock = clock
        self.device_name = ""
        self.reopen_count = 0
        self.received_at_ms = 0
        self._thread = threading.Thread(target=self._capture_loop, name="loopback-capture", daemon=True)
        self._thread.start()

    # ---------------------------------------------------------------- capture

    def _default_speaker(self) -> Any:
        return self._sc.default_speaker()

    def _open_recorder(self, speaker: Any) -> tuple[Any, int]:
        microphone = None
        for key in (getattr(speaker, "id", None), str(getattr(speaker, "name", ""))):
            if not key:
                continue
            try:
                microphone = self._sc.get_microphone(id=key, include_loopback=True)
                break
            except (IndexError, KeyError, ValueError, RuntimeError):
                continue
        if microphone is None:
            raise RuntimeError("no loopback device for the default speaker")
        try:
            recorder = microphone.recorder(samplerate=SAMPLE_RATE, channels=1, blocksize=FRAME_SAMPLES)
            recorder.__enter__()
            return recorder, SAMPLE_RATE
        except Exception:
            log.info("Loopback 16 kHz capture unavailable; resampling from %s Hz", FALLBACK_RATE)
        recorder = microphone.recorder(samplerate=FALLBACK_RATE, blocksize=FRAME_SAMPLES * 3)
        recorder.__enter__()
        return recorder, FALLBACK_RATE

    def _push(self, samples: Any) -> None:
        item = (samples, round(self._clock() * 1000))
        try:
            self.chunks.put_nowait(item)
        except queue.Full:
            try:
                self.chunks.get_nowait()  # Drop the oldest audio rather than fall behind live.
            except queue.Empty:
                pass
            self.chunks.put_nowait(item)

    def _capture_loop(self) -> None:
        _co_initialize()
        failures = 0
        opened_once = False
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            while not self.cancelled.is_set():
                recorder = None
                try:
                    speaker = self._default_speaker()
                    speaker_id = getattr(speaker, "id", None) or getattr(speaker, "name", "")
                    recorder, rate = self._open_recorder(speaker)
                    if opened_once:
                        self.reopen_count += 1
                    opened_once, failures = True, 0
                    self.device_name = str(getattr(speaker, "name", ""))
                    log.info("Capturing computer sound (loopback, %s Hz)", rate)
                    numframes = FRAME_SAMPLES if rate == SAMPLE_RATE else FRAME_SAMPLES * 3
                    checked = time.monotonic()
                    while not self.cancelled.is_set():
                        data = recorder.record(numframes=numframes)
                        samples = resample(to_mono(data), rate)
                        if len(samples):
                            self._push(samples)
                        if time.monotonic() - checked >= self._device_check_interval:
                            checked = time.monotonic()
                            current = self._default_speaker()
                            current_id = getattr(current, "id", None) or getattr(current, "name", "")
                            if current_id != speaker_id:
                                log.info("Default playback device changed; reopening loopback capture")
                                break
                except Exception as error:
                    failures += 1
                    log.warning("Loopback capture problem (%s); retrying", type(error).__name__)
                    if not opened_once and failures >= self._max_open_failures:
                        self._end_reason = OPEN_FAILED
                        self._fatal.set()
                        return
                    self.cancelled.wait(0.5)
                finally:
                    if recorder is not None:
                        try:
                            recorder.__exit__(None, None, None)
                        except Exception:
                            pass

    # ------------------------------------------------------------- interface

    def read(self, frame: List[float]) -> int:
        size = len(frame)
        deadline = time.monotonic() + self._silence_after
        while not self.cancelled.is_set():
            if len(self._buffer) >= size:
                frame[:] = self._buffer[:size]
                del self._buffer[:size]
                self.received_at_ms = self._buffer_received_at
                return int(self._clock() * 1000)
            try:
                samples, received_at = self.chunks.get(timeout=0.05)
            except queue.Empty:
                if self._fatal.is_set():
                    return -1
                if time.monotonic() >= deadline:
                    # Nothing is playing: loopback sends no packets, so feed silence.
                    padding = size - len(self._buffer)
                    frame[:] = self._buffer + [0.0] * padding
                    self._buffer.clear()
                    now = int(self._clock() * 1000)
                    self.received_at_ms = now
                    return now
                continue
            self._buffer.extend(float(value) for value in samples)
            self._buffer_received_at = received_at
        return -1

    @property
    def estimated(self) -> bool:
        return True

    def end_reason(self) -> Optional[str]:
        return self._end_reason

    def close(self) -> None:
        self.cancelled.set()
        thread = self._thread
        if thread is not threading.current_thread():
            thread.join(timeout=1.5)

    def cancel(self) -> None:
        self.close()


class PausableAudioSource(AudioSource):
    """Wraps any source; while ``paused`` is set, frames are replaced by silence.

    Like the reference app's pause, audio keeps flowing (so the live stream stays
    connected) but nothing reaches speech recognition, which flushes the segment.
    """

    def __init__(self, inner: AudioSource, paused: threading.Event) -> None:
        self.inner = inner
        self.paused = paused

    def read(self, frame: List[float]) -> int:
        result = self.inner.read(frame)
        if result >= 0 and self.paused.is_set():
            frame[:] = [0.0] * len(frame)
        return result

    @property
    def received_at_ms(self) -> int:
        return getattr(self.inner, "received_at_ms")

    @property
    def estimated(self) -> bool:
        return self.inner.estimated

    def end_reason(self) -> Optional[str]:
        return self.inner.end_reason()

    def close(self) -> None:
        self.inner.close()

    def cancel(self) -> None:
        self.inner.cancel()

    def __getattr__(self, name: str) -> Any:
        if name in ("inner", "paused"):
            raise AttributeError(name)
        return getattr(self.inner, name)
