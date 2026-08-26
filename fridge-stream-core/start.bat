@echo off
REM ============================================================
REM Fridge Stream Core - start (from inside this folder)
REM Prefer the workshop-root "START Stream Core.bat" if you have it.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo Working directory: %CD%
echo.

if not exist "main.py" (
  echo [ERROR] main.py not found. This .bat must live inside fridge-stream-core.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment not found (.venv\Scripts\python.exe).
  echo.
  echo Run install.bat in this folder first, or the workshop-root
  echo "INSTALL Stream Core.bat".
  echo.
  pause
  exit /b 1
)

if not exist "config\config.yaml" (
  echo config\config.yaml is missing - running wizard...
  echo.
  ".venv\Scripts\python.exe" wizard.py
  if errorlevel 1 (
    echo Wizard failed.
    pause
    exit /b 1
  )
)

echo Starting Fridge Stream Core with .venv...
echo Admin hub: http://127.0.0.1:3850/admin/
echo Press Ctrl+C to stop.
echo.

".venv\Scripts\python.exe" -u main.py
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
