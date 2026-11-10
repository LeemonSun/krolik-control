@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 main.py
    if errorlevel 1 pause
    exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
    python main.py
    if errorlevel 1 pause
    exit /b
)
echo Python 3.11 or later is required for this source test build.
echo Install Python from https://www.python.org/downloads/windows/
echo During installation, enable "Add python.exe to PATH".
pause
