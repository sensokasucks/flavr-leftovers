@echo off
echo Installing dependencies...
python -m pip install -r requirements.txt
python -m pip install pyinstaller
echo.
echo Building executable...
python -m PyInstaller --noconfirm --onefile --windowed --name "ReactiveImage" ^
  --hidden-import=PIL._tkinter_finder ^
  --hidden-import=pynput.keyboard._win32 ^
  --hidden-import=pynput.mouse._win32 ^
  reactive_image.py
echo.
if exist dist\ReactiveImage.exe (
  echo Built: dist\ReactiveImage.exe
) else (
  echo Build failed.
)
pause
