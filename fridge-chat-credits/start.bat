@echo off
REM ============================================================
REM Fridge Chat Credits – start (from inside this folder)
REM Prefer the workshop-root "START Chat Credits.bat" if you have it.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo Working directory: %CD%
echo.

if not exist "main.py" (
  echo [ERROR] main.py not found. This .bat must live inside fridge-chat-credits.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment not found (.venv\Scripts\python.exe).
  echo.
  echo Run install.bat in this folder first, or the workshop-root
  echo "INSTALL Chat Credits.bat".
  echo.
  pause
  exit /b 1
)

if not exist "config\config.yaml" (
  if exist "config\config.example.yaml" (
    echo config\config.yaml missing – copying from example.
    copy /Y "config\config.example.yaml" "config\config.yaml" >nul
  )
)

if not exist "data" mkdir data

echo Starting Fridge Chat Credits with .venv...
echo Control desk: http://127.0.0.1:3854/
echo Overlay:      http://127.0.0.1:3854/overlay/credits.html
echo Press Ctrl+C to stop.
echo.

".venv\Scripts\python.exe" -u main.py
set EXITCODE=%ERRORLEVEL%

echo.
if not %EXITCODE%==0 (
  echo Chat Credits exited with code %EXITCODE%.
  echo If you see a missing package, run install.bat again.
) else (
  echo Chat Credits stopped.
)
pause
endlocal
exit /b %EXITCODE%
