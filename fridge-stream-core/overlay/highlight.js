/*
 * Highlighted message overlay: /overlay/highlight.html (see the comment at the top of that file).
 *
 * Listens on /ws for {"type": "highlight", "data": {current, queue_len, hold_sec, show_avatar}}
 * (core/highlights.py HighlightBoard.state, sent on connect and after every change) and draws
 * ``current`` as the lower-third bar, or slides it away when it is null. The overlay keeps no
 * timers of its own: Core decides when a highlight moves on (highlight.hold_sec).
 *
 * The message HTML is built like the chat overlay's (overlay/chat.js renderMessageHtml: Twitch /
 * 7TV emote ranges, or Kick's [emote:ID:NAME] tokens). Keep the two in step.
 */
(() => {
  const box = document.getElementById("hl");
  const root = document.getElementById("hl-root");
  const customLink = document.getElementById("hl-custom-css");
  const params = new URLSearchParams(location.search);
  const hint = window.FridgeHint || { set() {}, count() {} };
  const preview = params.get("preview") === "1" || params.get("preview") === "true";
  // ?avatars=0|1 beats the dashboard's "Show the chatter's picture"
  const avatarParam = params.has("avatars") ? params.get("avatars") !== "0" : null;
  if ((params.get("pos") || "").toLowerCase() === "top") root.classList.add("top");
  // ?css=<name>: a saved chat stylesheet (Chat box → Custom CSS → Stylesheet), same file the
  // chat overlay loads with ?css=
  const cssSlot = (params.get("css") || "").trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").slice(0, 40);
  if (cssSlot && cssSlot !== "default" && customLink) customLink.href = "chat-css/" + cssSlot + ".css";

  const EMOTE_RE = /\[emote:(\d+):([^\]]+)\]/g;
  const EMOTE_URL = (id) => `https://files.kick.com/emotes/${id}/fullsize`;
  const PLATFORM_LABEL = { kick: "K", twitch: "T", youtube: "Y" };

  // Every chat value goes through this before it is put into HTML.
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // Emote ranges are inclusive code-point indices (chat.js renderRangesHtml).
  function rangesHtml(raw, emotes) {
    const chars = Array.from(raw);
    const list = emotes.filter((e) => Number.isInteger(e.start) && Number.isInteger(e.end) && e.url)
      .sort((a, b) => a.start - b.start);
    const parts = [];
    let pos = 0;
    for (const e of list) {
      if (e.start < pos || e.end >= chars.length) continue;
      if (e.start > pos) parts.push(esc(chars.slice(pos, e.start).join("")));
      const name = esc(e.name || chars.slice(e.start, e.end + 1).join(""));
      const cls = e.sticker ? "emote sticker" : e.gift ? "emote gift" : "emote";
      parts.push(`<img class="${cls}" src="${esc(e.url)}" alt="${name}" title="${name}" />`);
      pos = e.end + 1;
    }
    if (pos < chars.length) parts.push(esc(chars.slice(pos).join("")));
    return parts.join("");
  }

  function messageHtml(raw, emotes) {
    raw = String(raw || "");
    if (Array.isArray(emotes) && emotes.length) return rangesHtml(raw, emotes);
    const parts = [];
    let last = 0;
    let m;
    const re = new RegExp(EMOTE_RE.source, "g");
    while ((m = re.exec(raw)) !== null) {
      if (m.index > last) parts.push(esc(raw.slice(last, m.index)));
      const name = esc(m[2]);
      parts.push(`<img class="emote" src="${EMOTE_URL(m[1])}" alt="${name}" title="${name}" />`);
      last = m.index + m[0].length;
    }
    if (last < raw.length) parts.push(esc(raw.slice(last)));
    return parts.join("");
  }

  let shownId = null;
  let outTimer = null;

  // Draw one highlight (core/highlights.py clean_item fields), or slide the bar away (null).
  function show(item, showAvatar) {
    if (!item) {
      if (shownId === null) return;
      shownId = null;
      box.classList.remove("in");
      box.classList.add("out");
      clearTimeout(outTimer);
      outTimer = setTimeout(() => { if (shownId === null) box.hidden = true; }, 400);
      return;
    }
    if (item.id === shownId) return;
    shownId = item.id;
    clearTimeout(outTimer);
    const u = item.user || {};
    const plat = String(item.platform || "").toLowerCase();
    const name = u.display_name || u.username || "";
    const pic = u.avatar_local || u.profile_image_url || "";
    const wantPic = (avatarParam ?? showAvatar) && pic;
    const color = /^#[0-9a-f]{3,8}$/i.test(u.color || "") ? u.color : "";
    const paid = item.is_paid && item.paid_amount
      ? `<span class="paid">${esc((item.paid_currency || "") + " " + item.paid_amount)}</span>` : "";
    box.innerHTML =
      `<img class="avatar" alt="" ${wantPic ? `src="${esc(pic)}"` : "hidden"} />` +
      `<div class="body msg message-row chat_line" data-platform="${esc(plat)}" data-from="${esc(u.username || "")}">` +
      `<div class="meta user-box user_info">` +
      (PLATFORM_LABEL[plat] ? `<span class="plat plat-${esc(plat)}">${PLATFORM_LABEL[plat]}</span>` : "") +
      `<span class="name user-name nick"${color ? ` style="color:${color}"` : ""}>${esc(name)}</span>${paid}</div>` +
      `<div class="message user-message">${messageHtml(item.message, item.emotes)}</div></div>`;
    box.hidden = false;
    box.classList.remove("out", "in");
    void box.offsetWidth;          // restart the slide-in animation
    box.classList.add("in");
  }

  function apply(state) {
    if (!state || typeof state !== "object") return;
    show(state.current || null, state.show_avatar !== false);
    hint.set("note", state.current ? "showing a highlight" : "nothing highlighted" +
      (state.queue_len ? ` (${state.queue_len} waiting)` : ""));
  }

  if (preview) {
    apply({ current: { id: -1, platform: "twitch", message: "this is what a highlighted message looks like on stream",
      user: { display_name: "MarbleMoth", color: "#bf94ff" } }, show_avatar: false });
    return;
  }

  let ws;
  let retryMs = 1000;
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { retryMs = 1000; hint.set("core", "Connected to Core"); };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "highlight") apply(msg.data);
      } catch (_) {}
    };
    ws.onclose = () => {
      hint.set("core", "Can't reach Core at " + location.host + " (is it running?), retrying");
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 1.5, 10000);
    };
    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  }
  connect();
  setInterval(() => { if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping"); }, 25000);
})();
