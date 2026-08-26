@echo off
REM ============================================================
REM Fridge Workshop - start Chat Credits
REM Double-click this from the main workshop folder.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "APP=%~dp0fridge-chat-credits"
if not exist "%APP%\main.py" (
  echo [ERROR] Could not find fridge-chat-credits\main.py
  echo Put this .bat next to the fridge-chat-credits folder.
  echo.
  pause
  exit /b 1
)

cd /d "%APP%"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Chat Credits is not installed yet.
  echo.
  echo First time setup:
  echo   1. Double-click  "INSTALL Chat Credits.bat"  in this workshop folder
  echo   2. Then run this start file again
  echo.
  pause
  exit /b 1
)

if not exist "config\config.yaml" (
  if exist "config\config.example.yaml" (
    copy /Y "config\config.example.yaml" "config\config.yaml" >nul
  )
)

echo.
echo Starting Fridge Chat Credits...
echo.
echo   Control desk:  http://127.0.0.1:3854/
echo   Overlay:       http://127.0.0.1:3854/overlay/credits.html
echo.
echo Leave this window open while you stream. Press Ctrl+C to stop.
echo.

".venv\Scripts\python.exe" main.py
set EXITCODE=%ERRORLEVEL%

echo.
if not %EXITCODE%==0 (
  echo Chat Credits exited with code %EXITCODE%.
  echo If you see a missing package error, run INSTALL Chat Credits.bat again.
) else (
  echo Chat Credits stopped.
)
echo.
pause
endlocal
exit /b %EXITCODE%
