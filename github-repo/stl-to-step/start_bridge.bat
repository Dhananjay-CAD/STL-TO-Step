@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from python.org and tick Add Python to PATH.
  pause
  exit /b 1
)
python -m pip install --quiet pywin32
echo Starting the SolidWorks bridge. Keep this window open.
python sw_bridge.py
pause
