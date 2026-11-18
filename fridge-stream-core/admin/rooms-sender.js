/*
 * "Share to Stream Rooms" card on Live controls (<section id="live-sender-card"> in index.html):
 * Stream Rooms' sender page, run inside this dashboard instead of in a browser tab of its own.
 *
 * The sender page is what shares a browser tab or window to Stream Rooms' big screen, and what
 * feeds the podiums (its "Presenter feeds": a tab or window, a web page, a camera or a co-stream
 * avatar per presenter). It belongs to the game (stream-rooms web/sender.html, served by
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
 * When the card shows (update, called by admin.js loadRoomsCard on every Stream Rooms poll while
 * Live shows): whenever Stream Rooms is linked to Core and this dashboard runs on the game's PC. It
 * then starts the sender by itself, but only while no other sender page is connected (the game's
 * state says sender.connected), so opening the dashboard never takes the big screen away from a
 * sender page already open in another tab; the card then offers "Use it here" instead. "Stop the
 * sender" stops it and it stays stopped until "Start the sender" (or one of the buttons below).
 * Also opened (window.RoomsSender.open) by the Stream Rooms card's Big screen picker ("Browser tab
 * or window" + Show) and the address #live/sender (what the game opens while it's linked to Core).
 * Podiums (window.RoomsSender.pickPresenter): the "Pick a tab or window" / "Open the sender"
 * buttons on Setup > Stream Rooms > Presenters & Co-stream (admin/rooms-setup.js) and on the Live
 * page's Stream Rooms card (admin.js) open that presenter's tab picker through the page inside
 * (its window.SenderPage, stream-rooms web/sender.html "Called by Stream Core").
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
  // After the page inside has loaded, wait this long before pointing at a podium's row (ms): the
  // game first has to tell the page which podiums want a tab (its "presenters" message), and until
  // then the rows are hidden as unused.
  const PICK_AFTER_LOAD_MS = 1500;
  // The sender page only answers on the game's PC (127.0.0.1); same test as admin.js ROOMS_SAME_PC.
  const SAME_PC = ["127.0.0.1", "localhost", "::1", "[::1]"].includes(location.hostname);

  let frame = null;        // the <iframe> running the sender page, while the card is open
  let gameUrl = "";        // the game's own sender page address (the fallback link)
  let retryTimer = 0;
  let sizeObs = null;      // keeps the frame as tall as the page inside it
  let pendingPick = 0;     // a podium (1-4) to point at once the page inside has loaded (pickPresenter)
  let userStopped = false; // "Stop the sender" was pressed: update() doesn't start it again by itself

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
      // a podium button was pressed before the page was ready (pickPresenter): point at its row now
      if (pendingPick) {
        const n = pendingPick;
        pendingPick = 0;
        setTimeout(() => { const api = senderApi(); if (api) api.pickPresenter(n); }, PICK_AFTER_LOAD_MS);
      }
      try {
        if (sizeObs) sizeObs.disconnect();
        sizeObs = new ResizeObserver(fitFrame);
        sizeObs.observe(frame.contentDocument.body);
      } catch (_) {}
    };
    frame.srcdoc = got.html;
  }

  /** The idle line (sender not running here): why, and the button that starts it. */
  function idle(elsewhere) {
    if ($("sender-idle")) $("sender-idle").hidden = false;
    if ($("sender-idle-text")) {
      $("sender-idle-text").textContent = elsewhere
        ? "A sender page is already open somewhere else (another dashboard tab or the game's own page), so this one waits."
        : "The sender is stopped.";
    }
    if ($("sender-start")) $("sender-start").textContent = elsewhere ? "Use it here" : "Start the sender";
  }

  /**
   * admin.js loadRoomsCard, every poll while Live shows: r = GET /api/admin/rooms ({connected,
   * state}). Shows the card while Stream Rooms is linked and this dashboard is on the game's PC, and
   * starts the sender when nothing else sends (see the file comment). On another device the card
   * stays hidden: a sender there would share that device's screen (the Big screen picker and the
   * podium buttons open one on the game's PC instead).
   */
  function update(r) {
    const card = $("live-sender-card");
    if (!card) return;
    const linked = !!(r && r.connected && r.state);
    if (!SAME_PC || (!linked && !frame)) {
      card.hidden = true;
      return;
    }
    card.hidden = false;
    if (frame) return;
    // (after Stop the game may still report this card's own socket for a poll: stopped wins)
    const elsewhere = !!(r.state.sender && r.state.sender.connected);
    if (userStopped) idle(false);
    else if (elsewhere) idle(true);
    else open({ scroll: false });
  }

  /** Show the card and start the sender in it (does nothing more if it already runs). opts.scroll:
   *  false keeps the page where it is (update starting it by itself). */
  function open(opts) {
    const card = $("live-sender-card");
    if (!card) return;
    card.hidden = false;
    userStopped = false;
    if ($("sender-idle")) $("sender-idle").hidden = true;
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
    if (!opts || opts.scroll !== false) card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  /** The page inside's window.SenderPage (stream-rooms web/sender.html), or null (not loaded yet, or an older game). */
  function senderApi() {
    try {
      const api = frame && frame.contentWindow && frame.contentWindow.SenderPage;
      return api && typeof api.pickPresenter === "function" ? api : null;
    } catch (_) {
      return null;
    }
  }

  /** Show the card on the Live page (the address #live/sender; admin.js activateTab opens it). */
  function goToCard() {
    if (location.hash === "#live/sender") open();
    else location.hash = "#live/sender";
  }

  /**
   * A podium's button: "Pick a tab or window" (pick = true) or "Open the sender" (pick = false) for
   * presenter n (1-4). Called from a click (the browser's share box only opens right after one, and
   * the click counts for the same-origin frame too), by admin/rooms-setup.js and admin.js. Returns
   * the line to show next to the button.
   *  - On another device (phone, second PC) the game opens its sender on its own PC instead
   *    (rooms action "sender" "open", like the Big screen picker): the tab is picked there.
   *  - Sender already running here: its pickPresenter opens the share box straight away, or (the
   *    podium isn't set to a tab yet / no fresh click) outlines that podium's row on the Live page.
   *  - Sender not running yet: start it, go to the Live page, and outline the row once it's loaded.
   */
  function pickPresenter(n, pick) {
    if (!SAME_PC) {
      fetch("/api/admin/rooms", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Admin-Token": token() },
        body: JSON.stringify({ action: "sender", value: "open" }),
      }).catch(() => {});
      return "Opened the sender on the game's PC: pick Presenter " + n + "'s tab or window there.";
    }
    const api = senderApi();
    if (api && pick && api.pickPresenter(n) === "picking") {
      return "Pick Presenter " + n + "'s tab or window in the browser's share box.";
    }
    if (api) {
      goToCard();
      api.pickPresenter(n);   // (outlines the row; with pick = false nothing else happens)
      return "Presenter " + n + "'s row is outlined in the sender on the Live page.";
    }
    pendingPick = n;
    goToCard();
    return "Opening the sender on the Live page: click Presenter " + n + "'s button there.";
  }

  /** "Stop the sender": remove the frame (stops anything it shared and every podium feed it sends);
   *  the card stays, with "Start the sender". */
  function close() {
    if (sharing() && !confirm("Stop sharing to the big screen and stop the sender?")) return;
    userStopped = true;
    clearTimeout(retryTimer);
    if (sizeObs) sizeObs.disconnect();
    sizeObs = null;
    if (frame) frame.remove();
    frame = null;
    pendingPick = 0;
    say("");
    idle(false);
  }

  if ($("sender-close")) $("sender-close").addEventListener("click", close);
  if ($("sender-start")) $("sender-start").addEventListener("click", () => open());
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

  window.RoomsSender = { open, close, update, isOpen: () => !!frame, sharing, pickPresenter };
})();
