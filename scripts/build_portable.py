"""Build an isolated CPU-only Windows x64 onedir distribution."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
STAGE = BUILD / "portable-stage"
VENV = BUILD / "portable-venv"
NAME = "LiveSubtitles"
VERSION = "1.0.1"
SIBLING_MODULES = (
    "__init__", "bilibili", "browser_cookies", "user_login", "youtube_web",
    "missevan", "translate", "config", "emotes", "gifts", "slang",
    "openai_compatible_translate", "transcription",
)


def run(*args: str | Path) -> None:
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def stage_sources(sibling: Path, local_validation: bool) -> dict:
    license_files = [
        path for pattern in ("LICENSE*", "COPYING*", "NOTICE*")
        for path in sibling.glob(pattern) if path.is_file()
    ]
    authorization = ROOT / "packaging" / "licenses" / "STREAMING-AUTHORIZATION.txt"
    authorized = authorization.is_file()
    if not license_files and not authorized and not local_validation:
        raise SystemExit(
            "Streaming redistribution grant was not found. Supply a licensed sibling "
            "source tree, or use --local-validation for a private, NON-REDISTRIBUTABLE build."
        )
    if STAGE.exists():
        shutil.rmtree(STAGE)
    source_dir = STAGE / "Streaming" / "src"
    source_dir.mkdir(parents=True)
    hashes = {}
    for module in SIBLING_MODULES:
        source = sibling / "src" / f"{module}.py"
        ast.parse(source.read_text(encoding="utf-8-sig"))
        shutil.copy2(source, source_dir / source.name)
        hashes[f"src/{source.name}"] = hashlib.sha256(source.read_bytes()).hexdigest()
    licenses = STAGE / "licenses"
    licenses.mkdir()
    shutil.copy2(ROOT / "LICENSE", licenses / "APPLICATION-MIT.txt")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise SystemExit("Python redistribution license was not found.")
    shutil.copy2(python_license, licenses / "PYTHON-LICENSE.txt")
    shutil.copytree(ROOT / "packaging" / "licenses", licenses / "upstream")
    sibling_licenses = licenses / "Streaming"
    sibling_licenses.mkdir()
    for path in license_files:
        shutil.copy2(path, sibling_licenses / path.name)
    if authorized:
        shutil.copy2(authorization, sibling_licenses / "AUTHORIZATION.txt")
        shutil.copy2(ROOT / "packaging" / "licenses" / "STREAMING-MIT.txt",
                     sibling_licenses / "LICENSE.txt")
    if not license_files and not authorized:
        (sibling_licenses / "REDISTRIBUTION-BLOCKED.txt").write_text(
            "No redistribution license/grant was found in the sibling source tree.\n"
            "This is a private local-validation build, NOT a public release.\n"
            "Obtain permission from all relevant rightsholders before distributing.\n",
            encoding="utf-8",
        )
    return {"streaming_source_sha256": hashes,
            "streaming_license_present": bool(license_files) or authorized,
            "streaming_authorization": "xianren0111, copyright holder, MIT, 2026-11-01" if authorized else None}


def stage_ffmpeg(executable: Path) -> dict:
    if not executable.is_file():
        raise SystemExit(f"FFmpeg executable not found: {executable}")
    origin = executable.parent.parent
    source_manifest = origin / "SOURCE-MANIFEST.json"
    if source_manifest.is_file():
        manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
        if manifest["ffmpeg"]["license"] != "LGPL-2.1-or-later":
            raise SystemExit("Expected our verified LGPL-only FFmpeg build.")
        destination = STAGE / "ffmpeg" / "bin"
        destination.mkdir(parents=True)
        for path in executable.parent.iterdir():
            if path.suffix.lower() in (".dll", ".exe") and path.name != "ffplay.exe":
                expected = manifest["binary_sha256"].get(path.name)
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise SystemExit(f"FFmpeg binary hash does not match source manifest: {path.name}")
                shutil.copy2(path, destination / path.name)
        notices = STAGE / "licenses" / "FFmpeg"
        shutil.copytree(origin / "licenses", notices)
        shutil.copy2(source_manifest, notices / "SOURCE-MANIFEST.json")
        shutil.copy2(ROOT / "packaging" / "FFMPEG-SOURCE-README.txt", notices / "CORRESPONDING-SOURCE.txt")
        result = subprocess.run([str(destination / "ffmpeg.exe"), "-version"],
                                capture_output=True, text=True, check=True)
        return {"ffmpeg_version": result.stdout.splitlines()[0],
                "ffmpeg_configuration": result.stdout.splitlines()[2],
                "ffmpeg_source_ready": True,
                "ffmpeg_source_manifest": manifest}
    license_path = origin / "LICENSE"
    readme_path = origin / "README.txt"
    if not license_path.is_file() or not readme_path.is_file():
        raise SystemExit("FFmpeg distribution LICENSE and README.txt are required.")
    readme = readme_path.read_text(encoding="utf-8-sig")
    if "License: GPL v3" not in readme or "Source Code:" not in readme:
        raise SystemExit("Unrecognized FFmpeg license/source notice; verify the distribution.")
    destination = STAGE / "ffmpeg" / "bin"
    destination.mkdir(parents=True)
    for path in executable.parent.iterdir():
        if path.is_file() and (path.suffix.lower() == ".dll" or path.name in ("ffmpeg.exe", "ffprobe.exe")):
            shutil.copy2(path, destination / path.name)
    notices = STAGE / "licenses" / "FFmpeg"
    notices.mkdir()
    shutil.copy2(license_path, notices / "GPL-3.0.txt")
    shutil.copy2(readme_path, notices / "UPSTREAM-README.txt")
    (notices / "REDISTRIBUTION.txt").write_text(
        "FFmpeg is a separate GPLv3 executable with its shared libraries.\n"
        "The upstream README identifies the exact FFmpeg source commit and build configuration.\n"
        "A public binary release must satisfy GPLv3 corresponding-source obligations for FFmpeg\n"
        "and all incorporated libraries; this local build does not provide a source archive.\n",
        encoding="utf-8",
    )
    result = subprocess.run([str(destination / "ffmpeg.exe"), "-version"],
                            capture_output=True, text=True, check=True)
    return {"ffmpeg_version": result.stdout.splitlines()[0],
            "ffmpeg_configuration": result.stdout.splitlines()[2],
            "ffmpeg_source_ready": False}


def stage_dependency_notices(python: Path) -> None:
    code = """
