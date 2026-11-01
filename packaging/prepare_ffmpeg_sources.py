"""Prepare source materials and replace PyAV's codec DLLs with our LGPL build."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
PREFIX = BUILD / "ffmpeg-lgpl"
SOURCES = BUILD / "corresponding-source"
AV_LIBS = BUILD / "portable-venv" / "Lib" / "site-packages" / "av.libs"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    binary = PREFIX / "bin"
    dlls = list(binary.glob("*.dll"))
    if not dlls or not (binary / "ffmpeg.exe").is_file():
        raise SystemExit("Run packaging/build_ffmpeg.sh first.")
    filenames = {p.name.split("-")[0]: p.name for p in AV_LIBS.glob("*.dll")
                 if p.name.count("-") >= 2 and p.name.startswith(("avcodec-", "avdevice-", "avfilter-", "avformat-",
                                       "avutil-", "swresample-", "swscale-"))}
    if len(filenames) != 7:
        raise SystemExit("Expected exactly seven PyAV FFmpeg DLL names.")
    # Retain PyAV's repaired import names; remove all unrelated codec DLLs.
    shutil.rmtree(AV_LIBS)
    AV_LIBS.mkdir()
    for dll in dlls:
        shutil.copy2(dll, AV_LIBS / dll.name)
        component = dll.name.split("-")[0]
        if component in filenames:
            shutil.copy2(dll, AV_LIBS / filenames[component])
    SOURCES.mkdir(exist_ok=True)
    for source in (BUILD / "vendor-downloads" / "ffmpeg-n8.1.tar.gz",
                   BUILD / "vendor-downloads" / "qrcode-terminal-0.8.tar.gz"):
        shutil.copy2(source, SOURCES / source.name)
    shutil.copy2(ROOT / "packaging" / "build_ffmpeg.sh", SOURCES / "build_ffmpeg.sh")
    shutil.copy2(Path(__file__), SOURCES / "prepare_ffmpeg_sources.py")
    config_dir = SOURCES / "ffmpeg-build-config"
    config_dir.mkdir(exist_ok=True)
    for name in ("config.h", "config_components.h", "config.mak",
                 "BUILD-VERSION.txt", "LICENSE-REPORT.txt"):
        shutil.copy2(PREFIX / name, config_dir / name)
    source_root = BUILD / "ffmpeg-toolchain" / "FFmpeg-n8.1"
    notices = PREFIX / "licenses"
    notices.mkdir(exist_ok=True)
    for source in source_root.glob("COPYING*"):
        shutil.copy2(source, notices / source.name)
    shutil.copy2(source_root / "LICENSE.md", notices / "FFMPEG-LICENSE.md")
    toolchain = BUILD / "ffmpeg-toolchain" / "llvm-mingw-20261020-ucrt-x86_64"
    shutil.copy2(toolchain / "LICENSE.TXT", notices / "LLVM-LICENSE.TXT")
    runtime = toolchain / "x86_64-w64-mingw32" / "share" / "mingw32"
    for source in runtime.glob("COPYING*"):
        shutil.copy2(source, notices / source.name)
    manifest = {
        "ffmpeg": {"version": "n8.1", "source_url":
                   "https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/refs/tags/n8.1",
                   "source_archive": "ffmpeg-n8.1.tar.gz",
                   "sha256": sha256(SOURCES / "ffmpeg-n8.1.tar.gz"),
                   "license": "LGPL-2.1-or-later", "external_codec_libraries": [],
                   "patches": [],
                   "pyav_overlay": "Bundled PyAV 18.1.0 uses these same ABI-compatible LGPL DLLs, not its upstream codec DLLs."},
        "qrcode_terminal": {"version": "0.8", "source_archive": "qrcode-terminal-0.8.tar.gz",
                            "sha256": sha256(SOURCES / "qrcode-terminal-0.8.tar.gz"),
                            "source_url": "https://pypi.org/project/qrcode-terminal/0.8/"},
        "build_tools": {
            "compiler_url": "https://github.com/mstorsjo/llvm-mingw/releases/download/20261020/llvm-mingw-20261020-ucrt-x86_64.zip",
            "compiler_sha256": sha256(BUILD / "vendor-downloads" / "llvm-mingw.zip"),
            "make_url": "https://downloads.sourceforge.net/project/ezwinports/make-4.4.1-without-guile-w32-bin.zip",
            "make_sha256": sha256(BUILD / "vendor-downloads" / "make.zip"),
            "shell": "Git for Windows Bash"},
        "binary_sha256": {p.name: sha256(p) for p in binary.iterdir() if p.suffix in (".exe", ".dll")},
    }
    for destination in (SOURCES / "SOURCE-MANIFEST.json", PREFIX / "SOURCE-MANIFEST.json"):
        destination.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    shutil.copytree(notices, SOURCES / "licenses", dirs_exist_ok=True)
    shutil.copytree(ROOT / "packaging" / "licenses", SOURCES / "application-notices", dirs_exist_ok=True)
    shutil.copy2(ROOT / "packaging" / "FFMPEG-SOURCE-README.txt", SOURCES / "README.txt")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
