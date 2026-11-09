/*
 * Live page extras and the dashboard-wide helpers from the Stream Rooms menu redesign
 * (work list items 14, 15 and 17). Loaded after admin.js; admin.js calls
 * window.LiveExtras.openLive() each time the Live page opens.
 *
 *  - Arrange (item 14): an "Arrange" button on the Live page. While arranging, every card gets a
 *    small bar: move earlier / later (or drag it), Wide / Half, Hide. Hidden cards wait in a tray
 *    above the grid with Show. Stream events (#live-feed-card) starts last and full width, but moves,
 *    narrows and hides like any other card (Sen, 2026-11-06); its window has a fixed height, so new
 *    lines never push the cards around it. Done saves the
 *    layout in Core (data/dashboard_prefs.json, core/dashboard_prefs.py), one for the PC and one for
 *    the phone (a screen narrower than PHONE_PX), so both stay tidy their own way. Reset forgets it.
 *    A card that is hidden because it doesn't apply (Stream Rooms not running, TTS off...) uses the
 *    plain `hidden` attribute and stays that way; Arrange's own hiding is the .live-user-hidden class.
 *  - Pinned card (item 17): Stream Rooms settings pinned on Setup > Stream Rooms settings, each with
 *    its real control (admin/rooms-setup.js makeControl). Shown while Stream Rooms is connected.
 *  - Scenes card (item 17): one button that does several things in a row (Stream Rooms settings,
 *    Stream Rooms card buttons, the curtain). Core runs them (POST /api/admin/rooms/scene), so the
 *    phone's button does the same. "Edit scenes" opens a small editor in the card.
 *  - Help (item 15): a "?" button on every page's title opens the matching part of the manual
 *    (GET /api/admin/help = docs/manual/MANUAL.md) in a side panel; HELP_MAP says which part.
 *  - Ctrl+K (item 15): one search box over actions (the Live page's buttons and the scenes),
 *    settings and pages (admin.js's sidebar search index, window.AdminSearch) and the manual.
 *
 * Routes: GET / PUT /api/admin/dashboard-prefs, POST /api/admin/rooms/scene, GET /api/admin/help,
 * GET /api/admin/rooms (connected or not), plus whatever a pressed button does itself.
 */
