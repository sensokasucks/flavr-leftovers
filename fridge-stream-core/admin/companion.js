/*
 * Two small dashboard cards (admin token in X-Admin-Token, like admin.js):
 *
 * 1. Credits page → "When you go live" (#crd-golive-card): shows whether Core thinks the stream is live
 *    (core/stream_state.py), and saves credits.auto_session ("Start a new credits session when I go live")
 *    and stream.restart_grace_min. Routes: GET /api/admin/stream, PUT /api/admin/stream/settings.
 * 2. Setup → Discord & video requests → Companion bot tab (cp-* fields): the link to an always-on bot on
 *    another home PC (core/companion_link.py). Routes: GET /api/admin/companion,
 *    PUT /api/admin/companion/settings, POST /api/admin/companion/test. The password is never sent back
 *    (key_set only); typing a new one replaces it, "Remove the saved password" clears it.
 *
 * Both refresh every POLL_MS while their page shows (a section counts as showing when it has class
 * "active", set by admin.js). The Discord page's tabs are run by admin/discord.js.
 */
(() => {
  const $ = (id) => document.getElementById(id);
  const tokenKey = "stream_core_admin_token";   // same localStorage key as admin.js
  const POLL_MS = 5000;
  const CP_FIELDS = ["enabled", "url", "heartbeat_sec", "send_alerts", "send_points", "send_queue", "send_chat"];
  let cpDirty = false;
  let goDirty = false;

  function token() {
    return localStorage.getItem(tokenKey) || ($("token") ? $("token").value.trim() : "");
  }
  async function call(path, opts = {}) {
    const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Admin-Token": token(), ...(opts.headers || {}) } });
    if (!res.ok) {
      let msg = res.statusText || "HTTP " + res.status;
      try { const j = await res.json(); if (j && typeof j.detail === "string") msg = j.detail; } catch (_) { /* not JSON */ }
      throw new Error(msg);
    }
    return res.json();
  }
  function say(id, text, bad) {
    const el = $(id);
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("error", !!bad);
  }
  function showing(id) {
    const p = $(id);
    return !!(p && p.classList.contains("active"));
  }
  function dur(sec) {
    const m = Math.floor((sec || 0) / 60);
    return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
  }
  const title = (p) => p.charAt(0).toUpperCase() + p.slice(1);

  // ── Credits: When you go live ──
  function streamLine(st) {
    const names = (st.platforms || []).map(title).join(", ");
    if (st.state === "live") return `🔴 Live on ${names} for ${dur(st.length_sec)}`;
    if (st.state === "dropped") return `🟡 Every platform is offline; the stream ends in ${dur(st.ends_in)} unless you're back`;
    return "⚪ Offline" + (st.ended_at ? ` (last stream ended ${new Date(st.ended_at * 1000).toLocaleString()})` : "");
  }
  function renderGoLive(data, fill) {
    say("crd-stream-state", "Stream: " + streamLine(data.status || {}));
    if (fill && !goDirty) {
      $("crd-auto-session").checked = !!data.settings.auto_session;
      $("crd-grace").value = Math.round(data.settings.restart_grace_min);
    }
  }
  async function refreshGoLive(fill) {
    try { renderGoLive(await call("/api/admin/stream"), fill); } catch (e) { say("crd-stream-state", e.message, true); }
  }

  // ── Discord page: Companion bot tab ──
  function renderCompanion(data, fill) {
    const s = data.settings || {};
    const st = data.status || {};
    const dot = st.state === "on" ? "🟢" : st.state === "retrying" ? "🟡" : "⚪";
    say("cp-state", `${dot} ${st.message || ""}` + (st.waiting ? ` (${st.waiting} waiting to send)` : ""));
    $("cp-key-note").textContent = s.key_set ? "A password is saved. Type a new one only to change it." : "No password saved yet.";
    $("cp-key-clear-row").hidden = !s.key_set;
    if (fill && !cpDirty) {
      CP_FIELDS.forEach((k) => {
        const el = $("cp-" + k);
        if (!el || document.activeElement === el) return;
        if (el.type === "checkbox") el.checked = !!s[k];
        else el.value = s[k] == null ? "" : s[k];
      });
    }
  }
  async function refreshCompanion(fill) {
    try { renderCompanion(await call("/api/admin/companion"), fill); } catch (e) { say("cp-state", e.message, true); }
  }
  function readCompanion() {
    const out = {};
    CP_FIELDS.forEach((k) => {
      const el = $("cp-" + k);
      out[k] = el.type === "checkbox" ? el.checked : (el.type === "number" ? Number(el.value) : el.value.trim());
    });
    const key = $("cp-key").value.trim();
    if (key) out.key = key;
    if ($("cp-key-clear").checked) out.key_clear = true;
    return out;
  }

  function wire() {
    if ($("crd-golive-card")) {
      $("crd-golive-card").addEventListener("input", () => { goDirty = true; });
      $("crd-golive-save").addEventListener("click", async () => {
        try {
          const data = await call("/api/admin/stream/settings", { method: "PUT", body: JSON.stringify({
            auto_session: $("crd-auto-session").checked, restart_grace_min: Number($("crd-grace").value) }) });
          goDirty = false;
          renderGoLive(data, true);
          say("crd-golive-msg", "Saved.");
        } catch (e) { say("crd-golive-msg", e.message, true); }
      });
    }
    if ($("cp-save")) {
      document.querySelector('#tab-discord [data-dc-tab="companion"]').addEventListener("input", () => { cpDirty = true; });
      $("cp-save").addEventListener("click", async () => {
        try {
          const data = await call("/api/admin/companion/settings", { method: "PUT", body: JSON.stringify(readCompanion()) });
          cpDirty = false;
          $("cp-key").value = "";
          $("cp-key-clear").checked = false;
          renderCompanion(data, true);
          say("cp-msg", "Saved.");
        } catch (e) { say("cp-msg", e.message, true); }
      });
      $("cp-test").addEventListener("click", async () => {
        say("cp-msg", "Asking the companion bot…");
        try {
          const data = await call("/api/admin/companion/test", { method: "POST", body: "{}" });
          renderCompanion(data, false);
          say("cp-msg", data.message, !data.ok);
        } catch (e) { say("cp-msg", e.message, true); }
      });
    }
    // one timer for both cards: each refreshes only while its page shows; the first look fills the form
    let seenCredits = false, seenDiscord = false;
    const tick = () => {
      if (!token()) return;
      if (showing("tab-credits") && $("crd-golive-card")) { refreshGoLive(!seenCredits); seenCredits = true; } else seenCredits = false;
      if (showing("tab-discord") && $("cp-save")) { refreshCompanion(!seenDiscord); seenDiscord = true; } else seenDiscord = false;
    };
    setInterval(tick, POLL_MS);
    window.addEventListener("hashchange", () => setTimeout(tick, 100));   // a page switch shows fresh data at once
  }

  wire();
})();
