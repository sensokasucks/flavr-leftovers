/*
 * Phone remote page (phone/index.html). Talks only to the phone door (api/phone_server.py):
 *   /phone/api/pair, /me, /summary, /flagged, /reactions, /reply, and /phone/api/admin/<path>
 *   for the Live actions on that file's ALLOWED list.
 * Every call carries this phone's key (X-Phone-Key, kept in localStorage FRIDGE_KEY). A 401
 * means the phone was removed on the PC: the key is dropped and the pairing screen shows.
 *
 * Polling (only while the page is visible): summary + Stream events every SUMMARY_MS, chat
 * every CHAT_MS. A failed call shows the "Reconnecting" bar and greys the buttons, so a press
 * never goes nowhere; the next good call clears it.
 * Risky presses (red flag, taking points, clearing boards) are hold-to-confirm (holdButton).
 * Points changes get an Undo for UNDO_MS.
 */
(() => {
  const FRIDGE_KEY = "fridge_phone_key";
  const SUMMARY_MS = 3000;
  const CHAT_MS = 1500;
  const CHAT_MAX = 200;            // lines kept in the Chat list (busy chats stay light)
  const FEED_MAX = 60;
  const HOLD_MS = 800;             // keep a hold button pressed this long (matches phone.css .holding)
  const UNDO_MS = 30000;
  const $ = (id) => document.getElementById(id);

  let key = "";
  try { key = localStorage.getItem(FRIDGE_KEY) || ""; } catch (_) {}
  let tab = "live";
  let chatLast = 0;
  let chatRows = [];               // oldest first
  let feedLast = 0;
  let feedRows = [];               // newest first
  let summary = {};
  let followChat = true;           // false while scrolled up in Chat
  let reactionsList = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  // Kick emotes arrive as [emote:ID:NAME]: show the name
  const text = (s) => String(s || "").replace(/\[emote:\d+:([^\]]+)\]/g, "$1");
  const who = (r) => (r.user && (r.user.display_name || r.user.username)) || "?";

  function setOffline(off) {
    $("offline").hidden = !off;
    document.body.classList.toggle("offline", off);
  }

  // One call to the phone door. Throws Error(message) on failure; 401 = unpaired.
  async function call(path, opts = {}) {
    let res;
    try {
      res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Phone-Key": key, ...(opts.headers || {}) } });
    } catch (e) {
      setOffline(true);
      throw new Error("Can't reach Stream Core");
    }
    setOffline(false);
    if (res.status === 401 && !path.endsWith("/pair")) {
      key = "";
      try { localStorage.removeItem(FRIDGE_KEY); } catch (_) {}
      showPair("This phone isn't paired any more. Pair it again.");
      throw new Error("not paired");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || res.statusText || "Failed");
    return data;
  }
  const admin = (path, body, method) =>
    call("/phone/api/admin" + path, { method: method || (body === undefined ? "GET" : "POST"), body: body === undefined ? undefined : JSON.stringify(body) });

  let toastTimer = 0;
  function toast(msg, undo) {
    const t = $("toast");
    t.innerHTML = `<span>${esc(msg)}</span>` + (undo ? '<button type="button">Undo</button>' : "");
    t.hidden = false;
    if (undo) t.querySelector("button").onclick = () => { t.hidden = true; undo(); };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, undo ? UNDO_MS : 2500);
  }

  // Hold-to-confirm: ``fn`` runs only after HOLD_MS of pressing; letting go early cancels.
  function holdButton(btn, fn) {
    let timer = 0;
    const stop = () => { clearTimeout(timer); btn.classList.remove("holding"); };
    btn.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      btn.classList.add("holding");
      timer = setTimeout(() => { btn.classList.remove("holding"); fn(); }, HOLD_MS);
    });
    ["pointerup", "pointerleave", "pointercancel"].forEach((e) => btn.addEventListener(e, stop));
    btn.addEventListener("click", (ev) => ev.preventDefault());
  }

  // ── pairing ──

  function showPair(msg) {
    $("app").hidden = true;
    $("pair").hidden = false;
    $("pair-msg").textContent = msg || "";
  }

  async function pair(token) {
    const name = $("pair-name").value.trim() || "My phone";
    const code = $("pair-code").value.replace(/\D/g, "");   // the PC shows "123 456": spaces are fine
    if (!token && !/^\d{6}$/.test(code)) { $("pair-msg").textContent = "Type the 6-digit code from the PC."; return; }
    $("pair-msg").textContent = "Pairing…";
    try {
      const res = await call("/phone/api/pair", { method: "POST", body: JSON.stringify({ code, token, name }) });
      key = res.key;
      try { localStorage.setItem(FRIDGE_KEY, key); } catch (_) {}
      history.replaceState(null, "", location.pathname);   // the one-time link leaves the address bar
      start();
    } catch (e) {
      $("pair-msg").textContent = e.message;
    }
  }
  $("pair-go").onclick = () => pair(pairToken);
  const pairToken = (location.hash.match(/pair=([\w-]+)/) || [])[1] || "";

  // ── Live screen ──

  function renderSummary(s) {
    summary = s || {};
    $("lights").innerHTML = (s.platforms || []).map((p) =>
      `<span class="light${p.connected ? " on" : ""}"><i></i>${esc(p.name)}</span>`).join("") ||
      '<span class="muted">No chat platform on</span>';
    const h = s.highlight || {};
    $("hl-now").innerHTML = h.current
      ? `<span class="who">${esc(who(h.current))}</span>${esc(text(h.current.message))}`
      : '<span class="muted">Nothing on screen. Tap a line in Chat to highlight it.</span>';
    $("hl-state").textContent = h.queue_len ? `${h.queue_len} waiting` : "";
    const st = s.stage || {};
    $("stage-card").hidden = !st.connected;
    $("stage-state").textContent = st.curtain ? st.curtain : "";
    const cr = s.credits || {};
    $("credits-card").hidden = !cr.enabled;
    $("credits-state").textContent = cr.enabled ? `${cr.count} names` : "";
    const playing = !cr.play || cr.play.playing !== false;
    $("credits-pause").textContent = playing ? "Pause" : "Resume";
    $("games-card").hidden = !(s.chat_games && s.chat_games.enabled);
  }

  function feedTime(ts) {
    return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  function renderFeed() {
    $("feed").innerHTML = feedRows.length
      ? feedRows.map((r) => `<div class="feed-row k-${esc(r.kind)}"><time>${feedTime(r.ts)}</time>${esc(r.text)}</div>`).join("")
      : '<p class="muted">Alerts, redeems, commands and errors show up here.</p>';
  }

  async function pollLive() {
    try {
      const [s, f] = await Promise.all([call("/phone/api/summary"), admin("/activity?after=" + feedLast)]);
      renderSummary(s);
      if ((f.last || 0) < feedLast) { feedLast = 0; feedRows = []; }
      (f.items || []).forEach((it) => feedRows.unshift(it));
      feedRows = feedRows.slice(0, FEED_MAX);
      feedLast = Math.max(feedLast, f.last || 0);
      if ((f.items || []).length || !$("feed").children.length) renderFeed();
    } catch (_) {}
  }

  const CREDITS = {
    roll: { playing: true, mode: "loop", freeze: true, restart: true },
    once: { mode: "once", playing: true, freeze: true, restart: true },
    loop: { mode: "loop", playing: true, restart: true },
    live: { freeze: false, playing: true },
  };
  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("button");
    if (!b || b.classList.contains("hold") || document.body.classList.contains("offline")) return;
    try {
      if (b.dataset.act === "hl-next") { await admin("/highlight/next", {}); toast("Next"); }
      else if (b.dataset.act === "hl-clear") { await admin("/highlight/clear", {}); toast("Cleared"); }
      else if (b.dataset.stage) { await admin("/stage", { action: "curtain", value: b.dataset.stage }); toast("Curtain: " + b.textContent); }
      else if (b.dataset.credits) {
        const c = b.dataset.credits;
        const body = c === "pause" ? { playing: !(summary.credits && summary.credits.play && summary.credits.play.playing !== false) } : CREDITS[c];
        const res = await admin("/credits/play", body);
        toast(res.warning || "Credits: " + b.textContent);
      } else if (b.dataset.fun) {
        const [feature, action] = b.dataset.fun.split("/");
        const res = await admin("/chat_games/action", { feature, action });
        toast(res.message || res.error || b.textContent);
      } else return;
      pollLive();
    } catch (e) {
      if (e.message !== "not paired") toast(e.message);
    }
  });
  document.querySelectorAll("button.hold[data-fun]").forEach((b) => holdButton(b, async () => {
    const [feature, action] = b.dataset.fun.split("/");
    try { await admin("/chat_games/action", { feature, action }); toast("Done"); } catch (e) { toast(e.message); }
  }));

  // ── Chat ──

  function lineHtml(r, i) {
    const plat = String(r.platform || "");
    return `<div class="line${r.flagged ? " flagged" : ""}${r.is_paid ? " paid" : ""}" data-i="${i}">` +
      `<span class="plat plat-${esc(plat)}">${esc(plat.slice(0, 1).toUpperCase())}</span>` +
      (r.flagged ? "🚩 " : "") + `<span class="who">${esc(who(r))}</span>${esc(text(r.message))}</div>`;
  }
  function renderChat() {
    const box = $("chat");
    box.innerHTML = chatRows.map(lineHtml).join("") || '<p class="muted">Chat shows up here as it comes in.</p>';
    if (followChat) box.scrollTop = box.scrollHeight;
  }
  async function pollChat() {
    try {
      const d = await admin(`/highlight/recent?after=${chatLast}&limit=${CHAT_MAX}`);
      if (d.reset) chatRows = [];
      chatRows = chatRows.concat(d.items || []).slice(-CHAT_MAX);
      chatLast = d.last || 0;
      if (d.reset || (d.items || []).length) renderChat();
    } catch (_) {}
  }
  $("chat").addEventListener("scroll", () => {
    const box = $("chat");
    followChat = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    $("chat-live").hidden = followChat;
  });
  $("chat-live").onclick = () => { followChat = true; $("chat-live").hidden = true; renderChat(); };
  $("chat").addEventListener("click", (ev) => {
    const el = ev.target.closest(".line");
    if (el) openLine(chatRows[Number(el.dataset.i)]);
  });

  // ── the menu for one line / person ──

  function openSheet(title, html) {
    $("sheet-title").innerHTML = title;
    $("sheet-body").innerHTML = html;
    $("sheet").hidden = false;
  }
  function closeSheet() { $("sheet").hidden = true; }
  $("sheet-close").onclick = closeSheet;
  $("sheet").addEventListener("click", (ev) => { if (ev.target === $("sheet")) closeSheet(); });

  // The Core account (People row) of a chat line's chatter: found by platform user id, then name.
  async function findPerson(r) {
    const u = r.user || {};
    const want = (String(r.platform) + ":" + String(u.username || "")).toLowerCase();
    for (const q of [u.id, u.username]) {
      if (!q) continue;
      const rows = await admin("/users?q=" + encodeURIComponent(q) + "&limit=20");
      const hit = rows.find((p) => String(p.accounts || "").toLowerCase().split(", ").includes(want));
      if (hit) return hit;
    }
    return null;
  }

  async function changePoints(person, delta) {
    const res = await admin(`/users/${person.id}/points`, { delta, reason: "phone remote" });
    const total = res && res.balance != null ? res.balance : "";
    toast(`${delta > 0 ? "+" : ""}${delta} for ${person.display_name}${total !== "" ? ` (now ${total})` : ""}`, async () => {
      try { await admin(`/users/${person.id}/points`, { delta: -delta, reason: "phone remote undo" }); toast("Undone"); }
      catch (e) { toast(e.message); }
    });
  }

  function pointsButtons(prefix) {
    return `<h3>Points</h3><div class="row wrap">` +
      `<button type="button" class="big" data-pts="100">+100</button>` +
      `<button type="button" class="big" data-pts="500">+500</button>` +
      `<button type="button" class="big hold" data-pts="-100"><span>Hold: −100</span></button>` +
      `<button type="button" class="big" data-pts="custom">Other…</button></div>`;
  }
  function wirePoints(getPerson) {
    $("sheet-body").querySelectorAll("[data-pts]").forEach((b) => {
      const go = async () => {
        let delta = b.dataset.pts === "custom" ? Number(prompt("How many points? (minus to take)", "250")) : Number(b.dataset.pts);
        if (!Number.isFinite(delta) || !delta) return;
        if (delta < 0 && b.dataset.pts === "custom" && !confirm(`Take ${-delta} points?`)) return;
        try {
          const p = await getPerson();
          if (!p) { toast("They have no points account yet"); return; }
          await changePoints(p, Math.trunc(delta));
          closeSheet();
        } catch (e) { toast(e.message); }
      };
      if (b.classList.contains("hold")) holdButton(b, go); else b.onclick = go;
    });
  }

  async function openLine(r) {
    if (!r) return;
    const u = r.user || {};
    const name = who(r);
    openSheet(`<span class="who">${esc(name)}</span><span class="muted">${esc(r.platform)}</span><div>${esc(text(r.message))}</div>`,
      (r.flagged ? '<p class="muted">Red-flagged: stays off stream.</p>'
        : '<button type="button" class="big primary" id="s-hl">★ Highlight on stream</button>' +
          '<button type="button" class="big" id="s-reply">Reply</button>') +
      pointsButtons() +
      '<h3>Reactions</h3><div class="row wrap" id="s-rx"><span class="muted">Loading…</span></div>' +
      (r.flagged ? "" : '<h3>Moderation</h3><button type="button" class="big hold danger" id="s-flag"><span>Hold: red-flag ' + esc(name) + "</span></button>"));
    if ($("s-hl")) $("s-hl").onclick = async () => {
      try {
        const res = await admin("/highlight", { platform: r.platform, message_id: r.message_id || "", message: r.message, user: u });
        toast(res.on_screen ? "On screen" : `Queued (${res.queue_len} waiting)`);
        closeSheet();
        pollLive();
      } catch (e) { toast(e.message); }
    };
    if ($("s-reply")) $("s-reply").onclick = async () => {
      const msg = prompt("Reply to " + name, "@" + name + " ");
      if (!msg || !msg.trim()) return;
      try {
        await call("/phone/api/reply", { method: "POST", body: JSON.stringify({ platform: r.platform, message: msg,
          reply_to_user: u.username || name, reply_to_message_id: r.message_id || "" }) });
        toast("Sent");
        closeSheet();
      } catch (e) { toast(e.message); }
    };
    if ($("s-flag")) holdButton($("s-flag"), async () => {
      try {
        await admin("/red-flags/flag", { name: u.username || name, platform: r.platform,
          platform_user_id: u.id || "", display_name: u.display_name || name });
        toast(name + " is red-flagged");
        closeSheet();
      } catch (e) { toast(e.message); }
    });
    let person;
    wirePoints(async () => (person === undefined ? (person = await findPerson(r)) : person));
    try {
      if (!reactionsList) reactionsList = (await call("/phone/api/reactions")).reactions || [];
      const box = $("s-rx");
      if (!box) return;
      box.innerHTML = reactionsList.length
        ? reactionsList.map((x) => `<button type="button" class="big" data-rx="${esc(x.id)}">${esc(x.label)}</button>`).join("")
        : '<span class="muted">No reactions are switched on.</span>';
      box.querySelectorAll("[data-rx]").forEach((b) => b.onclick = async () => {
        try {
          await admin("/reactions/test", { id: b.dataset.rx, target: u.username || name, platform: r.platform, username: "Streamer" });
          toast(b.textContent + " → " + name);
        } catch (e) { toast(e.message); }
      });
    } catch (_) {}
  }

  // ── People ──

  let peopleTimer = 0;
  $("people-q").addEventListener("input", () => {
    clearTimeout(peopleTimer);
    peopleTimer = setTimeout(loadPeople, 300);
  });
  async function loadPeople() {
    const q = $("people-q").value.trim();
    try {
      const rows = await admin("/users?limit=30" + (q ? "&q=" + encodeURIComponent(q) : ""));
      $("people").innerHTML = rows.length ? rows.map((p, i) =>
        `<div class="person" data-i="${i}"><span class="name">${esc(p.display_name)}<br><span class="muted">${esc(p.accounts || "")}</span></span>` +
        `<span class="pts">${Number(p.points) || 0}</span></div>`).join("") : '<p class="muted">Nobody found.</p>';
      $("people").querySelectorAll(".person").forEach((el) => el.onclick = () => {
        const p = rows[Number(el.dataset.i)];
        openSheet(`<span class="who">${esc(p.display_name)}</span><span class="muted">${Number(p.points) || 0} points</span>`, pointsButtons());
        wirePoints(async () => p);
      });
    } catch (_) {}
  }
  async function loadFlagged() {
    try {
      const rows = (await call("/phone/api/flagged")).flagged || [];
      $("flagged").innerHTML = rows.length ? rows.map((r) =>
        `<div class="person"><span class="name">${esc(r.display_name || r.username)} <span class="muted">${esc(r.platform || "every platform")}</span></span>` +
        `<button type="button" class="big hold" data-unflag="${Number(r.id)}"><span>Hold: unflag</span></button></div>`).join("")
        : '<p class="muted">Nobody.</p>';
      $("flagged").querySelectorAll("[data-unflag]").forEach((b) => holdButton(b, async () => {
        try { await admin("/red-flags/" + b.dataset.unflag, {}, "DELETE"); toast("Unflagged (their new chat shows again)"); loadFlagged(); }
        catch (e) { toast(e.message); }
      }));
    } catch (_) {}
  }

  // ── tabs, timers, start ──

  document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
    tab = b.dataset.tab;
    document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    ["live", "chat", "people"].forEach((t) => { $("tab-" + t).hidden = t !== tab; });
    if (tab === "chat") { followChat = true; renderChat(); }
    if (tab === "people") { loadPeople(); loadFlagged(); }
  });

  let started = false;
  async function start() {
    try {
      const me = await call("/phone/api/me");
      $("me").textContent = me.name;
    } catch (e) {
      if (e.message !== "not paired") showPair(e.message);
      return;
    }
    $("pair").hidden = true;
    $("app").hidden = false;
    if (started) return;
    started = true;
    pollLive();
    pollChat();
    setInterval(() => { if (!document.hidden) pollLive(); }, SUMMARY_MS);
    setInterval(() => { if (!document.hidden) pollChat(); }, CHAT_MS);
  }

  if (pairToken && !key) {
    // came from the QR code: no code to type, just a name
    showPair("Give this phone a name and press Pair.");
    $("pair-code").closest("label").hidden = true;
    $("pair-name").focus();
  }
  else if (!key) showPair("");
  else start();
})();
