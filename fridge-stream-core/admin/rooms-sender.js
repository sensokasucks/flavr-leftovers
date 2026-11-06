/*
 * "Share to the big screen" card on Live controls (<section id="live-sender-card"> in index.html):
 * Stream Rooms' sender page, run inside this dashboard instead of in a browser tab of its own.
 *
 * The sender page is what shares a browser tab or window (and webcams, presenter cameras) to Stream
 * Rooms' big screen. It belongs to the game (stream-rooms web/sender.html, served by
 * core/capture_server.gd at http://127.0.0.1:8765/ with that run's stream key written in), so this
 * card always runs the copy of the running game and can't drift from it:
 *   1. GET /api/admin/rooms/sender-page (api/admin_routes.py) reads the page from the game server
 *      side and adds <base href="http://127.0.0.1:8765/">, so the page's /vdoninja-sdk.min.js and
 *      /backdrop links still go to the game.
 *   2. The page goes into an <iframe srcdoc>, which counts as this dashboard's own address (so its
 *      sharing, cameras and saved safe mode work like in a normal tab). allow= lets it share a
 *      screen, use cameras and play sound.
 *   3. window.RoomsSenderHost (below) is how the page talks back: fetchKey() for a new key after the
 *      game restarted (GET /api/admin/rooms/sender-key) and params (this address's ?query, so
 *      ?testshare and ?safeshare work here too). Keep in step with "Inside Stream Core" in
 *      stream-rooms web/sender.html.
 *
 * The game's own page stays the fallback: when Stream Rooms isn't linked to Core, the game's "Open
 * sender page" buttons open it (stream-rooms core/rooms_remote.gd open_sender_page), and this card
 * has a link to it too. Only one sender page sends at a time (the newest that connects); the other
 * one then says so and offers "Use this page".
 *
 * Who opens the card (window.RoomsSender.open): admin.js, from the Stream Rooms card's Big screen
 * picker ("Browser tab or window" + Show) when this dashboard runs on the game's PC, and for the
 * address #live/sender (what the game opens while it's linked to Core). The card stays hidden until
 * then, so opening the dashboard never takes the big screen away from a sender page already open.
 * Close removes the frame, which stops whatever it shared.
 *
 * Sharing keeps going while another dashboard page shows (the page's worker does the picture work),
 * but closing or reloading this browser tab stops it: the tab asks first while something is shared.
 */
(() => {
  const $ = (id) => document.getElementById(id);
  // Same localStorage key as admin.js: the admin token saved in this browser.
  const tokenKey = "stream_core_admin_token";
  // While the game isn't linked yet (Core just started, the game is loading): try again this often.
  const RETRY_MS = 3000;

  let frame = null;        // the <iframe> running the sender page, while the card is open
  let gameUrl = "";        // the game's own sender page address (the fallback link)
  let retryTimer = 0;
  let sizeObs = null;      // keeps the frame as tall as the page inside it

  function token() {
    try { return localStorage.getItem(tokenKey) || ($("token") ? $("token").value.trim() : ""); } catch (_) { return ""; }
  }

  /** GET an admin route; throws an Error carrying .status on a non-2xx answer. */
  async function get(path) {
    const res = await fetch(path, { headers: { "X-Admin-Token": token() }, cache: "no-store" });
    if (!res.ok) {
      let why = res.statusText;
      try { why = (await res.json()).detail || why; } catch (_) {}
      const err = new Error(why);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  function say(text) {
    if ($("sender-msg")) $("sender-msg").textContent = text || "";
  }

  // What the sender page inside the frame may use (web/sender.html "Inside Stream Core").
  window.RoomsSenderHost = {
    params: location.search,
    fetchKey: () => get("/api/admin/rooms/sender-key").then((r) => r.key || "").catch(() => ""),
  };

  /** True while the page inside is sharing something (its Stop button is live). */
  function sharing() {
    try {
      const stop = frame && frame.contentDocument && frame.contentDocument.getElementById("stopBtn");
      return !!(stop && !stop.disabled);
    } catch (_) {
      return false;
    }
  }

  /** Grow / shrink the frame with the page inside it (it changes when a share starts, cameras show...). */
  function fitFrame() {
    try {
      const doc = frame && frame.contentDocument;
      if (!doc || !doc.body) return;
      // the body's own height (the document's scrollHeight never drops below the frame's height,
      // so the frame could grow but not shrink back)
      frame.style.height = Math.max(120, Math.ceil(doc.body.getBoundingClientRect().height)) + "px";
    } catch (_) {}
  }

  /** Read the page from the game through Core and start it in the frame. Retries while the game isn't linked. */
  async function load() {
    clearTimeout(retryTimer);
    if (!frame) return;
    let got;
    try {
      got = await get("/api/admin/rooms/sender-page");
    } catch (e) {
      if (!frame) return;
      say(e.status === 409 ? "Waiting for Stream Rooms to connect to Core..."
        : e.status === 401 ? "Sign in to the dashboard first (admin token)."
          : "Couldn't load the sender page: " + e.message + ". Trying again...");
      retryTimer = setTimeout(load, RETRY_MS);   // (401: it goes on once the token box is filled in)
      return;
    }
    if (!frame) return;
    gameUrl = got.base || "";
    if ($("sender-own-page")) $("sender-own-page").hidden = !gameUrl;
    say("");
    frame.onload = () => {
      fitFrame();
      try {
        if (sizeObs) sizeObs.disconnect();
        sizeObs = new ResizeObserver(fitFrame);
        sizeObs.observe(frame.contentDocument.body);
      } catch (_) {}
    };
    frame.srcdoc = got.html;
  }

  /** Show the card and start the sender in it (does nothing more if it already runs). */
  function open() {
    const card = $("live-sender-card");
    if (!card) return;
    card.hidden = false;
    if (!frame) {
      frame = document.createElement("iframe");
      frame.className = "sender-frame";
      frame.title = "Stream Rooms sender";
      // share a tab or window, cameras for the webcam and presenters, sound without a click first
      frame.allow = "display-capture; camera; microphone; autoplay; fullscreen";
      $("sender-frame-box").appendChild(frame);
      say("Loading the sender page...");
      load();
    }
    card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  /** Close button: remove the frame (stops anything it shared) and hide the card. */
  function close() {
    if (sharing() && !confirm("Stop sharing to the big screen and close the sender?")) return;
    clearTimeout(retryTimer);
    if (sizeObs) sizeObs.disconnect();
    sizeObs = null;
    if (frame) frame.remove();
    frame = null;
    say("");
    if ($("live-sender-card")) $("live-sender-card").hidden = true;
  }

  if ($("sender-close")) $("sender-close").addEventListener("click", close);
  if ($("sender-own-page")) {
    // the old way: the game's own page in a tab of its own (it takes over from this card)
    $("sender-own-page").addEventListener("click", (ev) => {
      ev.preventDefault();
      if (gameUrl) window.open(gameUrl, "_blank", "noopener");
    });
  }
  // Closing or reloading the dashboard would cut the big screen: ask first while something is shared.
  window.addEventListener("beforeunload", (ev) => {
    if (sharing()) {
      ev.preventDefault();
      ev.returnValue = "";
    }
  });

  window.RoomsSender = { open, close, isOpen: () => !!frame, sharing };
})();
