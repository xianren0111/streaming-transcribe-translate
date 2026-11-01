"""Portable Windows entry point and explicit first-run speech model setup."""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .paths import RESOURCE_ROOT, ROOT
from .interface_preferences import system_language

log = logging.getLogger(__name__)
VERSION = "1.0.1"
TEXT = {
    "zh": (
        "同传字幕 · 首次准备", "首次使用需要下载语音模型（约 230 MB）。\n音频在本机识别，翻译需在设置中填写服务。\n请选择可写文件夹解压，不要从 ZIP 内直接运行。",
        "下载语音模型", "正在下载，请保持网络连接…", "下载失败，请检查网络后重试。", "取消并退出",
    ),
    "ja": (
        "字幕 · 初回準備", "初回は音声モデル（約230 MB）の導入が必要です。\n音声認識はローカル。翻訳サービスは設定で指定します。\n書き込み可能なフォルダーへ展開して実行してください。",
        "モデルをダウンロード", "ダウンロード中。ネット接続を維持してください…", "失敗しました。ネット接続を確認して再試行してください。", "キャンセルして終了",
    ),
    "en": (
        "Live Subtitles · First-time setup", "Download local speech models once (~230 MB).\nSpeech is recognized locally; configure a translation API in Settings.\nExtract the ZIP to a writable folder before running.",
        "Download speech models", "Downloading. Keep your internet connection active…", "Download failed. Check your connection and retry.", "Cancel and quit",
    ),
}


def configure_runtime() -> None:
    binary = RESOURCE_ROOT / "ffmpeg"
    if binary.is_dir():
        os.environ["PATH"] = str(binary) + os.pathsep + os.environ.get("PATH", "")
    # Model downloads and temporary hub metadata stay inside the portable folder.
    os.environ["HF_HOME"] = str(ROOT / "models" / ".hub-cache")


def ensure_models() -> bool:
    from .setup_models import download_reazonspeech, download_whisper, reazonspeech_ready, whisper_ready

    if reazonspeech_ready() and whisper_ready():
        return True
    text = TEXT.get(system_language(), TEXT["en"])
    window = tk.Tk()
    window.title(text[0])
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=text[1], wraplength=470).pack(anchor="w")
    status = tk.StringVar(value="")
    ttk.Label(frame, textvariable=status, wraplength=470).pack(anchor="w", pady=12)
    progress = ttk.Progressbar(frame, mode="indeterminate", length=460)
    progress.pack(pady=8)
    events: queue.Queue[Exception | None] = queue.Queue()
    finished = False
    busy = False

    def download() -> None:
        try:
            download_reazonspeech()
            download_whisper()
        except Exception as error:
            events.put(error)
        else:
            events.put(None)

    def start() -> None:
        nonlocal busy
        busy = True
        start_button.config(state="disabled")
        status.set(text[3])
        progress.start()
        threading.Thread(target=download, daemon=True).start()

    def poll() -> None:
        nonlocal busy, finished
        try:
            result = events.get_nowait()
        except queue.Empty:
            window.after(100, poll)
            return
        busy = False
        progress.stop()
        if result is not None:
            log.error("First-run model setup failed: %s", result)
            status.set(text[4])
            start_button.config(state="normal")
            messagebox.showerror(text[0], text[4] + "\n\n" + str(result), parent=window)
            window.after(100, poll)
        else:
            finished = True
            window.destroy()

    def close() -> None:
        if busy:
            # Downloads run in a daemon thread and incomplete files are retried.
            progress.stop()
        window.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=8)
    start_button = ttk.Button(buttons, text=text[2], command=start)
    start_button.pack(side="left")
    ttk.Button(buttons, text=text[5], command=close).pack(side="right")
    window.protocol("WM_DELETE_WINDOW", close)
    window.after(100, poll)
    window.mainloop()
    return finished


