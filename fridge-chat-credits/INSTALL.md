# Chat Credits — easy install (Windows)

You do **not** need Stream Core for this. You do **not** install pip yourself.

Python already includes pip. The installer below uses it for you.

Do these steps **once**. After that, just double-click **START Chat Credits**.

---

## What you need

- A Windows PC (the streaming PC is fine, even a low-end one)
- About 5 minutes
- Your Twitch and/or Kick channel name (the part after `twitch.tv/` or `kick.com/`)

You do **not** need:

- Stream Core
- A Twitch / Kick login token
- To type any commands

---

## Step 1 — Install Python (skip if Stream Core already runs on this PC)

1. Open [https://www.python.org/downloads/](https://www.python.org/downloads/)
2. Click the big yellow **Download Python** button.
3. Run the file you just downloaded.
4. **On the first screen, tick the box that says “Add python.exe to PATH”.**  
   If you miss this box, Chat Credits cannot start. It is at the **bottom** of that window.
5. Click **Install Now**.
6. If a last screen offers **Disable path length limit**, click that too, then Close.

To check it worked: press the Windows key, type `cmd`, open **Command Prompt**, and type:

```
python --version
```

You want something like `Python 3.12.x` (3.10 or newer is fine).  
If it says Python is not recognized, run the Python installer again and tick **Add python.exe to PATH**.

---

## Step 2 — Get the Chat Credits folder

If you already have the **Fridge Workshop** folder (`flavr-leftovers`) on this PC, skip to Step 3.

Otherwise:

1. Open [https://github.com/sensokasucks/flavr-leftovers](https://github.com/sensokasucks/flavr-leftovers)
2. Click the green **Code** button → **Download ZIP**
3. Unzip it somewhere easy, for example `C:\FridgeWorkshop`
4. Open that unzipped folder. You should see `fridge-chat-credits` inside it.

---

## Step 3 — One-time install (this is the pip part — you never type pip)

1. Open the **Fridge Workshop** folder (the one that contains `fridge-chat-credits`).
2. Double-click **`INSTALL Chat Credits.bat`**
3. A black window opens. Let it run. It will:
   - find Python
   - create a private folder called `.venv` (so nothing else on the PC is changed)
   - download the few packages Chat Credits needs
   - copy a starter config file
4. When it says **Install finished**, press any key.

If it says **Python was not found**, go back to Step 1 and tick **Add python.exe to PATH**.

You can also double-click `fridge-chat-credits\install.bat` if you are already inside that folder. Same thing.

---

## Step 4 — Start it every time you stream

1. Double-click **`START Chat Credits.bat`**
2. Leave that window open while you stream.
3. On this same PC, open a browser to:

**Control desk:** [http://127.0.0.1:3854/](http://127.0.0.1:3854/)

If the page does not load, the black window is not running — start it again.

To stop: click the black window and press `Ctrl+C`, or just close the window.

---

## Step 5 — Turn on your chat platforms (first start only)

In the control desk, scroll to **Config.yaml**.

1. Tick **Twitch** and/or **Kick**
2. Type your channel name  
   - Twitch: the part after `twitch.tv/` (example: `sensoka`)  
   - Kick: the part after `kick.com/`
3. Click **Save config**
4. **Close Chat Credits and start it again** (platform changes need one restart)

YouTube is optional and needs an API key — leave it off unless you know you want it.

Leave **Stream Core ingest** off unless Stream Core is already running and you *want* to reuse its chat instead of opening Kick twice.

---

## Step 6 — Add the overlay in XSplit or OBS

Add a **Webpage** (XSplit) or **Browser** (OBS) source:

| What | Address |
|------|---------|
| Credits roll | `http://127.0.0.1:3854/overlay/credits.html` |

Turn **transparent background** on. Size it however you like.

The control desk is only for you. The overlay is what viewers see.

---

## Step 7 — During the stream

Names collect automatically as people chat.

At the end of the show, on the control desk:

1. Click **Roll credits (freeze list)** — this locks the names so a late chatter does not shuffle the roll.
2. Show the overlay in your scene.

**Loop** keeps rolling. **Play once** stops at the end. **Hold still** freezes on screen.

Add a test name with **Add** if you want to preview before you go live.

---

## Next stream

You already installed. Only do this:

1. Double-click **START Chat Credits.bat**
2. If you want a fresh name list, click **Reset session** on the control desk.

---

## If something goes wrong

| What you see | What to do |
|--------------|------------|
| `Python was not found` | Reinstall Python and tick **Add python.exe to PATH**. Restart the PC if it still fails. |
| `Virtual environment not found` | Run **INSTALL Chat Credits.bat** once. |
| Control desk will not load | Make sure the black START window is still open. |
| Overlay is black / empty | That is normal until names exist. Add a test name, or wait for chat. |
| Names are not appearing | Platforms must be **enabled**, channel spelled right, then **restart** Chat Credits after saving. |
| `pip install failed` | You are probably on public Wi‑Fi that blocks downloads. Try again on a normal connection. You still do not install pip yourself. |
| Two copies of Kick names | Do not enable Kick **and** Stream Core ingest at the same time. |

---

## Stream Core users

If Stream Core is already installed and running, you can skip this whole app.

Use **Admin → Credits** in Stream Core instead, and the overlay:

`http://127.0.0.1:3850/overlay/credits.html`

Same roll, no second process, no second install.
