"""Extract and smoke-test the final ZIP without relying on installed tools."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-models", action="store_true")
    args = parser.parse_args()
    release = ROOT / "release"
    zip_path = release / "LiveSubtitles-1.0.0-windows-x64.zip"
    source_path = release / "LiveSubtitles-1.0.0-corresponding-source.zip"
    hashes = (release / "LiveSubtitles-1.0.0-SHA256SUMS.txt").read_text().splitlines()
    for line in hashes:
        expected, name = line.split("  ", 1)
        if hashlib.sha256((release / name).read_bytes()).hexdigest() != expected:
            raise SystemExit(f"Release hash mismatch: {name}")
    extraction = ROOT / "build" / "portable-smoke"
    if extraction.exists():
        shutil.rmtree(extraction)
    extraction.mkdir()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            parts = member.replace("\\", "/").split("/")
            if any(part in ("..", "models", "records", "logs", "torch", "nvidia",
                            "tests", "node_modules") for part in parts) or parts[-1] in (
                    ".env", ".login_secret", "youtube_token.json", "interface_preferences.json",
                    "subtitle_settings.json", "overlay_window.json") or (
                        "_sounddevice_data" in member and any(
                            marker in member.lower() for marker in ("-asio", "32bit", "arm64"))):
                raise SystemExit(f"Forbidden release payload: {member}")
        archive.extractall(extraction)
    with zipfile.ZipFile(source_path) as archive:
        source_manifest = json.loads(archive.read("corresponding-source/SOURCE-MANIFEST.json"))
        source = archive.read("corresponding-source/" + source_manifest["ffmpeg"]["source_archive"])
        if hashlib.sha256(source).hexdigest() != source_manifest["ffmpeg"]["sha256"]:
            raise SystemExit("Corresponding source archive hash mismatch.")
    application = extraction / "LiveSubtitles"
    if args.check_models:
        model_dir = application / "models"
        model_dir.mkdir()
        public_models = {
            "asr": ("encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt"),
            "vad": ("silero_vad.onnx",),
            "whisper-base": ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"),
        }
        for directory, names in public_models.items():
            destination = model_dir / directory
            destination.mkdir()
            for name in names:
                shutil.copy2(ROOT / "models" / directory / name, destination / name)
    environment = os.environ.copy()
    windows = environment.get("SystemRoot", r"C:\Windows")
    environment["PATH"] = str(Path(windows) / "System32") + os.pathsep + windows
    for name in ("PYTHONPATH", "PYTHONHOME"):
        environment.pop(name, None)
    node = application / "_internal" / "js" / "node.exe"
    subprocess.run([str(node), "-e", "if (6 * 7 !== 42) process.exit(1)"],
                   cwd=application, env=environment, check=True, timeout=20)
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(application / "LiveSubtitles.exe"))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    if not any(name.startswith("yt_dlp_ejs") for name in pyz.toc):
        raise SystemExit("yt-dlp EJS Python module is absent from the executable.")
    if not list((application / "_internal" / "yt_dlp_ejs").rglob("*.js")):
        raise SystemExit("yt-dlp EJS solver scripts are absent from the assets.")
    report = ROOT / "build" / "portable-zip-self-test.json"
    report.unlink(missing_ok=True)
    command = [str(application / "LiveSubtitles.exe"), "--self-test-report", str(report)]
    if args.check_models:
        command.append("--self-test-models")
    subprocess.run(command, cwd=application, env=environment, check=True, timeout=300)
    result = json.loads(report.read_text(encoding="utf-8"))
    if result.get("ok") is not True:
        raise SystemExit(json.dumps(result))
    print(json.dumps(result))
    if args.check_models:
        shutil.rmtree(application / "models")
    print("Final ZIP hashes, clean extraction, source materials, Node/EJS, and frozen self-test verified.")


if __name__ == "__main__":
    main()
