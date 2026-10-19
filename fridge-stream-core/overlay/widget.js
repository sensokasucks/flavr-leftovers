/*
 * Chat widget page: /overlay/widget.html?name=<widget>
 *
 * Loads the widget's sandboxed frame (/widget-frame/<name>), listens to Core's /ws and passes
 * chat, deletions and alerts in, translated by widget-bridge.js into StreamElements' or
 * Streamlabs' event shapes. The frame can't reach Core itself: its code is someone else's.
 *
 * URL options: ?name=<widget> (required), ?platform=kick | ?platforms=kick,twitch (omit = all),
 *   ?alerts=0 (chat only), ?hide=<seconds> (Streamlabs chat box: lines leave after that),
 *   ?history=1 (start with the last few messages), ?preview=1 (made-up chatters when quiet),
 *   ?hint=0 / ?hint=1 (the corner line outside OBS)
 *
 * Talks to: /api/overlay/widget/<name> (api/server.py: version, platform, values, channel,
 *   currency; polled every 4 s so a dashboard save reloads the frame), /api/overlay/chat-settings
 *   (badge pictures), /ws (chat, chat_history, chat_removed, chat_user_hidden, alert,
 *   alert_history, widget_button). The {fridge: ...} messages to and from the frame must match
 *   overlay/widget-frame.js.
 */
