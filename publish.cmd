@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==== Publish to GitHub ====
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\publish_to_github.ps1"
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" (
  echo FAILED with code %RC%
  echo Copy the last 20 lines and send them to the Lead.
) else (
  echo DONE
)
echo.
pause
