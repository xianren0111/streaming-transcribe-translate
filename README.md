# Streaming Transcribe and Translate

A Windows desktop app for live speech transcription, multilingual translation,
subtitles, and optional reviewed chat delivery. The browser UI is the primary
interface; a Tkinter fallback is also available.

## Install

Use Python 3.10 or later. From the project directory, create an environment and
install the project dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install sherpa-onnx soundcard
.\.venv\Scripts\python.exe -m streaming_transcribe_translate.setup_models
```

The final command installs the local speech models; they are not downloaded
when a subtitle session starts. Alternatively, run `Setup Models.bat` after
installing the project dependencies. Stream audio may also require FFmpeg on
`PATH`.

Platform stream and chat integrations use the sibling `Streaming` project.
At runtime, this source project resolves it at `..\Streaming`; the sibling
project must be present and its required dependencies installed in the same
Python environment for those integrations. This repository is not a standalone
packaged executable.

## Start

From the project directory:

```powershell
.\.venv\Scripts\python.exe -m streaming_transcribe_translate
```

Or double-click `Start Translation.bat`. The app opens its browser UI on
localhost. To use the fallback desktop window:

```powershell
.\.venv\Scripts\python.exe -m streaming_transcribe_translate --tk
```

For a Bilibili-only command-line sample that does not post chat messages:

```powershell
.\.venv\Scripts\python.exe examples\bilibili_live_translation.py 25760587
```

Choose a stream URL or microphone/system audio, then select one or more reading
languages. Translation appears in the subtitle display; choose one selected
language for the review/send queue. Manual review is the default. Automatic chat
sending is optional. Long messages are split conservatively for delivery; a
rejected or partially delivered message is not silently retried.

The browser app can open a native floating subtitle window and provides an OBS
browser-source overlay URL. Record saving is off by default and can be enabled
in the app's record settings. A separate Windows floating window is available
when using the `--tk` fallback.

## Configuration and local data

See [environment configuration](docs/ENV_CONFIGURATION.md) for supported
variables, defaults, and precedence. Translation credentials can be entered in
the app or configured in the project-root `.env`. Saved subtitle settings take
precedence over their environment defaults. `LIVE_ROOM_URL` identifies one
platform/room at a time; legacy per-platform URL variables remain readable.

Local configuration, models, records, logs, and the per-run browser URL are
private runtime data. They are excluded from Git; inspect files before sharing
them elsewhere. Do not publish API keys, cookies, records, or diagnostic logs.

## Development

Install dependencies as above, then run the test suite from the project root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

See the [developer guide](docs/DEVELOPER_GUIDE.md) for project structure and
focused test commands. User guides and related sharing materials will be linked
from the [guides folder](docs/guides/) as they become available.
