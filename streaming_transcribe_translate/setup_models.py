"""Download the speech models once into ./models, like simul-subtitle's setup.sh.

Run: python -m streaming_transcribe_translate.setup_models
Files are checked by size and SHA-256; the app never downloads models while
subtitles are starting.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

from .paths import ROOT

MODELS_ROOT = ROOT / "models"
ASR_DIR = MODELS_ROOT / "asr"
VAD_DIR = MODELS_ROOT / "vad"
WHISPER_DIR = MODELS_ROOT / "whisper-base"
WHISPER_REPO = "Systran/faster-whisper-base"

_GH = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
_ASR = (
    "https://huggingface.co/csukuangfj/reazonspeech-k2-v2-ja-en/resolve/"
    "12b44671ff48b9aed622551d64e02fea9a2cf870"
)
# path in models/, official URL, size, SHA-256 (identical to simul-subtitle).
MODELS = (
    ("asr/encoder.int8.onnx", f"{_ASR}/encoder-epoch-35-avg-1.int8.onnx", 70876409,
     "ead1579e118b821a767242a8eb9272634b0e63ba16f8dfc4d126732406eae268"),
    ("asr/decoder.onnx", f"{_ASR}/decoder-epoch-35-avg-1.onnx", 5165084,
     "90b60985672df5023e187e9d25aa2dc93abc4286bfacf71a35a78a6b76d88df5"),
    ("asr/joiner.int8.onnx", f"{_ASR}/joiner-epoch-35-avg-1.int8.onnx", 1033417,
     "c7f4ba40a8ae307a6c30b5c06e2570add04466bcb45bab62699f0ec5d00ed495"),
    ("asr/tokens.txt", f"{_ASR}/tokens.txt", 26631,
     "144f8a4f639373a1bdf7eabb2437482ef64b0cc5db24ad27cce65f293e4faa24"),
    ("vad/silero_vad.onnx", f"{_GH}/asr-models/silero_vad.onnx", 643854,
     "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"),
)


def _valid(path: Path, size: int, sha256: str) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest() == sha256


def reazonspeech_ready() -> bool:
    return all((MODELS_ROOT / name).is_file() for name, *_ in MODELS)


def whisper_ready() -> bool:
    return (WHISPER_DIR / "model.bin").is_file()


def download_reazonspeech() -> None:
    for name, url, size, sha256 in MODELS:
        target = MODELS_ROOT / name
        if _valid(target, size, sha256):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        print(f"Downloading {name} ({size / 1e6:.1f} MB)…", flush=True)
        urllib.request.urlretrieve(url, part)
        if not _valid(part, size, sha256):
            part.unlink(missing_ok=True)
            raise RuntimeError(f"{name}: wrong size or checksum")
        part.replace(target)


def download_whisper() -> None:
    if whisper_ready():
        return
    from huggingface_hub import snapshot_download

    print("Downloading Whisper base for Chinese input (~145 MB)…", flush=True)
    snapshot_download(WHISPER_REPO, local_dir=str(WHISPER_DIR))


def main() -> int:
    try:
        download_reazonspeech()
        download_whisper()
    except Exception as error:
        print(f"Model setup failed: {error}", file=sys.stderr)
        return 1
    print(f"Models ready: {MODELS_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
