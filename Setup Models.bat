@echo off
cd /d "%~dp0"
echo Installing speech recognition models (one time, about 230 MB)...
where python.exe >nul 2>nul
if not errorlevel 1 (
    python.exe -m pip install --quiet sherpa-onnx soundcard
    python.exe -m streaming_transcribe_translate.setup_models
    goto done
)
where py.exe >nul 2>nul
if not errorlevel 1 (
    py.exe -3 -m pip install --quiet sherpa-onnx soundcard
    py.exe -3 -m streaming_transcribe_translate.setup_models
    goto done
)
echo Python 3 could not be found. Install Python 3.10 or later, then try again.
:done
pause
