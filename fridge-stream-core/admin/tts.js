/*
 * Read aloud (TTS) page of the dashboard (#tts, <section id="tab-tts"> in index.html) and the
 * "Read aloud" card on Live controls (#live-tts-card). Core sends lines to the streamer's own
 * text-to-speech server (core/tts.py); this file only edits the settings and runs the buttons.
 *
 * Routes (api/tts_routes.py, admin token in X-Admin-Token like admin.js):
 *   GET  /api/admin/tts                settings (key hidden), status, missed, recent
 *   PUT  /api/admin/tts/settings       Save
 *   POST /api/admin/tts/check          Check connection          POST /api/admin/tts/test  Play here
 *   POST /api/admin/tts/say            Send to overlay           POST /api/admin/tts/filter-test
 *   POST /api/admin/tts/fake           pretend !tts / chat line  POST /api/admin/tts/skip | clear
 *   POST /api/admin/tts/pretend-down   POST /api/admin/tts/missed/replay | remove
 *
 * Work list item 19 added: tabs across the page (Server, Voice, What's read, Blocked, Test; each
 * block says its tab in data-tts-tab), a status strip, Blocked chatters (GET /tts/blocked, POST
 * /tts/block | /tts/unblock), "A longer line is" cut / not read (long_lines), and on the Live card
 * the line reading now and the next ones (✕ = POST /tts/drop), Pause (POST /tts/pause), "Off for N
 * min" with its countdown (POST /tts/quiet) and quick on/off switches for each trigger.
 *
 * admin.js calls window.TtsPage.open() when the page opens and window.TtsPage.openLive() when
 * Live controls opens (activateTab). Both refresh every POLL_MS while their page is showing.
 * TRIGGERS below must match core/tts.py DEFAULTS["triggers"] (names and fields).
 */
