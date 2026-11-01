"""Local, session-scoped speaker clustering for complete speech segments."""

from __future__ import annotations

import threading
import numpy as np

from .setup_models import MODELS_ROOT, _valid


MODEL_PATH = MODELS_ROOT / "speaker" / "campplus.onnx"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/"
    "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
)
MODEL_SIZE = 28281164
MODEL_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"
_DOWNLOAD_LOCK = threading.Lock()


def model_ready() -> bool:
    return _valid(MODEL_PATH, MODEL_SIZE, MODEL_SHA256)


def download_model() -> None:
    from .setup_models import download_verified

    with _DOWNLOAD_LOCK:
        download_verified(MODEL_PATH, MODEL_URL, MODEL_SIZE, MODEL_SHA256)


class SpeakerTracker:
    def __init__(self) -> None:
        import sherpa_onnx

        if not model_ready():
            raise RuntimeError("请先在设置中下载说话人模型。")
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(MODEL_PATH), num_threads=1, provider="cpu",
        )
        self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self.centroids: list[np.ndarray] = []
        self.counts: list[int] = []
        self.pending_embedding: np.ndarray | None = None

    def identify(self, samples: list[float]) -> int | None:
        # Short fragments and silence do not provide reliable speaker evidence.
        if len(samples) < 16000 or np.mean(np.square(samples)) < 1e-6:
            self.pending_embedding = None
            return None
        stream = self.extractor.create_stream()
        stream.accept_waveform(16000, samples)
        stream.input_finished()
        if not self.extractor.is_ready(stream):
            self.pending_embedding = None
            return None
        embedding = np.asarray(self.extractor.compute(stream), dtype=np.float32)
        norm = float(np.linalg.norm(embedding))
        if not np.isfinite(embedding).all() or not np.isfinite(norm) or norm <= 0:
            raise RuntimeError("说话人模型返回了无效声纹。")
        embedding /= norm
        scores = [float(np.dot(center, embedding)) for center in self.centroids]
        best = int(np.argmax(scores)) if scores else -1
        if best >= 0 and scores[best] >= 0.65:
            self.pending_embedding = None
            count = min(self.counts[best], 20)
            center = self.centroids[best] * count + embedding
            self.centroids[best] = center / np.linalg.norm(center)
            self.counts[best] += 1
            return best + 1
        # A weak match is not evidence of a new voice. Confirm novelty over
        # two longer segments; one changed tone or noisy fragment stays unknown.
        if len(samples) < 32000 or (best >= 0 and scores[best] >= 0.45):
            self.pending_embedding = None
            return None
        if len(self.centroids) >= 20:
            self.pending_embedding = None
            return None
        if self.centroids:
            if (self.pending_embedding is None
                    or float(np.dot(self.pending_embedding, embedding)) < 0.75):
                self.pending_embedding = embedding.copy()
                return None
            embedding = self.pending_embedding + embedding
            embedding /= np.linalg.norm(embedding)
            self.pending_embedding = None
        self.centroids.append(embedding.copy())
        self.counts.append(2 if len(self.centroids) > 1 else 1)
        return len(self.centroids)
