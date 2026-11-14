/*
 * Discord & video requests page of the dashboard (#discord, <section id="tab-discord"> in index.html)
 * and the "Video requests" card on Live controls (#live-vr-card).
 *
 * Core does the work (core/discord_bot.py logs in as the streamer's own bot; core/video_requests.py
 * keeps the queue); this file edits the settings and runs the buttons. Routes (api/video_request_routes.py,
 * admin token in X-Admin-Token like admin.js):
 *   GET  /api/admin/video-requests                  {queue, discord: {settings (token hidden), status}}
 *   PUT  /api/admin/video-requests/settings         Save ({discord, video_requests})
 *   POST /api/admin/video-requests/connect          {on}
 *   GET  /api/admin/video-requests/discord/server   {channels, roles} for the Channels tab
 *   POST /api/admin/video-requests/add | approve | deny | play | skip | remove | move | pause
 *
 * admin.js calls window.DiscordPage.open() when the page opens and window.DiscordPage.openLive() when
 * Live controls opens. Both refresh every POLL_MS while their page shows.
 * Form fields: dc-<key> for the discord: block, vr-<key> for video_requests: (minutes on the page,
 * seconds in config for max_seconds / deny_cooldown_sec). Keep in step with the two DEFAULTS in Python.
 */
(() => {
  const $ = (id) => document.getElementById(id);
  const tokenKey = "stream_core_admin_token";   // same localStorage key as admin.js
  const POLL_MS = 3000;
  const BASE = "/api/admin/video-requests";
  const STATE_WORDS = { off: "Not connected.", connecting: "Connecting…", online: "Online.", error: "Problem:" };

  let loaded = null;       // last GET answer
  let dirty = false;
  let pageTimer = 0;
  let liveTimer = 0;
  let serverFor = "";      // guild id whose channels / roles are in the dropdowns
  let server = { channels: [], roles: [] };

  // ── helpers ──
  function token() {
    return localStorage.getItem(tokenKey) || ($("token") ? $("token").value.trim() : "");
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  async function call(path, opts = {}) {
    const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Admin-Token": token(), ...(opts.headers || {}) } });
    if (!res.ok) {
      let msg = res.statusText || "HTTP " + res.status;
      try {
        const j = await res.json();
        if (j && typeof j.detail === "string") msg = j.detail;
      } catch (_) { /* not JSON */ }
      throw new Error(msg);
    }
    return res.json();
  }
  const post = (path, body) => call(BASE + path, { method: "POST", body: JSON.stringify(body || {}) });
  function say(id, text, bad) {
    const el = $(id);
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("error", !!bad);
  }
  function fmtLen(sec) {
    if (sec == null) return "length unknown";
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
  }
  function showing(id) {
    const p = $(id);
    return !!(p && p.classList.contains("active"));
  }

  // ── Setup page: tabs ──
  const TABS = ["bot", "channels", "rules", "player"];
  function showTab(name) {
    if (!TABS.includes(name)) name = "bot";
    document.querySelectorAll("#tab-discord [data-dc-tab]").forEach((el) => { el.hidden = el.dataset.dcTab !== name; });
    document.querySelectorAll("#tab-discord [data-dc-show]").forEach((b) => {
      b.classList.toggle("active", b.dataset.dcShow === name);
      b.setAttribute("aria-selected", String(b.dataset.dcShow === name));
    });
    try { localStorage.setItem("stream_core_discord_tab", name); } catch (_) { /* private window */ }
  }

  // ── Setup page: fill / read the form ──
  function statusLine(st) {
    const word = STATE_WORDS[st.state] || "";
    return st.state === "error" ? `⚠ ${st.text}` : `${st.state === "online" ? "🟢" : st.state === "connecting" ? "🟡" : "⚪"} ${st.text || word}`;
  }
  function stripHtml(data) {
    const st = data.discord.status || {};
    const q = data.queue || {};
    const s = q.settings || {};
    const bits = [esc(statusLine(st))];
    bits.push(s.enabled ? "Requests <strong>on</strong>" : "Requests off");
    bits.push(`${(q.pending || []).length} waiting, ${(q.approved || []).length} approved`);
    bits.push(s.play_on === "rooms" ? "Plays in Stream Rooms (downloaded)" : "Plays on the video player page");
    return bits.join(' <span class="muted">·</span> ');
  }
  function setVal(id, v) {
    const el = $(id);
    if (!el || document.activeElement === el) return;
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = v == null ? "" : v;
  }
  function fillSelect(id, rows, current, none) {
    const el = $(id);
    if (!el) return;
    const opts = [`<option value="">${esc(none)}</option>`].concat(rows.map((r) => `<option value="${esc(r.id)}">${esc(r.name)}</option>`));
    if (current && !rows.some((r) => r.id === current)) opts.push(`<option value="${esc(current)}">(saved: ${esc(current)})</option>`);
    el.innerHTML = opts.join("");
    el.value = current || "";
  }
  function fillRoles(id, roles, ticked) {
    const el = $(id);
    if (!el) return;
    el.innerHTML = roles.length
      ? roles.map((r) => `<label class="check"><input type="checkbox" value="${esc(r.id)}"${ticked.includes(r.id) ? " checked" : ""}> ${esc(r.name)}</label>`).join("")
      : '<span class="muted">(connect the bot and pick a server to list its roles)</span>';
  }
  function fillForm(data) {
    const d = data.discord.settings || {};
    const st = data.discord.status || {};
    const s = (data.queue || {}).settings || {};
    $("dc-token-note").textContent = d.token_set ? "A token is saved. Paste a new one only to replace it." : "No token saved yet.";
    $("dc-token-clear-row").hidden = !d.token_set;
    const guilds = st.guilds || [];
    fillSelect("dc-guild_id", guilds, d.guild_id, guilds.length ? "Pick your server" : "(connect the bot first)");
    fillSelect("dc-request_channel_id", server.channels, d.request_channel_id, "(none: requests only from the Live card)");
    fillSelect("dc-mod_channel_id", server.channels, d.mod_channel_id, "(none)");
    setVal("dc-clean_channel", d.clean_channel);
    fillRoles("dc-approver_role_ids", server.roles, d.approver_role_ids || []);
    fillRoles("dc-requester_role_ids", server.roles, d.requester_role_ids || []);
    setVal("vr-enabled", s.enabled);
    setVal("vr-max_minutes", Math.round((s.max_seconds || 0) / 60));
    setVal("vr-per_person", s.per_person);
    setVal("vr-repeats", s.repeats);
    setVal("vr-deny_cooldown_min", Math.round((s.deny_cooldown_sec || 0) / 60));
    setVal("vr-blocked_words", (s.blocked_words || []).join(", "));
    setVal("vr-bot_replies", s.bot_replies);
    setVal("vr-now_playing_post", s.now_playing_post);
    setVal("vr-auto_play", s.auto_play);
    setVal("vr-player_volume", s.player_volume);
    setVal("vr-title_seconds", s.title_seconds);
    setVal("vr-show_title", s.show_title);
    document.querySelectorAll('input[name="vr-play_on"]').forEach((r) => { r.checked = r.value === (s.play_on || "player"); });
  }
  function readRoles(id) {
    return [...document.querySelectorAll(`#${id} input:checked`)].map((i) => i.value);
  }
  function readForm() {
    const num = (id) => Number($(id).value || 0);
    const playOn = document.querySelector('input[name="vr-play_on"]:checked');
    const discord = {
      guild_id: $("dc-guild_id").value, request_channel_id: $("dc-request_channel_id").value,
      mod_channel_id: $("dc-mod_channel_id").value, clean_channel: $("dc-clean_channel").checked,
      token_clear: $("dc-token-clear").checked,
    };
    // roles only when this page has the server's list (else the saved ones stay as they are)
    if (server.roles.length) {
      discord.approver_role_ids = readRoles("dc-approver_role_ids");
      discord.requester_role_ids = readRoles("dc-requester_role_ids");
    }
    const tok = $("dc-token").value.trim();
    if (tok) discord.token = tok;
    return {
      discord,
      video_requests: {
        enabled: $("vr-enabled").checked, max_seconds: num("vr-max_minutes") * 60, per_person: num("vr-per_person"),
        repeats: $("vr-repeats").value, deny_cooldown_sec: num("vr-deny_cooldown_min") * 60,
        blocked_words: $("vr-blocked_words").value.split(",").map((w) => w.trim()).filter(Boolean),
        bot_replies: $("vr-bot_replies").checked, now_playing_post: $("vr-now_playing_post").checked,
        auto_play: $("vr-auto_play").checked, player_volume: num("vr-player_volume"), title_seconds: num("vr-title_seconds"),
        show_title: $("vr-show_title").checked, play_on: playOn ? playOn.value : "player",
      },
    };
  }

  function renderPage(data, fill) {
    loaded = data;
    $("dc-strip").innerHTML = stripHtml(data);
    const st = data.discord.status || {};
    $("dc-state").textContent = statusLine(st);
    $("dc-state").classList.toggle("error", st.state === "error");
    const inv = $("dc-invite");
    inv.hidden = !st.invite;
    if (st.invite) inv.href = st.invite;
    if (fill) fillForm(data);
    const guild = (data.discord.settings || {}).guild_id;
    if (st.state === "online" && guild && guild !== serverFor) loadServer(guild);
  }

  async function loadServer(guildId) {
    if (!guildId) return;
    serverFor = guildId;
    try {
      server = await call(`${BASE}/discord/server?guild_id=${encodeURIComponent(guildId)}`);
      if (loaded) fillForm(loaded);
    } catch (e) {
      serverFor = "";
      say("dc-msg", "Couldn't list the server's channels: " + e.message, true);
    }
  }

  async function refresh(fill) {
    try {
      renderPage(await call(BASE), fill);
    } catch (e) {
      say("dc-msg", e.message, true);
    }
  }

  async function save(connect) {
    say("dc-msg", "Saving…");
    try {
      const data = await call(BASE + "/settings", { method: "PUT", body: JSON.stringify(readForm()) });
      $("dc-token").value = "";
      $("dc-token-clear").checked = false;
      dirty = false;
      let out = data;
      if (connect) out = await post("/connect", { on: true });
      renderPage(out, true);
      say("dc-msg", connect ? "Saved. Connecting to Discord…" : "Saved.");
    } catch (e) {
      say("dc-msg", e.message, true);
    }
  }

  // ── Live card ──
  function rowHtml(item, kind) {
    const thumb = item.thumb ? `<img src="${esc(item.thumb)}" alt="" loading="lazy">` : "";
    const meta = `${esc(fmtLen(item.length))} · from ${esc(item.by)}${item.source === "discord" ? " (Discord)" : ""}`;
    let buttons = "";
    if (kind === "pending") {
      buttons = `<button type="button" data-vr="approve" data-id="${item.id}" class="primary">Approve</button>
        <button type="button" data-vr="play" data-id="${item.id}">Play now</button>
        <select data-vr-reason="${item.id}" title="Reason the bot gives (optional)"><option value="">No reason</option>${(loaded.queue.deny_reasons || []).map((r) => `<option>${esc(r)}</option>`).join("")}</select>
        <button type="button" data-vr="deny" data-id="${item.id}">Deny</button>`;
    } else if (kind === "approved") {
      buttons = `<button type="button" data-vr="play" data-id="${item.id}" class="primary">Play now</button>
        <button type="button" data-vr="up" data-id="${item.id}" title="Earlier">↑</button>
        <button type="button" data-vr="down" data-id="${item.id}" title="Later">↓</button>
        <button type="button" data-vr="remove" data-id="${item.id}" title="Take it out without telling anyone">✕</button>`;
    } else {
      const words = { played: "Played", denied: "Denied", skipped: "Skipped", failed: "Couldn't play" };
      buttons = `<span class="muted">${esc(words[item.status] || item.status)}${item.reason ? ": " + esc(item.reason) : ""}</span>`;
    }
    return `<div class="vr-row">${thumb}<div class="vr-info"><a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.title)}</a>
      <small>${meta}</small></div><div class="vr-btns">${buttons}</div></div>`;
  }

  function renderLive(data) {
    loaded = data;
    const q = data.queue || {};
    const s = q.settings || {};
    const card = $("live-vr-card");
    if (!card) return;
    card.hidden = !s.enabled;
    if (!s.enabled) return;
    const st = data.discord.status || {};
    $("live-vr-state").textContent = st.state === "online" ? "Discord bot online" : st.state === "error" ? "⚠ Discord: " + st.text : "Discord bot not connected";
    const cur = q.playing;
    let now = '<p class="muted">Nothing playing.</p>';
    if (cur) {
      let extra = "";
      if (s.play_on === "rooms" && q.rooms_job && /download|convert/.test(q.rooms_job.state)) extra = ` <span class="muted">(Stream Rooms: ${esc(q.rooms_job.text || "getting it ready…")})</span>`;
      now = `<div class="vr-playing">▶ <strong>${esc(cur.title)}</strong> <span class="muted">${esc(fmtLen(cur.length))} · from ${esc(cur.by)}</span>${extra}</div>`;
    }
    $("live-vr-now").innerHTML = now;
    $("live-vr-pause").setAttribute("aria-pressed", String(!!q.player_paused));
    $("live-vr-pause").textContent = q.player_paused ? "Resume" : "Pause";
    $("live-vr-pause").hidden = s.play_on === "rooms";
    if (document.activeElement !== $("live-vr-auto")) $("live-vr-auto").checked = !!s.auto_play;
    const pending = q.pending || [];
    const approved = q.approved || [];
    $("live-vr-pending-n").textContent = pending.length ? `(${pending.length})` : "";
    $("live-vr-approved-n").textContent = approved.length ? `(${approved.length})` : "";
    // don't redraw a list while someone is choosing a deny reason in it
    if (!(document.activeElement && document.activeElement.matches("#live-vr-pending select"))) {
      $("live-vr-pending").innerHTML = pending.length ? pending.map((i) => rowHtml(i, "pending")).join("") : '<p class="muted">None waiting.</p>';
    }
    $("live-vr-approved").innerHTML = approved.length ? approved.map((i) => rowHtml(i, "approved")).join("") : '<p class="muted">Nothing approved yet.</p>';
    $("live-vr-history").innerHTML = (q.history || []).map((i) => rowHtml(i, "history")).join("") || '<p class="muted">Nothing yet.</p>';
  }

  async function refreshLive() {
    try {
      renderLive(await call(BASE));
    } catch (_) { /* Core restarting: next poll */ }
  }

  async function act(path, body, okText) {
    try {
      const data = await post(path, body);
      renderLive(data);
      say("live-vr-msg", okText || "");
    } catch (e) {
      say("live-vr-msg", e.message, true);
    }
  }

  // ── wiring ──
  function wire() {
    document.querySelectorAll("#tab-discord [data-dc-show]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.dcShow)));
    let tab = "bot";
    try { tab = localStorage.getItem("stream_core_discord_tab") || "bot"; } catch (_) { /* private window */ }
    showTab(tab);
    $("tab-discord").addEventListener("input", () => { dirty = true; });
    $("tab-discord").addEventListener("change", () => { dirty = true; });
    $("dc-save").addEventListener("click", () => save(false));
    $("dc-connect").addEventListener("click", () => save(true));
    $("dc-disconnect").addEventListener("click", async () => {
      try { renderPage(await post("/connect", { on: false }), true); say("dc-msg", "Disconnected."); } catch (e) { say("dc-msg", e.message, true); }
    });
    $("dc-guild_id").addEventListener("change", () => { server = { channels: [], roles: [] }; loadServer($("dc-guild_id").value); });
    $("dc-reload-server").addEventListener("click", () => loadServer($("dc-guild_id").value));
    const base = location.origin + "/overlay/video-player.html";
    $("vr-link-obs").value = base;
    $("vr-link-tab").value = base + "?bg=black";
    document.querySelectorAll("#tab-discord [data-copy]").forEach((b) => b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText($(b.dataset.copy).value); b.textContent = "Copied ✓"; setTimeout(() => { b.textContent = "Copy"; }, 1500); } catch (_) { $(b.dataset.copy).select(); }
    }));

    // Live card buttons
    $("live-vr-next").addEventListener("click", () => act("/play", {}, "Playing the next video."));
    $("live-vr-skip").addEventListener("click", () => act("/skip", {}, "Skipped."));
    $("live-vr-pause").addEventListener("click", () => act("/pause", { on: $("live-vr-pause").getAttribute("aria-pressed") !== "true" }));
    $("live-vr-auto").addEventListener("change", async () => {
      try {
        renderLive(await call(BASE + "/settings", { method: "PUT", body: JSON.stringify({ video_requests: { auto_play: $("live-vr-auto").checked } }) }));
      } catch (e) { say("live-vr-msg", e.message, true); }
    });
    $("live-vr-add").addEventListener("click", async () => {
      const url = $("live-vr-url").value.trim();
      if (!url) return $("live-vr-url").focus();
      say("live-vr-msg", "Checking the video…");
      await act("/add", { url }, "Added to Up next.");
      $("live-vr-url").value = "";
    });
    $("live-vr-card").addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-vr]");
      if (!b) return;
      const id = Number(b.dataset.id);
      const what = b.dataset.vr;
      if (what === "approve") act("/approve", { id }, "Approved.");
      else if (what === "play") act("/play", { id }, "Playing now.");
      else if (what === "deny") {
        const sel = document.querySelector(`[data-vr-reason="${id}"]`);
        act("/deny", { id, reason: sel ? sel.value : "" }, "Denied.");
      } else if (what === "remove") act("/remove", { id }, "Removed.");
      else if (what === "up" || what === "down") act("/move", { id, step: what === "up" ? -1 : 1 });
    });
  }

  function open() {
    refresh(!dirty);
    clearInterval(pageTimer);
    pageTimer = setInterval(() => {
      if (showing("tab-discord")) refresh(false);
      else clearInterval(pageTimer);
    }, POLL_MS);
  }
  function openLive() {
    refreshLive();
    clearInterval(liveTimer);
    liveTimer = setInterval(() => {
      if (showing("tab-live")) refreshLive();
      else clearInterval(liveTimer);
    }, POLL_MS);
  }

  if ($("tab-discord")) wire();
  window.DiscordPage = { open, openLive, isDirty: () => dirty };
})();
