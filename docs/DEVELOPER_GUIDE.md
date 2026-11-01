# Developer guide

## Set up a working environment

From the project root on Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

For local speech-model and audio-device integration, install the additional
packages and download the models:

```powershell
.\.venv\Scripts\python.exe -m pip install sherpa-onnx soundcard
.\.venv\Scripts\python.exe -m streaming_transcribe_translate.setup_models
```

Platform stream/chat integration resolves the sibling project at `..\Streaming`
at runtime; that project must be present and its dependencies installed in the
same environment for those integrations. This repository is source code, not a
standalone packaged executable. Keep local credentials and generated runtime
data out of source changes.

## Run the application

The browser application is the default entry point:

```powershell
.\.venv\Scripts\python.exe -m streaming_transcribe_translate
```

The legacy Tk interface remains available with `--tk`. `Start Translation.bat`
launches the browser app, and `Setup Models.bat` is the Windows model-setup
helper.

## Project conventions

- Application code lives in `streaming_transcribe_translate`; preserve
  package-relative imports for modules within that package.
- Keep UI behavior in sync across the browser app and Tk fallback when changing
  shared session behavior.
- Project-root configuration and runtime paths are resolved independently of
  the current working directory.
- Environment variables provide defaults. Saved settings override those
  defaults for fields already stored by the UI. See
  [environment configuration](ENV_CONFIGURATION.md) before changing settings
  names, accepted values, or precedence.
- The browser UI connects to one live room at a time. Multiple reading
  languages can be displayed, while one selected language is used for review
  and chat delivery.
- Keep secrets, cookies, local models, records, logs, and per-run browser URLs
  private. The project `.gitignore` excludes local runtime data.

## Tests

Run the complete standard-library test suite from the project root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

For a focused test, pass its file pattern, for example:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_project_layout.py"
```

Add regression tests alongside the related tests when changing behavior. Prefer
offline tests that do not require live accounts, external services, or audio
devices.
