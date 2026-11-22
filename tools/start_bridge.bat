@echo off
REM Head tracking for SteamVR home and Unity apps (yaw offset 180).
REM For UEVR games use start_bridge_uevr.bat.
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m xreal_vr_bridge.cli --recenter-yaw-offset 180
pause
