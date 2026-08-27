@echo off
REM ============================================================
REM Fridge Chat Credits – one-time install (Windows)
REM Double-click this file. You do not need to install pip.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === Fridge Chat Credits - install ===
echo.
echo Python already includes pip. This script uses it for you.
echo You do NOT need Stream Core.
echo.

REM --- 1) Locate Python ---
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>&1
  if %ERRORLEVEL%==0 (
    set "PY=python"
  ) else (
    echo [ERROR] Python was not found on PATH.
    echo.
    echo 1. Download Python 3.10 or newer from:
    echo    https://www.python.org/downloads/
    echo 2. Run the installer.
    echo 3. Tick "Add python.exe to PATH" on the first screen.
    echo 4. Click Install Now, then run this file again.
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

REM --- 2) Create virtual environment if missing ---
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Creating private Python folder in .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create .venv
    echo Reinstall Python from python.org and tick Add to PATH.
    pause
    exit /b 1
  )
) else (
  echo Virtual environment already exists: .venv
)

REM --- 3) Install / upgrade dependencies (pip is built into Python) ---
echo.
echo Installing packages (this is pip - you do not run it yourself) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Package install failed.
  echo Check your internet connection and try again.
  pause
  exit /b 1
)

REM --- 4) Seed config if missing ---
if not exist "config\config.yaml" (
  if exist "config\config.example.yaml" (
    echo Copying config\config.example.yaml -^> config\config.yaml
    copy /Y "config\config.example.yaml" "config\config.yaml" >nul
  )
) else (
  echo config\config.yaml already present - leaving it alone
)

if not exist "data" mkdir data

echo.
echo ----------------------------------------------------------
echo  Install finished.
echo.
echo  Next: double-click  start.bat
echo  Then open:          http://127.0.0.1:3854/
echo  Overlay:            http://127.0.0.1:3854/overlay/credits.html
echo.
echo  Enable Twitch / Kick on the control desk, Save config,
echo  then restart Chat Credits once.
echo ----------------------------------------------------------
echo.
pause
endlocal