import importlib.metadata, json, shutil
from pathlib import Path
out = Path('build/portable-stage/licenses/python')
out.mkdir(parents=True, exist_ok=True)
manifest = []
supplemental = {
    'ctranslate2': '../upstream/CTRANSLATE2-LICENSE.txt',
    'flatbuffers': '../upstream/FLATBUFFERS-LICENSE.txt',
    'tokenizers': '../upstream/TOKENIZERS-LICENSE.txt',
    'qrcode-terminal': '../upstream/QRCODE-TERMINAL-MIT.txt',
    'wmi': '../upstream/WMI-MIT.txt',
}
for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
    name = dist.metadata['Name']
    copied = []
    for entry in dist.files or []:
        p = Path(str(entry))
        if any(token in p.name.lower() for token in ('license', 'licence', 'copying', 'notice', 'authors')):
            source = Path(dist.locate_file(entry))
            if source.is_file():
                target = out / name / str(entry).replace('..', '_').replace(':', '_')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied.append(str(target.relative_to(out)))
    manifest.append({'name': name, 'version': dist.version,
                     'license': dist.metadata.get('License-Expression') or dist.metadata.get('License', ''),
                     'notices': copied, 'supplemental_notice': supplemental.get(name.lower()),
                     'native_library_override': 'LGPL-only FFmpeg n8.1; see FFmpeg/SOURCE-MANIFEST.json' if name.lower() == 'av' else None,
                     'homepage': dist.metadata.get('Home-page', '')})
