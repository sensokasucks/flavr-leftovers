@echo off
if not exist .venv (
  echo Run install.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
if not exist config\config.yaml (
  echo config.yaml missing - launching wizard...
  python wizard.py
)
python main.py
