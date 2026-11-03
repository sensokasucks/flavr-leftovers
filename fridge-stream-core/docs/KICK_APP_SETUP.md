# Making your Kick app (for Connect Kick)

Stream Core reads Kick chat without any sign-in. **Connect Kick** is only needed when you want
Core to *post* into your Kick chat: command answers, game lines and chat game messages go into
the real chat instead of only the overlay (Settings → Core + chat platforms → **Where Core's
replies go** picks Auto / Real chat only / Overlay only / Both per platform).

Kick doesn't let one app be shared without a secret, and Stream Core's code is public, so every
streamer makes their own small Kick app. It's free, takes about five minutes, and you only do it
once. The same steps are on the Kick card in the dashboard (Settings → Core + chat platforms →
Kick → **How to make your Kick app**).

## What you need

- Your Kick account (the one you stream on).
- Two-Factor Authentication (2FA) turned on for that account. Kick only lets you make apps with
  2FA on.
- Stream Core running, with the dashboard open.

## Steps

1. **Turn on 2FA.** Sign in at [kick.com](https://kick.com), open your account **Settings**, and
   under security turn on **Two-Factor Authentication** (an authenticator app such as Google
   Authenticator or Authy works). Skip this if it's already on.
2. **Open the developer page.** Go to
   [kick.com/settings/developer](https://kick.com/settings/developer) and press **Create App**.
3. **Name it.** App name: anything, for example `My Stream Core`. Description: anything.
   The icon is optional.
4. **Redirect URL.** Paste exactly:

   ```
   http://localhost:3850/kick/callback
   ```

   If you changed Core's port (Settings → Core, normally 3850), use that number instead. The
   dashboard shows the right address with a **Copy** button. It must be `localhost`, not
   `127.0.0.1`, and match letter for letter.
5. **Scopes.** If the form lists scopes (permissions), tick the ones for reading user information
   (`user:read`) and writing to chat (`chat:write`). Core asks for nothing else. Leave webhooks off.
6. **Create it, then copy the keys.** Press **Create App**, open the app again (Edit / Manage),
   and copy its **Client ID** and **Client Secret**.
7. **Paste them into Core.** In the dashboard go to Settings → Core + chat platforms → **Kick**,
   paste them into **Client ID** and **Client Secret**, and press **Save** at the bottom.
8. **Connect.** Press **Connect Kick**. A Kick tab opens; check it shows your app's name and press
   **Allow**. The tab then says *Kick connected*; close it. The dashboard now says
   **Kick account: connected as** your name.
9. **Test it.** Press **Send test message**. The line *Stream Core is connected to Kick chat.*
   appears in your Kick chat.

## Good to know

- **Keep the Client Secret private.** Don't show it on stream, in a screenshot, or share your
  `config.yaml`. If it leaks, make a new secret in your Kick app, paste it into Core, Save, and
  press **Connect Kick** again.
- The sign-in is saved in `data\kick_token.json` on your PC and only ever sent to Kick. Core
  renews it in the background. **Disconnect** cancels it at Kick and deletes the file.
- Changing the Client ID forgets the old sign-in; press **Connect Kick** again.
- Messages are posted as the account that pressed Allow, into that account's own channel. Sign in
  with the channel you stream on.

## When it doesn't work

| What you see | What to do |
| --- | --- |
| Kick's page says the redirect URL / redirect URI is invalid | The Redirect URL in your Kick app doesn't match. Copy it again from the dashboard (step 4). |
| *Kick refused the sign-in: invalid_client* | The Client ID or Client Secret is wrong or has a space in it. Paste both again and Save. |
| *This sign-in link is not the one Core is waiting for* | Core restarted, or you used an old tab. Press **Connect Kick** again. |
| No Kick tab opens | Your browser blocked the pop-up. Use the *open Kick's sign-in page* link the dashboard shows. |
| *Press Save first…* | You pasted the keys but didn't press **Save** yet. |
| Test message: *Kick refused the message … press Reconnect* | The app is missing the chat scope. Tick it in the Kick app if the form has it, then press **Reconnect**. |
| The tab says it can't reach `localhost` | Stream Core isn't running, or runs on another port. Start Core, or fix the port in the Redirect URL. |