(() => {
  const B = window.FridgeWidgetBridge;
  const hint = window.FridgeHint || { set() {}, count() {} };
  const frame = document.getElementById("frame");
  const params = new URLSearchParams(location.search);
  const name = (params.get("name") || params.get("widget") || "").trim().toLowerCase();
  const preview = ["1", "true"].includes((params.get("preview") || "").toLowerCase());
  const wantAlerts = params.get("alerts") !== "0";
  const wantHistory = params.get("history") === "1";
  const hideSec = Math.max(0, Number(params.get("hide")) || 0);

  // Words accepted in ?platform= / ?platforms= (short forms too) -> Core's platform names.
  const PLATFORM_NAMES = { kick: "kick", twitch: "twitch", youtube: "youtube", yt: "youtube", ttv: "twitch", tw: "twitch", k: "kick" };
  const platformFilter = new Set();
  [params.get("platform") || "", ...(params.get("platforms") || "").split(/[,+\s]+/)]
    .map((p) => p.trim().toLowerCase())
    .forEach((p) => { if (PLATFORM_NAMES[p]) platformFilter.add(PLATFORM_NAMES[p]); });
  const allowed = (plat) => !platformFilter.size || platformFilter.has(String(plat || "").toLowerCase());
  hint.set("filter", platformFilter.size ? "showing " + [...platformFilter].join(" + ") + " only" : "showing every platform");

  let info = null;        // {name, platform, values, version, channel, currency}
  let media = {};         // the chat overlay's badge pictures, when uploaded
  let ready = false;      // the frame said hello after the widget's code ran
  // messages for the frame held until it says "ready" (a reload empties it)
  let queue = [];
  const seen = [];        // recent lines, so deletions by user / name can name the message ids

  // SE_API.store is shared by every widget (as on StreamElements); kept in this page's storage
  const storeKey = (key) => `fridge_widget_store:${key}`;
  // StreamElements' session data: the latest follower / sub / tip / cheer / raid and recent lists
  const session = {};

  // "*": the sandboxed frame has a blank ("null") origin, so it can't be named as the target.
  function post(msg) {
    if (!frame.contentWindow) return;
    frame.contentWindow.postMessage(msg, "*");
  }
  function deliver(msg) {
    if (ready) post(msg);
    else queue.push(msg);
  }
  const isSL = () => info && info.platform === "streamlabs";

  // (Re)load the widget's frame; ?v= changes with every saved edit so the browser doesn't cache it.
  function loadFrame() {
    ready = false;
    queue = [];
    frame.src = `/widget-frame/${encodeURIComponent(name)}?v=${info.version}`;
  }

  // Messages from the frame: "ready" (send "load" + the queue), and SE_API.store get / set.
  // Anything not from our own frame is ignored.
  window.addEventListener("message", (ev) => {
    if (ev.source !== frame.contentWindow) return;
    const m = ev.data || {};
    if (m.fridge === "ready") {
      ready = true;
      const detail = isSL() ? Object.assign({ fieldData: info.values }, info.values) : B.seLoadDetail(info, session);
      post({ fridge: "load", detail, hide: hideSec });
      const waiting = queue;
      queue = [];
      waiting.forEach(post);
    } else if (m.fridge === "store-get") {
      let value = null;
      try { value = JSON.parse(localStorage.getItem(storeKey(m.key)) || "null"); } catch (_) { value = null; }
      post({ fridge: "store-result", id: m.id, value });
    } else if (m.fridge === "store-set") {
      try { localStorage.setItem(storeKey(m.key), JSON.stringify(m.value)); } catch (_) {}
    }
  });

  // One Core chat line -> the frame. `quiet` = history / samples: not counted in the corner hint.
  function chat(data, quiet) {
    if (!data || !allowed(data.platform)) return;
    if (!quiet) hint.count("chat messages");
    const user = data.user || {};
    seen.push({ platform: data.platform, id: String(data.message_id || ""), user: String(user.id || ""),
      name: String(user.username || "").toLowerCase(), display: String(user.display_name || "").toLowerCase() });
    // (only the last 300 lines can be matched for deletions)
    if (seen.length > 300) seen.splice(0, seen.length - 300);
    if (isSL()) {
      const m = B.slMessage(data, media);
      deliver({ fridge: "sl-chat", item: m.item, detail: m.detail });
    } else {
      deliver({ fridge: "event", detail: B.seMessage(data, media) });
    }
  }

  // Tell the frame these `seen` lines are gone. StreamElements gets delete-message per id and
  // delete-messages for a whole user; Streamlabs' chat box removes the rows itself (sl-remove).
  function removed(list, userId) {
    const ids = list.map((s) => s.id).filter(Boolean);
    list.forEach((s) => { const i = seen.indexOf(s); if (i !== -1) seen.splice(i, 1); });
    if (isSL()) {
      deliver({ fridge: "sl-remove", ids, userId: userId || "" });
      return;
    }
    ids.forEach((id) => deliver({ fridge: "event", detail: { listener: "delete-message", event: { msgId: id } } }));
    if (userId) deliver({ fridge: "event", detail: { listener: "delete-messages", event: { userId } } });
  }

  // chat_removed: a mod deleted a line, timed out / banned someone, or cleared chat
  function chatRemoved(d) {
    const plat = String(d.platform || "");
    const mid = String(d.message_id || "");
    const uid = String(d.user_id || "");
    const uname = String(d.username || "").toLowerCase();
    const hits = seen.filter((s) => (!plat || s.platform === plat) && (d.all || (mid ? s.id === mid
      : (uid && s.user === uid) || (uname && (s.name === uname || s.display === uname)))));
    // A line not in `seen` (older, or before this page loaded) can still be removed by its id.
    if (!hits.length && mid) hits.push({ id: mid });
    removed(hits, !mid && !d.all ? uid || (hits[0] && hits[0].user) || "" : "");
  }

  // chat_user_hidden: the chatter was red-flagged in Core
  function userHidden(d) {
    const plat = String(d.platform || "");
    const id = String(d.id || "");
    const names = [d.username, d.display_name].filter(Boolean).map((n) => String(n).toLowerCase());
    const hits = seen.filter((s) => (!plat || s.platform === plat) && ((id && s.user === id) || names.includes(s.name) || names.includes(s.display)));
    removed(hits, id || (hits[0] && hits[0].user) || "");
  }

  // One Core alert -> the frame (unless ?alerts=0 or another platform). StreamElements widgets
  // also get onSessionUpdate with the latest / recent lists.
  function alert(a) {
    if (!wantAlerts || !a || !allowed(a.platform)) return;
    if (isSL()) {
      const ev = B.slAlert(a);
      if (ev) deliver({ fridge: "event", detail: ev });
    } else {
      const ev = B.seAlert(a);
      if (!ev) return;
      B.seRemember(session, ev);
      deliver({ fridge: "event", detail: ev });
      deliver({ fridge: "session", detail: { session: { data: session, settings: {} } } });
    }
  }

  // alert_history on connect: fills the session data (no events, nothing new happened)
  function alertHistory(list) {
    list.forEach((a) => {
      if (!a || a.is_test || !allowed(a.platform)) return;
      const ev = B.seAlert(a);
      if (ev) B.seRemember(session, ev);
    });
  }

  // ?preview=1: made-up chatters and a test follow, shown when no real chat came in yet.
  function samples() {
    const now = Date.now() / 1000;
    [
      { platform: "twitch", message_id: "sample-1", timestamp: now, message: "hi everyone! this is a widget preview",
        user: { id: "s1", username: "lunabyte", display_name: "LunaByte", color: "#9b7bff", is_subscriber: true, badges: ["subscriber"] } },
      { platform: "twitch", message_id: "sample-2", timestamp: now, message: "the chains look great",
        user: { id: "s2", username: "pixelpirate", display_name: "PixelPirate", color: "#53fc18", is_mod: true, badges: ["moderator"] } },
      { platform: "youtube", message_id: "sample-3", timestamp: now, message: "love it",
        user: { id: "s3", username: "marblemoth", display_name: "MarbleMoth", color: "#ff4e45", is_vip: true } },
    ].forEach((d) => chat(d, true));
    alert({ kind: "follow", platform: "twitch", display_name: "NewFriend", username: "newfriend", is_test: true });
  }

  async function loadMedia() {
    try {
      const s = await fetch("/api/overlay/chat-settings?t=" + Date.now()).then((r) => (r.ok ? r.json() : {}));
      media = (s && s.media) || {};
    } catch (_) { media = {}; }
  }

  // Fetch the widget's info; reload the frame only when its version or platform changed.
  // Returns false (and keeps retrying from the caller) while Core or the widget isn't there.
  async function loadInfo() {
    if (!name) {
      hint.set("core", "Add ?name=<widget> to the address (Overlays → Chat widgets copies it)");
      return false;
    }
    try {
      const res = await fetch(`/api/overlay/widget/${encodeURIComponent(name)}?t=${Date.now()}`);
      if (res.status === 404) {
        hint.set("core", `No widget called "${name}" in Core (Overlays → Chat widgets)`);
        return false;
      }
      if (!res.ok) return false;
      const next = await res.json();
      const changed = !info || next.version !== info.version || next.platform !== info.platform;
      info = next;
      if (changed) loadFrame();
      return true;
    } catch (_) {
      return false;
    }
  }

  let ws;
  let retryMs = 1000;
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      retryMs = 1000;
      hint.set("core", "Connected to Core");
      if (preview) setTimeout(() => { if (!seen.length) samples(); }, 1200);
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (!msg || !msg.data) return;
      if (msg.type === "chat") chat(msg.data);
      else if (msg.type === "chat_history" && wantHistory && Array.isArray(msg.data)) msg.data.slice(-10).forEach((d) => chat(d, true));
      else if (msg.type === "chat_removed") chatRemoved(msg.data);
      else if (msg.type === "chat_user_hidden") userHidden(msg.data);
      else if (msg.type === "alert") alert(msg.data);
      else if (msg.type === "alert_history" && Array.isArray(msg.data)) alertHistory(msg.data);
      // the dashboard's buttons for the widget's own "button" fields (its test messages)
      else if (msg.type === "widget_button" && msg.data.name === name) {
        deliver({ fridge: "event", detail: { listener: "widget-button", event: { listener: "widget-button", field: msg.data.field, value: msg.data.value } } });
      }
    };
    ws.onclose = () => {
      hint.set("core", "Can't reach Core at " + location.host + " (is it running?), retrying");
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 1.5, 10000);
    };
    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  }

  function start() {
    connect();
    // keep checking: saving the widget's settings on the dashboard reloads it here
    setInterval(loadInfo, 4000);
    setInterval(loadMedia, 30000);
    // keep the WebSocket from going idle (25 s)
    setInterval(() => { if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping"); }, 25000);
  }

  (async () => {
    await loadMedia();
    if (await loadInfo()) return start();
    const retry = setInterval(async () => {
      if (await loadInfo()) { clearInterval(retry); start(); }
    }, 4000);
  })();
})();
