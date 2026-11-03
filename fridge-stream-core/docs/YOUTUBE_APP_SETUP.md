# Making your Google client (for Connect YouTube)

Stream Core reads YouTube chat without any sign-in. **Connect YouTube** is only needed when you
want Core to *post* its replies (command answers, game lines, chat game messages) into your
YouTube live chat instead of only showing them on the overlay. Settings → Core + chat platforms →
**Where Core's replies go** decides per platform: Auto / Real chat only / Overlay only / Both.

Google only lets the channel owner's own sign-in post into live chat, and Stream Core's code is
public, so every streamer makes their own Google client. It's free, takes about ten minutes, and
you only do it once. The same steps are on the YouTube card in the dashboard (Settings → Core +
chat platforms → YouTube → **How to make your Google client**). The code behind it is
`adapters/youtube_auth.py`.

## Steps

1. **Make a project.** Go to [console.cloud.google.com](https://console.cloud.google.com/projectcreate),
   sign in with any Google account and create a project, for example `My Stream Core`.
2. **Turn on the YouTube API.** In that project open
   [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) and
   press **Enable**.
3. **Consent screen.** Open [Google Auth Platform](https://console.cloud.google.com/auth/overview)
   and press **Get started**: any app name, your e-mail as support e-mail, Audience **External**,
   your e-mail as contact, agree, **Create**.
4. **Publish it.** Under **Audience** press **Publish app** so the status says *In production*.
   Left in *Testing*, Google signs Core out every 7 days. You do **not** need Google's
   verification for your own use; when you connect, Google shows "Google hasn't verified this
   app": press **Advanced**, then **Go to (your app name)**.
5. **Make the client.** Under **Clients** press **Create client**. Application type:
   **TVs and Limited Input devices** (this matters: other types don't work with Core's code
   sign-in). Any name, then **Create**.
6. **Paste it into Core.** Copy the **Client ID** (ends in `.apps.googleusercontent.com`) and
   **Client secret** into Settings → YouTube → **Client ID** / **Client Secret**, and press
   **Save** at the bottom.
7. **Connect.** Press **Connect YouTube**. Open [google.com/device](https://www.google.com/device),
   type the code the card shows, choose the Google account **that owns your YouTube channel**
   (pick the channel if it asks) and press **Allow**. The card then says
   **YouTube account: connected as** your channel.
8. **Test it** while you are live and the **Live video** box (or Live controls) has this stream's
   link: press **Send test message**. *Stream Core is connected to YouTube chat.* appears in
   your live chat.

## Good to know

- **Quota.** Your Google project gets 10,000 free API units a day. Each posted reply costs 50
  (about 200 replies a day); finding the stream's chat costs 1, once per stream. When the
  quota runs out, replies go back to the overlay until it resets (midnight Pacific time) when
  **Where Core's replies go** is on Auto. Reading chat in innertube mode uses no quota at all.
- YouTube chat has no reply threads, so Core starts a reply with `@name`.
- **Keep the Client secret private.** The sign-in is saved in `data\youtube_token.json` and only
  sent to Google. **Disconnect** cancels it at Google and deletes the file.
- Changing the Client ID forgets the old sign-in; press **Connect YouTube** again.

## When it doesn't work

| What you see | What to do |
|---|---|
| "invalid_client" / "Unauthorized" when pressing Connect | The client type must be **TVs and Limited Input devices**. Make a new client of that type. |
| "that video has no live chat right now" | Fill in this stream's link in Live video / Live controls, and be live. |
| Signed out after a week | Publish the app (step 4) and connect again. |
| "exceeded your quota" | Wait for the daily reset; replies show on the overlay meanwhile. |
| "connect with the channel owner's account" | Disconnect and connect with the account that owns the channel. |