(() => {
  const $ = (id) => document.getElementById(id);
  const tokenKey = "stream_core_admin_token";   // same key as admin.js
  const PHONE_PX = 700;                          // narrower than this = the phone's layout
  const FEED_ID = "live-feed-card";              // Stream events: last and wide until it is arranged
  const POLL_MS = 5000;

  // Manual section (the number in "## 17. Stream Rooms") for each page; "page/sub" beats "page".
  const HELP_MAP = {
    live: "4", phone: "4", status: "23", "config/core": "5", "config/points": "7", "config/advanced": "21",
    "config/commands": "10", "config/groups": "10", "config/reactions": "11", "config/games": "17",
    chat: "8", redflags: "8", paid: "8", creditslist: "14", users: "7", fun: "12", alerts: "13",
    credits: "14", sources: "16", chatlook: "16", widgets: "16", files: "21", rooms: "17", looks: "17",
    integrations: "18",
  };

  let prefs = { live_layout: { pc: {}, phone: {} }, pins: [], scenes: [] };
  let arranging = false;
  let liveTimer = 0;
  let roomsUp = false;
  let manual = null;        // [{num, title, md}] once loaded

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
  const device = () => (window.innerWidth < PHONE_PX ? "phone" : "pc");
  const grid = () => document.querySelector("#tab-live > .live-grid");
  function slug(text) {
    return String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "card";
  }

  /** Every Live card, each with a stable id (data-card, else its id, else its title). */
  function cards() {
    const g = grid();
    if (!g) return [];
    return [...g.querySelectorAll(":scope > .live-card")].map((c) => {
      if (!c.dataset.card) c.dataset.card = c.id || slug((c.querySelector("h3") || {}).textContent);
      return c;
    });
  }

  // ── Arrange (item 14) ───────────────────────────────────────────────────
  function layoutNow() {
    const lay = (prefs.live_layout || {})[device()] || {};
    return { order: lay.order || [], wide: lay.wide || [], hidden: lay.hidden || [] };
  }

  /**
   * Put the cards in the saved order (unknown ones keep their place after them). Stream events goes
   * last and full width while the saved layout doesn't mention it (no layout yet, or one saved before
   * it could move); once it has been arranged it follows the layout like every other card.
   */
  function applyLayout() {
    const g = grid();
    if (!g) return;
    const lay = layoutNow();
    const all = cards();
    const feedArranged = lay.order.includes(FEED_ID);
    const rank = (c) => {
      const i = lay.order.indexOf(c.dataset.card);
      return i >= 0 ? i : c.id === FEED_ID ? 1e6 : 1000 + all.indexOf(c);
    };
    // Cards are only moved when the order changed: moving a card reloads any frame inside it, and the
    // "Share to Stream Rooms" card's frame (admin/rooms-sender.js) would stop what it shares. This
    // runs each time Live opens, so without the check every visit to Live would cut the big screen.
    const sorted = all.slice().sort((a, b) => rank(a) - rank(b));
    if (sorted.some((c, i) => c !== all[i])) sorted.forEach((c) => g.appendChild(c));
    all.forEach((c) => {
      const wide = c.id === FEED_ID && !feedArranged ? true : lay.wide.includes(c.dataset.card);
      c.classList.toggle("live-wide", wide);
      c.classList.toggle("live-user-hidden", lay.hidden.includes(c.dataset.card));
    });
    renderTray();
  }

  /** The layout as the page shows it now (while arranging). */
  function readLayout() {
    const all = cards();
    return {
      order: all.map((c) => c.dataset.card),
      wide: all.filter((c) => c.classList.contains("live-wide")).map((c) => c.dataset.card),
      hidden: all.filter((c) => c.classList.contains("live-user-hidden")).map((c) => c.dataset.card),
    };
  }

  async function saveLayout(lay) {
    try {
      prefs = await call("/api/admin/dashboard-prefs", { method: "PUT", body: JSON.stringify({ live_layout: { [device()]: lay } }) });
      say(lay.order.length ? "Layout saved for this " + (device() === "phone" ? "phone" : "PC") + "." : "Layout reset.");
    } catch (e) {
      say(String(e.message || e), true);
    }
  }

  function say(text, bad) {
    const el = $("live-arrange-msg");
    if (!el) return;
    el.textContent = text || "";
    el.style.color = bad ? "var(--bad, #ff6b6b)" : "";
  }

  /** Hidden cards' tray (only while arranging): one Show button each. */
  function renderTray() {
    const tray = $("live-tray");
    if (!tray) return;
    const hidden = cards().filter((c) => c.classList.contains("live-user-hidden"));
    tray.hidden = !arranging;
    tray.innerHTML = hidden.length
      ? "<span class=\"muted\">Hidden cards:</span> " + hidden.map((c) =>
          `<button type="button" data-tray-show="${esc(c.dataset.card)}">Show ${esc((c.querySelector("h3") || {}).textContent || c.dataset.card)}</button>`).join(" ")
      : '<span class="muted">No hidden cards. Use Hide on a card to tuck it away here.</span>';
  }

  /** The small bar on top of a card while arranging. */
  function cardBar(c) {
    let bar = c.querySelector(":scope > .arrange-bar");
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "arrange-bar";
      c.prepend(bar);
    }
    bar.innerHTML = '<span class="arrange-grip" aria-hidden="true" title="Drag to move">⠿</span>' +
        '<button type="button" data-arr="up" title="Move earlier">◀</button>' +
        '<button type="button" data-arr="down" title="Move later">▶</button>' +
        `<button type="button" data-arr="wide" aria-pressed="${c.classList.contains("live-wide")}" title="Full width or half">${c.classList.contains("live-wide") ? "Half" : "Wide"}</button>` +
        '<button type="button" data-arr="hide" title="Tuck it into the tray above">Hide</button>';
    c.draggable = true;
  }

  function setArranging(on) {
    arranging = on;
    document.body.classList.toggle("arranging", on);
    $("live-arrange").textContent = on ? "Done" : "Arrange";
    $("live-arrange").setAttribute("aria-pressed", String(on));
    $("live-arrange-reset").hidden = !on;
    cards().forEach((c) => {
      if (on) cardBar(c);
      else {
        const bar = c.querySelector(":scope > .arrange-bar");
        if (bar) bar.remove();
        c.draggable = false;
      }
    });
    renderTray();
    if (!on) saveLayout(readLayout());
    else say("Move, widen or hide cards, then press Done. This " + (device() === "phone" ? "phone" : "PC") + " keeps its own layout.");
  }

  function buildArrange() {
    const head = document.querySelector("#tab-live > .page-head");
    if (!head || $("live-arrange")) return;
    const row = document.createElement("div");
    row.className = "arrange-row";
    row.innerHTML = '<button type="button" id="live-arrange" aria-pressed="false" title="Move, widen or hide the cards on this page">Arrange</button>' +
      '<button type="button" id="live-arrange-reset" class="link-btn" hidden title="Back to the standard order, all cards shown">Reset</button>' +
      '<span id="live-arrange-msg" class="muted" role="status" aria-live="polite"></span>';
    head.appendChild(row);
    const tray = document.createElement("div");
    tray.id = "live-tray";
    tray.className = "live-tray";
    tray.hidden = true;
    grid().before(tray);
    $("live-arrange").onclick = () => setArranging(!arranging);
    $("live-arrange-reset").onclick = () => {
      const lay = { order: [], wide: [], hidden: [] };
      prefs.live_layout = { ...(prefs.live_layout || {}), [device()]: lay };
      const g = grid();
      // the page's own order: by where each card first was (data-home, set once below)
      cards().sort((a, b) => Number(a.dataset.home) - Number(b.dataset.home)).forEach((c) => g.appendChild(c));
      applyLayout();
      cards().forEach(cardBar);
      saveLayout(lay);
    };
    cards().forEach((c, i) => { c.dataset.home = String(i); });

    // buttons on the card bars and the tray
    document.addEventListener("click", (ev) => {
      const show = ev.target.closest("[data-tray-show]");
      if (show) {
        const c = cards().find((x) => x.dataset.card === show.dataset.trayShow);
        if (c) c.classList.remove("live-user-hidden");
        renderTray();
        return;
      }
      const b = ev.target.closest(".arrange-bar [data-arr]");
      if (!b) return;
      const c = b.closest(".live-card");
      const g = grid();
      // only cards on screen count, so one press always moves past a card you can see
      const visible = cards().filter((x) => !x.hidden && !x.classList.contains("live-user-hidden"));
      const i = visible.indexOf(c);
      if (b.dataset.arr === "up" && i > 0) g.insertBefore(c, visible[i - 1]);
      if (b.dataset.arr === "down" && i < visible.length - 1) g.insertBefore(visible[i + 1], c);
      if (b.dataset.arr === "wide") c.classList.toggle("live-wide");
      if (b.dataset.arr === "hide") c.classList.add("live-user-hidden");
      cardBar(c);
      renderTray();
      if (b.dataset.arr === "up" || b.dataset.arr === "down") {
        const again = c.querySelector(`[data-arr="${b.dataset.arr}"]`);
        if (again) again.focus();
      }
    });
    // drag and drop: drop a card on another to put it there
    let dragged = null;
    document.addEventListener("dragstart", (ev) => {
      const c = arranging && ev.target.closest && ev.target.closest("#tab-live .live-card");
      if (!c) return;
      dragged = c;
      c.classList.add("dragging");
      ev.dataTransfer.effectAllowed = "move";
    });
    document.addEventListener("dragover", (ev) => {
      if (!dragged) return;
      const over = ev.target.closest && ev.target.closest("#tab-live .live-card");
      if (!over || over === dragged) return;
      ev.preventDefault();
      const r = over.getBoundingClientRect();
      const after = ev.clientY > r.top + r.height / 2 || ev.clientX > r.left + r.width * 0.75;
      grid().insertBefore(dragged, after ? over.nextSibling : over);
    });
    document.addEventListener("dragend", () => {
      if (dragged) dragged.classList.remove("dragging");
      dragged = null;
    });
  }

  // ── Pinned and Scenes cards (item 17) ───────────────────────────────────
  function buildCards() {
    const g = grid();
    if (!g || $("live-pins-card")) return;
    const pinsCard = document.createElement("section");
    pinsCard.className = "live-card";
    pinsCard.id = "live-pins-card";
    pinsCard.hidden = true;
    pinsCard.innerHTML = '<div class="live-card-head"><h3>Pinned</h3><a href="#rooms" class="live-link">Pin more →</a></div>' +
      '<div id="live-pins" class="pins-list"></div><p id="live-pins-msg" class="muted" role="status"></p>';
    const scCard = document.createElement("section");
    scCard.className = "live-card";
    scCard.id = "live-scenes-card";
    scCard.hidden = true;
    scCard.innerHTML = '<div class="live-card-head"><h3>Scenes</h3><button type="button" class="link-btn live-link" id="scenes-edit">Edit scenes</button></div>' +
      '<p class="hint">One button, several steps: for example "Intermission" closes the curtain, turns the stream sound down and goes to the wide camera.</p>' +
      '<div id="scenes-buttons" class="live-buttons"></div><div id="scenes-editor" hidden></div><p id="scenes-msg" class="muted" role="status"></p>';
    const feed = $(FEED_ID);
    g.insertBefore(pinsCard, feed || null);
    g.insertBefore(scCard, feed || null);
    $("scenes-edit").onclick = () => {
      const ed = $("scenes-editor");
      ed.hidden = !ed.hidden;
      $("scenes-edit").textContent = ed.hidden ? "Edit scenes" : "Close editor";
      if (!ed.hidden) renderEditor();
    };
  }

  function renderPins() {
    const box = $("live-pins");
    const RS = window.RoomsSetup;
    if (!box || !RS) return;
    const pins = prefs.pins || [];
    $("live-pins-card").hidden = !roomsUp || !pins.length;
    const sig = JSON.stringify(pins.map((p) => p.key)) + JSON.stringify(RS.data().schema.length);
    if (box.dataset.sig !== sig) {
      box.dataset.sig = sig;
      box.innerHTML = "";
      pins.forEach((p) => {
        const e = RS.entry(p.key);
        const row = document.createElement("label");
        row.className = "pin-row";
        // the page's current name for it ("Left of the screen: Show this window"), else the saved one
        row.innerHTML = `<span>${esc(e && RS.fullLabel ? RS.fullLabel(p.key) : p.label)}</span>`;
        if (e) {
          row.appendChild(RS.makeControl(e, (ok, msg) => {
            $("live-pins-msg").textContent = ok ? "" : msg;
          }));
        } else {
          row.insertAdjacentHTML("beforeend", '<span class="muted">not in this Stream Rooms version</span>');
        }
        box.appendChild(row);
      });
    } else {
      box.querySelectorAll("[data-rs-key]").forEach((el) => {
        const e = RS.entry(el.dataset.rsKey);
        if (e) RS.setControl(el, e, RS.data().values[e.key]);
      });
    }
  }

  function renderScenes() {
    const box = $("scenes-buttons");
    if (!box) return;
    const scenes = prefs.scenes || [];
    $("live-scenes-card").hidden = !roomsUp && !scenes.length;
    box.innerHTML = scenes.length
      ? scenes.map((sc) => `<button type="button" data-scene="${esc(sc.id)}" title="${esc(sc.steps.length + " steps")}">${esc(sc.name)}</button>`).join("")
      : '<span class="muted">No scenes yet: press Edit scenes.</span>';
  }

  async function runScene(id) {
    try {
      const r = await call("/api/admin/rooms/scene", { method: "POST", body: JSON.stringify({ id }) });
      const sc = (prefs.scenes || []).find((s) => s.id === id);
      $("scenes-msg").textContent = r.ok ? "Done: " + (sc ? sc.name : id) : "Some steps didn't work: " + r.failed_steps.join(", ");
    } catch (e) {
      $("scenes-msg").textContent = String(e.message || e);
    }
  }

  // Scene editor: the steps a scene can take. "set" = a Stream Rooms setting (from its own list),
  // "cmd" = a Stream Rooms card button (core/reactions.py ROOMS_ACTIONS), "curtain" = open / close / reveal.
  const CMDS = [["pause", "Pause to react", ["on", "off", "toggle"]], ["focus", "Focus view", ["on", "off", "toggle"]],
    ["clean", "Clean feed", ["on", "off", "toggle"]], ["room", "Room", null], ["view", "Camera view", null],
    ["volume", "Stream sound (0 to 1)", null], ["ambience", "Room sound (0 to 1)", null]];
  let draft = [];

  function renderEditor() {
    const ed = $("scenes-editor");
    const RS = window.RoomsSetup;
    const schema = RS ? RS.data().schema : [];
    draft = JSON.parse(JSON.stringify(prefs.scenes || []));
    const draw = () => {
      ed.innerHTML = draft.map((sc, si) => `<fieldset class="scene-ed" data-si="${si}">
          <legend><input type="text" data-f="name" value="${esc(sc.name)}" aria-label="Scene name" /></legend>
          ${sc.steps.map((st, i) => `<div class="scene-step" data-i="${i}">
              <span class="muted">${i + 1}.</span>
              <select data-f="kind" aria-label="What this step does">
                <option value="curtain"${st.kind === "curtain" ? " selected" : ""}>Curtain</option>
                <option value="cmd"${st.kind === "cmd" ? " selected" : ""}>Stream Rooms button</option>
                <option value="set"${st.kind === "set" ? " selected" : ""}>Stream Rooms setting</option>
              </select>
              ${st.kind === "curtain" ? `<select data-f="value">${["close", "open", "reveal", "toggle"].map((v) => `<option${st.value === v ? " selected" : ""}>${v}</option>`).join("")}</select>` : ""}
              ${st.kind === "cmd" ? `<select data-f="action">${CMDS.map(([a, l]) => `<option value="${a}"${st.action === a ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
                 <input type="text" data-f="value" value="${esc(st.value)}" placeholder="${esc((CMDS.find((c) => c[0] === st.action) || [0, 0, null])[2] ? "on / off / toggle" : "value")}" aria-label="Value" />` : ""}
              ${st.kind === "set" ? `<select data-f="key">${schema.map((e) => `<option value="${esc(e.key)}"${st.key === e.key ? " selected" : ""}>${esc(e.tab + " › " + (e.label || e.key))}</option>`).join("")}</select>
                 <input type="text" data-f="value" value="${esc(typeof st.value === "string" ? st.value : JSON.stringify(st.value))}" placeholder="value (true, 0.5, text)" aria-label="Value" />` : ""}
              <button type="button" data-ed="del-step" title="Remove this step">✕</button>
            </div>`).join("")}
          <div class="live-buttons"><button type="button" data-ed="add-step">Add a step</button><button type="button" data-ed="del-scene" class="link-btn">Delete scene</button></div>
        </fieldset>`).join("") +
        '<div class="live-buttons"><button type="button" data-ed="add-scene">New scene</button><button type="button" class="primary" data-ed="save">Save scenes</button></div>';
    };
    draw();
    ed.oninput = ed.onchange = (ev) => {
      const fs = ev.target.closest("[data-si]");
      if (!fs) return;
      const sc = draft[Number(fs.dataset.si)];
      const f = ev.target.dataset.f;
      if (f === "name") { sc.name = ev.target.value; return; }
      const stEl = ev.target.closest("[data-i]");
      if (!stEl) return;
      const st = sc.steps[Number(stEl.dataset.i)];
      if (f === "kind") {
        sc.steps[Number(stEl.dataset.i)] = ev.target.value === "curtain" ? { kind: "curtain", value: "close" }
          : ev.target.value === "cmd" ? { kind: "cmd", action: "pause", value: "on" } : { kind: "set", key: (schema[0] || {}).key || "", value: "" };
        if (ev.type === "change") draw();
        return;
      }
      if (f === "value" && st.kind !== "curtain") {
        // numbers and true / false become real values (a Stream Rooms setting checks its own type)
        const raw = ev.target.value.trim();
        st.value = raw === "true" ? true : raw === "false" ? false : raw !== "" && !isNaN(Number(raw)) ? Number(raw) : raw;
      } else st[f] = ev.target.value;
    };
    ed.onclick = async (ev) => {
      const b = ev.target.closest("[data-ed]");
      if (!b) return;
      const fs = b.closest("[data-si]");
      const sc = fs ? draft[Number(fs.dataset.si)] : null;
      if (b.dataset.ed === "add-scene") draft.push({ id: "s" + Date.now().toString(36), name: "New scene", steps: [{ kind: "curtain", value: "close" }] });
      if (b.dataset.ed === "add-step" && sc) sc.steps.push({ kind: "cmd", action: "pause", value: "on" });
      if (b.dataset.ed === "del-step" && sc) sc.steps.splice(Number(b.closest("[data-i]").dataset.i), 1);
      if (b.dataset.ed === "del-scene" && sc) draft.splice(Number(fs.dataset.si), 1);
      if (b.dataset.ed === "save") {
        try {
          prefs = await call("/api/admin/dashboard-prefs", { method: "PUT", body: JSON.stringify({ scenes: draft }) });
          $("scenes-msg").textContent = "Scenes saved.";
          renderScenes();
          renderEditor();
        } catch (e) {
          $("scenes-msg").textContent = String(e.message || e);
        }
        return;
      }
      draw();
    };
  }

  document.addEventListener("click", (ev) => {
    const b = ev.target.closest && ev.target.closest("[data-scene]");
    if (b) runScene(b.dataset.scene);
  });

  async function refreshLive() {
    try {
      const r = await call("/api/admin/rooms");
      roomsUp = !!r.connected;
      if (roomsUp && window.RoomsSetup) await window.RoomsSetup.load();
    } catch (_) {
      roomsUp = false;
    }
    renderPins();
    renderScenes();
  }

  async function loadPrefs() {
    try {
      prefs = await call("/api/admin/dashboard-prefs");
      if (window.RoomsSetup) window.RoomsSetup.setPins(prefs.pins);
    } catch (_) { /* not signed in yet */ }
  }

  /** admin.js activateTab: the Live page opened. */
  async function openLive() {
    buildArrange();
    buildCards();
    await loadPrefs();
    if (!arranging) applyLayout();
    refreshLive();
    if (!liveTimer) {
      liveTimer = setInterval(() => {
        const p = $("tab-live");
        if (p && p.classList.contains("active")) refreshLive();
      }, POLL_MS);
    }
  }

  // ── Help panel (item 15) ────────────────────────────────────────────────
  /** MANUAL.md split into its "## N. Title" sections. */
  async function loadManual() {
    if (manual) return manual;
    try {
      const md = (await call("/api/admin/help")).markdown || "";
      manual = [];
      let cur = null;
      md.split(/\r?\n/).forEach((line) => {
        const m = line.match(/^##\s+(\d+)\.\s+(.*)$/);
        if (m) {
          cur = { num: m[1], title: m[2].trim(), md: "" };
          manual.push(cur);
        } else if (cur && !/^#\s/.test(line)) cur.md += line + "\n";
      });
    } catch (_) {
      manual = [];
    }
    return manual;
  }

  /** A small Markdown reader for the manual: headings, lists, paragraphs, **bold**, `code`, [links](x). */
  function mdToHtml(md) {
    const inline = (t) => esc(t)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+|#[^)\s]*)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
    const out = [];
    let list = null;
    let para = [];
    const flush = () => {
      if (para.length) out.push("<p>" + inline(para.join(" ")) + "</p>");
      para = [];
      if (list) out.push("<" + list.tag + ">" + list.items.map((i) => "<li>" + inline(i) + "</li>").join("") + "</" + list.tag + ">");
      list = null;
    };
    md = md.replace(/<!--[\s\S]*?-->/g, "");
    let table = null;
    md.split("\n").forEach((line) => {
      // a Markdown table: header row, |---| row, body rows
      if (/^\s*\|/.test(line)) {
        if (!table) { flush(); table = []; }
        if (!/^\s*\|[\s:|-]+\|\s*$/.test(line)) table.push(line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
        return;
      }
      if (table) {
        out.push("<table class=\"help-table\">" + table.map((r, i) => "<tr>" + r.map((c) => (i ? "<td>" : "<th>") + inline(c) + (i ? "</td>" : "</th>")).join("") + "</tr>").join("") + "</table>");
        table = null;
      }
      const h = line.match(/^(#{3,6})\s+(.*)$/);
      const li = line.match(/^\s*[-*]\s+(.*)$/);
      const ol = line.match(/^\s*\d+\.\s+(.*)$/);
      if (h) { flush(); out.push("<h4>" + inline(h[2]) + "</h4>"); }
      else if (li || ol) {
        if (para.length) { const keep = list; list = null; flush(); list = keep; }
        const tag = li ? "ul" : "ol";
        if (!list || list.tag !== tag) { flush(); list = { tag, items: [] }; }
        list.items.push((li || ol)[1]);
      } else if (!line.trim()) flush();
      else if (list) list.items[list.items.length - 1] += " " + line.trim();
      else para.push(line.trim());
    });
    flush();
    if (table) out.push("<table class=\"help-table\">" + table.map((r) => "<tr>" + r.map((c) => "<td>" + inline(c) + "</td>").join("") + "</tr>").join("") + "</table>");
    return out.join("");
  }

  async function openHelp(num, fallbackTitle) {
    const secs = await loadManual();
    let sec = secs.find((s) => s.num === num);
    if (!sec && fallbackTitle) {
      const words = fallbackTitle.toLowerCase().split(/\W+/).filter((w) => w.length > 3);
      sec = secs.find((s) => words.some((w) => s.title.toLowerCase().includes(w)));
    }
    let box = $("help-panel");
    if (!box) {
      box = document.createElement("aside");
      box.id = "help-panel";
      box.className = "help-panel";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-label", "Help");
      document.body.appendChild(box);
      box.addEventListener("click", (ev) => {
        if (ev.target.closest("[data-help-close]")) box.hidden = true;
        const other = ev.target.closest("[data-help-num]");
        if (other) openHelp(other.dataset.helpNum);
      });
    }
    box.hidden = false;
    box.innerHTML = '<div class="help-head"><b>Help</b><button type="button" data-help-close aria-label="Close help">✕</button></div>' +
      (sec ? `<h3>${esc(sec.num)}. ${esc(sec.title)}</h3><div class="help-body">${mdToHtml(sec.md)}</div>`
        : '<p class="muted">The manual has no section for this page yet.</p>') +
      '<details class="help-more"><summary>Other parts of the manual</summary>' +
      secs.map((s) => `<button type="button" class="link-btn" data-help-num="${esc(s.num)}">${esc(s.num)}. ${esc(s.title)}</button>`).join("<br>") +
      "</details>";
    const close = box.querySelector("[data-help-close]");
    if (close) close.focus();
  }

  /** A "?" on every page title; it opens that page's part of the manual. */
  function addHelpButtons() {
    document.querySelectorAll(".panel > .page-head").forEach((head) => {
      if (head.querySelector(".help-btn")) return;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "help-btn";
      b.textContent = "?";
      b.title = "Help for this page (the manual)";
      b.setAttribute("aria-label", "Help for this page");
      b.onclick = () => {
        const panel = head.closest(".panel");
        const tab = panel.id.replace(/^tab-/, "");
        const sub = panel.dataset.sub || "";
        const title = (head.querySelector(".page-title") || {}).textContent || tab;
        openHelp(HELP_MAP[tab + "/" + sub] || HELP_MAP[tab] || "", title);
      };
      const title = head.querySelector(".page-title");
      if (title) title.after(b);
      else head.prepend(b);
    });
  }

  // ── Ctrl+K (item 15) ────────────────────────────────────────────────────
  let kHits = [];
  let kSel = 0;

  /** What Ctrl+K can find: Live buttons (pressed for you), scenes, pages + settings, manual sections. */
  async function kIndex() {
    const out = [];
    document.querySelectorAll("#tab-live .live-card button").forEach((b) => {
      const card = b.closest(".live-card");
      if (b.closest(".arrange-bar") || card.hidden || card.classList.contains("live-user-hidden") || b.hidden) return;
      const text = b.textContent.trim();
      if (!text || text.length > 40) return;
      // where: the card's title, plus the small heading above the button inside it (e.g. "Curtain")
      let sub = "";
      for (let el = b.closest(".live-buttons") || b; el && el !== card && !sub; el = el.previousElementSibling || null) {
        if (el.matches && el.matches("h4")) sub = el.textContent.trim();
      }
      const where = ((card.querySelector("h3") || {}).textContent || "Live") + (sub ? " › " + sub : "");
      out.push({ kind: "Action", text: sub ? sub + ": " + text : text, where, run: () => b.click(), kw: (b.title || "").toLowerCase() });
    });
    (prefs.scenes || []).forEach((sc) => out.push({ kind: "Scene", text: sc.name, where: "Scenes", run: () => runScene(sc.id) }));
    if (window.AdminSearch) {
      window.AdminSearch.build().forEach((it) => out.push({
        kind: it.kind === "page" ? "Page" : "Setting", text: it.text, where: it.where, run: () => window.AdminSearch.open(it), kw: it.kw,
      }));
    }
    (await loadManual()).forEach((s) => out.push({ kind: "Help", text: s.title, where: "Manual " + s.num, run: () => openHelp(s.num), kw: s.md.slice(0, 4000).toLowerCase() }));
    return out;
  }

  async function openK() {
    let box = $("ck-box");
    if (!box) {
      box = document.createElement("div");
      box.id = "ck-box";
      box.className = "ck-box";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-label", "Find an action, setting or help");
      box.innerHTML = '<input type="search" id="ck-input" placeholder="Do or find anything: close curtain, chat colour, TTS help…" autocomplete="off" aria-label="Find" />' +
        '<div id="ck-results" role="listbox"></div><p class="muted ck-foot">Enter runs it · ↑↓ choose · Esc closes</p>';
      document.body.appendChild(box);
      const input = $("ck-input");
      input.addEventListener("input", () => renderK(input.value));
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
          ev.preventDefault();
          if (!kHits.length) return;
          kSel = (kSel + (ev.key === "ArrowDown" ? 1 : -1) + kHits.length) % kHits.length;
          renderK(input.value, true);
        } else if (ev.key === "Enter") {
          ev.preventDefault();
          runK(kHits[kSel]);
        } else if (ev.key === "Escape") closeK();
      });
      $("ck-results").addEventListener("mousedown", (ev) => {
        const b = ev.target.closest("[data-k]");
        if (!b) return;
        ev.preventDefault();
        runK(kHits[Number(b.dataset.k)]);
      });
      box.addEventListener("focusout", () => setTimeout(() => { if (!box.contains(document.activeElement)) closeK(); }, 100));
    }
    box.hidden = false;
    box.index = await kIndex();
    const input = $("ck-input");
    input.value = "";
    renderK("");
    input.focus();
  }

  function closeK() {
    const box = $("ck-box");
    if (box) box.hidden = true;
  }

  function runK(hit) {
    if (!hit) return;
    closeK();
    hit.run();
  }

  function renderK(q, keepSel) {
    const box = $("ck-box");
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const rank = { Action: 5, Scene: 5, Page: 3, Setting: 2, Help: 1 };
    kHits = !words.length ? (box.index || []).filter((h) => h.kind === "Scene" || h.kind === "Action").slice(0, 10)
      : (box.index || []).map((h) => {
          const hay = (h.text + " " + h.where + " " + (h.kw || "")).toLowerCase();
          if (!words.every((w) => hay.includes(w))) return null;
          const t = h.text.toLowerCase();
          return { h, s: (t.startsWith(q.toLowerCase()) ? 6 : 0) + (t.includes(q.toLowerCase()) ? 3 : 0) + rank[h.kind] };
        }).filter(Boolean).sort((a, b) => b.s - a.s || a.h.text.length - b.h.text.length).slice(0, 14).map((x) => x.h);
    if (!keepSel) kSel = 0;
    $("ck-results").innerHTML = kHits.length
      ? kHits.map((h, i) => `<button type="button" role="option" class="ck-hit${i === kSel ? " sel" : ""}" data-k="${i}" aria-selected="${i === kSel}">` +
          `<span class="ck-kind">${esc(h.kind)}</span><span>${esc(h.text)}</span><small>${esc(h.where)}</small></button>`).join("")
      : `<p class="muted">Nothing matches “${esc(q)}”.</p>`;
    const sel = $("ck-results").querySelector(".sel");
    if (sel) sel.scrollIntoView({ block: "nearest" });
  }

  document.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key === "k" || ev.key === "K")) {
      ev.preventDefault();
      openK();
    } else if (ev.key === "Escape") {
      const help = $("help-panel");
      if (help && !help.hidden) help.hidden = true;
    }
  });

  addHelpButtons();
  // a "Find anything (Ctrl+K)" button under the sidebar search, for mouse and phone users
  const navSearch = document.querySelector(".nav-search");
  if (navSearch && !$("ck-open")) {
    const b = document.createElement("button");
    b.type = "button";
    b.id = "ck-open";
    b.className = "link-btn ck-open";
    b.textContent = "Find anything (Ctrl+K)";
    b.onclick = openK;
    navSearch.appendChild(b);
  }

  window.LiveExtras = { openLive, openHelp, openK, applyLayout };
  // admin.js may have opened Live before this file loaded
  const live = $("tab-live");
  if (live && live.classList.contains("active")) openLive();
})();
