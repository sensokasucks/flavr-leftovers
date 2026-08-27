@echo off
REM ============================================================
REM Fridge Workshop - one-time install for Chat Credits
REM Double-click this from the main workshop folder.
REM You do not need Stream Core. You do not install pip yourself.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "APP=%~dp0fridge-chat-credits"
if not exist "%APP%\install.bat" (
  echo [ERROR] Could not find fridge-chat-credits\install.bat
  echo Put this .bat next to the fridge-chat-credits folder.
  echo.
  pause
  exit /b 1
)

echo.
echo Handing off to fridge-chat-credits\install.bat ...
echo.
call "%APP%\install.bat"
endlocal
