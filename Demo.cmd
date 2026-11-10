@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 main.py --demo
    if errorlevel 1 pause
    exit /b
)
python main.py --demo
if errorlevel 1 pause
