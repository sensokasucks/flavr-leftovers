@echo off
REM ============================================================
REM Fridge Workshop - start Stream Core
REM Double-click this from the main workshop folder.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "CORE=%~dp0fridge-stream-core"
if not exist "%CORE%\main.py" (
  echo [ERROR] Could not find fridge-stream-core\main.py
  echo Put this .bat next to the fridge-stream-core folder.
  echo.
  pause
  exit /b 1
)

cd /d "%CORE%"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment not found in fridge-stream-core\.venv
  echo.
  echo First time setup:
  echo   1. Double-click  "INSTALL Stream Core.bat"  in this workshop folder
  echo   2. Then run this start file again
  echo.
  pause
  exit /b 1
)

if not exist "config\config.yaml" (
  echo config\config.yaml is missing - launching setup wizard...
  echo.
  ".venv\Scripts\python.exe" wizard.py
  if errorlevel 1 (
    echo Wizard failed. Run INSTALL Stream Core.bat or copy config.example.yaml.
    pause
    exit /b 1
  )
)

echo.
echo Starting Fridge Stream Core...
echo.
echo   Admin hub:     http://127.0.0.1:3850/admin/
echo   Chat overlay:  http://127.0.0.1:3850/overlay/chat.html
echo   Stats overlay: http://127.0.0.1:3850/overlay/overlay.html
echo.
echo Leave this window open while you stream. Press Ctrl+C to stop.
echo.

".venv\Scripts\python.exe" main.py
set EXITCODE=%ERRORLEVEL%

echo.
if not %EXITCODE%==0 (
  echo Stream Core exited with code %EXITCODE%.
  echo If you see "Missing a Python package", run INSTALL Stream Core.bat again.
) else (
  echo Stream Core stopped.
)
echo.
pause
endlocal
exit /b %EXITCODE%
