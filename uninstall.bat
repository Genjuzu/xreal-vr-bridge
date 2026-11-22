@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" pause
exit /b %ERR%
