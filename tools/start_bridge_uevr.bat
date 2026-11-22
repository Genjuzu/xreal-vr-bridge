@echo off
REM Head tracking for UEVR and other games (yaw offset 0).
REM For SteamVR home and Unity apps use start_bridge.bat.
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m xreal_vr_bridge.cli --recenter-yaw-offset 0
pause
