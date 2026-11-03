# Phone remote

Use your phone as a remote for Stream Core while you stream: highlight a chat line on stream,
roll the credits, open the curtain, give points and red-flag chatters, all from the couch.

It works over your **home Wi-Fi only**. Nobody on the internet can reach it, and the phone can't
change settings, sign-ins or files. Only phones you pair on the PC can use it.

## Switch it on

1. Open the Stream Core dashboard on the PC: **Setup → Core → Phone remote**.
2. Tick **Phone remote on**. The page shows the address phones open, like
   `http://192.168.1.20:3860/phone/`.
3. The first time, Windows asks whether Python may use the network. Tick **Private networks**
   (not Public) and press **Allow**.

**Turn off when Core closes** is on by default: the phone remote switches itself off when Core
closes, so you tick it on again each stream. Untick it to keep it on all the time.

## Pair a phone

1. On the PC page, press **Add a phone**. A QR code and a 6-digit code show for two minutes.
2. On the phone, scan the QR code with the camera (or open the address and type the code).
3. Give the phone a name and press **Pair**. Done: the phone remembers it.

Each phone has its own key. **Remove** next to a phone on the PC page cuts it off straight away
(do this if you lose a phone). Up to 10 phones.

## What's on the phone

- **Live**: the highlighted message with **Next** and **Clear**, the stage curtain (when Stream
  Rooms is connected), the end credits (when they're on), chat game buttons, and the Stream events
  list (alerts, redeems, commands, errors).
- **Chat**: every platform's chat as it happens. Scroll up to read back, **Back to live** jumps to
  the newest line. Tap a line for:
  - **Highlight on stream** (puts it on the Highlighted message overlay),
  - **Reply** (Core answers that chatter in chat),
  - **Points** (+100, +500, take 100, or any amount),
  - **Reactions** (throw a tomato, confetti... at that chatter),
  - **Red-flag** that chatter.
- **People**: find a chatter by name, change their points, and see who is red-flagged (with
  **Unflag**).

Buttons that are hard to undo (red-flag, taking points, clearing boards) are **hold to press**:
keep your finger on them until the bar fills. After a points change, **Undo** shows for 30 seconds.

## If it doesn't connect

- The phone must be on the **same Wi-Fi** as the PC. A guest network usually can't see the PC.
- If the page shows "Reconnecting", check that Core is running and **Phone remote on** is ticked.
- If the PC page says the port couldn't open, another program is using port 3860, or the PC's
  network address changed: untick and tick **Phone remote on** again. Under **Advanced** you can
  type the PC's address by hand.
- If Windows marked your Wi-Fi as a **Public** network, the PC page warns you. Change it to
  Private in Windows Settings → Network & internet → Wi-Fi → your network.

## Not built yet

Timing out or banning someone on Twitch / Kick / YouTube from the phone is planned but not built.
