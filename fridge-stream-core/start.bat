@echo off
if not exist .venv (
  echo Run install.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python main.py
