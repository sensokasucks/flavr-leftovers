@echo off
REM Pull latest from GitHub (rebase onto local)
setlocal
cd /d "%~dp0"
if not exist ".git\" (
  echo Run git-setup.bat first.
  pause
  exit /b 1
)
git pull --rebase origin main
if errorlevel 1 (
  echo Pull/rebase failed — resolve conflicts, then: git rebase --continue
)
pause
endlocal
