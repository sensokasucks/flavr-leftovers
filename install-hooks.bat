@echo off
REM Point this repo at version-controlled hooks in githooks\
setlocal
cd /d "%~dp0"

where git >nul 2>&1
if errorlevel 1 (
  echo Git not found.
  pause
  exit /b 1
)

if not exist ".git\" (
  echo Not a git repo yet. Run git-setup.bat first, then this script.
  pause
  exit /b 1
)

if not exist "githooks\pre-commit" (
  echo githooks\ folder missing.
  pause
  exit /b 1
)

git config core.hooksPath githooks
echo.
echo core.hooksPath = githooks
git config --get core.hooksPath
echo.
echo Hooks active:
echo   pre-commit  — block config.yaml, .env, data/, jars
echo   commit-msg  — require a real message
echo   pre-push    — run Stream Core tests if Python is available
echo.
echo Skip any hook: set SKIP_HOOKS=1
echo.
pause
endlocal
