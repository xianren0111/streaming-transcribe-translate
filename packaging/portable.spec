"""Windows x64 CPU-only onedir bundle; inputs are staged by build_portable.py."""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

project = Path(SPECPATH).parent
stage = project / "build" / "portable-stage"
name = "LiveSubtitles"
data = [
    (str(project / "streaming_transcribe_translate" / "web"), "streaming_transcribe_translate/web"),
    (str(stage / "Streaming" / "src"), "Streaming/src"),
    (str(stage / "licenses"), "licenses"),
    (str(stage / "BUILD-INFO.json"), "."),
]
binaries = []
if (stage / "js" / "node.exe").is_file():
    binaries.append((str(stage / "js" / "node.exe"), "js"))
ffmpeg_bin = stage / "ffmpeg" / "bin"
for path in ffmpeg_bin.iterdir():
    if path.suffix.lower() in (".exe", ".dll"):
        binaries.append((str(path), "ffmpeg"))

hidden = [
    "tkinter", "_tkinter", "PIL.Image", "PIL.ImageTk",
    "pythoncom", "pywintypes", "win32crypt",
    "src.bilibili", "src.browser_cookies", "src.user_login",
    "src.youtube_web", "src.missevan", "src.translate",
    "src.config", "src.emotes", "src.gifts", "src.slang",
    "src.openai_compatible_translate", "src.transcription",
]
for package in ("sherpa_onnx", "soundcard", "qrcode", "bilibili_api", "av", "yt_dlp_ejs"):
    hidden += collect_submodules(package, filter=lambda module: ".tests" not in module)
for package in ("sherpa_onnx", "ctranslate2", "onnxruntime"):
    binaries += collect_dynamic_libs(package)
for package in ("faster_whisper", "soundcard", "_sounddevice_data", "certifi", "yt_dlp_ejs"):
    data += collect_data_files(package, excludes=[
        "**/tests/**", "**/__pycache__/**", "**/*-asio.dll",
        "**/*32bit*.dll", "**/*arm64*.dll",
    ])
for package in ("yt-dlp", "yt-dlp-ejs", "faster-whisper", "ctranslate2", "sherpa-onnx", "sherpa-onnx-core",
                "onnxruntime", "numpy", "sounddevice", "soundcard", "bilibili-api-python",
                "browser-cookie3", "huggingface-hub", "openai"):
    data += copy_metadata(package)

a = Analysis(
    [str(project / "packaging" / "portable_entry.py")],
    pathex=[str(project), str(stage / "Streaming")],
    binaries=binaries,
    datas=data,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project / "packaging" / "runtime_hook.py")],
    excludes=[
        "torch", "torchaudio", "silero_vad", "nvidia", "tensorflow", "jax",
        "PySide6", "PyQt6", "PyQt5", "PySide2", "streamlit", "playwright",
        "pytest", "sphinx", "black", "flake8", "mypy", "IPython", "notebook",
        "matplotlib", "pandas", "scipy", "sympy", "docx", "pymupdf", "fitz",
    ],
    noarchive=False,
    optimize=1,
)
# Dependency analysis also places FFmpeg's DLLs in _internal. Keep just the
# explicitly staged copies alongside ffmpeg.exe, avoiding a second ~240 MB set.
ffmpeg_names = {path.name.lower() for path in ffmpeg_bin.iterdir()}
a.binaries = [
    entry for entry in a.binaries
    if entry[0].lower() not in ffmpeg_names
    and not ("_sounddevice_data" in entry[0] and any(
        marker in entry[0].lower() for marker in ("-asio", "32bit", "arm64")))
]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name=name, debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    disable_windowed_traceback=False,
    version=str(project / "packaging" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=name)
