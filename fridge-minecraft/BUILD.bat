@echo off
REM Build both Fabric mods (client + server)
setlocal
cd /d "%~dp0"

if not exist "client-mod\gradlew.bat" (
  echo Missing client-mod\gradlew.bat
  pause
  exit /b 1
)

echo === Building client mod ===
cd client-mod
call gradlew.bat build
if errorlevel 1 (
  echo Client build failed
  pause
  exit /b 1
)
cd ..

echo === Building server mod ===
cd server-mod
if not exist gradlew.bat (
  copy /Y ..\client-mod\gradlew.bat .
  if not exist gradle\wrapper mkdir gradle\wrapper
  copy /Y ..\client-mod\gradle\wrapper\* gradle\wrapper\
)
call gradlew.bat build
if errorlevel 1 (
  echo Server build failed
  pause
  exit /b 1
)
cd ..

echo.
echo Build complete. JARs under */build/libs/
echo Copy them into Minecraft mods folders as needed.
pause
