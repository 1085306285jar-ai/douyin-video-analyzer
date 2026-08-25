@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\build_windows.ps1"
if errorlevel 1 (
  echo.
  echo BUILD FAILED. Please read the error above.
  pause
  exit /b 1
)
echo.
echo Build completed successfully.
pause
