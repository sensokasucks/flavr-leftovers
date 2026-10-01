@echo off
REM ============================================================
REM Fridge Chat Credits – one-time install (Windows)
REM Double-click this file inside fridge-chat-credits.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === Fridge Chat Credits – install ===
echo.

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>&1
  if %ERRORLEVEL%==0 (
    set "PY=python"
  ) else (
    echo [ERROR] Python was not found on PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo During setup, tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
  )
)

echo Using: %PY%
%PY% --version
if errorlevel 1 (
  echo [ERROR] Could not run Python.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Creating virtual environment in .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create .venv
    pause
    exit /b 1
  )
) else (
  echo Virtual environment already exists: .venv
)

echo.
echo Installing Python packages from requirements.txt ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed.
  pause
  exit /b 1
)

if not exist "config\config.yaml" (
  if exist "config\config.example.yaml" (
    echo Copying config\config.example.yaml -^> config\config.yaml
    copy /Y "config\config.example.yaml" "config\config.yaml" >nul
  )
) else (
  echo config\config.yaml already present – leaving it alone
)

if not exist "data" mkdir data

echo.
echo ----------------------------------------------------------
echo  Next: edit config\config.yaml (enable Twitch / Kick / etc.)
echo  Then double-click start.bat
echo  Control desk:  http://127.0.0.1:3854/
echo  Overlay:       http://127.0.0.1:3854/overlay/credits.html
echo ----------------------------------------------------------
echo.
pause
endlocal
