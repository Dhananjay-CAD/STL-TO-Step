@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from python.org and tick Add Python to PATH.
  pause
  exit /b 1
)
echo Installing or checking libraries, please wait...
python -m pip install --quiet numpy cadquery-ocp pywin32
echo Starting the dashboard. Your browser will open. Close this window to stop it.
python dashboard.py
pause
