@echo off
cd /d "%~dp0"
where pythonw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pythonw.exe -m streaming_transcribe_translate
    exit /b 0
)
where pyw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pyw.exe -3 -m streaming_transcribe_translate
    exit /b 0
)
echo Python 3 could not be found. Install Python 3.10 or later, then try again.
pause
