@echo off
setlocal
cd /d "%~dp0.."
".venv\Scripts\python.exe" tools\fix_vrto3d_display.py
echo.
echo Starte SteamVR neu ...
taskkill /IM vrserver.exe /F >nul 2>&1
taskkill /IM vrcompositor.exe /F >nul 2>&1
taskkill /IM vrmonitor.exe /F >nul 2>&1
timeout /t 3 /nobreak >nul
start "" "steam://run/250820"
echo Fertig. SteamVR startet auf der XREAL-Brille.