(() => {
  const $ = (id) => document.getElementById(id);
  // Same localStorage key as admin.js: the admin token saved in this browser.
  const tokenKey = "stream_core_admin_token";
  const POLL_MS = 4000;
  // Words for the status light (core/tts.py TtsEngine.status "state").
  const STATE_WORDS = {
    off: "Read aloud is off.",
    no_server: "On, but no server address yet.",
    unknown: "On. Not tried yet: press Check connection.",
    ok: "Server answering.",
    trouble: "Server failed on the last try.",
    down: "Server down: lines are skipped and Core checks again every 30 s.",
  };
  const WHO = [["everyone", "Everyone"], ["subs", "Subs, VIPs and mods"], ["vips", "VIPs and mods"], ["mods", "Mods only"]];
  // One row per trigger: [key, title, what it reads, extra fields]. Field: [setting, label, type, extra].
  const TRIGGERS = [
    ["alerts", "Alerts", "Follows, subs, resubs, gifted subs, raids, memberships …", [["template", "Wording", "text"]]],
    ["paid", "Paid messages", "Super Chats, bits, KICKs, tips, power-ups …", [["template", "Wording", "text"],
      ["min_amount", "Smallest amount (bits and KICKs: 100 = 1)", "number", { min: 0, step: 0.5 }]]],
    ["command", "The !tts command", "A chatter types !tts and a message", [["word", "Command word", "text"],
      ["cost", "Points it costs", "number", { min: 0, step: 10 }], ["cooldown_sec", "Each chatter waits (seconds)", "number", { min: 0, step: 5 }],
      ["who", "Who can use it", "who"], ["template", "Wording", "text"]]],
    ["chat", "Chat lines", "Ordinary chat lines (not commands, not paid ones)", [["who", "Whose lines", "who"],
      ["every_nth", "Read 1 line in every", "number", { min: 1, step: 1 }], ["min_gap_sec", "At least (seconds) between lines", "number", { min: 0, step: 1 }],
      ["template", "Wording", "text"]]],
    ["highlight", "Highlighted message", "The chat line you put on the lower third", [["template", "Wording", "text"]]],
    ["plugins", "Game plugins", "Lines a game plugin asks Core to say", []],
  ];

  let loaded = null;        // last GET /api/admin/tts
  let dirty = false;
  let pageTimer = 0;
  let liveTimer = 0;
  let built = false;

  // ── Helpers ─────────────────────────────────────────────────────────────
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
    return opts.raw ? res : res.json();
  }
  const post = (path, body) => call(path, { method: "POST", body: JSON.stringify(body || {}) });
  function say(id, text, bad) {
    const el = $(id);
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("tts-bad", !!bad);
  }
  function ago(t) {
    if (!t) return "";
    const s = Math.max(0, Math.round(Date.now() / 1000 - t));
    if (s < 60) return s + " s ago";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    return Math.round(s / 3600) + " h ago";
  }
  function lightHtml(st) {
    const state = (st && st.state) || "unknown";
    let words = STATE_WORDS[state] || state;
    if (st && st.pretend_down) words += " (pretending it is down)";
    if (st && state === "ok" && st.last_seconds) words += ` Last line took ${Number(st.last_seconds).toFixed(2)} s.`;
    if (st && (state === "trouble" || state === "down") && st.last_error) words += " " + st.last_error;
    return `<span class="tts-light" data-state="${esc(state)}" aria-hidden="true"></span> ${esc(words)}`;
  }

  // ── Build the trigger rows once ─────────────────────────────────────────
  function buildTriggers() {
    const box = $("tts-triggers");
    if (!box || built) return;
    built = true;
    box.innerHTML = TRIGGERS.map(([key, title, what, fields]) => {
      const extra = fields.map(([f, label, type, o]) => {
        const id = `tts-t-${key}-${f}`;
        if (type === "who") {
          return `<label>${esc(label)}<select id="${id}">` + WHO.map(([v, w]) => `<option value="${v}">${esc(w)}</option>`).join("") + "</select></label>";
        }
        const attrs = type === "number" ? ` type="number" min="${o.min}" step="${o.step}"` : ' type="text" maxlength="300"';
        return `<label>${esc(label)}<input id="${id}"${attrs} /></label>`;
      }).join("");
      return `<div class="tts-trigger" data-trigger="${key}">` +
        `<label class="check"><input id="tts-t-${key}-enabled" type="checkbox" /> <strong>${esc(title)}</strong> <span class="muted">${esc(what)}</span></label>` +
        `<div class="tts-trigger-fields"><label>Voice<input id="tts-t-${key}-voice" type="text" list="tts-voice-list" placeholder="main voice" autocomplete="off" /></label>${extra}</div></div>`;
    }).join("");
  }

  // ── Fill / read the form ────────────────────────────────────────────────
  function setVal(id, v) {
    const el = $(id);
    if (!el || document.activeElement === el) return;
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = v == null ? "" : v;
  }
  function fillForm(s) {
    const srv = s.server || {};
    setVal("tts-enabled", s.enabled);
    setVal("tts-url", srv.url);
    setVal("tts-backup-url", srv.backup_url);
    setVal("tts-api-key", "");
    setVal("tts-model", srv.model);
    setVal("tts-format", srv.format);
    setVal("tts-timeout", srv.timeout_sec);
    $("tts-key-note").textContent = srv.api_key_set ? "A key is saved (hidden). Type a new one to replace it." : "";
    // .cfg-card label.check sets display: flex, which beats the hidden attribute
    $("tts-key-clear-row").style.display = srv.api_key_set ? "" : "none";
    setVal("tts-api-key-clear", false);
    setVal("tts-voice", s.voice);
    setVal("tts-speed", s.speed);
    setVal("tts-volume", s.volume);
    setVal("tts-max-chars", s.max_chars);
    setVal("tts-long-lines", s.long_lines || "cut");
    setVal("tts-queue-max", s.queue_max);
    const f = s.filters || {};
    setVal("tts-blocked", Array.isArray(f.blocked) ? f.blocked.join("\n") : (f.blocked || ""));
    setVal("tts-on-match", f.on_match);
    setVal("tts-check-names", f.check_names);
    setVal("tts-use-red-flags", f.use_red_flags);
    setVal("tts-drop-links", f.drop_links);
    TRIGGERS.forEach(([key, , , fields]) => {
      const t = (s.triggers || {})[key] || {};
      setVal(`tts-t-${key}-enabled`, t.enabled);
      setVal(`tts-t-${key}-voice`, t.voice);
      fields.forEach(([field]) => setVal(`tts-t-${key}-${field}`, t[field]));
    });
  }
  function num(id) {
    const v = $(id).value.trim();
    return v === "" ? undefined : Number(v);
  }
  function readForm() {
    const server = {
      url: $("tts-url").value.trim(), backup_url: $("tts-backup-url").value.trim(), model: $("tts-model").value.trim(),
      format: $("tts-format").value, timeout_sec: num("tts-timeout"),
    };
    // the key is only sent when typed (Core keeps the saved one otherwise)
    if ($("tts-api-key").value.trim()) server.api_key = $("tts-api-key").value.trim();
    if ($("tts-api-key-clear").checked) server.api_key_clear = true;
    const triggers = {};
    TRIGGERS.forEach(([key, , , fields]) => {
      const t = { enabled: $(`tts-t-${key}-enabled`).checked, voice: $(`tts-t-${key}-voice`).value.trim() };
      fields.forEach(([field, , type]) => {
        const id = `tts-t-${key}-${field}`;
        t[field] = type === "number" ? num(id) : $(id).value.trim();
      });
      triggers[key] = t;
    });
    return {
      enabled: $("tts-enabled").checked, server, voice: $("tts-voice").value.trim(), speed: num("tts-speed"),
      volume: num("tts-volume"), max_chars: num("tts-max-chars"), queue_max: num("tts-queue-max"),
      long_lines: $("tts-long-lines").value,
      filters: {
        blocked: $("tts-blocked").value.split("\n").map((l) => l.trim()).filter(Boolean),
        on_match: $("tts-on-match").value, check_names: $("tts-check-names").checked,
        use_red_flags: $("tts-use-red-flags").checked, drop_links: $("tts-drop-links").checked,
      },
      triggers,
    };
  }

  // ── Status, missed, recent ──────────────────────────────────────────────
  function missedHtml(rows, limit) {
    if (!rows || !rows.length) return '<span class="muted">Nothing missed.</span>';
    return "<ul>" + rows.slice(0, limit || 50).map((m) =>
      `<li><span class="muted">${esc(ago(m.at))} · ${esc(m.trigger)}${m.refunded ? ` · ${m.refunded} points given back` : ""}</span><br>` +
      `${esc(m.text)} <span class="muted">(${esc(m.why)})</span><br>` +
      `<button type="button" data-tts-replay="${m.id}">Replay</button> <button type="button" data-tts-forget="${m.id}">Remove</button></li>`).join("") + "</ul>";
  }
  function recentHtml(rows) {
    if (!rows || !rows.length) return '<span class="muted">Nothing yet.</span>';
    return '<table class="data-table"><thead><tr><th>When</th><th>From</th><th>Line</th><th>Result</th><th>Server time</th></tr></thead><tbody>' +
      rows.map((r) => `<tr><td>${esc(ago(r.at))}</td><td>${esc(r.trigger)}</td><td>${esc(r.text)}</td>` +
        `<td class="tts-r-${esc(r.result)}">${esc(r.result)}${r.why ? ": " + esc(r.why) : ""}</td>` +
        `<td>${r.seconds ? esc(Number(r.seconds).toFixed(2)) + " s" : ""}</td></tr>`).join("") + "</tbody></table>";
  }
  const FOR_WORDS = { stream: "this stream", day: "a day", forever: "until unblocked" };
  function blockedHtml(rows) {
    if (!rows || !rows.length) return '<span class="muted">Nobody blocked.</span>';
    return "<ul>" + rows.map((b) => `<li><b>${esc(b.name)}</b> <span class="muted">${esc(b.platform || "any")} · ${esc(FOR_WORDS[b.for] || b.for)}` +
      `${b.until ? " · until " + esc(new Date(b.until * 1000).toLocaleString()) : ""}</span> ` +
      `<button type="button" class="link-btn" data-tts-unblock="${esc(b.key)}">Unblock</button></li>`).join("") + "</ul>";
  }
  /** "12:30 left" for the Off for N min countdown. */
  function left(until) {
    const sec = Math.max(0, Math.round(until - Date.now() / 1000));
    return Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
  }
  /** The strip over the page: the light, the line, paused / off, blocked count. */
  function stripHtml(data) {
    const st = data.status || {};
    const bits = [lightHtml(st)];
    if (st.queue_len) bits.push(`${st.queue_len} waiting`);
    if (st.paused) bits.push("<b>Paused</b>");
    if (st.quiet_until) bits.push(`<b>Off</b> for ${left(st.quiet_until)} more`);
    if (data.missed && data.missed.length) bits.push(`${data.missed.length} missed`);
    if (data.blocked && data.blocked.length) bits.push(`${data.blocked.length} chatter${data.blocked.length === 1 ? "" : "s"} blocked`);
    return bits.join(" <span class=\"muted\">·</span> ");
  }
  // Tabs across the page; the open one is remembered in this browser.
  const TABS = ["server", "voice", "read", "blocked", "test"];
  function showTab(name) {
    if (!TABS.includes(name)) name = "server";
    document.querySelectorAll("#tab-tts [data-tts-tab]").forEach((el) => { el.hidden = el.dataset.ttsTab !== name; });
    document.querySelectorAll("#tab-tts [data-tts-show]").forEach((b) => {
      b.classList.toggle("active", b.dataset.ttsShow === name);
      b.setAttribute("aria-selected", String(b.dataset.ttsShow === name));
    });
    try { localStorage.setItem("stream_core_tts_tab", name); } catch (_) { /* private window */ }
  }
  function renderState(data) {
    loaded = data;
    const st = data.status || {};
    if ($("tts-state")) $("tts-state").innerHTML = lightHtml(st);
    if ($("tts-strip")) $("tts-strip").innerHTML = stripHtml(data);
    if ($("tts-blocked-people")) $("tts-blocked-people").innerHTML = blockedHtml(data.blocked);
    setVal("tts-pretend-down", st.pretend_down);
    if ($("tts-missed")) $("tts-missed").innerHTML = missedHtml(data.missed);
    if ($("tts-missed-count")) $("tts-missed-count").textContent = data.missed && data.missed.length ? `(${data.missed.length})` : "";
    if ($("tts-recent")) $("tts-recent").innerHTML = recentHtml(data.recent);
    renderLive(data);
  }
  async function refresh(full) {
    if (!token()) return;
    try {
      const data = await call("/api/admin/tts");
      if (full || !dirty) {
        buildTriggers();
        fillForm(data.settings);
        dirty = false;
      }
      renderState(data);
    } catch (e) {
      say("tts-save-msg", String(e.message || e), true);
    }
  }

  // ── Live controls card ──────────────────────────────────────────────────
  function renderLive(data) {
    const card = $("live-tts-card");
    if (!card) return;
    const st = data.status || {};
    card.hidden = !st.enabled;
    if (!st.enabled) return;
    $("live-tts-light").innerHTML = lightHtml(st);
    $("live-tts-state").textContent = st.queue_len ? `${st.queue_len} waiting` : "";
    // reading now + the next lines, each with ✕
    const now = st.now;
    $("live-tts-now").innerHTML =
      (now ? `<div class="tts-reading"><span class="muted">Reading now</span> ${esc(now.text)}</div>` : "") +
      ((st.next || []).length ? '<ol class="tts-next">' + st.next.map((j) =>
        `<li>${esc(j.text)} <button type="button" class="link-btn" data-tts-drop="${j.id}" title="Take this line out">✕</button></li>`).join("") + "</ol>" : "");
    const pause = $("live-tts-pause");
    pause.textContent = st.paused ? "Resume" : "Pause";
    pause.setAttribute("aria-pressed", String(!!st.paused));
    $("live-tts-quiet").textContent = st.quiet_until ? "Back on now" : "Turn off";
    $("live-tts-quiet").dataset.on = st.quiet_until ? "1" : "";
    $("live-tts-quiet-left").textContent = st.quiet_until ? `off, ${left(st.quiet_until)} left` : "";
    // quick switches: each trigger on / off (saved at once, like the settings page's Save)
    const trig = ((data.settings || {}).triggers) || {};
    const sw = $("live-tts-switches");
    const sig = JSON.stringify(TRIGGERS.map(([k]) => !!(trig[k] || {}).enabled));
    if (sw.dataset.sig !== sig) {
      sw.dataset.sig = sig;
      sw.innerHTML = TRIGGERS.map(([key, title]) =>
        `<label class="check"><input type="checkbox" data-tts-switch="${key}"${(trig[key] || {}).enabled ? " checked" : ""} /> ${esc(title)}</label>`).join("");
    }
    const m = $("live-tts-missed");
    m.hidden = !(data.missed && data.missed.length);
    m.innerHTML = m.hidden ? "" : `<h4>Missed (${data.missed.length}) <button type="button" class="link-btn" data-tts-replay="">Replay all</button></h4>` + missedHtml(data.missed, 5);
  }
  async function refreshLive() {
    if (!token()) return;
    try {
      const data = await call("/api/admin/tts");
      loaded = loaded || data;
      loaded.status = data.status;
      renderLive(data);
    } catch (_) { /* the status line already says when Core can't be reached */ }
  }

  // ── Buttons ─────────────────────────────────────────────────────────────
  function on(id, fn) {
    const el = $(id);
    if (el) el.addEventListener("click", fn);
  }
  async function run(btnId, msgId, fn) {
    const btn = $(btnId);
    if (btn) btn.disabled = true;
    try {
      await fn();
    } catch (e) {
      say(msgId, String(e.message || e), true);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function wire() {
    const page = $("tab-tts");
    if (page) {
      page.addEventListener("input", (ev) => {
        if (ev.target.closest(".cfg-card") && ev.target.id !== "tts-pretend-down" && !/^tts-(test|filter|fake)-/.test(ev.target.id)) {
          dirty = true;
          say("tts-save-msg", "Not saved yet.");
        }
      });
    }
    on("tts-save", () => run("tts-save", "tts-save-msg", async () => {
      say("tts-save-msg", "Saving…");
      const data = await call("/api/admin/tts/settings", { method: "PUT", body: JSON.stringify(readForm()) });
      dirty = false;
      fillForm(data.settings);
      renderState(data);
      say("tts-save-msg", "Saved.");
    }));
    on("tts-check", () => run("tts-check", "tts-check-result", async () => {
      if (dirty) say("tts-check-result", "Checking the SAVED settings (press Save first to check your changes)…");
      else say("tts-check-result", "Checking…");
      const r = await post("/api/admin/tts/check");
      const list = $("tts-voice-list");
      if (list && r.voices && r.voices.length) list.innerHTML = r.voices.map((v) => `<option value="${esc(v)}"></option>`).join("");
      const voices = r.voices && r.voices.length ? ` It lists ${r.voices.length} voices (in the Voice boxes' drop-down).` : "";
      if (r.ok) say("tts-check-result", `Answered in ${Number(r.seconds).toFixed(2)} s with ${r.content_type || r.format} audio.${voices}`);
      else say("tts-check-result", `No audio: ${r.error}${voices}`, true);
      refresh(false);
    }));
    on("tts-test-play", () => run("tts-test-play", "tts-test-msg", async () => {
      say("tts-test-msg", "Asking your server…");
      const res = await call("/api/admin/tts/test", {
        method: "POST", raw: true,
        body: JSON.stringify({ text: $("tts-test-text").value, voice: $("tts-test-voice").value.trim() }),
      });
      const url = URL.createObjectURL(await res.blob());
      const audio = new Audio(url);
      audio.volume = Math.max(0, Math.min(1, (Number($("tts-volume").value) || 80) / 100));
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
      say("tts-test-msg", "Playing here.");
      refresh(false);
    }));
    on("tts-test-overlay", () => run("tts-test-overlay", "tts-test-msg", async () => {
      await post("/api/admin/tts/say", { text: $("tts-test-text").value, voice: $("tts-test-voice").value.trim() });
      say("tts-test-msg", "Sent: listen in OBS (the alerts overlay plays it).");
      setTimeout(() => refresh(false), 1500);
    }));
    on("tts-filter-run", () => run("tts-filter-run", "tts-filter-msg", async () => {
      const r = await post("/api/admin/tts/filter-test", { text: $("tts-filter-text").value, name: $("tts-filter-name").value });
      const name = r.name ? ` Name read as "${r.name}".` : "";
      if (r.why) say("tts-filter-msg", `Skipped: ${r.why}.${name}`, true);
      else say("tts-filter-msg", `Read as: "${r.text}"${name}`);
    }));
    const fake = (kind) => run(kind === "command" ? "tts-fake-command" : "tts-fake-chat", "tts-fake-msg", async () => {
      const r = await post("/api/admin/tts/fake", {
        kind, text: $("tts-fake-text").value, name: $("tts-fake-name").value, who: $("tts-fake-who").value,
      });
      if (!r.ok) say("tts-fake-msg", r.why || "Not read.", true);
      else say("tts-fake-msg", (r.answer ? `Core would answer in chat: ${r.answer} ` : "") + "Queued: listen in OBS.");
      setTimeout(() => refresh(false), 1500);
    });
    on("tts-fake-command", () => fake("command"));
    on("tts-fake-chat", () => fake("chat"));
    const pretend = $("tts-pretend-down");
    if (pretend) pretend.addEventListener("change", async () => {
      try {
        renderState({ ...(loaded || {}), status: (await post("/api/admin/tts/pretend-down", { on: pretend.checked })).status });
      } catch (e) { say("tts-save-msg", String(e.message || e), true); }
    });
    on("tts-replay-all", () => run("tts-replay-all", "tts-save-msg", async () => renderState(await post("/api/admin/tts/missed/replay", {}))));
    on("tts-forget-all", () => run("tts-forget-all", "tts-save-msg", async () => {
      if (!confirm("Remove every missed line?")) return;
      renderState(await post("/api/admin/tts/missed/remove", {}));
    }));
    // Replay / Remove buttons inside the missed lists (settings page and Live card)
    document.addEventListener("click", async (ev) => {
      const rep = ev.target.closest("[data-tts-replay]");
      const del = ev.target.closest("[data-tts-forget]");
      if (!rep && !del) return;
      const id = (rep || del).getAttribute(rep ? "data-tts-replay" : "data-tts-forget");
      try {
        renderState(await post(rep ? "/api/admin/tts/missed/replay" : "/api/admin/tts/missed/remove", id ? { id: Number(id) } : {}));
      } catch (e) { say("live-tts-msg", String(e.message || e), true); say("tts-save-msg", String(e.message || e), true); }
    });
    // tabs across the page
    document.querySelectorAll("#tab-tts [data-tts-show]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.ttsShow)));
    let saved = "server";
    try { saved = localStorage.getItem("stream_core_tts_tab") || "server"; } catch (_) { /* private window */ }
    showTab(saved);
    // Blocked chatters
    on("tts-block-add", () => run("tts-block-add", "tts-save-msg", async () => {
      const r = await post("/api/admin/tts/block", { name: $("tts-block-name").value.trim(), platform: $("tts-block-platform").value, for: $("tts-block-for").value });
      $("tts-blocked-people").innerHTML = blockedHtml(r.blocked);
      say("tts-save-msg", "Blocked " + $("tts-block-name").value.trim() + ".");
      $("tts-block-name").value = "";
    }));
    document.addEventListener("click", async (ev) => {
      const un = ev.target.closest("[data-tts-unblock]");
      const drop = ev.target.closest("[data-tts-drop]");
      const sw = ev.target.closest("[data-tts-switch]");
      try {
        if (un) {
          const r = await post("/api/admin/tts/unblock", { key: un.dataset.ttsUnblock });
          $("tts-blocked-people").innerHTML = blockedHtml(r.blocked);
        } else if (drop) {
          await post("/api/admin/tts/drop", { id: Number(drop.dataset.ttsDrop) });
          refreshLive();
        } else if (sw) {
          await call("/api/admin/tts/settings", { method: "PUT", body: JSON.stringify({ triggers: { [sw.dataset.ttsSwitch]: { enabled: sw.checked } } }) });
          say("live-tts-msg", (sw.checked ? "On: " : "Off: ") + sw.parentElement.textContent.trim());
        }
      } catch (e) { say("live-tts-msg", String(e.message || e), true); }
    });
    on("live-tts-pause", () => run("live-tts-pause", "live-tts-msg", async () => {
      const r = await post("/api/admin/tts/pause", { on: $("live-tts-pause").getAttribute("aria-pressed") !== "true" });
      say("live-tts-msg", r.status.paused ? "Paused: lines wait until Resume." : "Going on.");
      refreshLive();
    }));
    on("live-tts-quiet", () => run("live-tts-quiet", "live-tts-msg", async () => {
      const off = $("live-tts-quiet").dataset.on === "1";
      const r = await post("/api/admin/tts/quiet", { minutes: off ? 0 : Number($("live-tts-quiet-min").value) });
      say("live-tts-msg", off ? "Read aloud is back on." : `Off for ${$("live-tts-quiet-min").value} min` + (r.dropped ? ` (${r.dropped} waiting dropped).` : "."));
      refreshLive();
    }));
    on("live-tts-skip", () => run("live-tts-skip", "live-tts-msg", async () => { await post("/api/admin/tts/skip"); say("live-tts-msg", "Skipped."); }));
    on("live-tts-clear", () => run("live-tts-clear", "live-tts-msg", async () => {
      const r = await post("/api/admin/tts/clear");
      say("live-tts-msg", r.dropped ? `Cleared (${r.dropped} waiting dropped).` : "Cleared.");
      refreshLive();
    }));
    // Blocked list import / export as a plain text file, one entry per line
    on("tts-blocked-export", () => {
      const blob = new Blob([$("tts-blocked").value.trim() + "\n"], { type: "text/plain" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "tts-blocked-words.txt";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    });
    on("tts-blocked-import", () => $("tts-blocked-file").click());
    const file = $("tts-blocked-file");
    if (file) file.addEventListener("change", async () => {
      const f = file.files && file.files[0];
      if (!f) return;
      const have = new Set($("tts-blocked").value.split("\n").map((l) => l.trim().toLowerCase()).filter(Boolean));
      const add = (await f.text()).split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !have.has(l.toLowerCase()));
      $("tts-blocked").value = ($("tts-blocked").value.trim() + "\n" + add.join("\n")).trim();
      dirty = true;
      say("tts-save-msg", `Added ${add.length} from the file. Not saved yet.`);
      file.value = "";
    });
  }

  // ── Opening the pages ───────────────────────────────────────────────────
  function showing(id) {
    const p = $(id);
    return !!(p && p.classList.contains("active"));
  }
  function open() {
    refresh(!dirty);
    clearInterval(pageTimer);
    pageTimer = setInterval(() => {
      if (showing("tab-tts")) refresh(false);
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

  window.addEventListener("beforeunload", (ev) => {
    if (dirty) {
      ev.preventDefault();
      ev.returnValue = "";
    }
  });
  wire();
  window.TtsPage = { open, openLive, isDirty: () => dirty };
})();
