/*
 * Setup > Stream Rooms settings (#rooms, <section id="tab-rooms"> in index.html): every setting
 * Stream Rooms' in-game panel has a control for, drawn here from the list the game sends
 * (work list items 16 and 18).
 *
 * Where the list comes from: Stream Rooms' ui/control_panel.gd settings_schema() describes each
 * control (key, label, help text, panel tab, heading, Advanced or not, type and range / choices);
 * core/rooms_remote.gd sends it to Core as "rooms_settings" and changes as "rooms_values";
 * core/reactions.py keeps it. A new control in the game shows up here with no change in this file.
 *
 * Routes (api/admin_routes.py, admin token like admin.js):
 *   GET  /api/admin/rooms/settings   {connected, schema, values, defaults}
 *   POST /api/admin/rooms/set        {key, value}  (checked again in core/reactions.py check_rooms_value)
 *   GET  /api/admin/rooms            the Live card state (for the Start here checklist)
 *   GET / PUT /api/admin/dashboard-prefs   pins (the pin buttons here; the Live "Pinned" card is
 *                                          in admin/live-extras.js and uses makeControl below)
 *
 * The page's tabs: PAGES maps each of Core's sub-pages to the game panel's tabs. Keep it in step
 * with PAGE_SETS.roomset in admin.js and the .acc[data-sub] blocks in index.html.
 *
 * On each page: Basics / More (More shows the game's Advanced ▸ settings too), a filter box, a dot
 * and Reset on every setting that differs from its default ("changed" marks), a warning mark on a
 * few risky values (WARN), the pin button, and on the first page a Start here checklist.
 * admin.js calls window.RoomsSetup.open(sub) from activateTab.
 */
