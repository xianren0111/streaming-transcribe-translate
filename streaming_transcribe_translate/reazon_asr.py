"""Local ReazonSpeech (sherpa-onnx) recognizer, as used by simul-subtitle."""

from __future__ import annotations

import logging
import os
from typing import List

from .setup_models import ASR_DIR, reazonspeech_ready, whisper_ready
from .simul_interfaces import Asr

log = logging.getLogger(__name__)

MODELS_MISSING = "语音识别模型尚未安装，请先双击「Setup Models.bat」完成安装。"


class ReazonSpeechAsr(Asr):
    """Japanese/English recognizer using the bundled ReazonSpeech k2 v2 model."""

    def __init__(self, num_threads: int = 0) -> None:
        if not reazonspeech_ready():
            raise RuntimeError(MODELS_MISSING)
        import sherpa_onnx

        threads = num_threads or max(1, min(4, (os.cpu_count() or 2) // 2))
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(ASR_DIR / "encoder.int8.onnx"),
            decoder=str(ASR_DIR / "decoder.onnx"),
            joiner=str(ASR_DIR / "joiner.int8.onnx"),
            tokens=str(ASR_DIR / "tokens.txt"),
            num_threads=threads,
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
        )
        log.info("ReazonSpeech model ready (%d threads)", threads)

    def recognize(self, samples: List[float]) -> str:
        import numpy as np

        if len(samples) == 0:
            return ""
        stream = self._recognizer.create_stream()
        stream.accept_waveform(16000, np.asarray(samples, dtype=np.float32))
        self._recognizer.decode_stream(stream)
        return stream.result.text.strip()


def create_asr(language: str | None) -> Asr:
    """ReazonSpeech for Japanese/English/auto; Whisper only for Chinese input."""
    if language == "zh":
        if not whisper_ready():
            raise RuntimeError(MODELS_MISSING)
        from .setup_models import WHISPER_DIR
        from .simul_streaming_adapter import StreamingProjectAsr

        return StreamingProjectAsr(str(WHISPER_DIR), "zh")
    return ReazonSpeechAsr()
