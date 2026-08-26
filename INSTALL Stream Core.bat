@echo off
REM ============================================================
REM Fridge Workshop - one-time install for Stream Core
REM Double-click this from the main workshop folder.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "CORE=%~dp0fridge-stream-core"
if not exist "%CORE%\install.bat" (
  echo [ERROR] Could not find fridge-stream-core\install.bat
  echo Put this .bat next to the fridge-stream-core folder.
  echo.
  pause
  exit /b 1
)

echo.
echo Handing off to fridge-stream-core\install.bat ...
echo.
call "%CORE%\install.bat"
endlocal