def self_test(*, check_models: bool = False) -> dict[str, object]:
    """Exercise bundled native dependencies without reading personal settings."""
    import http.client
    import tempfile

    for module in (
        "sherpa_onnx", "faster_whisper", "onnxruntime", "sounddevice", "soundcard",
        "numpy", "av", "yt_dlp", "huggingface_hub", "qrcode", "browser_cookie3",
    ):
        importlib.import_module(module)
    from .streaming_bridge import _modules, _missevan_module
    _modules()
    _missevan_module()
    from .web_server import WebApp
    window = tk.Tk()
    window.withdraw()
    window.update()
    window.destroy()
    result = subprocess.run(
        ["ffmpeg", "-version"], capture_output=True, check=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    audio = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
         "-t", "0.1", "-f", "s16le", "-"],
        capture_output=True, check=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if len(audio.stdout) != 3200:
        raise RuntimeError("Bundled FFmpeg failed PCM audio conversion.")
    web = WebApp(None, port=0)
    web.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", web.port, timeout=10)
        try:
            connection.request("GET", "/?t=" + web.token)
            response = connection.getresponse()
            if response.status != 200 or b"app-token" not in response.read():
                raise RuntimeError("Bundled browser UI failed the HTTP check.")
        finally:
            connection.close()
    finally:
        web.stop()
    with tempfile.TemporaryDirectory(dir=ROOT):
        pass
    checks = ["runtime imports", "platform imports", "Tk", "FFmpeg", "PCM audio conversion", "browser HTTP", "writable portable folder"]
    from .caption_session import is_sound_only
    from .subtitle_settings import SubtitleSettings
    if not SubtitleSettings().ignore_onomatopoeia or not is_sound_only("hahaha!"):
        raise RuntimeError("Bundled sound-only filter failed its default-enabled check.")
    if is_sound_only("ha ha that's funny"):
        raise RuntimeError("Bundled sound-only filter removed meaningful speech.")
    checks.append("default-enabled sound-only filter")
    from .sound_filter import SemanticSoundFilter
    from .speaker_tracking import SpeakerTracker, MODEL_PATH
    if not SubtitleSettings().semantic_sound_filter or SubtitleSettings().distinguish_speakers:
        raise RuntimeError("Bundled optional feature defaults are incorrect.")
    checks.append("semantic filter and speaker tracking imports")
    if check_models:
        from .reazon_asr import create_asr
        for language in ("ja", "zh"):
            recognizer = create_asr(language)
            text = recognizer.recognize([0.0] * 16000)
            if not isinstance(text, str):
                raise RuntimeError("Bundled ASR returned an invalid result.")
            checks.append("local recognition: " + language)
        if MODEL_PATH.is_file():
            import math
            tracker = SpeakerTracker()
            tone = [0.1 * math.sin(2 * math.pi * 220 * n / 16000) for n in range(32000)]
            if tracker.identify(tone) != 1 or tracker.identify(tone) != 1:
                raise RuntimeError("Bundled speaker embedding inference failed.")
            checks.append("local speaker embedding inference")
    return {
        "ok": True, "version": VERSION, "frozen": bool(getattr(sys, "frozen", False)),
        "ffmpeg": result.stdout.decode("utf-8", errors="replace").splitlines()[0],
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup-models", action="store_true")
    parser.add_argument("--self-test-report", type=Path)
    parser.add_argument("--self-test-models", action="store_true")
    parser.add_argument("--tk", action="store_true")
    args = parser.parse_args()
    configure_runtime()
    # PyInstaller windowed mode has no stdout/stderr; model setup prints progress.
    output = (ROOT / "logs")
    output.mkdir(exist_ok=True)
    with (output / "portable-startup.log").open("a", encoding="utf-8", buffering=1) as stream:
        previous = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = stream
        try:
            if args.self_test_report:
                try:
                    report = self_test(check_models=args.self_test_models)
                except Exception as error:
                    args.self_test_report.write_text(
                        json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), encoding="utf-8",
                    )
                    raise
                args.self_test_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
                return
            if not args.setup_models:
                from .web_server import _running_instance_url
                existing = _running_instance_url()
                if existing:
                    import webbrowser
                    webbrowser.open(existing)
                    return
            if not ensure_models():
                return
            if args.setup_models:
                return
            if args.tk:
                from .desktop_app import main as run
            else:
                from .web_server import main as run
            run()
        finally:
            sys.stdout, sys.stderr = previous


if __name__ == "__main__":
    main()
