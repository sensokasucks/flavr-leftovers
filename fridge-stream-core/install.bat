@echo off
REM ============================================================
REM Fridge Stream Core – one-time install (Windows)
REM Double-click this file after extracting / cloning the folder.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === Fridge Stream Core – install ===
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

REM --- 2) Create virtual environment if missing ---
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

REM --- 3) Install / upgrade dependencies ---
echo.
echo Installing Python packages from requirements.txt ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed.
  pause
  exit /b 1
)

REM --- 4) Seed config files if missing ---
if not exist "config\config.yaml" (
  if exist "config\config.example.yaml" (
    echo Copying config\config.example.yaml -^> config\config.yaml
    copy /Y "config\config.example.yaml" "config\config.yaml" >nul
  )
) else (
  echo config\config.yaml already present – leaving it alone
)

if not exist "config\commands.json" (
  if exist "config\commands.example.json" (
    echo Copying config\commands.example.json -^> config\commands.json
    copy /Y "config\commands.example.json" "config\commands.json" >nul
  )
) else (
  echo config\commands.json already present – leaving it alone
)

if not exist "data" mkdir data

REM --- 5) Offer first-run wizard ---
echo.
echo Install finished.
echo.
set /p RUN_WIZARD="Run the first-run setup wizard now? (Y/n): "
if /I "%RUN_WIZARD%"=="n" goto done
if /I "%RUN_WIZARD%"=="no" goto done

echo.
".venv\Scripts\python.exe" wizard.py
if errorlevel 1 (
  echo Wizard exited with an error – you can run wizard.py later.
)

:done
echo.
echo ----------------------------------------------------------
echo  To start Stream Core later:  double-click start.bat
echo  Admin dashboard:             http://127.0.0.1:3850/admin/
echo  Chat overlay:                http://127.0.0.1:3850/overlay/chat.html
echo ----------------------------------------------------------
echo.
pause
endlocal
