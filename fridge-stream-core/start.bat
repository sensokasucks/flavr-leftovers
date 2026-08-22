@echo off
REM ============================================================
REM Fridge Stream Core – start
REM Double-click to launch. Close the window (or Ctrl+C) to stop.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment not found.
  echo Run install.bat first (one time).
  echo.
  pause
  exit /b 1
)

if not exist "config\config.yaml" (
  echo config\config.yaml is missing.
  echo Running first-run wizard...
  echo.
  ".venv\Scripts\python.exe" wizard.py
  if errorlevel 1 (
    echo Wizard failed. Copy config\config.example.yaml to config\config.yaml and edit it.
    pause
    exit /b 1
  )
)

echo Starting Fridge Stream Core...
echo Overlay / admin will be at http://127.0.0.1:3850/
echo Press Ctrl+C to stop.
echo.

".venv\Scripts\python.exe" main.py
set EXITCODE=%ERRORLEVEL%

echo.
if not %EXITCODE%==0 (
  echo Stream Core exited with code %EXITCODE%.
) else (
  echo Stream Core stopped.
)
pause
endlocal
exit /b %EXITCODE%
