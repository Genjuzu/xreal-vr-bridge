@echo off
REM Template: copy this file, set APP to an OpenXR program, and double-click.
REM SteamVR is the OpenXR runtime for that program only.
set "APP=C:\Path\To\YourOpenXrApp.exe"
if "%APP%"=="C:\Path\To\YourOpenXrApp.exe" (
  echo Edit APP in this file, or run launch-openxr-steamvr.ps1 and pick an exe.
)
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0launch-openxr-steamvr.ps1" -Exe "%APP%"
if errorlevel 1 pause