(() => {
  const $ = (id) => document.getElementById(id);
  const tokenKey = "stream_core_admin_token";   // same key as admin.js
  const moreKey = "stream_core_rooms_more";      // Basics / More, remembered in this browser
  const POLL_MS = 3000;

  // [sub-page id, title, the game panel tabs it shows]
  const PAGES = [
    ["room", "Room & sound", ["Room", "Sound", "Panel"]],
    ["screen", "Big screen", ["Source"]],
    ["chat", "Chat windows", ["Chat"]],
    ["audience", "Audience", ["Audience", "Seating"]],
    ["reactions", "Reactions & games", ["React", "Games"]],
    ["people", "Presenters & Co-stream", ["Presenters", "Co-stream"]],
  ];

  // Warning marks: setting key -> (value, all values) => text when it's worth a second look, else "".
  // Keys that the game doesn't have are skipped, so an entry here can't break anything.
  const WARN = {
    photosensitive_safe: (v) => (v === false ? "Flashes and strobes are on. Viewers sensitive to flashing light may need this ticked." : ""),
    flash_strength: (v, all) => (Number(v) > 0.8 && all.photosensitive_safe === false ? "Very strong flashes." : ""),
    graphics_quality: (v) => (v === "high" || v === "custom" ? "Heavy on a low-end PC: use Medium on the second PC." : ""),
    together_hide_address: (v) => (v === false ? "Guests can see your home address (IP) while this is off." : ""),
    messages_on_picture: (v) => (v === true ? "Status messages show on stream." : ""),
    volume: (v) => (Number(v) === 0 ? "The big screen is muted." : ""),
  };

  let data = { connected: false, schema: [], values: {}, defaults: {} };
  let byKey = {};
  let pins = [];
  let state = null;          // GET /api/admin/rooms .state (Start here)
  let current = "room";
  let timer = 0;
  let built = "";            // signature of the schema the page was drawn from

  // ── Helpers ─────────────────────────────────────────────────────────────
  function token() {
    return localStorage.getItem(tokenKey) || ($("token") ? $("token").value.trim() : "");
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  async function call(path, opts = {}) {
    const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Admin-Token": token() } });
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
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const changed = (key) => key in data.defaults && !same(data.values[key], data.defaults[key]);
  function showMore() {
    try { return localStorage.getItem(moreKey) === "1"; } catch (_) { return false; }
  }

  /** A slider value as the game shows it ("75%"): fmt is Godot's (%d, %.1f, %s), times scale. */
  function shown(e, v) {
    const x = Number(v) * (e.scale || 1);
    if (e.zero && Math.abs(x) < 1e-9) return e.zero;
    const fmt = String(e.fmt || "%s");
    return fmt.replace(/%(\.(\d+))?([dfs])/, (_m, _p, dec, t) => (t === "d" ? String(Math.round(x)) : t === "f" ? x.toFixed(Number(dec || 2)) : String(x)))
      .replace(/%%/g, "%");
  }

  // ── One setting's control (also used by the Live "Pinned" card) ────────
  /**
   * The input for one schema entry, with its value, sending changes to the game. onSent(ok, msg)
   * runs after each send. Returns the element (a checkbox, a slider row, a select, a text or a
   * colour box).
   */
  function makeControl(e, onSent) {
    const v = data.values[e.key];
    const send = async (value) => {
      try {
        await call("/api/admin/rooms/set", { method: "POST", body: JSON.stringify({ key: e.key, value }) });
        data.values[e.key] = value;
        if (onSent) onSent(true, "");
      } catch (err) {
        if (onSent) onSent(false, String(err.message || err));
      }
    };
    let el;
    if (e.type === "bool") {
      el = document.createElement("input");
      el.type = "checkbox";
      el.checked = !!v;
      el.addEventListener("change", () => send(el.checked));
    } else if (e.type === "range") {
      el = document.createElement("span");
      el.className = "rs-range";
      const r = document.createElement("input");
      r.type = "range";
      r.min = e.min;
      r.max = e.max;
      r.step = e.step || "any";
      r.value = v;
      const out = document.createElement("output");
      out.textContent = shown(e, v);
      r.addEventListener("input", () => { out.textContent = shown(e, r.value); });
      r.addEventListener("change", () => send(e.int ? Math.round(Number(r.value)) : Number(r.value)));
      el.append(r, out);
    } else if (e.type === "choice") {
      el = document.createElement("select");
      (e.options || []).forEach(([val, label]) => {
        const o = document.createElement("option");
        o.value = JSON.stringify(val);   // keeps a number a number
        o.textContent = label;
        el.appendChild(o);
      });
      el.value = JSON.stringify(v);
      el.addEventListener("change", () => send(JSON.parse(el.value)));
    } else if (e.type === "color") {
      el = document.createElement("input");
      el.type = "color";
      el.value = typeof v === "string" ? v : "#ffffff";
      el.addEventListener("change", () => send(el.value));
    } else {
      el = document.createElement("input");
      el.type = "text";
      el.value = v == null ? "" : String(v);
      el.addEventListener("change", () => send(el.value.trim()));
    }
    el.dataset.rsKey = e.key;
    return el;
  }

  /** Put a value into a control made by makeControl (unless the person is using it right now). */
  function setControl(el, e, v) {
    if (!el || el.contains(document.activeElement)) return;
    if (e.type === "bool") el.checked = !!v;
    else if (e.type === "range") {
      el.querySelector("input").value = v;
      el.querySelector("output").textContent = shown(e, v);
    } else if (e.type === "choice") el.value = JSON.stringify(v);
    else el.value = v == null ? "" : String(v);
  }

  // ── The page ────────────────────────────────────────────────────────────
  function pageBox(sub) {
    return $("rooms-page-" + sub);
  }

  /** Draw every page from the schema (once per schema; values are refreshed by refreshValues). */
  function build() {
    const sig = JSON.stringify(data.schema.map((e) => e.key));
    if (sig === built) return;
    built = sig;
    PAGES.forEach(([sub, title, tabs]) => {
      const box = pageBox(sub);
      if (!box) return;
      const entries = data.schema.filter((e) => tabs.includes(e.tab));
      // group cards: "<panel tab> › <heading>" in the game's order
      const groups = [];
      entries.forEach((e) => {
        const name = e.group || e.tab;
        let g = groups.find((x) => x.name === name && x.tab === e.tab);
        if (!g) groups.push((g = { name, tab: e.tab, items: [] }));
        g.items.push(e);
      });
      box.innerHTML =
        (sub === "room" ? '<div class="rs-start" id="rooms-start" hidden></div>' : "") +
        `<div class="rs-bar">
          <div class="rs-mode" role="group" aria-label="How many settings to show">
            <button type="button" data-rs-more="0" title="The settings you'd change most">Basics</button>
            <button type="button" data-rs-more="1" title="Also the ones under Advanced ▸ in the game">More</button>
          </div>
          <label class="rs-filter">Find <input type="search" data-rs-filter placeholder="setting name or help text" /></label>
          <label class="check rs-only"><input type="checkbox" data-rs-changed /> Changed only</label>
          <span class="muted rs-count" data-rs-count></span>
        </div>` +
        `<div class="config-grid rs-grid">` +
        groups.map((g) => `<fieldset class="cfg-card rs-card" data-rs-group><legend>${esc(g.name)}${g.name !== g.tab ? ` <small class="muted rs-tab">${esc(g.tab)}</small>` : ""}</legend>` +
          g.items.map((e) => `<div class="rs-row${e.adv ? " rs-adv" : ""}" data-key="${esc(e.key)}">
              <label class="rs-label"><span class="rs-dot" title="Changed from the default" aria-label="changed"></span><span class="rs-name">${esc(e.label || e.key)}</span>${e.adv ? '<span class="rs-badge" title="Under Advanced ▸ in the game">More</span>' : ""}<span class="rs-slot"></span></label>
              <span class="rs-warn" hidden title=""></span>
              <div class="rs-actions">
                ${e.tip ? `<p class="field-help">${esc(e.tip)}</p>` : '<span></span>'}
                <button type="button" class="rs-reset link-btn" title="Put the default back">Reset</button>
                <button type="button" class="rs-pin" aria-pressed="false" title="Pin to the Live page">Pin</button>
              </div>
            </div>`).join("") + "</fieldset>").join("") +
        "</div>" +
        (entries.length ? "" : '<p class="muted">Nothing here from Stream Rooms yet.</p>');
      box.querySelectorAll(".rs-row").forEach((row) => {
        const e = byKey[row.dataset.key];
        const ctl = makeControl(e, (ok, msg) => {
          if (!ok) {
            say(msg, true);
            setControl(ctl, e, data.values[e.key]);
          }
          markRow(row);
        });
        row.querySelector(".rs-slot").appendChild(ctl);
      });
    });
    applyView();
  }

  function say(text, bad) {
    const el = $("rooms-setup-msg");
    if (!el) return;
    el.textContent = text || "";
    el.style.color = bad ? "var(--bad, #ff6b6b)" : "";
  }

  /** The changed dot, Reset, warning mark and pin state of one row. */
  function markRow(row) {
    const key = row.dataset.key;
    const e = byKey[key];
    if (!e) return;
    const ch = changed(key);
    row.classList.toggle("rs-changed", ch);
    row.querySelector(".rs-reset").hidden = !ch;
    const w = WARN[key] ? WARN[key](data.values[key], data.values) : "";
    const mark = row.querySelector(".rs-warn");
    mark.hidden = !w;
    mark.title = w;
    mark.textContent = w ? "⚠ " + w : "";
    const pin = row.querySelector(".rs-pin");
    const on = pins.some((p) => p.key === key);
    pin.setAttribute("aria-pressed", on ? "true" : "false");
    pin.textContent = on ? "Pinned" : "Pin";
  }

  /** Basics / More, the filter box and Changed only, on every page. */
  function applyView() {
    const more = showMore();
    document.querySelectorAll("#tab-rooms [data-rs-more]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.rsMore === (more ? "1" : "0"))));
    PAGES.forEach(([sub]) => {
      const box = pageBox(sub);
      if (!box) return;
      const q = (box.querySelector("[data-rs-filter]") || {}).value || "";
      const words = q.toLowerCase().split(/\s+/).filter(Boolean);
      const only = !!(box.querySelector("[data-rs-changed]") || {}).checked;
      let shownCount = 0;
      let changedCount = 0;
      box.querySelectorAll(".rs-row").forEach((row) => {
        markRow(row);
        const e = byKey[row.dataset.key];
        const hay = ((e.label || "") + " " + (e.tip || "") + " " + (e.group || "") + " " + e.key).toLowerCase();
        const ch = changed(e.key);
        if (ch) changedCount++;
        // a search or "Changed only" also finds Advanced settings, so nothing is out of reach
        const on = (more || !e.adv || words.length > 0 || only) && words.every((w) => hay.includes(w)) && (!only || ch);
        row.hidden = !on;
        if (on) shownCount++;
      });
      box.querySelectorAll("[data-rs-group]").forEach((fs) => {
        fs.hidden = !fs.querySelector(".rs-row:not([hidden])");
      });
      const count = box.querySelector("[data-rs-count]");
      if (count) count.textContent = `${shownCount} shown · ${changedCount} changed from default`;
    });
  }

  /** New values from the game (it may have changed them itself): controls and marks follow. */
  function refreshValues() {
    document.querySelectorAll("#tab-rooms .rs-row").forEach((row) => {
      const e = byKey[row.dataset.key];
      setControl(row.querySelector("[data-rs-key]"), e, data.values[e.key]);
    });
    applyView();
  }

  /** Start here: the few things that make Stream Rooms work, ticked from the game's state. */
  function renderStart() {
    const box = $("rooms-start");
    if (!box) return;
    const st = state || {};
    const scr = st.screen || {};
    const snd = st.sender || {};
    const v = data.values;
    const items = [
      [data.connected, "Stream Rooms is running and connected to Core", ""],
      [!!scr.ok, "Something on the big screen (" + (scr.text || "nothing yet") + ")", "screen"],
      [scr.mode !== "capture" || (!!snd.connected && !!snd.sharing), "The sender page shares a tab or window", "screen"],
      [v.audience_enabled !== false, "Chat sits in the room as the audience", "audience"],
    ];
    const todo = items.filter((i) => !i[0]).length;
    box.hidden = todo === 0;
    box.innerHTML = `<h3>Start here <small class="muted">${items.length - todo} of ${items.length} done</small></h3><ul>` +
      items.map(([ok, text, sub]) => `<li class="${ok ? "rs-ok" : "rs-todo"}">${ok ? "✓" : "○"} ${esc(text)}` +
        (!ok && sub ? ` <a href="#rooms/${sub}">Go there</a>` : "") + "</li>").join("") + "</ul>";
  }

  async function load() {
    try {
      const [s, r, p] = await Promise.all([
        call("/api/admin/rooms/settings"),
        call("/api/admin/rooms").catch(() => ({})),
        call("/api/admin/dashboard-prefs").catch(() => ({ pins: [] })),
      ]);
      data = s;
      byKey = Object.fromEntries((s.schema || []).map((e) => [e.key, e]));
      state = r.state || null;
      pins = p.pins || [];
      const off = $("rooms-setup-off");
      if (off) off.hidden = !!(s.connected && s.schema.length);
      build();
      refreshValues();
      renderStart();
    } catch (e) {
      say(String(e.message || e), true);
    }
    return data;
  }

  async function togglePin(key) {
    const e = byKey[key];
    if (!e) return;
    const on = pins.some((p) => p.key === key);
    const next = on ? pins.filter((p) => p.key !== key) : [...pins, { key, label: e.label || key }];
    try {
      const saved = await call("/api/admin/dashboard-prefs", { method: "PUT", body: JSON.stringify({ pins: next }) });
      pins = saved.pins || [];
      say(on ? "Unpinned " + (e.label || key) : "Pinned " + (e.label || key) + " to the Live page", false);
      applyView();
    } catch (err) {
      say(String(err.message || err), true);
    }
  }

  // ── Events (one listener for all pages) ────────────────────────────────
  document.addEventListener("click", (ev) => {
    const t = ev.target;
    if (!t.closest || !t.closest("#tab-rooms")) return;
    const more = t.closest("[data-rs-more]");
    if (more) {
      try { localStorage.setItem(moreKey, more.dataset.rsMore); } catch (_) { /* private window */ }
      applyView();
      return;
    }
    const row = t.closest(".rs-row");
    if (!row) return;
    const key = row.dataset.key;
    if (t.closest(".rs-reset")) {
      const e = byKey[key];
      call("/api/admin/rooms/set", { method: "POST", body: JSON.stringify({ key, value: data.defaults[key] }) })
        .then(() => {
          data.values[key] = data.defaults[key];
          setControl(row.querySelector("[data-rs-key]"), e, data.defaults[key]);
          applyView();
          say("Reset " + (e.label || key), false);
        })
        .catch((err) => say(String(err.message || err), true));
    } else if (t.closest(".rs-pin")) togglePin(key);
  });
  document.addEventListener("input", (ev) => {
    if (ev.target.closest && ev.target.closest("#tab-rooms") && ev.target.matches("[data-rs-filter]")) applyView();
  });
  document.addEventListener("change", (ev) => {
    if (ev.target.closest && ev.target.closest("#tab-rooms") && ev.target.matches("[data-rs-changed]")) applyView();
  });

  /** admin.js activateTab: the page opened (sub = the tab across the top). Refreshes while it shows. */
  function open(sub) {
    if (sub) current = sub;
    load();
    if (!timer) {
      timer = setInterval(() => {
        const panel = $("tab-rooms");
        if (panel && panel.classList.contains("active")) load();
      }, POLL_MS);
    }
  }

  window.RoomsSetup = {
    open,
    load,
    makeControl,
    setControl,
    entry: (key) => byKey[key],
    data: () => data,
    pins: () => pins,
    setPins: (p) => { pins = p || []; applyView(); },
    PAGES,
  };
})();