(out / 'DEPENDENCIES.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
"""
    run(python, "-c", code)


def stage_javascript_runtime() -> dict:
    vendor = BUILD / "node-vendor"
    archive = BUILD / "vendor-downloads" / "node-v24.22.2-win-x64.zip"
    expected = "ca1bff5d8ead13c9f2ea404a176db46bd430704d5b5113734049fa365e7799e2"
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise SystemExit("Verified Node v24.22.2 x64 archive is required; see packaging/NODE-RUNTIME.txt.")
    with zipfile.ZipFile(archive) as z:
        for name in ("node.exe", "LICENSE"):
            if (vendor / name).read_bytes() != z.read(f"node-v24.22.2-win-x64/{name}"):
                raise SystemExit(f"Node vendor file differs from the verified archive: {name}")
    notices = (vendor / "LICENSE").read_text(encoding="utf-8")
    if "Copyright Node.js contributors" not in notices or "deps/v8" not in notices:
        raise SystemExit("Node and comprehensive third-party notices are required.")
    target = STAGE / "js"
    target.mkdir()
    shutil.copy2(vendor / "node.exe", target / "node.exe")
    license_dir = STAGE / "licenses" / "Node"
    license_dir.mkdir()
    shutil.copy2(vendor / "LICENSE", license_dir / "LICENSE.txt")
    shutil.copy2(ROOT / "packaging" / "NODE-RUNTIME.txt", license_dir / "PROVENANCE.txt")
    source_notices = BUILD / "corresponding-source" / "node-notices"
    shutil.copytree(license_dir, source_notices, dirs_exist_ok=True)
    return {"javascript_runtime": "Node.js v24.22.2 x64",
            "javascript_runtime_archive_sha256": expected,
            "javascript_runtime_binary_sha256": hashlib.sha256((target / "node.exe").read_bytes()).hexdigest(),
            "javascript_runtime_source": "https://nodejs.org/dist/v24.22.2/node-v24.22.2-win-x64.zip"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--streaming-root", type=Path, default=ROOT.parent / "Streaming")
    built_ffmpeg = BUILD / "ffmpeg-lgpl" / "bin" / "ffmpeg.exe"
    parser.add_argument("--ffmpeg", type=Path, default=built_ffmpeg if built_ffmpeg.is_file()
                        else Path(shutil.which("ffmpeg") or "ffmpeg.exe"))
    parser.add_argument("--local-validation", action="store_true",
                        help="Build privately despite unresolved sibling redistribution licensing; do not publish.")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-self-test", action="store_true")
    parser.add_argument("--release", action="store_true", help="Create binary and corresponding-source ZIPs after passing checks.")
    args = parser.parse_args()
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64") or sys.maxsize <= 2**32:
        raise SystemExit("Build requires 64-bit Windows and 64-bit Python.")
    BUILD.mkdir(exist_ok=True)
    info = stage_sources(args.streaming_root, args.local_validation)
    info.update(stage_ffmpeg(args.ffmpeg))
    info.update(stage_javascript_runtime())
    ready = info["streaming_license_present"] and info["ffmpeg_source_ready"]
    if not ready and not args.local_validation:
        raise SystemExit("Corresponding source is not ready; run packaging/build_ffmpeg.sh and prepare_ffmpeg_sources.py first.")
    if args.release and (not ready or args.local_validation or args.skip_self_test):
        raise SystemExit("Release creation requires resolved licensing and the frozen self-test.")
    info.update({"application_version": VERSION, "python": platform.python_version(),
                 "architecture": "windows-x64", "cpu_only": True,
                 "redistribution_ready": ready})
    python = VENV / "Scripts" / "python.exe"
    if not python.is_file():
        run(sys.executable, "-m", "venv", VENV)
    if not args.skip_install:
        run(python, "-m", "pip", "install", "--disable-pip-version-check", "-r", ROOT / "requirements-build.txt")
    run(python, "-m", "pip", "check")
    if ready:
        av_libs = VENV / "Lib" / "site-packages" / "av.libs"
        known_hashes = set(info["ffmpeg_source_manifest"]["binary_sha256"].values())
        actual = list(av_libs.glob("*.dll"))
        if not actual or any(hashlib.sha256(path.read_bytes()).hexdigest() not in known_hashes
                             for path in actual):
            raise SystemExit("PyAV contains unverified native codecs. Run packaging/prepare_ffmpeg_sources.py after installing dependencies.")
    stage_dependency_notices(python)
    (STAGE / "BUILD-INFO.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    run(python, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--workpath", BUILD / "portable-pyinstaller",
        "--distpath", ROOT / "dist", ROOT / "packaging" / "portable.spec")
    output = ROOT / "dist" / NAME
    # Keep notices discoverable without requiring users to explore _internal.
    shutil.copytree(STAGE / "licenses", output / "licenses", dirs_exist_ok=True)
    shutil.copy2(STAGE / "BUILD-INFO.json", output / "BUILD-INFO.json")
    if not args.skip_self_test:
        report = BUILD / "portable-self-test.json"
        report.unlink(missing_ok=True)
        environment = os.environ.copy()
        windows = environment.get("SystemRoot", r"C:\Windows")
        environment["PATH"] = str(Path(windows) / "System32") + os.pathsep + windows
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        subprocess.run([str(output / f"{NAME}.exe"), "--self-test-report", str(report)],
                       cwd=output, env=environment, check=True, timeout=180)
        if not report.is_file():
            raise SystemExit("Frozen self-test did not create its JSON report.")
        result = json.loads(report.read_text(encoding="utf-8"))
        print(json.dumps(result))
        if result.get("ok") is not True:
            raise SystemExit("Frozen self-test reported a failure.")
        shutil.rmtree(output / "logs", ignore_errors=True)
    size = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    print(json.dumps({"output": str(output), "bytes": size, "redistribution_ready": ready}))
    if args.release:
        release = ROOT / "release"
        release.mkdir(exist_ok=True)
        source_dir = BUILD / "corresponding-source"
        source_zip = release / f"{NAME}-{VERSION}-corresponding-source.zip"
        binary_zip = release / f"{NAME}-{VERSION}-windows-x64.zip"
        for archive, base in ((source_zip, source_dir), (binary_zip, output)):
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for path in sorted(base.rglob("*")):
                    if path.is_file():
                        z.write(path, str(Path(base.name) / path.relative_to(base)))
        hashes = []
        for archive in (binary_zip, source_zip):
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            hashes.append(f"{digest}  {archive.name}")
            print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size, "sha256": digest}))
        (release / f"{NAME}-{VERSION}-SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="ascii")
    elif not ready:
        print("PRIVATE VALIDATION BUILD: redistribution obligations remain unresolved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
