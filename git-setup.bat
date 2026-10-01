@echo off
REM ============================================================
REM FlaVR Leftovers — one-time git setup (run from this folder)
REM Requires: Git for Windows + GitHub login (gh auth or credential manager)
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Git not found. Install from https://git-scm.com/download/win
  pause
  exit /b 1
)

if exist ".git\" (
  echo Git repo already initialized.
) else (
  echo Initializing git repo...
  git init -b main
  if errorlevel 1 (
    git init
    git branch -M main
  )
)

if not exist ".gitignore" (
  echo [WARN] .gitignore missing — secrets might get committed.
)

echo.
echo Checking remote...
git remote get-url origin >nul 2>&1
if errorlevel 1 (
  git remote add origin https://github.com/sensokasucks/flavr-leftovers.git
  echo Added origin -^> https://github.com/sensokasucks/flavr-leftovers.git
) else (
  echo Origin already set:
  git remote -v
  echo.
  echo To force remote URL:
  echo   git remote set-url origin https://github.com/sensokasucks/flavr-leftovers.git
)

echo.
echo First commit tip:
echo   git add -A
echo   git status
echo   git commit -m "Sync FlaVR Leftovers monorepo"
echo   git push -u origin main
echo.
if exist "githooks\pre-commit" (
  git config core.hooksPath githooks
  echo Hooks path set to githooks\
)

echo Or double-click git-push.bat after setup.
echo Optional: install-hooks.bat  (if hooks path was not set)
echo.
pause
endlocal
