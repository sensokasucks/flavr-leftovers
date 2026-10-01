@echo off
REM ============================================================
REM FlaVR Leftovers — stage, commit, push to GitHub
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Git not found.
  pause
  exit /b 1
)

if not exist ".git\" (
  echo [ERROR] Not a git repo. Run git-setup.bat first.
  pause
  exit /b 1
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
  git remote add origin https://github.com/sensokasucks/flavr-leftovers.git
)

echo.
echo === Status (before add) ===
git status -sb
echo.

echo Staging all tracked/untracked (respects .gitignore)...
git add -A

echo.
echo === Status (staged) ===
git status -sb
echo.

REM Abort if nothing to commit
git diff --cached --quiet
if not errorlevel 1 (
  echo Nothing new to commit. Checking if push is needed...
  git push -u origin main
  if errorlevel 1 git push -u origin HEAD:main
  echo.
  pause
  exit /b 0
)

set "MSG=%*"
if "%MSG%"=="" set "MSG=Sync FlaVR Leftovers from workshop tree"

echo Committing: %MSG%
git commit -m "%MSG%"
if errorlevel 1 (
  echo Commit failed.
  pause
  exit /b 1
)

echo.
echo Pushing to origin main...
git push -u origin main
if errorlevel 1 (
  echo.
  echo Push failed. Common fixes:
  echo   1. gh auth login
  echo   2. Or: git remote set-url origin https://github.com/sensokasucks/flavr-leftovers.git
  echo   3. If remote has commits you lack: git pull --rebase origin main
  echo      then run this script again
  echo.
  pause
  exit /b 1
)

echo.
echo Done. https://github.com/sensokasucks/flavr-leftovers
echo.
pause
endlocal
