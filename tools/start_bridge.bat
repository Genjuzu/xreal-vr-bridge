@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo .venv fehlt - bitte einmalig anlegen: python -m venv .venv && .venv\Scripts\pip install pytest
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m xreal_vr_bridge.cli --no-gravity-ref --recenter-hotkey F9 --axis-hotkey F10 --invert-yaw-hotkey F11 --invert-pitch-hotkey F12
pause
