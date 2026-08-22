# Windows helper scripts – line-by-line

These batch files live next to `main.py`. They are optional: you can still create a venv and run `python main.py` by hand. They exist so a non-tech user only has to **double-click**.

| File | When to use |
|------|-------------|
| **install.bat** | Once after download / clone |
| **start.bat** / **run.bat** | Every time you stream |
| **wizard.py** | First setup, or when you change Kick channel / admins |

`run.bat` is only an alias that calls `start.bat`.

---

## install.bat

```bat
@echo off
```
Turns off command echoing so the window stays readable.

```bat
setlocal EnableExtensions
cd /d "%~dp0"
```
`setlocal` keeps variable changes inside this script.  
`cd /d "%~dp0"` switches to the folder that contains this `.bat` (drive letter included), no matter where you launched it from.

```bat
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>&1
  ...
)
```
Looks for the Windows **Python launcher** (`py -3`) first, then plain `python`.  
If neither is on PATH, prints a short error and exits — you must install Python from python.org with “Add to PATH” checked.

```bat
%PY% -m venv .venv
```
Creates an isolated environment in `.venv` so Stream Core’s packages do not touch system Python.

```bat
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
```
Uses **that** venv’s Python to install FastAPI, uvicorn, httpx, PyYAML, etc.

```bat
if not exist "config\config.yaml" (
  copy /Y "config\config.example.yaml" "config\config.yaml"
)
```
Copies the example config **only if** you do not already have one (so re-running install never wipes your settings). Same idea for `commands.json`.

```bat
if not exist "data" mkdir data
```
Ensures the SQLite folder exists.

```bat
set /p RUN_WIZARD="Run the first-run setup wizard now? (Y/n): "
...
".venv\Scripts\python.exe" wizard.py
```
Offers the interactive wizard. Answering `n` skips it; you can run `wizard.py` later.

---

## start.bat

```bat
cd /d "%~dp0"
```
Same “run from this folder” safety as install.

```bat
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first
  exit /b 1
)
```
Refuses to start if install was never run.

```bat
if not exist "config\config.yaml" (
  ".venv\Scripts\python.exe" wizard.py
)
```
If config is still missing, forces the wizard once before launching.

```bat
".venv\Scripts\python.exe" main.py
```
Starts Stream Core with the venv interpreter (correct packages, correct paths).

```bat
pause
```
Keeps the window open after exit so you can read any error messages.

---

## run.bat

```bat
call "%~dp0start.bat"
```
Simply calls `start.bat` in the same folder. Use whichever name you prefer.

---

## wizard.py (not a .bat, but part of first-run)

Run via install, or:

```bat
.venv\Scripts\python.exe wizard.py
```

What it does:

1. Loads existing `config.yaml` (or defaults).
2. Asks for:
   - Kick channel slug
   - Admin / mod usernames
   - Admin dashboard token (generates a random one if still `change-me`)
   - Whether to enable Minecraft + player name
3. Tries **Kick chatroom autodetection** (same logic as the live adapter).
4. Writes `config/config.yaml` via `core.config.save_config`.

Re-run anytime; Enter keeps the current value shown in `[brackets]`.

---

## Kick chatroom autodetection (runtime)

Inside `adapters/kick.py`:

1. If `kick.chatroom_id` is already set → use it (no network).
2. Otherwise try several public URLs (`/api/v2/channels/{slug}`, v1, `/chat`, `/chatroom`) with a few browser-like header sets.
3. On success → **write the id back into `config.yaml`** so the next start skips the lookup (important when Cloudflare starts returning 403).
4. On failure → clear log message with the browser fallback URL.

You never need to set `chatroom_id` by hand unless Kick blocks the automated lookup.

---

## Typical first-time flow

1. Install **Python 3.11+** (tick Add to PATH).
2. Double-click **install.bat** → answer **Y** for the wizard.
3. Double-click **start.bat**.
4. Open `http://127.0.0.1:3850/admin/`, paste the admin token, finish any tweaks on the Config tab.
5. Add Webpage sources in XSplit / OBS (URLs in the main README).
