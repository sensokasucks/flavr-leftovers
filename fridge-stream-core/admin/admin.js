(() => {
  const $ = (id) => document.getElementById(id);
  const tokenKey = "stream_core_admin_token";

  function token() {
    return localStorage.getItem(tokenKey) || $("token").value.trim();
  }

  function headers() {
    return {
      "Content-Type": "application/json",
      "X-Admin-Token": token(),
    };
  }

  /** FastAPI answers errors as {"detail": ...}; show the detail, not the JSON around it. */
  function readableError(text, status, statusText) {
    let msg = text || statusText || ("HTTP " + status);
    try {
      const j = JSON.parse(text);
      const d = j && j.detail !== undefined ? j.detail : j && j.error;
      if (typeof d === "string") msg = d;
      else if (Array.isArray(d)) msg = d.map((x) => (x.loc ? x.loc.slice(1).join(".") + ": " : "") + (x.msg || JSON.stringify(x))).join("; ");
      else if (d && typeof d === "object") msg = JSON.stringify(d);
    } catch (_) {}
    if (status === 401 && !/token/i.test(msg)) msg = "Admin token missing or wrong. " + msg;
    return msg;
  }

  // A 401 anywhere: bring the token box back (it hides once a token is saved) and point at it.
  let tokenNag = 0;
  function needToken() {
    const row = $("token-row");
    if (!row) return;
    row.classList.remove("has-token");
    row.classList.add("needs-token");
    if ($("token-change")) $("token-change").hidden = true;
    if (!tokenNag) {
      tokenNag = 1;
      setStatus("Paste the admin token: it's printed when Stream Core starts, and saved in data/admin_token.txt (or set points.admin_token in config.yaml).", false);
      $("token").focus();
    }
  }

  /**
   * "Deleted X · Undo" at the bottom of the page for edits that only change the form (nothing is
   * written until Save), instead of an "Are you sure?" box. Announced to screen readers.
   */
  let undoTimer = 0;
  function undoToast(message, undo) {
    let box = $("undo-toast");
    if (!box) {
      box = document.createElement("div");
      box.id = "undo-toast";
      box.className = "undo-toast";
      box.setAttribute("role", "status");
      box.setAttribute("aria-live", "polite");
      document.body.appendChild(box);
    }
    box.innerHTML = "";
    const msg = document.createElement("span");
    msg.textContent = message;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Undo";
    btn.onclick = () => {
      box.hidden = true;
      clearTimeout(undoTimer);
      undo();
    };
    const close = document.createElement("button");
    close.type = "button";
    close.className = "link-btn";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "×";
    close.onclick = () => { box.hidden = true; };
    box.append(msg, btn, close);
    box.hidden = false;
    clearTimeout(undoTimer);
    undoTimer = setTimeout(() => { box.hidden = true; }, 10000);
  }
  // Ctrl/Cmd+Z right after a delete undoes it too (not while typing in a box)
  document.addEventListener("keydown", (ev) => {
    if (!(ev.ctrlKey || ev.metaKey) || String(ev.key).toLowerCase() !== "z") return;
    const box = $("undo-toast");
    const t = ev.target;
    if (!box || box.hidden || (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable))) return;
    ev.preventDefault();
    box.querySelector("button").click();
  });

  // High contrast: brighter text, solid borders, stronger focus outline. Follows the system
  // "more contrast" setting until you pick; the choice is remembered in this browser.
  const hcKey = "stream_core_high_contrast";
  function applyContrast() {
    let pref = null;
    try { pref = localStorage.getItem(hcKey); } catch (_) {}
    const on = pref === null ? window.matchMedia("(prefers-contrast: more)").matches : pref === "1";
    document.documentElement.classList.toggle("hc", on);
    const b = $("hc-toggle");
    if (b) b.setAttribute("aria-pressed", on ? "true" : "false");
  }
  if ($("hc-toggle")) {
    $("hc-toggle").onclick = () => {
      const on = !document.documentElement.classList.contains("hc");
      try { localStorage.setItem(hcKey, on ? "1" : "0"); } catch (_) {}
      applyContrast();
    };
  }
  applyContrast();

  // Write calls that worked / calls that failed. The page save bar compares these around a
  // section's own save handler (those catch their errors) to tell whether the save went through.
  var apiWrites = 0;
  var apiFails = 0;

  async function api(path, opts = {}) {
    const write = String(opts.method || "GET").toUpperCase() !== "GET";
    let res;
    try {
      res = await fetch(path, {
        ...opts,
        headers: { ...headers(), ...(opts.headers || {}) },
      });
    } catch (e) {
      apiFails += 1;
      throw e;
    }
    if (!res.ok) {
      apiFails += 1;
      const t = await res.text();
      if (res.status === 401) needToken();
      throw new Error(readableError(t, res.status, res.statusText));
    }
    if (write) apiWrites += 1;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res;
  }

  function setStatus(msg, ok = true) {
    const el = $("status");
    el.textContent = msg;
    el.style.color = ok ? "#53fc18" : "#ff5c5c";
  }

  function setCfgStatus(msg, ok = true) {
    const el = $("cfg-status");
    if (!el) return;
    el.textContent = msg;
    el.style.color = ok ? "#53fc18" : "#ff5c5c";
  }

  function setCmdStatus(msg, ok = true) {
    const el = $("cmd-status");
    if (!el) return;
    el.textContent = msg;
    el.style.color = ok ? "#53fc18" : "#ff5c5c";
  }

  // Token
  // "change-me" is never accepted any more — paste the real token.
  $("token").value = localStorage.getItem(tokenKey) || "";
  $("save-token").onclick = () => {
    localStorage.setItem(tokenKey, $("token").value.trim());
    tokenNag = 0;
    $("token-row").classList.remove("needs-token");
    setStatus("Token saved");
    refreshStats();
    loadStatus();
    loadUsers();
    if ($("tab-alerts") && $("tab-alerts").classList.contains("active")) {
      initAlertsTab(true);
    }
    if ($("tab-integrations") && $("tab-integrations").classList.contains("active")) {
      initIntegrationsTab(true);
    }
  };

  // ------------------------------------------------------------------
  // Navigation: flat sidebar -> page -> (optional) sub-page pills.
  // One sub-page is shown at a time; there are no accordions to open.
  // Address is #page or #page/sub so Back works and links can deep-link.
  // ------------------------------------------------------------------
  const navStateKey = "stream_core_admin_nav";
  // Config sub-pages that the "Save config.yaml" bar applies to.
  const YAML_SUBS = new Set(["core", "games", "points", "advanced"]);

  function loadJson(key, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key) || "") || fallback;
    } catch {
      return fallback;
    }
  }

  function saveJson(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (_) { /* ignore quota */ }
  }

  function stackFor(tabId) {
    const panel = $("tab-" + tabId);
    return panel ? panel.querySelector(".acc-stack[data-acc]") : null;
  }

  function subsFor(tabId) {
    const stack = stackFor(tabId);
    if (!stack) return [];
    return [...stack.querySelectorAll(":scope > .acc[data-sub]:not([data-aside])")].map((el) => el.dataset.sub);
  }

  // Every paged stack: sub-pages always open, summaries hidden by CSS.
  document.querySelectorAll(".acc-stack[data-acc]").forEach((stack) => {
    stack.classList.add("paged");
    if (stack.querySelector(":scope > .acc[data-aside]")) stack.classList.add("has-aside");
    stack.querySelectorAll(":scope > .acc[data-sub]").forEach((el) => {
      el.open = true;
      const sum = el.querySelector(":scope > summary");
      if (sum) sum.addEventListener("click", (ev) => ev.preventDefault());
    });
  });

  function showSub(tabId, sub) {
    const stack = stackFor(tabId);
    if (!stack) return null;
    const subs = subsFor(tabId);
    if (!subs.length) return null;
    const nav = loadJson(navStateKey, {});
    const remembered = (nav.subs || {})[tabId];
    const pick = subs.includes(sub) ? sub : subs.includes(remembered) ? remembered : subs[0];
    stack.querySelectorAll(":scope > .acc[data-sub]").forEach((el) => {
      const on = el.hasAttribute("data-aside") || el.dataset.sub === pick;
      el.hidden = !on;
      el.open = true;
    });
    const bar = document.querySelector('.subtabs[data-subtabs="' + stack.dataset.acc + '"]');
    if (bar) {
      bar.querySelectorAll(".subtab[data-sub]").forEach((b) => b.classList.toggle("active", b.dataset.sub === pick));
    }
    const panel = $("tab-" + tabId);
    if (panel) panel.dataset.sub = pick;
    if (tabId === "config" && panel) panel.classList.toggle("yaml-sub", YAML_SUBS.has(pick));
    nav.subs = { ...(nav.subs || {}), [tabId]: pick };
    saveJson(navStateKey, nav);
    return pick;
  }

  function markNav(tabId, sub) {
    document.querySelectorAll(".admin-nav .tab").forEach((b) => {
      const hit = b.dataset.tab === tabId && (!b.dataset.sub || b.dataset.sub === sub);
      b.classList.toggle("active", hit);
      if (hit) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
      if (hit && $("nav-toggle-label")) $("nav-toggle-label").textContent = b.textContent.trim();
    });
  }

  // Page title at the top of every page (the sidebar name; Settings pages use the sub name).
  document.querySelectorAll(".panel").forEach((panel) => {
    if (panel.querySelector(":scope > .page-head")) return;
    const head = document.createElement("div");
    head.className = "page-head";
    head.innerHTML = '<h2 class="page-title"></h2>';
    panel.prepend(head);
    const intro = panel.querySelector(":scope > .tab-intro");
    if (intro) head.appendChild(intro);
  });

  function setPageTitle(tabId, sub) {
    const panel = $("tab-" + tabId);
    const h = panel && panel.querySelector(":scope > .page-head .page-title");
    if (!h) return;
    const exact = sub && document.querySelector('.admin-nav .tab[data-tab="' + tabId + '"][data-sub="' + sub + '"]');
    const page = document.querySelector('.admin-nav .tab[data-tab="' + tabId + '"]');
    h.textContent = (exact || page || { textContent: tabId }).textContent.trim();
  }

  function activateTab(tabId, sub) {
    const panel = $("tab-" + tabId);
    if (!panel) return;
    const wasActive = panel.classList.contains("active");
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p === panel));
    const pick = showSub(tabId, sub);
    markNav(tabId, pick);
    setPageTitle(tabId, pick);
    const nav = loadJson(navStateKey, {});
    nav.lastTab = tabId;
    saveJson(navStateKey, nav);
    const hash = "#" + tabId + (pick ? "/" + pick : "");
    if (location.hash !== hash) history.replaceState(null, "", hash);
    if (!wasActive) window.scrollTo(0, 0);
    if (liveTimer && tabId !== "live") {
      clearInterval(liveTimer);
      liveTimer = 0;
    }
    if (wasActive) return;
    if (tabId === "config") {
      loadConfigForm();
      loadGroups();
      loadCommands();
      loadReactions();
    }
    if (tabId === "live") {
      loadLive();
      loadFun();
    }
    if (tabId === "fun") loadFun();
    if (tabId === "status") loadStatus();
    if (tabId === "sources") loadSources();
    if (tabId === "alerts") initAlertsTab();
    if (tabId === "integrations") initIntegrationsTab();
    if (tabId === "credits") initCreditsTab();
    if (tabId === "market") initMarketTab();
    if (tabId === "chat") {
      loadChat();
      refreshChatLogBanner();
    }
  }

  function go(tabId, sub) {
    if (!pageCanLeave(tabId)) return;
    if (typeof setNavOpen === "function" && narrow) setNavOpen(false);
    const hash = "#" + tabId + (sub ? "/" + sub : "");
    if (location.hash !== hash) history.pushState(null, "", hash);
    activateTab(tabId, sub);
  }

  function routeFromHash() {
    const raw = decodeURIComponent((location.hash || "").replace(/^#/, ""));
    if (!raw) return false;
    const [tabId, sub] = raw.split("/");
    if (!$("tab-" + tabId)) return false;
    if (!pageCanLeave(tabId)) {
      // Back / Forward away from unsaved edits: stay, and put the address back
      const cur = document.querySelector(".panel.active");
      const here = cur ? cur.id.replace(/^tab-/, "") : "";
      if (here) history.pushState(null, "", "#" + here + (cur.dataset.sub ? "/" + cur.dataset.sub : ""));
      return true;
    }
    activateTab(tabId, sub);
    return true;
  }

  document.querySelectorAll(".admin-nav .tab").forEach((btn) => {
    btn.onclick = () => {
      go(btn.dataset.tab, btn.dataset.sub);
      setNavOpen(false);
    };
  });

  // Narrow screens (phone / tablet beside the stream): the sidebar becomes a drawer behind "☰ Menu".
  var narrow = window.matchMedia("(max-width: 900px)");
  function setNavOpen(open) {
    const on = !!open && narrow.matches;
    document.body.classList.toggle("nav-open", on);
    if ($("nav-toggle")) $("nav-toggle").setAttribute("aria-expanded", on ? "true" : "false");
    if (on && $("nav-search")) $("nav-search").focus();
  }
  if ($("nav-toggle")) $("nav-toggle").onclick = () => setNavOpen(!document.body.classList.contains("nav-open"));
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && document.body.classList.contains("nav-open")) {
      setNavOpen(false);
      $("nav-toggle").focus();
    }
  });
  document.addEventListener("click", (ev) => {
    if (!document.body.classList.contains("nav-open")) return;
    if (ev.target.closest("#admin-nav") || ev.target.closest("#nav-toggle")) return;
    setNavOpen(false);
  });
  narrow.addEventListener("change", () => setNavOpen(false));
  document.querySelectorAll(".subtabs").forEach((bar) => {
    const panel = bar.closest(".panel");
    bar.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".subtab[data-sub]");
      if (btn && panel) go(panel.id.replace(/^tab-/, ""), btn.dataset.sub);
    });
  });
  window.addEventListener("popstate", routeFromHash);
  window.addEventListener("hashchange", routeFromHash);

  // ------------------------------------------------------------------
  // Search: pages, sub-pages and every labelled setting.
  // ------------------------------------------------------------------
  let searchIndex = [];
  let searchHits = [];
  let searchSel = 0;

  function cleanText(el) {
    const c = el.cloneNode(true);
    c.querySelectorAll("input, select, textarea, button, .field-help, option").forEach((n) => n.remove());
    return c.textContent.replace(/\s+/g, " ").trim();
  }

  function pageTitle(tabId, sub) {
    const exact = document.querySelector('.admin-nav .tab[data-tab="' + tabId + '"][data-sub="' + sub + '"]');
    if (exact) return exact.textContent.trim();
    const page = document.querySelector('.admin-nav .tab[data-tab="' + tabId + '"]');
    let title = page ? page.textContent.trim() : tabId;
    if (sub) {
      const pill = document.querySelector('#tab-' + tabId + ' .subtab[data-sub="' + sub + '"]');
      if (pill) title += " › " + pill.textContent.trim();
    }
    return title;
  }

  function buildSearchIndex() {
    const out = [];
    const seen = new Set();
    const add = (text, tabId, sub, el, kind, group, keywords) => {
      if (!text || text.length < 2) return;
      const key = tabId + "|" + (sub || "") + "|" + (group || "") + "|" + text.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      const where = pageTitle(tabId, sub) + (group && group.toLowerCase() !== text.toLowerCase() ? " › " + group : "");
      out.push({ text, tabId, sub: sub || "", el, kind, where, lc: text.toLowerCase(), kw: (keywords || "").toLowerCase() });
    };
    document.querySelectorAll(".admin-nav .tab").forEach((b) => add(b.textContent.trim(), b.dataset.tab, b.dataset.sub, null, "page", "", b.dataset.keywords));
    document.querySelectorAll(".subtab[data-sub]").forEach((b) => {
      const panel = b.closest(".panel");
      if (panel) add(b.textContent.trim(), panel.id.replace(/^tab-/, ""), b.dataset.sub, null, "page");
    });
    document.querySelectorAll(".panel label, .panel legend, .panel h3, .panel .acc > summary, .panel .cs-motion, .panel .cs-preset").forEach((el) => {
      const panel = el.closest(".panel");
      if (!panel) return;
      const tabId = panel.id.replace(/^tab-/, "");
      if (tabId === "live") return;
      const acc = el.closest(".acc-stack.paged > .acc[data-sub]");
      const sub = acc && !acc.hasAttribute("data-aside") ? acc.dataset.sub : "";
      const isChip = el.classList.contains("cs-motion") || el.classList.contains("cs-preset");
      const text = isChip ? (el.querySelector("b") || el).textContent.trim() : cleanText(el);
      if (text.length > 70) return;
      const fs = el.closest("fieldset");
      const legend = fs && fs.querySelector(":scope > legend");
      let group = legend && legend !== el ? cleanText(legend) : "";
      if (isChip) group = el.classList.contains("cs-motion") ? "Motion" : "Preset";
      add(text, tabId, sub, el, el.tagName === "LABEL" || isChip ? "setting" : "section", group);
    });
    searchIndex = out;
  }

  function renderSearch(q) {
    const box = $("nav-results");
    q = q.trim().toLowerCase();
    if (!q) {
      box.hidden = true;
      searchHits = [];
      return;
    }
    const words = q.split(/\s+/);
    const score = (it) => {
      const hay = it.lc + " " + it.where.toLowerCase() + " " + it.kw;
      if (!words.every((w) => hay.includes(w))) return -1;
      let s = 0;
      if (it.lc.startsWith(q)) s += 4;
      if (it.lc.includes(q)) s += 2;
      if (it.kind === "page") s += 3;
      if (it.kind === "section") s += 1;
      return s;
    };
    searchHits = searchIndex
      .map((it) => ({ it, s: score(it) }))
      .filter((x) => x.s >= 0)
      .sort((a, b) => b.s - a.s || a.it.text.length - b.it.text.length)
      .slice(0, 12)
      .map((x) => x.it);
    searchSel = 0;
    box.innerHTML = searchHits.length
      ? searchHits.map((it, i) =>
          `<button type="button" class="nav-hit${i === 0 ? " sel" : ""}" data-i="${i}">` +
          `<span>${escapeHtml(it.text)}</span><small>${escapeHtml(it.kind === "page" && !it.sub ? "Page" : it.where)}</small></button>`
        ).join("")
      : `<div class="nav-none">Nothing matches “${escapeHtml(q)}”</div>`;
    box.hidden = false;
  }

  function openHit(it) {
    if (!it) return;
    const input = $("nav-search");
    input.value = "";
    renderSearch("");
    input.blur();
    go(it.tabId, it.sub || undefined);
    if (!it.el) return;
    const target = it.el.closest(".acc > summary") ? it.el.closest(".acc") : it.el;
    setTimeout(() => {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.remove("flash");
      void target.offsetWidth;
      target.classList.add("flash");
      const field = it.el.tagName === "LABEL" ? it.el.querySelector("input, select, textarea") : null;
      if (field) setTimeout(() => field.focus({ preventScroll: true }), 350);
    }, 60);
  }

  if ($("nav-search")) {
    const input = $("nav-search");
    input.addEventListener("focus", () => {
      buildSearchIndex();
      renderSearch(input.value);
    });
    input.addEventListener("input", () => renderSearch(input.value));
    input.addEventListener("keydown", (ev) => {
      const box = $("nav-results");
      const items = [...box.querySelectorAll(".nav-hit")];
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        if (!items.length) return;
        searchSel = (searchSel + (ev.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach((b, i) => b.classList.toggle("sel", i === searchSel));
        items[searchSel].scrollIntoView({ block: "nearest" });
      } else if (ev.key === "Enter") {
        ev.preventDefault();
        openHit(searchHits[searchSel]);
      } else if (ev.key === "Escape") {
        input.value = "";
        renderSearch("");
        input.blur();
      }
    });
    input.addEventListener("blur", () => setTimeout(() => { $("nav-results").hidden = true; }, 150));
    $("nav-results").addEventListener("mousedown", (ev) => {
      const b = ev.target.closest(".nav-hit");
      if (!b) return;
      ev.preventDefault();
      openHit(searchHits[Number(b.dataset.i)]);
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key !== "/" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      const t = ev.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      ev.preventDefault();
      input.focus();
    });
  }

  // ------------------------------------------------------------------
  // Token: collapse the field once a token is saved.
  // ------------------------------------------------------------------
  function syncTokenRow() {
    const row = $("token-row");
    if (!row) return;
    const has = !!localStorage.getItem(tokenKey);
    row.classList.toggle("has-token", has);
    if ($("token-change")) $("token-change").hidden = !has;
  }
  if ($("token-change")) {
    $("token-change").onclick = () => {
      $("token-row").classList.remove("has-token");
      $("token-change").hidden = true;
      $("token").focus();
    };
  }
  if ($("save-token")) $("save-token").addEventListener("click", syncTokenRow);
  syncTokenRow();

  // ------------------------------------------------------------------
  // Live controls page
  // ------------------------------------------------------------------
  let liveTimer = 0;

  // Live buttons press the real button on the feature page, so each action
  // has one implementation.
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-proxy]");
    if (!btn) return;
    const real = $(btn.dataset.proxy);
    if (real) real.click();
  });

  async function loadLiveStatus() {
    const box = $("live-status");
    if (!box) return;
    try {
      const s = await api("/api/admin/status");
      const chips = [];
      for (const [name, p] of Object.entries(s.platforms || {})) {
        if (!p.configured_enabled && !p.running) continue;
        chips.push(pill(!!p.running, escapeHtml(name) + (p.running ? "" : " stopped")));
      }
      for (const [name, g] of Object.entries(s.games || {})) {
        if (!g.configured_enabled && !g.running) continue;
        chips.push(pill(!!g.running, escapeHtml(name) + (g.running ? "" : " stopped")));
      }
      if (!chips.length) chips.push('<span class="muted">No chat platforms or games switched on</span>');
      const m = s.metrics || {};
      const cr = s.credits || {};
      const rx = s.reactions || {};
      if ($("live-stage-state")) {
        const cur = (rx.stage || {}).curtain;
        $("live-stage-state").textContent = !rx.game_connected ? "Stream Rooms not connected" : cur ? "curtain " + cur : "";
      }
      box.innerHTML =
        `<div class="live-chips">${chips.join("")}</div>` +
        `<div class="live-metrics">` +
        `<span>Viewers <strong>${m.viewers ?? 0}</strong></span>` +
        `<span>Chat / min <strong>${Number(m.cpm ?? 0).toFixed(1)}</strong></span>` +
        `<span>Credits <strong>${cr.running ? (cr.count || 0) + " names" : "off"}</strong></span>` +
        `<span class="muted">${new Date().toLocaleTimeString()}</span></div>`;
    } catch (e) {
      box.innerHTML = `<span class="muted">Can't reach Core: ${escapeHtml(String(e.message || e))}</span>`;
    }
  }

  async function loadLiveCredits() {
    try {
      const data = await api("/api/admin/credits");
      renderCreditsPlay(data.play);
      renderCreditsRoster(data.roster);
      connectCreditsWs();
    } catch (e) {
      if ($("live-crd-state")) $("live-crd-state").textContent = String(e.message || e);
    }
  }

  async function loadLiveAlerts() {
    const host = $("live-alerts");
    if (!host) return;
    await initAlertsTab();
    const kinds = alertKinds || [];
    if (!kinds.length) {
      host.innerHTML = '<span class="muted">No alert kinds (is the token saved?)</span>';
      return;
    }
    host.innerHTML = "";
    kinds.forEach((k) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = k.label;
      b.onclick = () => {
        const real = document.querySelector('#alert-presets button[data-kind="' + k.kind + '"]');
        if (real) real.click();
      };
      host.appendChild(b);
    });
    if ($("live-alert-user") && $("alert-username")) {
      $("live-alert-user").textContent = $("alert-username").value || "TestViewer";
    }
  }

  function loadLive() {
    loadLiveStatus();
    loadLiveCredits();
    loadLiveAlerts();
    if (liveTimer) clearInterval(liveTimer);
    liveTimer = setInterval(() => {
      if ($("tab-live") && $("tab-live").classList.contains("active")) loadLiveStatus();
    }, 15000);
  }

  // Mirror the alert status line onto the Live page.
  if ($("alert-status") && $("live-alert-status")) {
    new MutationObserver(() => {
      $("live-alert-status").textContent = $("alert-status").textContent;
      $("live-alert-status").style.color = $("alert-status").style.color;
    }).observe($("alert-status"), { childList: true, characterData: true, subtree: true, attributes: true });
  }

  async function liveCommand() {
    const text = ($("live-cmd-input").value || "").trim();
    if (!text || !$("integ-message")) return;
    $("integ-message").value = text;
    await runCommandTest(true);
    const src = $("integ-cmd-result");
    const out = $("live-cmd-result");
    if (src && out) {
      out.hidden = src.hidden;
      out.className = src.className;
      out.textContent = src.textContent;
    }
  }
  if ($("live-cmd-run")) $("live-cmd-run").onclick = liveCommand;
  if ($("live-cmd-input")) {
    $("live-cmd-input").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") liveCommand();
    });
  }

  function pill(ok, label) {
    const cls = ok ? "pill ok" : "pill off";
    return `<span class="${cls}">${label}</span>`;
  }

  async function loadStatus() {
    const body = $("status-body");
    if (!body) return;
    try {
      const s = await api("/api/admin/status");
      const m = s.metrics || {};
      let html = "";
      html += `<div class="cfg-card"><legend>Core</legend>
        <p>Listening on <code>${s.core.host}:${s.core.port}</code> · prefix <code>${s.core.command_prefix}</code></p>
        <p>Active command groups: <strong>${(s.command_groups_active || []).join(", ") || "—"}</strong>
        · ${s.commands_loaded || 0} command defs loaded</p>
        <p>Points system: ${s.points_enabled ? pill(true, "on") : pill(false, "off")}
        · Chat log: ${s.chat_log_enabled ? pill(true, "on") : pill(false, "off")}
        · Credits: ${s.credits && s.credits.running ? pill(true, "on") : pill(false, "off")}
          ${s.credits ? `<span class="muted">${s.credits.count || 0} unique</span>` : ""}</p>
      </div>`;

      html += `<div class="cfg-card"><legend>Chat platforms</legend><ul class="status-list">`;
      for (const [name, p] of Object.entries(s.platforms || {})) {
        const run = p.running;
        const want = p.configured_enabled;
        let note = "";
        if (want && !run) note = " (enabled but not connected — check the channel, then Reconnect)";
        if (!want && !run) note = " (disabled)";
        html += `<li><strong>${name}</strong> ${run ? pill(true, "running") : pill(false, "stopped")}
          ${want ? pill(true, "config on") : pill(false, "config off")}
          ${p.detail ? `<span class="muted">${p.detail}</span>` : ""}
          <span class="muted">${note}</span>
          ${want ? `<button class="platform-reconnect" data-platform="${name}">Reconnect</button>` : ""}</li>`;
      }
      html += `</ul></div>`;

      html += `<div class="cfg-card"><legend>Game integrations</legend><ul class="status-list">`;
      for (const [name, g] of Object.entries(s.games || {})) {
        html += `<li><strong>${name}</strong> ${g.running ? pill(true, "running") : pill(false, "stopped")}
          ${g.configured_enabled ? pill(true, "config on") : pill(false, "config off")}
          ${g.player_name ? `<span class="muted">player ${g.player_name}</span>` : ""}</li>`;
      }
      html += `</ul>
        <p class="hint">Commands are grouped by integration. Stopped games hide their command group. Factorio and Granvir start as stats/overlay only; Granvir chat commands stay host-only in the BepInEx plugin.</p>
      </div>`;

      html += `<div class="cfg-card"><legend>Live metrics</legend>
        <p>Viewers <strong>${m.viewers ?? 0}</strong>
        · CPM <strong>${(m.cpm ?? 0).toFixed ? m.cpm.toFixed(1) : m.cpm}</strong>
        · Power <strong>${m.power_level ?? 0}</strong>/15
        · Cmd rate <strong>${m.command_rate ?? 0}</strong></p>
      </div>`;

      body.innerHTML = html;
      body.querySelectorAll(".platform-reconnect").forEach((btn) => {
        btn.onclick = async () => {
          btn.disabled = true;
          try {
            const res = await api(`/api/admin/platforms/${btn.dataset.platform}/reconnect`, { method: "POST" });
            setStatus(res.message || "Reconnected", res.ok !== false);
          } catch (e) {
            setStatus(String(e.message || e), false);
          }
          loadStatus();
        };
      });
      if ($("status-updated")) {
        $("status-updated").textContent = "Updated " + new Date().toLocaleTimeString();
      }
      setStatus("Status loaded");
    } catch (e) {
      body.innerHTML = `<p class="muted">Could not load status: ${e.message || e}</p>`;
      setStatus(String(e.message || e), false);
    }
  }

  async function loadSources() {
    const tb = $("sources-table") && $("sources-table").querySelector("tbody");
    if (!tb) return;
    try {
      const s = await api("/api/admin/status");
      tb.innerHTML = "";
      for (const src of s.sources || []) {
        const tr = document.createElement("tr");
        tr.innerHTML =
          `<td><strong>${src.name}</strong></td>` +
          `<td><code class="url-cell">${src.url}</code></td>` +
          `<td class="muted">${src.notes || ""}</td>` +
          `<td><button type="button" class="copy-url" data-url="${src.url.replace(/"/g, "&quot;")}">Copy</button></td>`;
        tb.appendChild(tr);
      }
      tb.querySelectorAll(".copy-url").forEach((btn) => {
        btn.onclick = async () => {
          try {
            await navigator.clipboard.writeText(btn.dataset.url);
            setStatus("Copied URL");
          } catch {
            setStatus("Copy failed — select the URL manually", false);
          }
        };
      });
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }

  if ($("status-refresh")) $("status-refresh").onclick = () => loadStatus();
  // Status keeps itself current while it's open (platforms reconnect on their own after a save).
  setInterval(() => {
    if ($("tab-status") && $("tab-status").classList.contains("active") && document.visibilityState === "visible") loadStatus();
  }, 10000);
  if ($("sources-refresh")) $("sources-refresh").onclick = () => loadSources();

  // ------------------------------------------------------------------
  // Alert test tab
  // ------------------------------------------------------------------

  let alertKinds = [];
  let alertsReady = false;

  function setAlertStatus(msg, ok = true) {
    const el = $("alert-status");
    if (!el) return;
    el.textContent = msg;
    el.style.color = ok ? "#53fc18" : "#ff5c5c";
  }

  function applyKindDefaults(kind) {
    const meta = alertKinds.find((k) => k.kind === kind);
    if (!meta) return;
    const d = meta.defaults || {};
    if (d.amount != null && $("alert-amount")) $("alert-amount").value = d.amount;
    if (d.currency && $("alert-currency")) $("alert-currency").value = d.currency;
    if (d.months != null && $("alert-months")) $("alert-months").value = d.months;
    if (d.qty != null && $("alert-qty")) $("alert-qty").value = d.qty;
    if (d.viewers != null && $("alert-viewers")) $("alert-viewers").value = d.viewers;
    if (meta.accent && $("alert-platform")) {
      const sel = $("alert-platform");
      const ok = [...sel.options].some((o) => o.value === meta.accent);
      if (ok) sel.value = meta.accent;
    }
  }

  async function initAlertsTab(force) {
    if (alertsReady && !force) return;
    const kindSel = $("alert-kind");
    const presets = $("alert-presets");
    if (!kindSel || !presets) return;
    try {
      const data = await api("/api/admin/alerts/kinds");
      alertKinds = data.kinds || [];
      kindSel.innerHTML = "";
      presets.innerHTML = "";
      for (const k of alertKinds) {
        const opt = document.createElement("option");
        opt.value = k.kind;
        opt.textContent = k.label;
        kindSel.appendChild(opt);

        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = k.label;
        btn.dataset.kind = k.kind;
        btn.onclick = () => {
          kindSel.value = k.kind;
          applyKindDefaults(k.kind);
          fireTestAlert();
        };
        presets.appendChild(btn);
      }
      if (data.default_duration_ms && $("alert-duration")) {
        $("alert-duration").value = data.default_duration_ms;
      }
      kindSel.onchange = () => applyKindDefaults(kindSel.value);
      if (alertKinds.length) applyKindDefaults(kindSel.value);
      alertsReady = true;
      setAlertStatus("Ready — click a preset or Fire test alert");
      loadAlertStyle();
    } catch (e) {
      alertsReady = false;
      setAlertStatus(String(e.message || e), false);
      setStatus(String(e.message || e), false);
    }
  }

  function optNum(id) {
    const el = $(id);
    if (!el) return null;
    const v = String(el.value || "").trim();
    if (v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  async function fireTestAlert() {
    const kind = ($("alert-kind") && $("alert-kind").value) || "follow";
    const body = {
      kind,
      username: ($("alert-username") && $("alert-username").value.trim()) || "TestViewer",
      platform: ($("alert-platform") && $("alert-platform").value) || "kick",
      currency: ($("alert-currency") && $("alert-currency").value.trim()) || "USD",
      message: ($("alert-message") && $("alert-message").value) || "",
      amount: optNum("alert-amount"),
      months: optNum("alert-months"),
      qty: optNum("alert-qty"),
      viewers: optNum("alert-viewers"),
      duration_ms: optNum("alert-duration"),
    };
    const btn = $("alert-fire");
    if (btn) btn.disabled = true;
    setAlertStatus("Firing…");
    try {
      const res = await api("/api/admin/alerts/test", {
        method: "POST",
        body: JSON.stringify(body),
      });
      const h = (res.alert && res.alert.headline) || kind;
      setAlertStatus("Fired: " + h);
      setStatus("Test alert: " + h);
    } catch (e) {
      setAlertStatus(String(e.message || e), false);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  if ($("alert-fire")) $("alert-fire").onclick = fireTestAlert;

  function setCssStatus(msg, ok = true) {
    const el = $("alert-css-status");
    if (!el) return;
    el.textContent = msg;
    el.style.color = ok ? "#53fc18" : "#ff5c5c";
  }

  function selectedSkin() {
    const el = document.querySelector('input[name="alert-skin"]:checked');
    return (el && el.value) || "classic";
  }

  function applyPreviewSkin(skin) {
    const iframe = $("alert-preview");
    if (!iframe) return;
    iframe.src = "/overlay/alerts.html?preview=1&skin=" + encodeURIComponent(skin || "classic");
  }

  async function loadAlertStyle() {
    if (!$("alert-css")) return;
    try {
      const data = await api("/api/admin/alerts/style");
      const skin = data.skin || "classic";
      const radio = $("alert-skin-" + skin);
      if (radio) radio.checked = true;
      $("alert-css").value = data.css || "";
      applyPreviewSkin(skin);
      setCssStatus("Loaded");
    } catch (e) {
      setCssStatus(String(e.message || e), false);
    }
  }

  async function saveAlertStyle(opts) {
    const cssOnly = opts && opts.cssOnly;
    const skinOnly = opts && opts.skinOnly;
    const body = {};
    if (!cssOnly) body.skin = selectedSkin();
    if (!skinOnly) body.css = $("alert-css") ? $("alert-css").value : undefined;
    try {
      const res = await api("/api/admin/alerts/style", {
        method: "PUT",
        body: JSON.stringify(body),
      });
      applyPreviewSkin(res.skin || selectedSkin());
      setCssStatus(res.message || "Saved");
    } catch (e) {
      setCssStatus(String(e.message || e), false);
    }
  }

  document.querySelectorAll('input[name="alert-skin"]').forEach((el) => {
    el.onchange = () => saveAlertStyle({ skinOnly: true });
  });
  if ($("alert-css-save")) {
    $("alert-css-save").onclick = () => saveAlertStyle();
  }
  if ($("alert-css-reload")) {
    $("alert-css-reload").onclick = () => applyPreviewSkin(selectedSkin());
  }

  // Stats
  async function refreshStats() {
    try {
      const s = await api("/api/admin/stats");
      $("stats").innerHTML =
        `<span>Users <strong>${s.users}</strong></span>` +
        `<span>Messages <strong>${s.messages}</strong></span>` +
        `<span>Points in circulation <strong>${s.total_points}</strong></span>`;
      setStatus("Connected");
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }

  // ------------------------------------------------------------------
  // Integrations test bench (per-game sub-panels + command tester)
  // ------------------------------------------------------------------
  let integReady = false;
  let integData = null;

  function setIntegCmdStatus(msg, ok = true) {
    const el = $("integ-cmd-status");
    if (!el) return;
    el.textContent = msg;
    el.style.color = ok ? "#53fc18" : "#ff5c5c";
  }

  function showIntegResult(data, ok) {
    const pre = $("integ-cmd-result");
    if (!pre) return;
    pre.hidden = false;
    pre.classList.toggle("ok", !!ok);
    pre.classList.toggle("err", !ok);
    pre.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  }

  async function runCommandTest(dryRun) {
    const message = ($("integ-message") && $("integ-message").value.trim()) || "";
    if (!message) {
      setIntegCmdStatus("Enter a message (e.g. !spawn creeper)", false);
      return;
    }
    setIntegCmdStatus(dryRun ? "Dry run…" : "Live execute…");
    try {
      const res = await api("/api/admin/commands/test", {
        method: "POST",
        body: JSON.stringify({
          message,
          username: ($("integ-username") && $("integ-username").value.trim()) || "TestAdmin",
          platform: ($("integ-platform") && $("integ-platform").value) || "kick",
          is_admin: !!( $("integ-admin") && $("integ-admin").checked ),
          is_mod: !!( $("integ-mod") && $("integ-mod").checked ),
          is_subscriber: !!( $("integ-sub") && $("integ-sub").checked ),
          dry_run: !!dryRun,
        }),
      });
      const ok = !!res.ok;
      setIntegCmdStatus(
        ok
          ? (dryRun ? "Dry run OK — template rendered" : "Executed")
          : (res.error || "Failed"),
        ok
      );
      showIntegResult(res, ok);
    } catch (e) {
      setIntegCmdStatus(String(e.message || e), false);
      showIntegResult(String(e.message || e), false);
    }
  }

  function exampleForCommand(cmd, prefix) {
    if (cmd.examples && cmd.examples.length) return cmd.examples[0];
    const p = prefix || "!";
    if (cmd.args && cmd.args.length) {
      const sample = cmd.args
        .map((a) => {
          const low = String(a).toLowerCase();
          if (low.includes("qty")) return "1";
          if (low.includes("sec")) return "30";
          if (low.includes("entity")) return "creeper";
          if (low.includes("item")) return "diamond";
          if (low.includes("effect")) return "speed";
          return "arg";
        })
        .join(" ");
      return `${p}${cmd.name} ${sample}`.trim();
    }
    return `${p}${cmd.name}`;
  }

  function fillCommandTester(message) {
    if ($("integ-message")) $("integ-message").value = message;
    setIntegCmdStatus("Filled — Dry run or Live execute");
  }

  function renderGamePanel(game, prefix) {
    const cmds = game.commands || [];
    const cmdList =
      cmds.length === 0
        ? `<p class="integ-empty">No commands in group <code>${escapeHtml(game.command_group)}</code>. Add them under Config → Commands (group: ${escapeHtml(game.id)}).</p>`
        : `<ul class="integ-cmd-list">${cmds
            .map((c) => {
              const ex = exampleForCommand(c, prefix);
              return (
                `<li>` +
                `<code>!${escapeHtml(c.name)}</code>` +
                `<span class="cmd-desc">${escapeHtml(c.description || c.permission || "")}</span>` +
                `<button type="button" data-ex="${escapeHtml(ex)}" class="integ-fill">Fill</button>` +
                `<button type="button" data-ex="${escapeHtml(ex)}" class="integ-dry-one">Dry</button>` +
                `</li>`
              );
            })
            .join("")}</ul>`;

    const overlays =
      (game.overlays || [])
        .map(
          (o) =>
            `<div class="integ-overlay-row">` +
            `<strong>${escapeHtml(o.name)}</strong>` +
            `<a href="${escapeHtml(o.url)}" target="_blank" rel="noopener">${escapeHtml(o.url)}</a>` +
            `<button type="button" data-url="${escapeHtml(o.url)}" class="integ-copy">Copy</button>` +
            (o.notes ? `<span class="muted">${escapeHtml(o.notes)}</span>` : "") +
            `</div>`
        )
        .join("") || `<p class="integ-empty">No dedicated overlay for this integration.</p>`;

    const previewUrl =
      game.overlays && game.overlays[0] ? game.overlays[0].url + "?preview=1" : "";

    return (
      `<details class="integ-game-panel acc" open data-game="${escapeHtml(game.id)}">` +
      `<summary class="integ-game-head">` +
      `<h3>${escapeHtml(game.label)}</h3>` +
      pill(game.configured_enabled, game.configured_enabled ? "enabled in config" : "disabled in config") +
      pill(game.running, game.running ? "running" : "not running") +
      pill(game.health, game.health ? "healthy" : game.running ? "unreachable" : "offline") +
      `<button type="button" class="integ-health-btn" data-game="${escapeHtml(game.id)}">Recheck health</button>` +
      `</summary>` +
      `<div class="integ-game-body">` +
      `<div>` +
      `<p class="hint" style="margin-top:0">Commands in group <code>${escapeHtml(game.command_group)}</code>${game.player_name ? ` · player <code>${escapeHtml(game.player_name)}</code>` : ""}</p>` +
      cmdList +
      `</div>` +
      `<div>` +
      `<fieldset class="cfg-card" style="margin:0">` +
      `<legend>Metrics test</legend>` +
      `<p class="hint">Pushes synthetic viewers / CPM / power level (0–15) to this integration and overlays.</p>` +
      `<div class="integ-metrics-grid">` +
      `<label>Viewers <input type="number" class="integ-m-viewers" value="42" min="0" /></label>` +
      `<label>CPM <input type="number" class="integ-m-cpm" value="5" min="0" step="0.1" /></label>` +
      `<label>Cmd rate <input type="number" class="integ-m-cmd" value="1" min="0" step="0.1" /></label>` +
      `<label>Power 0–15 <input type="number" class="integ-m-power" value="8" min="0" max="15" /></label>` +
      `</div>` +
      `<div class="form-row" style="margin-top:10px">` +
      `<button type="button" class="primary integ-metrics-btn" data-game="${escapeHtml(game.id)}">Push metrics</button>` +
      `<span class="muted integ-metrics-status"></span>` +
      `</div>` +
      `</fieldset>` +
      `<div style="margin-top:12px">` +
      `<p class="hint" style="margin:0 0 6px">Overlays</p>` +
      overlays +
      (previewUrl
        ? `<div class="integ-preview-wrap"><div class="alert-preview-label">Preview</div>` +
          `<iframe src="${escapeHtml(previewUrl)}" title="${escapeHtml(game.label)} overlay"></iframe></div>`
        : "") +
      `</div>` +
      `</div>` +
      `</div>` +
      `</details>`
    );
  }

  async function initIntegrationsTab(force) {
    if (integReady && !force) return;
    const host = $("integ-games");
    if (!host) return;
    host.innerHTML = `<p class="muted">Loading integrations…</p>`;
    try {
      integData = await api("/api/admin/integrations");
      const prefix = integData.prefix || "!";
      const games = integData.games || [];
      if (!games.length) {
        host.innerHTML = `<p class="integ-empty">No game integrations registered. Enable Minecraft in Config and restart Core.</p>`;
      } else {
        host.innerHTML = games.map((g) => renderGamePanel(g, prefix)).join("");
      }

      const shared = $("integ-shared-overlays");
      if (shared) {
        const rows = integData.shared_overlays || [];
        shared.innerHTML = rows
          .map(
            (o) =>
              `<div class="integ-overlay-row">` +
              `<strong>${escapeHtml(o.name)}</strong>` +
              `<a href="${escapeHtml(o.url)}" target="_blank" rel="noopener">${escapeHtml(o.url)}</a>` +
              `<button type="button" data-url="${escapeHtml(o.url)}" class="integ-copy">Copy</button>` +
              (o.notes ? `<span class="muted">${escapeHtml(o.notes)}</span>` : "") +
              `</div>`
          )
          .join("");
      }

      // Wire dynamic buttons inside game panels
      host.querySelectorAll(".integ-fill").forEach((btn) => {
        btn.onclick = () => fillCommandTester(btn.dataset.ex || "");
      });
      host.querySelectorAll(".integ-dry-one").forEach((btn) => {
        btn.onclick = () => {
          fillCommandTester(btn.dataset.ex || "");
          runCommandTest(true);
        };
      });
      host.querySelectorAll(".integ-health-btn").forEach((btn) => {
        btn.onclick = async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const gid = btn.dataset.game;
          btn.disabled = true;
          try {
            const h = await api("/api/admin/games/" + encodeURIComponent(gid) + "/health");
            setIntegCmdStatus(
              `${gid}: ${h.health ? "healthy" : "unreachable"} (${h.detail || ""})`,
              !!h.health
            );
          } catch (e) {
            setIntegCmdStatus(String(e.message || e), false);
          }
          btn.disabled = false;
          initIntegrationsTab(true);
        };
      });
      host.querySelectorAll(".integ-metrics-btn").forEach((btn) => {
        btn.onclick = async () => {
          const panel = btn.closest(".integ-game-panel");
          const status = panel && panel.querySelector(".integ-metrics-status");
          const viewers = Number((panel.querySelector(".integ-m-viewers") || {}).value) || 0;
          const cpm = Number((panel.querySelector(".integ-m-cpm") || {}).value) || 0;
          const command_rate = Number((panel.querySelector(".integ-m-cmd") || {}).value) || 0;
          const power_level = Number((panel.querySelector(".integ-m-power") || {}).value) || 0;
          if (status) status.textContent = "Pushing…";
          try {
            const res = await api(
              "/api/admin/games/" + encodeURIComponent(btn.dataset.game) + "/metrics-test",
              {
                method: "POST",
                body: JSON.stringify({ viewers, cpm, command_rate, power_level }),
              }
            );
            if (status) {
              status.textContent = res.ok
                ? `OK → ${ (res.games_notified || []).join(", ") || "no games" }`
                : "Failed";
              status.style.color = res.ok ? "#53fc18" : "#ff5c5c";
            }
            showIntegResult(res, !!res.ok);
          } catch (e) {
            if (status) {
              status.textContent = String(e.message || e);
              status.style.color = "#ff5c5c";
            }
          }
        };
      });

      document.querySelectorAll(".integ-copy").forEach((btn) => {
        btn.onclick = async () => {
          try {
            await navigator.clipboard.writeText(btn.dataset.url || "");
            setIntegCmdStatus("URL copied");
          } catch {
            setIntegCmdStatus("Copy failed — select the link manually", false);
          }
        };
      });

      integReady = true;
      setIntegCmdStatus("Ready — fill a command or use Dry run");
    } catch (e) {
      host.innerHTML = `<p class="integ-empty">${escapeHtml(String(e.message || e))}</p>`;
      integReady = false;
      setIntegCmdStatus(String(e.message || e), false);
    }
  }

  if ($("integ-dry")) $("integ-dry").onclick = () => runCommandTest(true);
  if ($("integ-live")) {
    $("integ-live").onclick = () => {
      if (!confirm("Live execute will call the game integration (e.g. Minecraft server mod). Continue?")) {
        return;
      }
      runCommandTest(false);
    };
  }
  if ($("integ-message")) {
    $("integ-message").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        runCommandTest(true);
      }
    });
  }

  // Users
  let selectedId = null;

  async function loadUsers() {
    try {
      const q = $("user-q").value.trim();
      const users = await api("/api/admin/users?q=" + encodeURIComponent(q));
      const tb = $("users-table").querySelector("tbody");
      tb.innerHTML = "";
      for (const u of users) {
        const tr = document.createElement("tr");
        if (u.id === selectedId) tr.classList.add("selected");
        tr.innerHTML =
          `<td>${u.id}</td>` +
          `<td>${escapeHtml(u.display_name || "")}</td>` +
          `<td>${u.points}</td>` +
          `<td class="muted">${escapeHtml(u.accounts || "")}</td>`;
        tr.onclick = () => selectUser(u.id);
        tb.appendChild(tr);
      }
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }

  async function selectUser(id) {
    selectedId = id;
    loadUsers();
    try {
      const u = await api("/api/admin/users/" + id);
      const idents = (u.identities || [])
        .map(
          (i) =>
            `<li><strong>${escapeHtml(i.platform)}</strong> ` +
            `${escapeHtml(i.username || i.display_name)} ` +
            `<span class="muted">(${escapeHtml(i.platform_user_id)})</span></li>`
        )
        .join("");
      const ledger = (u.ledger || [])
        .map((l) => {
          const cls = l.delta >= 0 ? "pos" : "neg";
          const sign = l.delta >= 0 ? "+" : "";
          return `<div class="${cls}">${sign}${l.delta} → ${l.balance_after} · ${escapeHtml(
            l.reason
          )} · ${escapeHtml(l.source)} · ${fmtTime(l.created_at)}</div>`;
        })
        .join("");

      $("user-detail").innerHTML = `
        <h2>${escapeHtml(u.display_name || "User #" + u.id)}</h2>
        <div class="points">${u.points} pts</div>
        <h3>Linked accounts</h3>
        <ul class="identities">${idents || "<li class='muted'>None</li>"}</ul>

        <h3>Adjust points</h3>
        <div class="form-row">
          <input type="number" id="pts-delta" placeholder="e.g. 50 or -20" />
          <input id="pts-reason" placeholder="Reason" value="admin adjust" />
          <button class="primary" id="pts-apply">Apply</button>
        </div>

        <h3>Link another platform account</h3>
        <div class="form-row">
          <select id="link-platform">
            <option value="kick">kick</option>
            <option value="twitch">twitch</option>
            <option value="youtube">youtube</option>
          </select>
          <input id="link-pid" placeholder="Platform user id" />
          <input id="link-user" placeholder="Username" />
          <button id="link-btn">Link / merge</button>
        </div>
        <p class="muted">If that platform id already has a user, their points merge into this one.</p>

        <h3>Merge another user into this one</h3>
        <div class="form-row">
          <input type="number" id="merge-id" placeholder="Absorb user ID" />
          <button class="danger" id="merge-btn">Merge</button>
        </div>

        <h3>Notes</h3>
        <div class="form-row">
          <textarea id="user-notes" rows="2" style="width:100%">${escapeHtml(
            u.notes || ""
          )}</textarea>
          <button id="notes-btn">Save notes</button>
        </div>

        <h3>Recent ledger</h3>
        <div class="ledger">${ledger || "<span class='muted'>Empty</span>"}</div>
      `;

      $("pts-apply").onclick = async () => {
        const delta = parseInt($("pts-delta").value, 10);
        if (Number.isNaN(delta)) return alert("Enter a number");
        await api("/api/admin/users/" + id + "/points", {
          method: "POST",
          body: JSON.stringify({
            delta,
            reason: $("pts-reason").value || "admin adjust",
          }),
        });
        selectUser(id);
        refreshStats();
      };
      $("link-btn").onclick = async () => {
        await api("/api/admin/users/" + id + "/link", {
          method: "POST",
          body: JSON.stringify({
            platform: $("link-platform").value,
            platform_user_id: $("link-pid").value.trim(),
            username: $("link-user").value.trim(),
          }),
        });
        selectUser(id);
      };
      $("merge-btn").onclick = async () => {
        const absorb = parseInt($("merge-id").value, 10);
        if (Number.isNaN(absorb)) return alert("Enter user ID");
        if (!confirm("Merge user " + absorb + " into this one?")) return;
        await api("/api/admin/users/" + id + "/merge", {
          method: "POST",
          body: JSON.stringify({ absorb_user_id: absorb }),
        });
        selectUser(id);
        loadUsers();
        refreshStats();
      };
      $("notes-btn").onclick = async () => {
        await api("/api/admin/users/" + id + "/notes", {
          method: "POST",
          body: JSON.stringify({ notes: $("user-notes").value }),
        });
        setStatus("Notes saved");
      };
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }

  $("user-search").onclick = loadUsers;
  $("user-refresh").onclick = () => {
    loadUsers();
    refreshStats();
  };
  $("user-q").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadUsers();
  });

  // Chat
  async function refreshChatLogBanner() {
    const banner = $("chat-log-banner");
    if (!banner) return;
    try {
      const s = await api("/api/admin/status");
      banner.hidden = !!s.chat_log_enabled;
    } catch {
      banner.hidden = true;
    }
  }

  async function loadChat() {
    try {
      const params = new URLSearchParams();
      const uid = $("chat-user-id").value.trim();
      if (uid) params.set("user_id", uid);
      const plat = $("chat-platform").value;
      if (plat) params.set("platform", plat);
      const q = $("chat-q").value.trim();
      if (q) params.set("q", q);
      params.set("limit", "200");
      const rows = await api("/api/admin/chat?" + params.toString());
      const tb = $("chat-table").querySelector("tbody");
      tb.innerHTML = "";
      for (const r of rows) {
        const tr = document.createElement("tr");
        tr.innerHTML =
          `<td>${fmtTime(r.timestamp)}</td>` +
          `<td>${escapeHtml(r.display_name || r.username)} <span class="muted">#${
            r.user_id || "?"
          }</span></td>` +
          `<td>${escapeHtml(r.platform)}</td>` +
          `<td>${escapeHtml(r.message)}</td>`;
        tb.appendChild(tr);
      }
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }

  $("chat-search").onclick = loadChat;
  $("chat-export").onclick = () => {
    const uid = $("chat-user-id").value.trim();
    downloadCsv(uid ? parseInt(uid, 10) : null);
  };

  function downloadCsv(userId) {
    const params = new URLSearchParams();
    if (userId) params.set("user_id", String(userId));
    const url = "/api/admin/chat/export?" + params.toString();
    fetch(url, { headers: { "X-Admin-Token": token() } })
      .then(async (res) => {
        if (!res.ok) throw new Error(await res.text());
        return res.blob();
      })
      .then((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = userId ? `chat_user_${userId}.csv` : "chat_all.csv";
        a.click();
        URL.revokeObjectURL(a.href);
      })
      .catch((e) => alert(String(e.message || e)));
  }

  // ------------------------------------------------------------------
  // Config form
  // ------------------------------------------------------------------

  let lastDefaults = null;
  let lastLoadedConfig = null;
  let commandsState = {}; // name -> def
  let selectedCmd = null;
  let groupsState = []; // catalog rows from API
  let groupConflicts = [];

  function linesToList(text) {
    return String(text || "")
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function listToLines(arr) {
    return (arr || []).join("\n");
  }

  function fillConfigForm(cfg, defaults) {
    lastDefaults = defaults || lastDefaults;
    lastLoadedConfig = cfg || lastLoadedConfig;
    const c = cfg.core || {};
    const k = cfg.kick || {};
    const tw = cfg.twitch || {};
    const m = cfg.minecraft || {};
    const p = cfg.permissions || {};
    const pts = cfg.points || {};
    const yt = cfg.youtube || {};
    const met = cfg.metrics || {};
    const ov = cfg.overlay || {};

    $("cfg-core-host").value = c.host ?? "";
    $("cfg-core-port").value = c.port ?? 3850;
    $("cfg-core-prefix").value = c.command_prefix ?? "!";
    $("cfg-core-log").value = (c.log_level || "INFO").toUpperCase();

    $("cfg-kick-enabled").checked = !!k.enabled;
    $("cfg-kick-slug").value = k.channel_slug ?? "";
    $("cfg-kick-poll").value = k.poll_viewer_interval_sec ?? 15;
    $("cfg-kick-avatars").checked = k.avatars !== false;
    $("cfg-kick-chatroom").value =
      k.chatroom_id != null && k.chatroom_id !== "" ? String(k.chatroom_id) : "";

    $("cfg-tw-enabled").checked = !!tw.enabled;
    $("cfg-tw-channel").value = tw.channel ?? "";
    $("cfg-tw-3p").checked = tw.third_party_emotes !== false;
    $("cfg-tw-avatars").checked = tw.avatars !== false;
    $("cfg-tw-client-id").value = tw.client_id ?? "";
    $("cfg-tw-client-secret").value = tw.client_secret ?? "";
    if (tw.client_id || tw.client_secret) document.querySelector(".tw-advanced").open = true;
    loadTwitchAuth();

    $("cfg-mc-enabled").checked = !!m.enabled;
    $("cfg-mc-player").value = m.player_name ?? "";
    $("cfg-mc-client").value = m.client_mod_url ?? "";
    $("cfg-mc-server").value = m.server_mod_url ?? "";

    const fx = cfg.factorio || {};
    if ($("cfg-fx-enabled")) $("cfg-fx-enabled").checked = !!fx.enabled;
    if ($("cfg-fx-bridge")) $("cfg-fx-bridge").value = fx.bridge_url ?? "http://127.0.0.1:3847";

    const gv = cfg.granvir || {};
    if ($("cfg-gv-enabled")) $("cfg-gv-enabled").checked = !!gv.enabled;
    if ($("cfg-gv-bridge")) $("cfg-gv-bridge").value = gv.bridge_url ?? "http://127.0.0.1:3855";

    const ot = cfg.openttd || {};
    if ($("cfg-ot-enabled")) $("cfg-ot-enabled").checked = !!ot.enabled;
    if ($("cfg-ot-host")) $("cfg-ot-host").value = ot.host ?? "127.0.0.1";
    if ($("cfg-ot-port")) $("cfg-ot-port").value = ot.admin_port ?? 3977;
    if ($("cfg-ot-pass")) $("cfg-ot-pass").value = ot.admin_password ?? "";
    if ($("cfg-ot-rate")) $("cfg-ot-rate").value = ot.pounds_per_point ?? 1000;

    $("cfg-perm-admin").value = listToLines(p.admin);
    $("cfg-perm-mod").value = listToLines(p.mod);

    $("cfg-pts-enabled").checked = !!pts.enabled;
    $("cfg-pts-per").value = pts.per_message ?? 1;
    $("cfg-pts-cd").value = pts.cooldown_sec ?? 30;
    $("cfg-pts-sub").value = pts.sub_points ?? 500;
    $("cfg-pts-follow").value = pts.follow_points ?? 250;
    $("cfg-pts-gift").value = pts.gift_points ?? 1000;
    $("cfg-pts-token").value = pts.admin_token ?? "";
    syncTokenHint();

    const clog = cfg.chat_log || {};
    if ($("cfg-chatlog-enabled")) {
      $("cfg-chatlog-enabled").checked = !!clog.enabled;
    }
    const crd = cfg.credits || {};
    if ($("cfg-credits-enabled")) {
      $("cfg-credits-enabled").checked = !!crd.enabled;
    }
    if ($("cfg-credits-ignore")) $("cfg-credits-ignore").value = listToLines(crd.ignore_usernames || []);
    if ($("cfg-credits-minlen")) $("cfg-credits-minlen").value = crd.min_message_length ?? 1;
    if ($("cfg-credits-own")) $("cfg-credits-own").checked = crd.ignore_own_channel !== false;

    $("cfg-yt-enabled").checked = !!yt.enabled;
    $("cfg-yt-mode").value = yt.mode || "innertube";
    $("cfg-yt-channel").value = yt.channel_id ?? "";
    $("cfg-yt-video").value = yt.video_id ?? "";
    $("cfg-yt-apikey").value = yt.api_key ?? "";
    $("cfg-yt-livechat").value = yt.live_chat_id ?? "";

    $("cfg-met-msgwin").value = met.messageWindowSec ?? 60;
    $("cfg-met-cmdwin").value = met.commandWindowSec ?? 120;
    $("cfg-met-vw").value = met.viewerWeight ?? 0.4;
    $("cfg-met-cw").value = met.cpmWeight ?? 0.3;
    $("cfg-met-cmdw").value = met.commandWeight ?? 0.3;
    $("cfg-met-maxv").value = met.maxViewersForFull ?? 500;
    $("cfg-met-maxc").value = met.maxCpmForFull ?? 30;
    $("cfg-met-maxcmd").value = met.maxCommandsForFull ?? 10;

    $("cfg-ov-inv").value = ov.show_inventory_seconds ?? 12;
    if ($("cfg-ov-alert-ms")) {
      $("cfg-ov-alert-ms").value = ov.alert_duration_ms ?? 6000;
    }
    const mods = ov.modules || {};
    document.querySelectorAll("[data-ov-mod]").forEach((el) => {
      const key = el.getAttribute("data-ov-mod");
      el.checked = mods[key] !== false;
    });
  }

  // ── Twitch account (device code sign-in) ──────────────────
  // Core does the talking to Twitch; this only shows the code and the state. While a code is
  // waiting, the state is re-read every few seconds so the page flips to "Connected" by itself.
  let twAuthTimer = null;

  function showTwitchAuth(s) {
    const state = $("tw-auth-state");
    const codeBox = $("tw-auth-code");
    if (!state || !codeBox) return;
    const pending = s.pending;
    codeBox.hidden = !pending;
    $("tw-auth-connect").hidden = !!pending;
    $("tw-auth-cancel").hidden = !pending;
    $("tw-auth-disconnect").hidden = !s.connected || !!pending;
    if (pending) {
      $("tw-auth-digits").textContent = pending.user_code || "";
      $("tw-auth-link").href = pending.verification_uri || "https://www.twitch.tv/activate";
      state.textContent = "Twitch account: waiting for you to enter the code…";
    } else if (s.connected) {
      state.textContent = `Twitch account: connected as ${s.login || "(name pending)"}` +
        (s.builtin_app ? "" : " (your own app)");
      $("tw-auth-connect").textContent = "Reconnect";
    } else {
      state.textContent = s.has_secret
        ? "Twitch account: not connected (pictures use your app's secret)"
        : "Twitch account: not connected";
      $("tw-auth-connect").textContent = "Connect Twitch";
    }
    if (s.error) state.textContent += ` — ${s.error}`;
    clearTimeout(twAuthTimer);
    if (pending) twAuthTimer = setTimeout(loadTwitchAuth, 3000);
  }

  async function loadTwitchAuth() {
    if (!$("tw-auth-state")) return;
    try {
      showTwitchAuth(await api("/api/admin/twitch/auth"));
    } catch (e) {
      $("tw-auth-state").textContent = `Twitch account: ${e.message || e}`;
    }
  }

  async function twitchAuthAction(action) {
    try {
      showTwitchAuth(await api(`/api/admin/twitch/auth/${action}`, { method: "POST" }));
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }

  if ($("tw-auth-connect")) {
    $("tw-auth-connect").onclick = () => twitchAuthAction("start");
    $("tw-auth-cancel").onclick = () => twitchAuthAction("cancel");
    $("tw-auth-disconnect").onclick = () => {
      if (confirm("Disconnect your Twitch account from Stream Core? Chatter pictures stop until you connect again.")) {
        twitchAuthAction("disconnect");
      }
    };
  }

  function collectConfigFromForm() {
    const chatroomRaw = $("cfg-kick-chatroom").value.trim();
    const kick = {
      enabled: $("cfg-kick-enabled").checked,
      channel_slug: $("cfg-kick-slug").value.trim(),
      poll_viewer_interval_sec: num($("cfg-kick-poll").value, 15),
      avatars: $("cfg-kick-avatars").checked,
    };
    if (chatroomRaw !== "") {
      const n = Number(chatroomRaw);
      kick.chatroom_id = Number.isFinite(n) ? n : chatroomRaw;
    }

    const next = {
      ...(lastLoadedConfig || {}),
      core: {
        ...((lastLoadedConfig || {}).core || {}),
        host: $("cfg-core-host").value.trim() || "127.0.0.1",
        port: num($("cfg-core-port").value, 3850),
        command_prefix: $("cfg-core-prefix").value || "!",
        log_level: $("cfg-core-log").value || "INFO",
      },
      kick,
      twitch: {
        enabled: $("cfg-tw-enabled").checked,
        channel: $("cfg-tw-channel").value.trim().replace(/^#/, ""),
        third_party_emotes: $("cfg-tw-3p").checked,
        avatars: $("cfg-tw-avatars").checked,
        client_id: $("cfg-tw-client-id").value.trim(),
        client_secret: $("cfg-tw-client-secret").value.trim(),
      },
      youtube: {
        enabled: $("cfg-yt-enabled").checked,
        mode: $("cfg-yt-mode").value || "innertube",
        api_key: $("cfg-yt-apikey").value.trim(),
        channel_id: $("cfg-yt-channel").value.trim(),
        video_id: $("cfg-yt-video").value.trim(),
        live_chat_id: $("cfg-yt-livechat").value.trim(),
      },
      minecraft: {
        ...((lastLoadedConfig || {}).minecraft || {}),
        enabled: $("cfg-mc-enabled").checked,
        player_name: $("cfg-mc-player").value.trim(),
        client_mod_url: $("cfg-mc-client").value.trim(),
        server_mod_url: $("cfg-mc-server").value.trim(),
      },
      factorio: {
        enabled: $("cfg-fx-enabled") ? $("cfg-fx-enabled").checked : false,
        bridge_url: $("cfg-fx-bridge")
          ? $("cfg-fx-bridge").value.trim() || "http://127.0.0.1:3847"
          : "http://127.0.0.1:3847",
      },
      granvir: {
        enabled: $("cfg-gv-enabled") ? $("cfg-gv-enabled").checked : false,
        bridge_url: $("cfg-gv-bridge")
          ? $("cfg-gv-bridge").value.trim() || "http://127.0.0.1:3855"
          : "http://127.0.0.1:3855",
      },
      openttd: {
        ...((lastLoadedConfig || {}).openttd || {}),
        enabled: $("cfg-ot-enabled") ? $("cfg-ot-enabled").checked : false,
        host: $("cfg-ot-host") ? $("cfg-ot-host").value.trim() || "127.0.0.1" : "127.0.0.1",
        admin_port: $("cfg-ot-port") ? num($("cfg-ot-port").value, 3977) : 3977,
        admin_password: $("cfg-ot-pass") ? $("cfg-ot-pass").value : "",
        pounds_per_point: $("cfg-ot-rate") ? num($("cfg-ot-rate").value, 1000) : 1000,
      },
      permissions: {
        admin: linesToList($("cfg-perm-admin").value),
        mod: linesToList($("cfg-perm-mod").value),
      },
      metrics: {
        messageWindowSec: num($("cfg-met-msgwin").value, 60),
        commandWindowSec: num($("cfg-met-cmdwin").value, 120),
        viewerWeight: num($("cfg-met-vw").value, 0.4),
        cpmWeight: num($("cfg-met-cw").value, 0.3),
        commandWeight: num($("cfg-met-cmdw").value, 0.3),
        maxViewersForFull: num($("cfg-met-maxv").value, 500),
        maxCpmForFull: num($("cfg-met-maxc").value, 30),
        maxCommandsForFull: num($("cfg-met-maxcmd").value, 10),
      },
      overlay: {
        ...((lastLoadedConfig || {}).overlay || {}),
        show_inventory_seconds: num($("cfg-ov-inv").value, 12),
        alert_duration_ms: num(
          $("cfg-ov-alert-ms") ? $("cfg-ov-alert-ms").value : 6000,
          6000
        ),
        modules: Object.fromEntries(
          [...document.querySelectorAll("[data-ov-mod]")].map((el) => [
            el.getAttribute("data-ov-mod"),
            !!el.checked,
          ])
        ),
      },
      points: {
        enabled: $("cfg-pts-enabled").checked,
        per_message: num($("cfg-pts-per").value, 1),
        cooldown_sec: num($("cfg-pts-cd").value, 30),
        sub_points: num($("cfg-pts-sub").value, 500),
        follow_points: num($("cfg-pts-follow").value, 250),
        gift_points: num($("cfg-pts-gift").value, 1000),
        admin_token: $("cfg-pts-token").value.trim() || "change-me",
      },
      chat_log: {
        enabled: $("cfg-chatlog-enabled") ? $("cfg-chatlog-enabled").checked : false,
      },
      credits: creditsConfigBlock(),
    };
    return next;
  }

  // Merge onto what was loaded so the look keys (Admin → Credits → Style) are kept.
  function creditsConfigBlock() {
    const block = { ...((lastLoadedConfig || {}).credits || {}) };
    block.enabled = $("cfg-credits-enabled") ? $("cfg-credits-enabled").checked : false;
    if ($("cfg-credits-ignore")) block.ignore_usernames = linesToList($("cfg-credits-ignore").value);
    if ($("cfg-credits-minlen")) block.min_message_length = Math.max(0, Math.round(num($("cfg-credits-minlen").value, 1)));
    if ($("cfg-credits-own")) block.ignore_own_channel = $("cfg-credits-own").checked;
    return block;
  }

  function num(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  async function loadConfigForm() {
    try {
      const data = await api("/api/admin/config");
      fillConfigForm(data.config, data.defaults);
      const paths = $("config-paths");
      if (paths) {
        paths.textContent =
          "Files: " + (data.config_path || "") + " · " + (data.commands_path || "");
      }
      setCfgStatus("Loaded");
      setCfgDirty(false);
    } catch (e) {
      setCfgStatus(String(e.message || e), false);
    }
  }

  $("cfg-reload").onclick = () => loadConfigForm();
  $("cfg-reset-defaults").onclick = () => {
    if (!lastDefaults) {
      setCfgStatus("Load config first", false);
      return;
    }
    // nothing is written until Save, so: do it, and offer Undo instead of asking first
    const before = collectConfigFromForm();
    const wasDirty = $("cfg-savebar") && $("cfg-savebar").classList.contains("dirty");
    fillConfigForm(lastDefaults, lastDefaults);
    setCfgDirty(true);
    setCfgStatus("Form reset to defaults — click Save & apply to write disk");
    undoToast("Form reset to built-in defaults (not saved).", () => {
      fillConfigForm(before, lastDefaults);
      setCfgDirty(wasDirty);
      setCfgStatus("Reset undone");
    });
  };

  $("cfg-save").onclick = async () => {
    try {
      const config = collectConfigFromForm();
      const newToken = String(((config.points || {}).admin_token) || "").trim();
      const res = await api("/api/admin/config", {
        method: "PUT",
        body: JSON.stringify({ config }),
      });
      // points.admin_token applies as soon as it's saved: switch this page to it too, or every
      // call from here on would be refused with the old one
      if (newToken && newToken !== "change-me" && newToken !== token()) {
        localStorage.setItem(tokenKey, newToken);
        $("token").value = newToken;
        syncTokenRow();
        setStatus("Admin token changed — this page now uses the new one", true);
      }
      setCfgStatus(res.message || "Saved", true);
      setStatus(res.message || "Config saved — chat platforms applied", true);
      setCfgDirty(false);
    } catch (e) {
      setCfgStatus(String(e.message || e), false);
    }
  };

  // "change-me" / empty in the token field means the generated token in data/admin_token.txt is in use.
  function syncTokenHint() {
    const el = $("cfg-pts-token-hint");
    if (!el || !$("cfg-pts-token")) return;
    const v = $("cfg-pts-token").value.trim();
    el.textContent = (!v || v === "change-me")
      ? "Not set: Stream Core uses the random token it printed at startup (data/admin_token.txt). Type your own here to replace it; saving switches this page to it."
      : "Your own token. Saving applies it at once and switches this page to it.";
  }
  if ($("cfg-pts-token")) $("cfg-pts-token").addEventListener("input", syncTokenHint);

  // Save bar: flag unsaved edits, Ctrl/Cmd+S saves while Config is open.
  function setCfgDirty(dirty) {
    const bar = $("cfg-savebar");
    if (bar) bar.classList.toggle("dirty", !!dirty);
    const flag = $("cfg-dirty");
    if (flag) flag.hidden = !dirty;
  }
  ["input", "change"].forEach((type) => {
    $("tab-config").addEventListener(type, (ev) => {
      const id = (ev.target && ev.target.id) || "";
      if (id.startsWith("cfg-")) setCfgDirty(true);
    });
  });
  document.addEventListener("keydown", (ev) => {
    if (!(ev.ctrlKey || ev.metaKey) || ev.altKey || String(ev.key).toLowerCase() !== "s") return;
    const panel = $("tab-config");
    if (!panel || !panel.classList.contains("active") || !panel.classList.contains("yaml-sub")) return;
    ev.preventDefault();
    $("cfg-save").click();
  });

  // ------------------------------------------------------------------
  // Command groups
  // ------------------------------------------------------------------

  function setGrpStatus(msg, ok) {
    const el = $("grp-status");
    if (!el) return;
    el.textContent = msg || "";
    el.style.color = ok === false ? "var(--danger)" : "";
  }

  function showConflicts(list) {
    const box = $("grp-conflicts");
    if (!box) return;
    groupConflicts = list || [];
    if (!groupConflicts.length) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML =
      `<strong>Command name / alias conflicts</strong>` +
      `<ul>${groupConflicts
        .map(
          (c) =>
            `<li><code>!${escapeHtml(c.token)}</code> — ` +
            `<code>${escapeHtml(c.winner)}</code> wins over ` +
            `<code>${escapeHtml(c.loser)}</code> ` +
            `(${escapeHtml(c.reason || "")})</li>`
        )
        .join("")}</ul>` +
      `<p style="margin:6px 0 0">Raise <code>priority</code> on the command you want, or rename the alias.</p>`;
  }

  function collectGroupsFromTable() {
    const out = {};
    document.querySelectorAll("#grp-table tbody tr").forEach((tr) => {
      const id = (tr.querySelector(".grp-id") || {}).value;
      const name = String(id || "").trim().toLowerCase();
      if (!name) return;
      out[name] = {
        enabled: !!(tr.querySelector(".grp-enabled") || {}).checked,
        always: !!(tr.querySelector(".grp-always") || {}).checked || name === "core",
        bind: String((tr.querySelector(".grp-bind") || {}).value || "").trim() || null,
        description: String((tr.querySelector(".grp-desc") || {}).value || "").trim(),
      };
    });
    return out;
  }

  function renderGroupsTable() {
    const tb = $("grp-table") && $("grp-table").querySelector("tbody");
    if (!tb) return;
    tb.innerHTML = "";
    (groupsState || []).forEach((g) => {
      const tr = document.createElement("tr");
      const locked = !!g.always || g.id === "core";
      const live = g.active
        ? `<span class="pill ok">active</span>`
        : `<span class="pill off">off</span>`;
      tr.innerHTML =
        `<td><input class="grp-id" type="text" value="${escapeHtml(g.id)}" ${locked ? "readonly" : ""} /></td>` +
        `<td><input class="grp-enabled" type="checkbox" ${g.enabled || locked ? "checked" : ""} ${locked ? "disabled" : ""} /></td>` +
        `<td><input class="grp-always" type="checkbox" ${locked ? "checked disabled" : ""} /></td>` +
        `<td><input class="grp-bind" type="text" value="${escapeHtml(g.bind || "")}" placeholder="minecraft / points" ${locked ? "disabled" : ""} /></td>` +
        `<td>${live}<div class="muted">${escapeHtml(g.reason || "")}</div></td>` +
        `<td><input class="grp-desc" type="text" value="${escapeHtml(g.description || "")}" /></td>` +
        `<td>${locked ? "" : `<button type="button" class="danger grp-del">×</button>`}</td>`;
      const del = tr.querySelector(".grp-del");
      if (del) {
        del.onclick = () => {
          const at = groupsState.indexOf(g);
          groupsState = groupsState.filter((x) => x.id !== g.id);
          renderGroupsTable();
          undoToast(`Removed group "${g.id}" (Save groups to make it stick).`, () => {
            groupsState.splice(Math.max(0, Math.min(at, groupsState.length)), 0, g);
            renderGroupsTable();
          });
        };
      }
      tb.appendChild(tr);
    });
  }

  async function loadGroups() {
    try {
      const data = await api("/api/admin/command-groups");
      groupsState = data.groups || [];
      showConflicts(data.conflicts || []);
      renderGroupsTable();
      setGrpStatus("Loaded · active: " + (data.active || []).join(", "));
    } catch (e) {
      setGrpStatus(String(e.message || e), false);
    }
  }

  if ($("grp-reload")) {
    $("grp-reload").onclick = async () => {
      try {
        const data = await api("/api/admin/command-groups/reload", { method: "POST", body: "{}" });
        showConflicts(data.conflicts || []);
        await loadGroups();
        setGrpStatus("Hot-reloaded · groups: " + (data.groups_active || []).join(", "), true);
      } catch (e) {
        setGrpStatus(String(e.message || e), false);
      }
    };
  }
  if ($("grp-add")) {
    $("grp-add").onclick = () => {
      let n = 1;
      const ids = new Set((groupsState || []).map((g) => g.id));
      while (ids.has("group" + n)) n++;
      groupsState.push({
        id: "group" + n,
        enabled: true,
        always: false,
        bind: "",
        description: "",
        active: true,
        reason: "unbound",
      });
      renderGroupsTable();
    };
  }
  if ($("grp-save")) {
    $("grp-save").onclick = async () => {
      try {
        const groups = collectGroupsFromTable();
        const res = await api("/api/admin/command-groups", {
          method: "PUT",
          body: JSON.stringify({ groups }),
        });
        groupsState = res.groups || groupsState;
        renderGroupsTable();
        showConflicts(res.conflicts || groupConflicts);
        setGrpStatus(res.message || "Saved", true);
        setStatus("Command groups hot-applied", true);
      } catch (e) {
        setGrpStatus(String(e.message || e), false);
      }
    };
  }

  // ------------------------------------------------------------------
  // Config → Reactions (chat emoji / commands → Stream Rooms effects)
  // ------------------------------------------------------------------

  let rxCfg = null;
  let rxEffects = [];
  let rxStatus = null;
  let rxSel = -1;
  let rxPrefix = "!";

  const RX_MSG_LABELS = {
    cooldown: "On cooldown",
    no_points: "Not enough points",
    no_permission: "Not allowed (mods / subs only)",
    opted_out: "Target opted out",
    bad_target: "Unknown target",
    target_not_allowed: "Target type not allowed",
    stage_closed: "Nothing to play it on",
    opt_out_ok: "Opted out",
    opt_in_ok: "Opted in",
    targets: "Target list",
    targets_none: "Target list (no room open)",
  };

  function setRxStatus(msg, ok) {
    const el = $("rx-status");
    if (!el) return;
    el.textContent = msg || "";
    el.style.color = ok === false ? "var(--danger)" : "";
  }

  function rxEffect(id) {
    return rxEffects.find((e) => e.id === id) || null;
  }

  function rxSplitList(text, emoji) {
    const parts = String(text || "").split(emoji ? /[\s,]+/ : /[,\n]+/);
    const out = [];
    parts.forEach((p) => {
      const v = p.trim();
      if (v && !out.includes(v)) out.push(v);
    });
    return out;
  }

  function rxRenderLive() {
    const el = $("rx-live");
    if (!el || !rxStatus) return;
    const st = rxStatus;
    const bits = [];
    bits.push(st.active ? `<span class="pill ok">reactions live</span>` : `<span class="pill off">reactions off</span>`);
    if (st.game_connected) {
      const names = (st.game_clients || []).map((c) => c.client).join(", ");
      bits.push(`<span class="pill ok">game connected</span>${escapeHtml(names)}`);
      const room = st.room_state;
      if (room) {
        const t = (room.targets || []).map((x) => x.id).concat((room.guests || []).map((g) => g.name || g.id));
        bits.push(` · room <strong>${escapeHtml(room.room || "?")}</strong>` +
          (t.length ? ` · targets: ${escapeHtml(t.join(", "))}` : "") +
          (room.seated ? ` · ${room.seated.length} seated` : ""));
      }
    } else {
      bits.push(`<span class="pill off">game not connected</span>fallback overlay plays what it can`);
    }
    if (!st.points_enabled) bits.push(` · <span class="rx-warn">points are off — reactions with a cost won't run</span>`);
    const s = st.stats || {};
    bits.push(` · fired ${s.fired || 0}, rejected ${s.rejected || 0}, refunded ${s.refunded || 0}, points spent ${s.points_spent || 0}`);
    el.innerHTML = bits.join(" ");
  }

  function rxRenderConflicts(list) {
    const box = $("rx-conflicts");
    if (!box) return;
    if (!list || !list.length) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML = `<strong>Command name clashes</strong><ul>${list
      .map((c) => `<li><code>${escapeHtml(rxPrefix + c.token)}</code> — ${escapeHtml(c.winner)} wins over ${escapeHtml(c.loser)} (${escapeHtml(c.reason)})</li>`)
      .join("")}</ul>`;
  }

  function rxRenderRecent() {
    const tb = $("rx-recent") && $("rx-recent").querySelector("tbody");
    if (!tb || !rxStatus) return;
    const rows = rxStatus.recent || [];
    tb.innerHTML = rows.length
      ? rows
          .map((r) => {
            const t = r.target ? `${r.target.type}${r.target.name ? ": " + r.target.name : ""}` : "—";
            return `<tr><td>${escapeHtml(fmtTime(r.ts))}</td><td>${escapeHtml(r.reaction)}${r.count > 1 ? " ×" + r.count : ""}</td>` +
              `<td>${escapeHtml(r.platform + ":" + r.from)}</td><td>${escapeHtml(t)}</td><td>${escapeHtml(r.route)}</td>` +
              `<td>${r.cost || 0}</td><td>${escapeHtml(r.outcome || "")}</td></tr>`;
          })
          .join("")
      : `<tr><td colspan="7" class="muted">Nothing yet</td></tr>`;
  }

  function rxFillSettings() {
    const c = rxCfg;
    $("rx-enabled").checked = !!c.enabled;
    $("rx-send-to").value = c.send_to || "auto";
    $("rx-targeting").value = c.targeting || "opt_out";
    $("rx-admins-free").checked = !!c.admins_free;
    $("rx-refund").checked = !!c.refund_if_dropped;
    $("rx-replies").checked = !!c.chat_replies;
    $("rx-cmd-out").value = c.opt_out_command || "";
    $("rx-cmd-in").value = c.opt_in_command || "";
    $("rx-cmd-targets").value = c.targets_command || "";
    $("rx-say").value = c.say_per_minute != null ? c.say_per_minute : 6;
    const box = $("rx-messages");
    box.innerHTML = Object.keys(RX_MSG_LABELS)
      .map((k) => `<label>${escapeHtml(RX_MSG_LABELS[k])}<input type="text" data-rx-msg="${k}" value="${escapeHtml((c.messages || {})[k] || "")}" /></label>`)
      .join("");
  }

  function rxCollectSettings() {
    const c = rxCfg;
    c.enabled = $("rx-enabled").checked;
    c.send_to = $("rx-send-to").value;
    c.targeting = $("rx-targeting").value;
    c.admins_free = $("rx-admins-free").checked;
    c.refund_if_dropped = $("rx-refund").checked;
    c.chat_replies = $("rx-replies").checked;
    c.opt_out_command = $("rx-cmd-out").value.trim().replace(/^!/, "");
    c.opt_in_command = $("rx-cmd-in").value.trim().replace(/^!/, "");
    c.targets_command = $("rx-cmd-targets").value.trim().replace(/^!/, "");
    c.say_per_minute = num($("rx-say").value, 6);
    c.messages = c.messages || {};
    document.querySelectorAll("[data-rx-msg]").forEach((inp) => {
      c.messages[inp.dataset.rxMsg] = inp.value;
    });
    return c;
  }

  function rxWho(e) {
    let w = e.permission || "public";
    if ((e.require || []).length) w += " + " + e.require.join("/");
    return w;
  }

  function rxRenderTable() {
    const tb = $("rx-table") && $("rx-table").querySelector("tbody");
    if (!tb) return;
    const usable = {};
    ((rxStatus && rxStatus.entries) || []).forEach((s) => (usable[s.id] = s));
    tb.innerHTML = "";
    (rxCfg.entries || []).forEach((e, i) => {
      const tr = document.createElement("tr");
      if (i === rxSel) tr.classList.add("selected");
      const trig = []
        .concat((e.emoji || []).map((x) => `<span class="rx-emo">${escapeHtml(x)}</span>`))
        .concat((e.emotes || []).map((x) => escapeHtml(x)))
        .concat((e.commands || []).map((x) => escapeHtml(rxPrefix + x)));
      const eff = rxEffect(e.effect);
      const u = usable[e.id];
      const warn = u && !u.usable && u.why !== "disabled" ? `<div class="rx-warn">${escapeHtml(u.why)}</div>` : "";
      tr.innerHTML =
        `<td><input type="checkbox" class="rx-on" ${e.enabled ? "checked" : ""} /></td>` +
        `<td>${escapeHtml(e.label || e.id)}<div class="muted">${escapeHtml(e.id)}</div>${warn}</td>` +
        `<td class="rx-trig">${trig.join(" ") || "—"}</td>` +
        `<td>${escapeHtml(eff ? eff.label : e.effect)}</td>` +
        `<td>${e.cost || 0}</td>` +
        `<td>${escapeHtml(rxWho(e))}</td>`;
      tr.querySelector(".rx-on").onclick = (ev) => {
        ev.stopPropagation();
        e.enabled = ev.target.checked;
        if (i === rxSel) rxRenderDetail();
      };
      tr.onclick = () => {
        rxSel = i;
        rxRenderTable();
        rxRenderDetail();
      };
      tb.appendChild(tr);
    });
  }

  // ── Reaction pictures ("img:name" objects) ──
  let rxImages = [];

  function rxImgByName(name) {
    return rxImages.find((im) => im.name === String(name || "").toLowerCase());
  }

  function rxRenderImages() {
    const grid = $("rx-img-grid");
    const list = $("rx-img-list");
    if (list) {
      list.innerHTML = rxImages.map((im) => `<option value="img:${escapeHtml(im.name)}"></option>`).join("");
    }
    if (!grid) return;
    grid.innerHTML = rxImages.length
      ? rxImages.map((im) =>
          `<div class="rx-img-card" title="${escapeHtml(im.file)} · ${Math.round(im.bytes / 1024)} KB">` +
          `<img src="${escapeHtml(im.url)}" alt="" />` +
          `<code>img:${escapeHtml(im.name)}</code>` +
          `<span class="muted">${escapeHtml(im.source)}${im.animated ? " · animated" : ""}</span>` +
          (im.source === "custom"
            ? `<button type="button" class="danger" data-rx-img-del="${escapeHtml(im.name)}">Delete</button>`
            : "") +
          `</div>`).join("")
      : `<span class="muted">No pictures yet.</span>`;
    grid.querySelectorAll("[data-rx-img-del]").forEach((b) => {
      b.onclick = async () => {
        const name = b.dataset.rxImgDel;
        if (!confirm(`Delete the picture "${name}"? Reactions using img:${name} fall back to their text.`)) return;
        try {
          const res = await api("/api/admin/reactions/images/" + encodeURIComponent(name), { method: "DELETE" });
          rxImages = res.images || [];
          rxRenderImages();
          if (rxSel >= 0) rxRenderDetail();
        } catch (e) {
          if ($("rx-img-status")) $("rx-img-status").textContent = String(e.message || e);
        }
      };
    });
  }

  async function rxLoadImages() {
    try {
      const res = await api("/api/admin/reactions/images");
      rxImages = res.images || [];
    } catch (e) {
      rxImages = [];
    }
    rxRenderImages();
  }

  if ($("rx-img-file")) {
    $("rx-img-file").onchange = () => {
      const f = $("rx-img-file").files[0];
      if (f && $("rx-img-name") && !$("rx-img-name").value.trim()) {
        $("rx-img-name").value = f.name.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-").slice(0, 40);
      }
    };
  }
  if ($("rx-img-upload")) {
    $("rx-img-upload").onclick = async () => {
      const st = $("rx-img-status");
      const f = $("rx-img-file").files[0];
      const name = $("rx-img-name").value.trim();
      if (!f) { st.textContent = "Pick a file first."; return; }
      if (!name) { st.textContent = "Give it a name."; return; }
      st.textContent = "Uploading…";
      try {
        const data = await new Promise((resolve, reject) => {
          const rd = new FileReader();
          rd.onload = () => resolve(rd.result);
          rd.onerror = () => reject(new Error("Couldn't read the file"));
          rd.readAsDataURL(f);
        });
        const res = await api("/api/admin/reactions/images", {
          method: "POST",
          body: JSON.stringify({ name, data }),
        });
        rxImages = res.images || [];
        rxRenderImages();
        st.textContent = `Saved as img:${res.image.name}`;
        $("rx-img-file").value = "";
        $("rx-img-name").value = "";
        if (rxSel >= 0) rxRenderDetail();
      } catch (e) {
        st.textContent = String(e.message || e);
      }
    };
  }

  function rxParamInput(p, value) {
    const v = value != null ? value : p.default;
    const name = escapeHtml(p.name);
    const lab = escapeHtml(p.label || p.name);
    if (p.name === "object") {
      const cur = String(v || "");
      const pic = cur.toLowerCase().startsWith("img:") ? rxImgByName(cur.slice(4)) : null;
      const picks = rxImages.map((im) =>
        `<button type="button" class="rx-img-pick${pic && pic.name === im.name ? " is-on" : ""}" data-rx-pick="img:${escapeHtml(im.name)}" title="img:${escapeHtml(im.name)}">` +
        `<img src="${escapeHtml(im.url)}" alt="" /></button>`).join("");
      const warn = cur.toLowerCase().startsWith("img:") && !pic
        ? `<span class="field-help" style="color:var(--danger)">no picture called "${escapeHtml(cur.slice(4))}"</span>` : "";
      return `<label>${lab} ${warn}<input type="text" list="rx-img-list" data-rx-p="${name}" value="${escapeHtml(cur)}" /></label>` +
        (picks ? `<div class="rx-img-picks">${picks}</div>` : "");
    }
    if (p.type === "select") {
      const opts = (p.options || [])
        .map((o) => `<option value="${escapeHtml(o)}" ${String(o) === String(v) ? "selected" : ""}>${escapeHtml(o)}</option>`)
        .join("");
      return `<label>${lab}<select data-rx-p="${name}">${opts}</select></label>`;
    }
    if (p.type === "bool") {
      return `<label class="check"><input type="checkbox" data-rx-p="${name}" ${v ? "checked" : ""} /> ${lab}</label>`;
    }
    const type = p.type === "number" ? "number" : p.type === "color" ? "color" : "text";
    const extra = p.type === "number"
      ? ` step="any"${p.min != null ? ` min="${p.min}"` : ""}${p.max != null ? ` max="${p.max}"` : ""}`
      : "";
    return `<label>${lab}<input type="${type}" data-rx-p="${name}" value="${escapeHtml(v != null ? v : "")}"${extra} /></label>`;
  }

  function rxRenderParams(e) {
    const box = $("rx-params");
    if (!box) return;
    const eff = rxEffect(e.effect);
    $("rx-effect-desc").textContent = eff
      ? (eff.description || "") +
        (eff.in_game === false ? " (the connected game doesn't list this effect)" : "") +
        (eff.overlay ? " Fallback overlay: yes." : " Fallback overlay: no.")
      : "Unknown effect id — the game decides what to do.";
    const params = (eff && eff.params) || [];
    box.innerHTML = params.length
      ? `<legend>Effect settings</legend>` + params.map((p) => rxParamInput(p, (e.params || {})[p.name])).join("")
      : `<legend>Effect settings</legend><p class="muted">No settings.</p>`;
    box.querySelectorAll("[data-rx-pick]").forEach((b) => {
      b.onclick = () => {
        e.params = e.params || {};
        e.params.object = b.dataset.rxPick;
        rxRenderParams(e);
      };
    });
    box.querySelectorAll("[data-rx-p]").forEach((inp) => {
      const pdef = params.find((p) => p.name === inp.dataset.rxP) || {};
      const handler = () => {
        e.params = e.params || {};
        let val = inp.type === "checkbox" ? inp.checked : inp.value;
        if (pdef.type === "number") val = num(val, pdef.default);
        e.params[inp.dataset.rxP] = val;
      };
      inp.oninput = handler;
      inp.onchange = handler;
    });
  }

  function rxRenderDetail() {
    const pane = $("rx-detail");
    const e = (rxCfg.entries || [])[rxSel];
    if (!e) {
      pane.innerHTML = `<p class="muted">Select a reaction or click Add</p>`;
      return;
    }
    const effOpts = rxEffects
      .map((f) => {
        const where = [f.in_game !== false ? "game" : null, f.overlay ? "overlay" : null].filter(Boolean).join(" + ") || "game (not reported)";
        return `<option value="${escapeHtml(f.id)}" ${f.id === e.effect ? "selected" : ""}>${escapeHtml(f.label)} — ${where}</option>`;
      })
      .join("");
    const known = rxEffect(e.effect) ? "" : `<option value="${escapeHtml(e.effect)}" selected>${escapeHtml(e.effect)} (unknown)</option>`;
    const tchk = (t, label) =>
      `<label><input type="checkbox" data-rx-target="${t}" ${(e.targets || []).includes(t) ? "checked" : ""} /> ${label}</label>`;
    const rchk = (r, label) =>
      `<label><input type="checkbox" data-rx-req="${r}" ${(e.require || []).includes(r) ? "checked" : ""} /> ${label}</label>`;
    pane.innerHTML = `
      <div class="cmd-form">
        <div class="rx-row">
          <label>Name <input data-rx-f="label" type="text" value="${escapeHtml(e.label || "")}" /></label>
          <label>Id <span class="field-help">letters, numbers, _ -</span><input data-rx-f="id" type="text" value="${escapeHtml(e.id)}" /></label>
        </div>
        <div class="rx-checks"><label><input data-rx-f="enabled" type="checkbox" ${e.enabled ? "checked" : ""} /> Enabled</label></div>

        <label>Emoji <span class="field-help">space-separated, e.g. 🍅 🥚</span>
          <input data-rx-f="emoji" type="text" value="${escapeHtml((e.emoji || []).join(" "))}" /></label>
        <label>Emote names <span class="field-help">Twitch / 7TV / BTTV / FFZ / Kick, comma-separated</span>
          <input data-rx-f="emotes" type="text" value="${escapeHtml((e.emotes || []).join(", "))}" /></label>
        <label>Commands <span class="field-help">without ${escapeHtml(rxPrefix)}, comma-separated</span>
          <input data-rx-f="commands" type="text" value="${escapeHtml((e.commands || []).join(", "))}" /></label>

        <label>Effect <select data-rx-f="effect">${known}${effOpts}</select></label>
        <p class="hint rx-effect-desc" id="rx-effect-desc"></p>
        <fieldset class="rx-params" id="rx-params"></fieldset>

        <div class="muted">Can be aimed at</div>
        <div class="rx-checks">${tchk("stage", "Stage spots")}${tchk("user", "Audience (@name)")}${tchk("guest", "Guests")}</div>
        <label>When no target is given
          <select data-rx-f="default_target">
            <option value="" ${e.default_target === "" ? "selected" : ""}>nothing (untargeted)</option>
            <option value="stage" ${e.default_target === "stage" ? "selected" : ""}>the stage</option>
            <option value="sender" ${e.default_target === "sender" ? "selected" : ""}>the sender</option>
          </select></label>

        <div class="rx-row">
          <label>Who can use it
            <select data-rx-f="permission">
              <option value="public" ${e.permission === "public" ? "selected" : ""}>everyone</option>
              <option value="mod" ${e.permission === "mod" ? "selected" : ""}>mods</option>
              <option value="admin" ${e.permission === "admin" ? "selected" : ""}>admins</option>
            </select></label>
          <label>Cost (Core points) <input data-rx-f="cost" type="number" min="0" value="${e.cost || 0}" /></label>
        </div>
        <div class="rx-checks"><span class="muted">Also require:</span>${rchk("sub", "Sub")}${rchk("vip", "VIP")}<span class="muted">(either one; mods always pass)</span></div>

        <div class="rx-row3">
          <label>Cooldown per user (s) <input data-rx-f="cooldown_user_sec" type="number" min="0" step="any" value="${e.cooldown_user_sec || 0}" /></label>
          <label>Cooldown for everyone (s) <input data-rx-f="cooldown_global_sec" type="number" min="0" step="any" value="${e.cooldown_global_sec || 0}" /></label>
          <label>Cooldown per target (s) <input data-rx-f="cooldown_target_sec" type="number" min="0" step="any" value="${e.cooldown_target_sec || 0}" /></label>
        </div>
        <label>Max per message <span class="field-help">🍅🍅🍅🍅 or !tomato x4 counts as this many at most (each one costs)</span>
          <input data-rx-f="max_per_message" type="number" min="1" max="50" value="${e.max_per_message || 1}" /></label>
        <label>Per command <span class="field-help">how many one !command fires when no number is typed (e.g. 10 for a !barrage)</span>
          <input data-rx-f="command_count" type="number" min="1" max="50" value="${e.command_count || 1}" /></label>
        <label>Reply when it works <span class="field-help">optional, e.g. @{user} 🎉 ({cost} pts)</span>
          <input data-rx-f="reply_ok" type="text" value="${escapeHtml(e.reply_ok || "")}" /></label>

        <div class="rx-test">
          <input id="rx-test-target" type="text" placeholder="target: screen / @bob / blank" />
          <button type="button" id="rx-test-btn">Test (free)</button>
          <button type="button" class="danger" id="rx-del-btn">Delete</button>
        </div>
        <p class="muted" id="rx-test-out"></p>
      </div>`;

    pane.querySelectorAll("[data-rx-f]").forEach((inp) => {
      const f = inp.dataset.rxF;
      const handler = () => {
        if (f === "enabled") e.enabled = inp.checked;
        else if (f === "emoji") e.emoji = rxSplitList(inp.value, true);
        else if (f === "emotes" || f === "commands")
          e[f] = rxSplitList(inp.value).map((x) => (f === "commands" ? x.replace(/^!/, "").toLowerCase() : x));
        else if (["cost", "cooldown_user_sec", "cooldown_global_sec", "cooldown_target_sec", "max_per_message", "command_count"].includes(f))
          e[f] = num(inp.value, 0);
        else if (f === "id") e.id = inp.value.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "");
        else e[f] = inp.value;
        if (f === "effect") {
          // drop settings the new effect doesn't have (keep the thrown object)
          const eff = rxEffect(e.effect);
          const keep = new Set(((eff && eff.params) || []).map((p) => p.name));
          const next = {};
          Object.keys(e.params || {}).forEach((k) => {
            if (keep.has(k)) next[k] = e.params[k];
          });
          e.params = next;
          rxRenderParams(e);
        }
        rxRenderTable();
      };
      inp.oninput = handler;
      inp.onchange = handler;
    });
    pane.querySelectorAll("[data-rx-target]").forEach((inp) => {
      inp.onchange = () => {
        const set = new Set(e.targets || []);
        if (inp.checked) set.add(inp.dataset.rxTarget);
        else set.delete(inp.dataset.rxTarget);
        e.targets = ["stage", "user", "guest"].filter((t) => set.has(t));
      };
    });
    pane.querySelectorAll("[data-rx-req]").forEach((inp) => {
      inp.onchange = () => {
        const set = new Set(e.require || []);
        if (inp.checked) set.add(inp.dataset.rxReq);
        else set.delete(inp.dataset.rxReq);
        e.require = ["sub", "vip"].filter((t) => set.has(t));
        rxRenderTable();
      };
    });
    $("rx-del-btn").onclick = () => {
      const at = rxSel;
      const gone = rxCfg.entries.splice(at, 1)[0];
      rxSel = -1;
      rxRenderTable();
      rxRenderDetail();
      undoToast(`Deleted reaction "${gone.label || gone.id}" (Save to make it stick).`, () => {
        rxCfg.entries.splice(Math.min(at, rxCfg.entries.length), 0, gone);
        rxSel = rxCfg.entries.indexOf(gone);
        rxRenderTable();
        rxRenderDetail();
      });
    };
    $("rx-test-btn").onclick = async () => {
      const out = $("rx-test-out");
      try {
        const r = await api("/api/admin/reactions/test", {
          method: "POST",
          body: JSON.stringify({ id: e.id, target: $("rx-test-target").value.trim() }),
        });
        rxStatus = r.status || rxStatus;
        rxRenderLive();
        rxRenderRecent();
        out.textContent = r.ok
          ? `Sent to ${r.route}${r.target ? " → " + r.target.type + (r.target.name ? " " + r.target.name : "") : ""}`
          : `Not sent: ${r.reason}${r.target ? " (" + r.target + ")" : ""}`;
      } catch (err) {
        out.textContent = String(err.message || err) + " — save the reaction first if it's new";
      }
    };
    rxRenderParams(e);
  }

  function rxApply(data) {
    rxCfg = data.reactions || rxCfg;
    rxEffects = data.effects || rxEffects;
    rxStatus = data.status || rxStatus;
    rxPrefix = data.prefix || rxPrefix;
    if (lastLoadedConfig) lastLoadedConfig.reactions = rxCfg;
    rxFillSettings();
    rxRenderLive();
    rxRenderConflicts(data.conflicts || []);
    if (rxSel >= (rxCfg.entries || []).length) rxSel = -1;
    rxRenderTable();
    rxRenderDetail();
    rxRenderRecent();
  }

  async function loadReactions() {
    if (!$("rx-table")) return;
    try {
      const data = await api("/api/admin/reactions");
      await rxLoadImages();
      rxApply(data);
      setRxStatus("Loaded");
    } catch (e) {
      setRxStatus(String(e.message || e), false);
    }
  }

  if ($("rx-reload")) $("rx-reload").onclick = () => loadReactions();
  if ($("rx-add")) {
    $("rx-add").onclick = () => {
      if (!rxCfg) return;
      let n = 1;
      const ids = new Set(rxCfg.entries.map((e) => e.id));
      while (ids.has("reaction" + n)) n++;
      rxCfg.entries.push({
        id: "reaction" + n,
        label: "New reaction",
        enabled: true,
        emoji: [],
        emotes: [],
        commands: [],
        effect: "throw",
        params: {},
        targets: ["stage"],
        default_target: "stage",
        permission: "public",
        require: [],
        cost: 0,
        cooldown_user_sec: 5,
        cooldown_global_sec: 0,
        cooldown_target_sec: 0,
        max_per_message: 1,
        command_count: 1,
        reply_ok: "",
      });
      rxSel = rxCfg.entries.length - 1;
      rxRenderTable();
      rxRenderDetail();
    };
  }
  if ($("rx-save")) {
    $("rx-save").onclick = async () => {
      if (!rxCfg) return;
      const ids = rxCfg.entries.map((e) => e.id);
      const dup = ids.find((id, i) => !id || ids.indexOf(id) !== i);
      if (dup !== undefined) {
        setRxStatus(dup ? `Two reactions use the id "${dup}"` : "A reaction has an empty id", false);
        return;
      }
      try {
        const res = await api("/api/admin/reactions", {
          method: "PUT",
          body: JSON.stringify({ reactions: rxCollectSettings() }),
        });
        rxApply(res);
        setRxStatus(res.message || "Saved", true);
        setStatus("Reactions saved and live", true);
      } catch (e) {
        setRxStatus(String(e.message || e), false);
      }
    };
  }

  function localConflicts(map) {
    const owners = {};
    const hits = [];
    Object.keys(map || {}).forEach((name) => {
      const d = map[name] || {};
      const tokens = [name, ...((d.aliases || []).map((a) => String(a)))];
      tokens.forEach((raw) => {
        const t = String(raw || "").toLowerCase().trim();
        if (!t) return;
        if (owners[t] && owners[t] !== name) {
          hits.push({
            token: t,
            winner: owners[t],
            loser: name,
            reason: "duplicate name or alias (save uses priority / first-wins)",
          });
        } else {
          owners[t] = name;
        }
      });
    });
    return hits;
  }

  // ------------------------------------------------------------------
  // Commands editor
  // ------------------------------------------------------------------

  function groupOptions(selected) {
    const ids = new Set((groupsState || []).map((g) => g.id));
    ids.add("core");
    ids.add("points");
    ids.add("minecraft");
    if (selected) ids.add(selected);
    return [...ids]
      .sort()
      .map((id) => `<option value="${escapeHtml(id)}"${id === selected ? " selected" : ""}>${escapeHtml(id)}</option>`)
      .join("");
  }

  function renderCmdTable() {
    const tb = $("cmd-table").querySelector("tbody");
    tb.innerHTML = "";
    const names = Object.keys(commandsState).sort();
    const clash = new Set(localConflicts(commandsState).map((c) => c.token));
    for (const name of names) {
      const d = commandsState[name] || {};
      const aliases = Array.isArray(d.aliases) ? d.aliases : [];
      const flagged = clash.has(String(name).toLowerCase()) || aliases.some((a) => clash.has(String(a).toLowerCase()));
      const tr = document.createElement("tr");
      if (name === selectedCmd) tr.classList.add("selected");
      tr.innerHTML =
        `<td><strong>${escapeHtml(name)}</strong>${flagged ? ' <span class="cmd-conflict">conflict</span>' : ""}</td>` +
        `<td>${escapeHtml(d.group || "core")}</td>` +
        `<td>${escapeHtml(d.permission || "public")}</td>` +
        `<td>${d.priority != null ? d.priority : 0}</td>` +
        `<td class="muted">${escapeHtml(d.description || "")}</td>`;
      tr.onclick = () => selectCommand(name);
      tb.appendChild(tr);
    }
  }

  function selectCommand(name) {
    selectedCmd = name;
    renderCmdTable();
    const d = commandsState[name] || {};
    const aliases = Array.isArray(d.aliases) ? d.aliases.join(", ") : "";
    const args = Array.isArray(d.args) ? d.args.join(", ") : "";
    const examples = Array.isArray(d.examples) ? d.examples.join("\n") : "";
    const allowed = Array.isArray(d.allowedValues) ? d.allowedValues.join(", ") : "";

    $("cmd-detail").innerHTML = `
      <div class="cmd-form">
        <label>Command name (no ! prefix)
          <input id="cmd-name" type="text" value="${escapeHtml(name)}" />
        </label>
        <label>Description
          <input id="cmd-desc" type="text" value="${escapeHtml(d.description || "")}" />
        </label>
        <div class="row2">
          <label>Permission
            <select id="cmd-perm">
              <option value="public">public</option>
              <option value="mod">mod</option>
              <option value="admin">admin</option>
            </select>
          </label>
          <label>Cost (points)
            <input id="cmd-cost" type="number" min="0" value="${d.cost != null ? d.cost : 0}" />
          </label>
        </div>
        <div class="row2">
          <label>Group
            <select id="cmd-group">${groupOptions(d.group || "core")}</select>
          </label>
          <label>Handler
            <select id="cmd-handler">
              <option value="game">game</option>
              <option value="core">core</option>
            </select>
          </label>
        </div>
        <div class="row2">
          <label>Priority (conflicts)
            <input id="cmd-priority" type="number" value="${d.priority != null ? d.priority : 0}" />
          </label>
          <label class="check" style="display:flex;align-items:flex-end;gap:8px;color:var(--text)">
            <input id="cmd-enabled" type="checkbox" ${d.enabled === false ? "" : "checked"} /> Enabled
          </label>
        </div>
        <label>Aliases (comma-separated)
          <input id="cmd-aliases" type="text" value="${escapeHtml(aliases)}" />
        </label>
        <label>Args (comma-separated, optional ones end with ?)
          <input id="cmd-args" type="text" value="${escapeHtml(args)}" placeholder="entity, qty?" />
        </label>
        <label>Minecraft template
          <textarea id="cmd-template" rows="2">${escapeHtml(d.template || "")}</textarea>
        </label>
        <label>Qty template (optional)
          <textarea id="cmd-qty-template" rows="2">${escapeHtml(d.qtyTemplate || "")}</textarea>
        </label>
        <div class="row2">
          <label>Default qty
            <input id="cmd-def-qty" type="number" value="${d.defaultQty != null ? d.defaultQty : ""}" />
          </label>
          <label>Max qty
            <input id="cmd-max-qty" type="number" value="${d.maxQty != null ? d.maxQty : ""}" />
          </label>
        </div>
        <label>Allowed values (comma-separated, optional)
          <input id="cmd-allowed" type="text" value="${escapeHtml(allowed)}" />
        </label>
        <label>Special (e.g. show_inventory)
          <input id="cmd-special" type="text" value="${escapeHtml(d.special || "")}" />
        </label>
        <label>Examples (one per line)
          <textarea id="cmd-examples" rows="2">${escapeHtml(examples)}</textarea>
        </label>
        <div class="form-row" style="margin-top:12px">
          <button class="primary" id="cmd-apply">Apply to list</button>
          <button class="danger" id="cmd-delete">Delete</button>
        </div>
        <p class="muted">Apply updates the in-memory list. Click <strong>Save commands.json</strong> to write disk.</p>
      </div>
    `;
    $("cmd-perm").value = d.permission || "public";
    if ($("cmd-handler")) $("cmd-handler").value = d.handler || (d.template ? "game" : "core");

    $("cmd-apply").onclick = () => {
      const newName = $("cmd-name").value.trim().replace(/^!/, "");
      if (!newName) return alert("Name required");
      const def = {
        permission: $("cmd-perm").value,
        description: $("cmd-desc").value.trim(),
        cost: num($("cmd-cost").value, 0),
        group: ($("cmd-group") && $("cmd-group").value) || "core",
        handler: ($("cmd-handler") && $("cmd-handler").value) || "game",
        priority: num($("cmd-priority") ? $("cmd-priority").value : 0, 0),
        enabled: $("cmd-enabled") ? $("cmd-enabled").checked : true,
      };
      const al = $("cmd-aliases").value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      if (al.length) def.aliases = al;
      const ar = $("cmd-args").value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      if (ar.length) def.args = ar;
      const tmpl = $("cmd-template").value.trim();
      if (tmpl) def.template = tmpl;
      const qt = $("cmd-qty-template").value.trim();
      if (qt) def.qtyTemplate = qt;
      const dq = $("cmd-def-qty").value;
      if (dq !== "") def.defaultQty = num(dq, 1);
      const mq = $("cmd-max-qty").value;
      if (mq !== "") def.maxQty = num(mq, 1);
      const av = $("cmd-allowed").value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      if (av.length) def.allowedValues = av;
      const sp = $("cmd-special").value.trim();
      if (sp) def.special = sp;
      const ex = $("cmd-examples").value
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter(Boolean);
      if (ex.length) def.examples = ex;

      if (selectedCmd && selectedCmd !== newName) {
        delete commandsState[selectedCmd];
      }
      commandsState[newName] = def;
      selectedCmd = newName;
      renderCmdTable();
      const clashes = localConflicts(commandsState);
      showConflicts(clashes);
      setCmdStatus(
        clashes.length
          ? `Updated — ${clashes.length} conflict(s) to resolve before or after save`
          : "Updated in list — save to hot-reload"
      );
    };

    $("cmd-delete").onclick = () => {
      const def = commandsState[name];
      delete commandsState[name];
      selectedCmd = null;
      $("cmd-detail").innerHTML = `<p class="muted">Select a command or click Add</p>`;
      renderCmdTable();
      setCmdStatus("Removed from list — save to write disk");
      undoToast("Deleted !" + name + " (Save to make it stick).", () => {
        commandsState[name] = def;
        selectCommand(name);
        setCmdStatus("Delete undone");
      });
    };
  }

  async function loadCommands() {
    try {
      const data = await api("/api/admin/commands");
      commandsState = data.commands || {};
      selectedCmd = null;
      $("cmd-detail").innerHTML = `<p class="muted">Select a command or click Add</p>`;
      renderCmdTable();
      showConflicts(data.conflicts || localConflicts(commandsState));
      setCmdStatus("Loaded");
    } catch (e) {
      setCmdStatus(String(e.message || e), false);
    }
  }

  $("cmd-reload").onclick = () => loadCommands();
  $("cmd-add").onclick = () => {
    let base = "newcmd";
    let n = 1;
    while (commandsState[base + (n > 1 ? n : "")]) n++;
    const name = base + (n > 1 ? n : "");
    commandsState[name] = {
      permission: "public",
      description: "",
      args: [],
      template: "",
      cost: 0,
      group: "core",
      handler: "game",
      priority: 0,
      enabled: true,
    };
    selectCommand(name);
    setCmdStatus("New command — edit then Apply, then Save");
  };

  $("cmd-save").onclick = async () => {
    try {
      const res = await api("/api/admin/commands", {
        method: "PUT",
        body: JSON.stringify({ commands: commandsState }),
      });
      showConflicts(res.conflicts || []);
      setCmdStatus(res.message || "Saved + hot-reloaded", true);
      setStatus("Commands hot-reloaded", true);
      loadGroups();
    } catch (e) {
      setCmdStatus(String(e.message || e), false);
    }
  };

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtTime(ts) {
    if (!ts) return "";
    try {
      return new Date(ts * 1000).toLocaleString();
    } catch {
      return String(ts);
    }
  }

  // ------------------------------------------------------------------
  // Credits tab
  // ------------------------------------------------------------------

  let creditsPlay = { playing: true, mode: "loop" };
  let creditsEditorReady = false;

  async function pushCreditsTheme(theme, persist) {
    await api("/api/admin/credits/theme", {
      method: "PUT",
      body: JSON.stringify({ ...theme, persist: !!persist }),
    });
  }

  function mountCreditsEditor() {
    if (creditsEditorReady || !window.CreditsStyleEditor || !$("crd-style-editor")) return;
    CreditsStyleEditor.mount($("crd-style-editor"), {
      onChange: (theme) => {
        pushCreditsTheme(theme, false).catch((e) => {
          const st = document.querySelector("#cs-status");
          if (st) st.textContent = String(e.message || e);
        });
      },
      onSave: async (theme) => {
        await pushCreditsTheme(theme, true);
      },
      onStyleChange: async (styleId) => {
        try {
          await api("/api/admin/credits/cast/style", {
            method: "PUT",
            body: JSON.stringify({ style_id: styleId }),
          });
        } catch (e) {
          const st = document.querySelector("#cs-status");
          if (st) st.textContent = String(e.message || e);
        }
      },
      onRestart: () => crdPlay({ playing: true, restart: true }),
    });
    creditsEditorReady = true;
  }

  function fillCreditsTheme(t) {
    mountCreditsEditor();
    if (window.CreditsStyleEditor) CreditsStyleEditor.fill(t || {});
  }

  function collectCreditsTheme() {
    if (window.CreditsStyleEditor) {
      return { ...CreditsStyleEditor.collect(), persist: true };
    }
    return { persist: true };
  }

  function renderCreditsRoster(r) {
    r = r || {};
    if ($("live-crd-count")) $("live-crd-count").textContent = (r.count || 0) + " names";
    if ($("crd-count-line")) {
      $("crd-count-line").textContent =
        "Unique chatters: " + (r.count || 0) +
        (r.by_platform
          ? " · " + Object.entries(r.by_platform).map(([k, v]) => k + " " + v).join(" · ")
          : "");
    }
    const list = $("crd-list");
    if (!list) return;
    const rows = r.chatters || [];
    list.innerHTML = rows.length
      ? rows
          .map((c) => {
            const tags = [
              c.is_mod ? "mod" : "",
              c.is_vip ? "vip" : "",
              c.is_subscriber ? "sub" : "",
              c.is_paid ? "paid" : "",
            ].filter(Boolean).join(" · ");
            const msgs = (c.messages || 1) + " msg" + ((c.messages || 1) === 1 ? "" : "s");
            return `<div class="crd-row${c.is_mod ? " is-mod" : ""}">` +
              `${c.is_mod ? "★ " : ""}${escapeHtml(c.display_name)} ` +
              `<span class="muted">${escapeHtml(c.platform)} · ${msgs}${tags ? " · " + escapeHtml(tags) : ""}` +
              `${c.job ? " · " + escapeHtml(c.job) : ""}</span></div>`;
          })
          .join("")
      : "<div>No chatters yet — enable credits and chat, or add a test name.</div>";
  }

  function renderCreditsPlay(p) {
    creditsPlay = { ...creditsPlay, ...(p || {}) };
    const mode = { loop: "Looping", once: "Play once", hold: "Holding still", clear: "Play once, then clear" }[creditsPlay.mode] || creditsPlay.mode;
    const text = (creditsPlay.playing === false ? "Paused · " : "") + mode +
      (creditsPlay.freeze ? " · list frozen" : " · live list");
    if ($("crd-play-state")) $("crd-play-state").textContent = text;
    if ($("live-crd-state")) $("live-crd-state").textContent = text;
    const label = creditsPlay.playing === false ? "Play" : "Pause";
    if ($("crd-pause")) $("crd-pause").textContent = label;
    if ($("live-crd-pause")) $("live-crd-pause").textContent = label;
  }

  // Live roster / play state while the Credits tab is open (same socket the overlay uses).
  let creditsWs = null;
  function connectCreditsWs() {
    if (creditsWs) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    try {
      creditsWs = new WebSocket(`${proto}://${location.host}/ws`);
    } catch (e) {
      creditsWs = null;
      return;
    }
    creditsWs.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (e) {
        return;
      }
      if (msg.type === "credits_roster") renderCreditsRoster(msg.data);
      else if (msg.type === "credits_play") renderCreditsPlay(msg.data);
    };
    creditsWs.onclose = () => {
      creditsWs = null;
      setTimeout(connectCreditsWs, 3000);
    };
  }

  async function initCreditsTab(force) {
    if (!$("tab-credits")) return;
    if ($("tab-credits").dataset.ready && !force) return;
    try {
      const data = await api("/api/admin/credits");
      $("tab-credits").dataset.ready = "1";
      if ($("crd-enabled")) $("crd-enabled").checked = !!data.enabled;
      fillCreditsTheme(data.theme);
      renderCreditsPlay(data.play);
      renderCreditsRoster(data.roster);
      connectCreditsWs();
      const cast = data.cast || {};
      if (window.CreditsStyleEditor) {
        CreditsStyleEditor.setStyles(cast.styles || [], cast.style_id);
      }
      if ($("crd-cmd-perm")) $("crd-cmd-perm").value = cast.command_permission || "mod";
      const pins = $("crd-pins");
      if (pins) {
        pins.innerHTML = (cast.overrides || []).map((p) =>
          `${escapeHtml(p.platform)}:${escapeHtml(p.username)} — ${escapeHtml(p.job)}`
        ).join("<br>") || "No pins";
      }
      const iframe = $("crd-preview");
      if (iframe) iframe.src = "/overlay/credits.html?t=" + Date.now();
    } catch (e) {
      if ($("crd-enable-status")) $("crd-enable-status").textContent = String(e.message || e);
    }
  }

  if ($("crd-enable-save")) {
    $("crd-enable-save").onclick = async () => {
      try {
        const res = await api("/api/admin/credits/enabled", {
          method: "PUT",
          body: JSON.stringify({ enabled: $("crd-enabled").checked }),
        });
        $("crd-enable-status").textContent = res.enabled ? "On" : "Off";
      } catch (e) {
        $("crd-enable-status").textContent = String(e.message || e);
      }
    };
  }
  if ($("crd-copy")) {
    $("crd-copy").onclick = async () => {
      const url = location.origin + "/overlay/credits.html";
      try {
        await navigator.clipboard.writeText(url);
        $("crd-enable-status").textContent = "URL copied";
      } catch {
        $("crd-enable-status").textContent = url;
      }
    };
  }
  async function crdPlay(body) {
    const res = await api("/api/admin/credits/play", { method: "POST", body: JSON.stringify(body) });
    renderCreditsPlay(res);
    return res;
  }
  if ($("crd-roll")) $("crd-roll").onclick = () => crdPlay({ playing: true, mode: "loop", freeze: true, restart: true });
  if ($("crd-live")) $("crd-live").onclick = () => crdPlay({ freeze: false, playing: true });
  if ($("crd-loop")) $("crd-loop").onclick = () => crdPlay({ mode: "loop", playing: true, restart: true });
  if ($("crd-once")) $("crd-once").onclick = () => crdPlay({ mode: "once", playing: true, freeze: true, restart: true });
  if ($("crd-hold")) $("crd-hold").onclick = () => crdPlay({ mode: "hold", playing: true });
  if ($("crd-once-clear")) {
    $("crd-once-clear").onclick = () => crdPlay({ mode: "clear", playing: true, freeze: true, restart: true });
  }
  if ($("crd-restart")) $("crd-restart").onclick = () => crdPlay({ playing: true, restart: true });
  if ($("crd-csv")) {
    $("crd-csv").onclick = async () => {
      try {
        const res = await fetch("/api/admin/credits/roster.csv", { headers: headers() });
        if (!res.ok) throw new Error((await res.text()) || res.statusText);
        const blob = await res.blob();
        const cd = res.headers.get("content-disposition") || "";
        const m = cd.match(/filename="?([^";]+)"?/);
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = m ? m[1] : "chatters.csv";
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
          URL.revokeObjectURL(a.href);
          a.remove();
        }, 1000);
      } catch (e) {
        if ($("crd-play-state")) $("crd-play-state").textContent = String(e.message || e);
      }
    };
  }
  if ($("crd-pause")) $("crd-pause").onclick = () => crdPlay({ playing: creditsPlay.playing === false });
  if ($("crd-reset")) {
    $("crd-reset").onclick = async () => {
      if (!confirm("Clear unique chatters for this session?")) return;
      await api("/api/admin/credits/reset", { method: "POST", body: "{}" });
      initCreditsTab(true);
    };
  }
  if ($("crd-save-look")) {
    $("crd-save-look").onclick = async () => {
      try {
        await api("/api/admin/credits/theme", {
          method: "PUT",
          body: JSON.stringify(collectCreditsTheme()),
        });
        $("crd-look-status").textContent = "Saved";
      } catch (e) {
        $("crd-look-status").textContent = String(e.message || e);
      }
    };
  }
  if ($("crd-seed")) {
    $("crd-seed").onclick = async () => {
      await api("/api/admin/credits/seed", {
        method: "POST",
        body: JSON.stringify({
          username: $("crd-seed-name").value,
          platform: $("crd-seed-plat").value,
        }),
      });
      initCreditsTab(true);
    };
  }
  if ($("crd-style-save")) {
    $("crd-style-save").onclick = async () => {
      try {
        await api("/api/admin/credits/command-permission", {
          method: "PUT",
          body: JSON.stringify({ command_permission: $("crd-cmd-perm").value }),
        });
        $("crd-style-status").textContent = "Saved";
        initCreditsTab(true);
      } catch (e) {
        $("crd-style-status").textContent = String(e.message || e);
      }
    };
  }
  if ($("crd-pin")) {
    $("crd-pin").onclick = async () => {
      await api("/api/admin/credits/cast/pin", {
        method: "POST",
        body: JSON.stringify({
          username: $("crd-pin-name").value,
          platform: $("crd-pin-plat").value,
          job: $("crd-pin-job").value,
        }),
      });
      initCreditsTab(true);
    };
  }
  if ($("crd-unpin")) {
    $("crd-unpin").onclick = async () => {
      await api("/api/admin/credits/cast/pin", {
        method: "POST",
        body: JSON.stringify({
          username: $("crd-pin-name").value,
          platform: $("crd-pin-plat").value,
          clear: true,
        }),
      });
      initCreditsTab(true);
    };
  }

  function fillMarketForm(data) {
    const mc = data.minecraft || {};
    const mkt = data.market || {};
    if ($("mkt-enabled")) $("mkt-enabled").checked = !!mkt.enabled;
    if ($("mkt-dyn-sym")) $("mkt-dyn-sym").value = (mc.dynamo_symbols || ["MINECRAF"]).join(", ");
    if ($("mkt-dyn-min")) $("mkt-dyn-min").value = mc.dynamo_min_factor ?? 0.25;
    if ($("mkt-dyn-max")) $("mkt-dyn-max").value = mc.dynamo_max_factor ?? 3;
    if ($("mkt-vault-sym")) $("mkt-vault-sym").value = mc.vault_symbol || "MINECRAF";
    if ($("mkt-vault-rate")) $("mkt-vault-rate").value = mc.vault_rf_per_point ?? 200;
    if ($("mkt-vault-min")) $("mkt-vault-min").value = mc.vault_min_rf ?? 1000;
    if ($("mkt-chest-sym")) $("mkt-chest-sym").value = mc.chest_symbol || "MINECRAF";
    if ($("mkt-chest-rate")) $("mkt-chest-rate").value = mc.chest_points_per_xp ?? 1;
    if ($("mkt-chest-min")) $("mkt-chest-min").value = mc.chest_min_xp ?? 1;
    if ($("mkt-chest-def")) $("mkt-chest-def").value = mc.chest_default_value ?? 0.05;
    if ($("mkt-chest-smelt")) $("mkt-chest-smelt").checked = mc.chest_use_smelt_xp !== false;
    if ($("mkt-chest-vals")) {
      const vals = mc.chest_item_values || {};
      $("mkt-chest-vals").value = Object.entries(vals).map(([k, v]) => k + ":" + v).join("\n");
    }
    if ($("mkt-hour-cap")) $("mkt-hour-cap").value = mkt.hourly_cap_points ?? 500;
    if ($("mkt-steam-sec")) $("mkt-steam-sec").value = mkt.steam_poll_sec ?? 1800;
    if ($("mkt-drain")) $("mkt-drain").checked = mc.power_drain !== false;
    if ($("mkt-drain-bps")) $("mkt-drain-bps").value = mc.power_drain_bps ?? 80;
    if ($("mkt-off-below")) $("mkt-off-below").value = mc.dynamo_off_below ?? 0.5;
    if ($("mkt-max-rf")) $("mkt-max-rf").value = mc.max_rf_per_tick ?? 2400;
    if ($("mkt-devices")) {
      const list = ((data.devices || {}).devices) || [];
      $("mkt-devices").hidden = false;
      $("mkt-devices").textContent = list.length
        ? list.map((d) => `${d.kind}  drain ${d.drainRate || 0}/15  FE ${d.orderedRf || 0}/t  ${d.id}`).join("\n")
        : "(no Fridge blocks reported — enable Minecraft + place a Dynamo / Chest)";
    }
    if ($("mkt-trade-impact")) $("mkt-trade-impact").checked = mkt.trade_impact !== false;
    if ($("mkt-trade-bps")) $("mkt-trade-bps").value = mkt.trade_impact_bps_per_100 ?? 40;
    const fx = data.factorio || {};
    const fxList = Array.isArray(fx.dynamo_symbols) ? fx.dynamo_symbols : String(fx.dynamo_symbols || "FACTORIO").split(",");
    if ($("mkt-fx-dyn-sym")) $("mkt-fx-dyn-sym").value = fxList.map((s) => String(s).trim()).filter(Boolean).join(", ");
    if ($("mkt-fx-dyn-min")) $("mkt-fx-dyn-min").value = fx.dynamo_min_factor ?? 0.25;
    if ($("mkt-fx-dyn-max")) $("mkt-fx-dyn-max").value = fx.dynamo_max_factor ?? 3;
    if ($("mkt-fx-vault-sym")) $("mkt-fx-vault-sym").value = fx.vault_symbol || "FACTORIO";
    if ($("mkt-fx-chest-sym")) $("mkt-fx-chest-sym").value = fx.chest_symbol || "FACTORIO";
    if ($("mkt-fx-flush-mj")) $("mkt-fx-flush-mj").value = fx.vault_flush_mj ?? 25;
    if ($("mkt-fx-flush-items")) $("mkt-fx-flush-items").value = fx.chest_flush_items ?? 20;
    if ($("mkt-fx-drain")) $("mkt-fx-drain").checked = !!fx.power_drain;
    if ($("mkt-fx-drain-bps")) $("mkt-fx-drain-bps").value = fx.power_drain_bps ?? 12;
    const fxBoost = data.factorio_boost || {};
    if ($("mkt-fx-boost")) {
      const bits = (fxBoost.symbols || []).map((s) => `${s.symbol} ${Number(s.factor).toFixed(2)}×`).join(" · ") || "no quotes";
      $("mkt-fx-boost").textContent = `Boost now: ${Number(fxBoost.factor || 1).toFixed(2)}×  (${bits})`;
    }
    const boost = data.boost || {};
    if ($("mkt-boost")) {
      const bits = (boost.symbols || []).map((s) => `${s.symbol} ${Number(s.factor).toFixed(2)}×`).join(" · ") || "no quotes";
      $("mkt-boost").textContent = `Boost now: ${Number(boost.factor || 1).toFixed(2)}×  (${bits})`;
    }
    const vault = data.vault || {};
    if ($("mkt-vault-live")) {
      $("mkt-vault-live").textContent =
        `Pending RF: ${vault.pendingRf ?? "—"}  lifetime ${vault.lifetimeRf ?? "—"}`;
    }
    if ($("mkt-chest-live")) {
      $("mkt-chest-live").textContent =
        `Pending XP: ${vault.pendingXp ?? "—"}  lifetime ${vault.lifetimeXp ?? "—"}`;
    }
    const holds = data.holdings || [];
    if ($("mkt-holdings")) {
      $("mkt-holdings").hidden = false;
      $("mkt-holdings").textContent = holds.length
        ? holds.map((h) => `user ${h.user_id}  ${h.symbol}  ${(h.milli_shares / 1000).toFixed(3)} sh`).join("\n")
        : "(no holdings — grant shares or dividends burn)";
    }
    if ($("mkt-status")) {
      const last = data.last_dividend;
      $("mkt-status").textContent = last
        ? `Last dividend ${last.symbol} ${last.points} pts (${last.reason || ""})`
        : "";
    }
    const body = document.querySelector("#mkt-book tbody");
    if (body) {
      const rows = ((data.tape || {}).instruments || []);
      body.innerHTML = rows.map((it) => {
        const ccu = it.steam_ccu != null ? it.steam_ccu : "—";
        const stale = it.steam_stale ? " stale" : "";
        const hidden = it.status === "hidden" || it.status === "delisted";
        return `<tr data-sym="${it.symbol}">
          <td><code>${it.symbol}</code></td>
          <td><input class="mkt-name" data-sym="${it.symbol}" type="text" value="${(it.name || "").replace(/"/g, "&quot;")}" /></td>
          <td>${it.book || ""}</td>
          <td><input class="mkt-appid" data-sym="${it.symbol}" type="number" min="0" value="${it.steam_appid || ""}" style="width:7.5em" /></td>
          <td class="${stale}">${ccu}</td>
          <td><input class="mkt-px" data-sym="${it.symbol}" type="number" step="0.1" value="${Number(it.price || 0).toFixed(2)}" style="width:5.5em" /></td>
          <td><input class="mkt-show" data-sym="${it.symbol}" type="checkbox" ${hidden ? "" : "checked"} /></td>
          <td>
            <button type="button" class="mkt-save-row" data-sym="${it.symbol}">Save</button>
            <button type="button" class="mkt-del-row" data-sym="${it.symbol}">Delist</button>
          </td>
        </tr>`;
      }).join("") || `<tr><td colspan="7" class="muted">No listings</td></tr>`;
    }
  }

  async function initMarketTab(force) {
    if (!$("tab-market")) return;
    if ($("tab-market").dataset.ready && !force) return;
    try {
      const data = await api("/api/admin/market");
      $("tab-market").dataset.ready = "1";
      fillMarketForm(data);
    } catch (e) {
      if ($("mkt-status")) $("mkt-status").textContent = String(e.message || e);
    }
  }

  if ($("mkt-refresh")) $("mkt-refresh").onclick = () => initMarketTab(true);
  if ($("mkt-save")) {
    $("mkt-save").onclick = async () => {
      try {
        await api("/api/admin/market/minecraft", {
          method: "PUT",
          body: JSON.stringify({
            enabled: $("mkt-enabled") ? $("mkt-enabled").checked : false,
            dynamo_symbols: $("mkt-dyn-sym").value,
            dynamo_min_factor: Number($("mkt-dyn-min").value),
            dynamo_max_factor: Number($("mkt-dyn-max").value),
            vault_symbol: $("mkt-vault-sym").value.trim().toUpperCase(),
            vault_rf_per_point: Number($("mkt-vault-rate").value),
            vault_min_rf: Number($("mkt-vault-min").value),
            chest_symbol: $("mkt-chest-sym").value.trim().toUpperCase(),
            chest_points_per_xp: Number($("mkt-chest-rate").value),
            chest_min_xp: Number($("mkt-chest-min").value),
            chest_default_value: Number($("mkt-chest-def") ? $("mkt-chest-def").value : 0.05),
            chest_use_smelt_xp: $("mkt-chest-smelt") ? $("mkt-chest-smelt").checked : true,
            chest_item_values: $("mkt-chest-vals") ? $("mkt-chest-vals").value : "",
            hourly_cap_points: Number($("mkt-hour-cap").value),
            steam_poll_sec: Number($("mkt-steam-sec") ? $("mkt-steam-sec").value : 1800),
            power_drain: $("mkt-drain") ? $("mkt-drain").checked : true,
            power_drain_bps: Number($("mkt-drain-bps") ? $("mkt-drain-bps").value : 12),
            dynamo_off_below: Number($("mkt-off-below") ? $("mkt-off-below").value : 0.5),
            max_rf_per_tick: Number($("mkt-max-rf") ? $("mkt-max-rf").value : 2400),
            trade_impact: $("mkt-trade-impact") ? $("mkt-trade-impact").checked : true,
            trade_impact_bps_per_100: Number($("mkt-trade-bps") ? $("mkt-trade-bps").value : 40),
          }),
        });
        if ($("mkt-status")) $("mkt-status").textContent = "Saved";
        initMarketTab(true);
      } catch (e) {
        if ($("mkt-status")) $("mkt-status").textContent = String(e.message || e);
      }
    };
  }
  if ($("mkt-fx-save")) {
    $("mkt-fx-save").onclick = async () => {
      try {
        await api("/api/admin/market/factorio", {
          method: "PUT",
          body: JSON.stringify({
            dynamo_symbols: $("mkt-fx-dyn-sym").value,
            dynamo_min_factor: Number($("mkt-fx-dyn-min").value),
            dynamo_max_factor: Number($("mkt-fx-dyn-max").value),
            vault_symbol: $("mkt-fx-vault-sym").value.trim().toUpperCase(),
            chest_symbol: $("mkt-fx-chest-sym").value.trim().toUpperCase(),
            vault_flush_mj: Number($("mkt-fx-flush-mj").value),
            chest_flush_items: Number($("mkt-fx-flush-items").value),
            power_drain: $("mkt-fx-drain") ? $("mkt-fx-drain").checked : false,
            power_drain_bps: Number($("mkt-fx-drain-bps") ? $("mkt-fx-drain-bps").value : 12),
          }),
        });
        if ($("mkt-status")) $("mkt-status").textContent = "Factorio market saved";
        initMarketTab(true);
      } catch (e) {
        if ($("mkt-status")) $("mkt-status").textContent = String(e.message || e);
      }
    };
  }
  if ($("mkt-hold-grant")) {
    $("mkt-hold-grant").onclick = async () => {
      try {
        const r = await api("/api/admin/market/holding", {
          method: "POST",
          body: JSON.stringify({
            user_id: Number($("mkt-hold-uid").value),
            symbol: $("mkt-hold-sym").value,
            shares: Number($("mkt-hold-shares").value),
          }),
        });
        if ($("mkt-status")) $("mkt-status").textContent = `Holding now ${r.milli_shares / 1000} sh`;
        initMarketTab(true);
      } catch (e) {
        if ($("mkt-status")) $("mkt-status").textContent = String(e.message || e);
      }
    };
  }
  if ($("mkt-add")) {
    $("mkt-add").onclick = async () => {
      try {
        const appid = $("mkt-new-appid").value;
        const feed = $("mkt-new-feed").value || (appid ? "steam" : "walk");
        await api("/api/admin/market/tickers", {
          method: "POST",
          body: JSON.stringify({
            symbol: $("mkt-new-sym").value,
            name: $("mkt-new-name").value,
            book: $("mkt-new-book").value,
            price: Number($("mkt-new-px").value || 10),
            base_price: Number($("mkt-new-px").value || 10),
            feed: feed,
            steam_appid: appid ? Number(appid) : null,
          }),
        });
        if ($("mkt-status")) $("mkt-status").textContent = "Ticker added";
        $("mkt-new-sym").value = "";
        $("mkt-new-name").value = "";
        $("mkt-new-appid").value = "";
        initMarketTab(true);
      } catch (e) {
        if ($("mkt-status")) $("mkt-status").textContent = String(e.message || e);
      }
    };
  }
  if ($("mkt-chat-add")) {
    $("mkt-chat-add").onclick = async () => {
      try {
        const uid = Number($("mkt-chat-uid").value);
        const sym = ($("mkt-chat-sym").value || "CHAT").toUpperCase();
        await api("/api/admin/market/tickers", {
          method: "POST",
          body: JSON.stringify({
            symbol: sym,
            name: "Chatter " + uid,
            book: "core",
            feed: "chatter",
            role: "chatter",
            chatter_user_id: uid,
            chatter_link_points: $("mkt-chat-link") ? $("mkt-chat-link").checked : true,
            chatter_streak_bonus: Number($("mkt-chat-bonus").value || 0.05),
            chatter_points_scale: Number($("mkt-chat-scale").value || 10),
          }),
        });
        if ($("mkt-status")) $("mkt-status").textContent = "Listed chatter " + uid + " as " + sym;
        initMarketTab(true);
      } catch (e) {
        if ($("mkt-status")) $("mkt-status").textContent = String(e.message || e);
      }
    };
  }
  if ($("mkt-steam-poll")) {
    $("mkt-steam-poll").onclick = async () => {
      try {
        const r = await api("/api/admin/market/steam/poll", { method: "POST", body: "{}" });
        if ($("mkt-status")) $("mkt-status").textContent = `Steam poll ${r.polled || 0} app(s)`;
        initMarketTab(true);
      } catch (e) {
        if ($("mkt-status")) $("mkt-status").textContent = String(e.message || e);
      }
    };
  }
  const bookTable = $("mkt-book");
  if (bookTable) {
    bookTable.addEventListener("click", async (ev) => {
      const save = ev.target.closest(".mkt-save-row");
      const del = ev.target.closest(".mkt-del-row");
      try {
        if (save) {
          const sym = save.dataset.sym;
          const input = bookTable.querySelector(`.mkt-appid[data-sym="${sym}"]`);
          const nameEl = bookTable.querySelector(`.mkt-name[data-sym="${sym}"]`);
          const pxEl = bookTable.querySelector(`.mkt-px[data-sym="${sym}"]`);
          const showEl = bookTable.querySelector(`.mkt-show[data-sym="${sym}"]`);
          const appid = input && input.value ? Number(input.value) : null;
          await api("/api/admin/market/tickers/" + encodeURIComponent(sym), {
            method: "PATCH",
            body: JSON.stringify({
              name: nameEl ? nameEl.value : undefined,
              price: pxEl ? Number(pxEl.value) : undefined,
              steam_appid: appid,
              feed: appid ? "steam" : "walk",
              status: showEl && !showEl.checked ? "hidden" : "listed",
            }),
          });
          if ($("mkt-status")) $("mkt-status").textContent = sym + " saved";
          initMarketTab(true);
        }
        if (del) {
          const sym = del.dataset.sym;
          await api("/api/admin/market/tickers/" + encodeURIComponent(sym), { method: "DELETE" });
          if ($("mkt-status")) $("mkt-status").textContent = sym + " delisted";
          initMarketTab(true);
        }
      } catch (e) {
        if ($("mkt-status")) $("mkt-status").textContent = String(e.message || e);
      }
    });
  }
  if ($("mkt-div-test")) {
    $("mkt-div-test").onclick = async () => {
      try {
        const r = await api("/api/admin/market/dividend", {
          method: "POST",
          body: JSON.stringify({
            symbol: ($("mkt-chest-sym") && $("mkt-chest-sym").value) || "MINECRAF",
            points: 10,
          }),
        });
        if ($("mkt-status")) $("mkt-status").textContent = JSON.stringify(r.payout);
        initMarketTab(true);
      } catch (e) {
        if ($("mkt-status")) $("mkt-status").textContent = String(e.message || e);
      }
    };
  }


  // ------------------------------------------------------------------
  // Chat games (page "Chat games"): run the live ones, settings, moods
  // ------------------------------------------------------------------
  let funData = null;
  let funTimer = 0;
  let funPrefix = "!";

  function funSay(id, msg, ok = true) {
    const el = $(id);
    if (!el) return;
    el.textContent = msg;
    el.style.color = ok ? "" : "#ff5c5c";
  }

  function funLines(text) {
    return String(text || "").split(/\n|\|/).map((x) => x.trim()).filter(Boolean);
  }

  function funBars(lines) {
    return (lines || []).map((l) =>
      `<div class="fun-bar${l.win ? " win" : ""}"><span class="lab">${escapeHtml(l.label)}</span>` +
      `<span class="track"><i style="width:${Math.round((Number(l.pct) || 0) * 100)}%"></i></span>` +
      `<span class="val">${escapeHtml(l.note || String(l.value ?? ""))}</span></div>`
    ).join("");
  }

  function funClock(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s2 = String(sec % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${s2}` : `${m}:${s2}`;
  }

  function renderFunStatus(st) {
    if (!st) return;
    const banner = $("fun-banner");
    const chips = [
      pill(!!st.active, st.active ? "Chat games on" : (st.enabled ? "on, but the command group is off" : "Chat games off")),
      pill(!!st.points_enabled, st.points_enabled ? "points on" : "points off"),
      pill(!!st.game_connected, st.game_connected ? "Stream Rooms connected" : "Stream Rooms not connected"),
    ];
    const boards = (st.boards || []).map((b) => escapeHtml(b.title || b.id)).join(" · ");
    if (banner) {
      banner.innerHTML = `<div class="live-chips">${chips.join("")}</div>` +
        `<div class="live-metrics"><span>Commands <strong>${(st.stats || {}).commands || 0}</strong></span>` +
        `<span>Combos <strong>${(st.stats || {}).combos || 0}</strong></span>` +
        `<span>Hype <strong>${(st.hype || {}).people || 0} chatting · level ${(st.hype || {}).level || 0}</strong></span>` +
        `<span class="muted">${boards ? "On screen: " + boards : "Nothing on screen"}</span></div>`;
    }
    const live = $("live-fun-state");
    if (live) live.textContent = !st.active ? "Off" : (boards ? "On screen: " + (st.boards || []).map((b) => b.title || b.id).join(" · ") : "Nothing on screen");
    // poll
    const poll = st.poll || {};
    funSay("fun-poll-state", poll.open ? "running" : "");
    const pollBoard = (st.boards || []).find((b) => b.id === "poll");
    if ($("fun-poll-view")) $("fun-poll-view").innerHTML = pollBoard ? funBars(pollBoard.lines) : "";
    // prediction
    const pr = st.predict || {};
    funSay("fun-pred-state", pr.open ? pr.state : "");
    const sel = $("fun-pred-win");
    if (sel) {
      const want = (pr.options || []).map((o, i) => `<option value="${i + 1}">${escapeHtml(o)}</option>`).join("");
      if (sel.dataset.sig !== want) {
        sel.innerHTML = want || '<option value="">winner…</option>';
        sel.dataset.sig = want;
      }
    }
    const prBoard = (st.boards || []).find((b) => b.id === "predict");
    if ($("fun-pred-view")) $("fun-pred-view").innerHTML = prBoard ? funBars(prBoard.lines) : "";
    // trivia / rating
    const tr = st.trivia || {};
    funSay("fun-trivia-state", (tr.open ? "asked: " + tr.question : "") + ` (${tr.bank || 0} questions)`);
    const rt = st.rate || {};
    funSay("fun-rate-state", rt.open ? `open · ${rt.average}/10 from ${rt.votes}` : "");
    if ($("fun-rate-history")) {
      $("fun-rate-history").innerHTML = (rt.history || []).map((r) =>
        `<li>${escapeHtml(r.title || "(untitled)")} — <strong>${Number(r.avg).toFixed(1)}</strong>/10 · ${r.votes} votes</li>`).join("");
    }
    // requests
    const q = (st.request || {}).queue || [];
    funSay("fun-req-count", q.length ? `${q.length} waiting` : "empty");
    const rb = $("fun-req-table") && $("fun-req-table").querySelector("tbody");
    if (rb) {
      rb.innerHTML = q.map((r, i) => {
        const link = r.url ? `<a href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.text)}</a>` : escapeHtml(r.text);
        return `<tr><td>${i + 1}${r.bumped ? " ⬆" : ""}</td><td>${link}</td><td>${escapeHtml((r.by || {}).display_name || "")}</td>` +
          `<td><button data-fun-req="played" data-id="${escapeHtml(r.id)}">Played</button> ` +
          `<button data-fun-req="remove" data-id="${escapeHtml(r.id)}">Remove</button></td></tr>`;
      }).join("") || '<tr><td colspan="4" class="muted">No requests</td></tr>';
    }
    // moments
    const moms = (st.moment || {}).moments || [];
    funSay("fun-mom-count", moms.length ? `${moms.length} shown` : "");
    const mb = $("fun-mom-table") && $("fun-mom-table").querySelector("tbody");
    if (mb) {
      mb.innerHTML = moms.map((m) =>
        `<tr><td><strong>${funClock(m.offset)}</strong></td><td>${new Date(m.ts * 1000).toLocaleString()}</td>` +
        `<td>${m.count} (${escapeHtml((m.users || []).join(", "))})</td><td>${escapeHtml(m.note || "")}</td></tr>`
      ).join("") || '<tr><td colspan="4" class="muted">No moments yet — chat types !clip</td></tr>';
    }
    if ($("fun-stream")) {
      const s2 = st.stream;
      $("fun-stream").textContent = s2 ? `Stream #${s2.id}, started ${new Date(s2.started * 1000).toLocaleString()}` : "No stream yet (starts with the first chat line).";
    }
  }

  function funFieldHtml(sec, f, val) {
    const id = `fun-f-${sec.id}-${f.key}`;
    const help = f.hint ? ` <span class="field-help">${escapeHtml(f.hint)}</span>` : "";
    if (f.kind === "bool") {
      return `<label class="check"><input type="checkbox" id="${id}" ${val ? "checked" : ""} /> ${escapeHtml(f.label)}</label>`;
    }
    if (f.kind === "select") {
      const opts = (f.options || []).map((o) => `<option ${o === val ? "selected" : ""}>${escapeHtml(o)}</option>`).join("");
      return `<label>${escapeHtml(f.label)}${help}<select id="${id}">${opts}</select></label>`;
    }
    if (f.kind === "list") {
      return `<label>${escapeHtml(f.label)}${help}<input id="${id}" type="text" value="${escapeHtml((val || []).join(", "))}" /></label>`;
    }
    const type = f.kind === "number" ? "number" : "text";
    const shown = f.kind === "command" ? funPrefix + (val || "") : (val ?? "");
    return `<label>${escapeHtml(f.label)}${help}<input id="${id}" type="${type}" step="any" value="${escapeHtml(String(shown))}" /></label>`;
  }

  function renderFunForm() {
    const cfg = funData.chat_games;
    $("fun-enabled").checked = !!cfg.enabled;
    $("fun-replies").checked = !!cfg.replies;
    $("fun-hold").value = cfg.board_hold_sec;
    $("fun-form").innerHTML = (funData.form || []).map((sec) => {
      const block = cfg[sec.id] || {};
      const pts = sec.needs_points ? ' <span class="pill-tag">points</span>' : "";
      return `<fieldset class="cfg-card"><legend>${escapeHtml(sec.title)}${pts}</legend>` +
        `<label class="check"><input type="checkbox" id="fun-f-${sec.id}-enabled" ${block.enabled ? "checked" : ""} /> On</label>` +
        `<p class="hint">${escapeHtml(sec.about || "")}</p>` +
        (sec.fields || []).map((f) => funFieldHtml(sec, f, block[f.key])).join("") + "</fieldset>";
    }).join("");
    const conf = funData.conflicts || [];
    const cb = $("fun-conflicts");
    if (cb) {
      cb.hidden = !conf.length;
      cb.innerHTML = conf.map((c) => `<div><code>${escapeHtml(funPrefix + c.token)}</code> (${escapeHtml(c.feature)}) is taken by the ${escapeHtml(c.winner)} — rename one of them.</div>`).join("");
    }
    renderFunMoods();
    try { buildSearchIndex(); } catch (_) { /* search index is optional */ }
  }

  function readFunForm() {
    const cfg = JSON.parse(JSON.stringify(funData.chat_games));
    cfg.enabled = $("fun-enabled").checked;
    cfg.replies = $("fun-replies").checked;
    cfg.board_hold_sec = Number($("fun-hold").value) || 12;
    (funData.form || []).forEach((sec) => {
      const block = cfg[sec.id] || (cfg[sec.id] = {});
      const on = $(`fun-f-${sec.id}-enabled`);
      if (on) block.enabled = on.checked;
      (sec.fields || []).forEach((f) => {
        const el = $(`fun-f-${sec.id}-${f.key}`);
        if (!el) return;
        if (f.kind === "bool") block[f.key] = el.checked;
        else if (f.kind === "number") block[f.key] = Number(el.value);
        else if (f.kind === "list") block[f.key] = el.value.split(",").map((x) => x.trim()).filter(Boolean);
        else if (f.kind === "command") block[f.key] = el.value.trim().replace(/^!+/, "").replace(new RegExp("^" + funPrefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), "");
        else block[f.key] = el.value;
      });
    });
    cfg.combos.moods = readFunMoods();
    return cfg;
  }

  function renderFunMoods() {
    const host = $("fun-moods");
    if (!host) return;
    const moods = funData.chat_games.combos.moods || [];
    host.innerHTML = moods.map((m, i) =>
      `<fieldset class="cfg-card fun-mood" data-i="${i}"><legend>` +
      `<input type="text" class="fm-label" value="${escapeHtml(m.label)}" /></legend>` +
      `<label class="check"><input type="checkbox" class="fm-on" ${m.enabled ? "checked" : ""} /> On</label>` +
      `<input type="hidden" class="fm-id" value="${escapeHtml(m.id)}" />` +
      `<label>Emotes <span class="field-help">comma separated</span><textarea class="fm-emotes" rows="3">${escapeHtml((m.emotes || []).join(", "))}</textarea></label>` +
      `<label>Emoji <input type="text" class="fm-emoji" value="${escapeHtml((m.emoji || []).join(" "))}" /></label>` +
      `<label>Effects <span class="field-help">[{"effect": "...", "params": {...}}]</span>` +
      `<textarea class="fm-effects" rows="4" spellcheck="false">${escapeHtml(JSON.stringify(m.effects || []))}</textarea></label>` +
      `<button type="button" class="danger fm-del">Remove mood</button></fieldset>`
    ).join("");
    host.querySelectorAll(".fm-del").forEach((b) => {
      b.onclick = () => {
        const i = Number(b.closest(".fun-mood").dataset.i);
        funData.chat_games.combos.moods = readFunMoods().filter((_, j) => j !== i);
        renderFunMoods();
      };
    });
  }

  function readFunMoods() {
    const out = [];
    document.querySelectorAll("#fun-moods .fun-mood").forEach((fs) => {
      let effects = [];
      try {
        effects = JSON.parse(fs.querySelector(".fm-effects").value || "[]");
      } catch (e) {
        throw new Error(`Effects for "${fs.querySelector(".fm-label").value}" aren't valid JSON`);
      }
      out.push({
        id: fs.querySelector(".fm-id").value || fs.querySelector(".fm-label").value,
        label: fs.querySelector(".fm-label").value,
        enabled: fs.querySelector(".fm-on").checked,
        emotes: fs.querySelector(".fm-emotes").value.split(",").map((x) => x.trim()).filter(Boolean),
        emoji: fs.querySelector(".fm-emoji").value.split(/[\s,]+/).map((x) => x.trim()).filter(Boolean),
        effects,
      });
    });
    return out;
  }

  async function loadFun() {
    try {
      funData = await api("/api/admin/chat_games");
      funPrefix = funData.prefix || "!";
      renderFunForm();
      renderFunStatus(funData.status);
      funSay("fun-status", "");
    } catch (e) {
      funSay("fun-status", String(e.message || e), false);
      if ($("fun-banner")) $("fun-banner").innerHTML = `<span class="muted">${escapeHtml(String(e.message || e))}</span>`;
    }
    if (funTimer) clearInterval(funTimer);
    funTimer = setInterval(async () => {
      const onFun = $("tab-fun") && $("tab-fun").classList.contains("active");
      const onLive = $("tab-live") && $("tab-live").classList.contains("active");
      if (!onFun && !onLive) {
        clearInterval(funTimer);
        funTimer = 0;
        return;
      }
      try {
        const d = await api("/api/admin/chat_games");
        funData.status = d.status;
        renderFunStatus(d.status);
      } catch (_) { /* keep the last view */ }
    }, 3000);
  }

  async function saveFun(statusId) {
    try {
      const cfg = readFunForm();
      const r = await api("/api/admin/chat_games", { method: "PUT", body: JSON.stringify({ chat_games: cfg }) });
      funData.chat_games = r.chat_games;
      funData.conflicts = r.conflicts;
      renderFunForm();
      renderFunStatus(r.status);
      funSay(statusId, r.message || "Saved");
    } catch (e) {
      funSay(statusId, String(e.message || e), false);
    }
  }

  async function funAction(feature, action, extra = {}) {
    try {
      const r = await api("/api/admin/chat_games/action", {
        method: "POST",
        body: JSON.stringify({ feature, action, ...extra }),
      });
      if (r.status) renderFunStatus(r.status);
      if (r.ok === false) funSay("fun-test-status", r.message || r.error || "Didn't work", false);
      return r;
    } catch (e) {
      funSay("fun-test-status", String(e.message || e), false);
      return null;
    }
  }

  function funExtra(key) {
    if (key === "poll/open") {
      const sec = $("fun-poll-sec").value;
      return { question: $("fun-poll-q").value, options: funLines($("fun-poll-opts").value), seconds: sec === "" ? null : Number(sec) };
    }
    if (key === "predict/open") return { question: $("fun-pred-q").value, options: funLines($("fun-pred-opts").value) };
    if (key === "predict/win") return { option: $("fun-pred-win").value };
    if (key === "rate/open") return { title: $("fun-rate-title").value };
    return {};
  }

  document.addEventListener("click", async (ev) => {
    const stageBtn = ev.target.closest("[data-stage]");
    if (stageBtn) {
      try {
        await api("/api/admin/stage", { method: "POST", body: JSON.stringify({ action: "curtain", value: stageBtn.dataset.stage }) });
        if ($("live-stage-msg")) $("live-stage-msg").textContent = "Sent: " + stageBtn.textContent.trim();
        setTimeout(loadLiveStatus, 800);
      } catch (e) {
        if ($("live-stage-msg")) $("live-stage-msg").textContent = String(e.message || e);
      }
      return;
    }
    const btn = ev.target.closest("[data-fun]");
    if (btn) {
      const key = btn.dataset.fun;
      if ((key.endsWith("/clear") || key === "predict/cancel") && !confirm("Sure? " + btn.textContent.trim())) return;
      const [feature, action] = key.split("/");
      await funAction(feature, action, funExtra(key));
      return;
    }
    const req = ev.target.closest("[data-fun-req]");
    if (req) {
      await funAction("request", req.dataset.funReq, { id: req.dataset.id });
      return;
    }
    const crowd = ev.target.closest("[data-fun-crowd]");
    if (crowd) {
      const names = ["TestAva", "TestBen", "TestCleo", "TestDev", "TestEmi"];
      const n = crowd.dataset.funCrowd === "!launch" ? 5 : 3;
      for (let i = 0; i < n; i++) await funSimulate(names[i], crowd.dataset.funCrowd, false);
    }
  });

  async function funSimulate(user, message, mod) {
    try {
      const r = await api("/api/admin/chat_games/simulate", {
        method: "POST",
        body: JSON.stringify({ username: user, message, platform: $("fun-test-plat").value, is_mod: mod }),
      });
      renderFunStatus(r.status);
      funSay("fun-test-status", `Sent as ${user}: ${message}`);
    } catch (e) {
      funSay("fun-test-status", String(e.message || e), false);
    }
  }

  if ($("fun-test-send")) {
    const send = () => {
      const msg = $("fun-test-msg").value.trim();
      if (msg) funSimulate($("fun-test-user").value.trim() || "TestViewer", msg, $("fun-test-mod").checked);
    };
    $("fun-test-send").onclick = send;
    $("fun-test-msg").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  }
  if ($("fun-save")) $("fun-save").onclick = () => saveFun("fun-status");
  if ($("fun-save-moods")) $("fun-save-moods").onclick = () => saveFun("fun-moods-status");
  if ($("fun-reload")) $("fun-reload").onclick = loadFun;
  if ($("fun-add-mood")) {
    $("fun-add-mood").onclick = () => {
      try {
        const moods = readFunMoods();
        moods.push({ id: "mood" + (moods.length + 1), label: "New mood", enabled: true, emotes: [], emoji: [],
          effects: [{ effect: "confetti", params: { count: 80 } }] });
        funData.chat_games.combos.moods = moods;
        renderFunMoods();
      } catch (e) {
        funSay("fun-moods-status", String(e.message || e), false);
      }
    };
  }
  if ($("fun-mom-csv")) {
    $("fun-mom-csv").onclick = async () => {
      try {
        const res = await fetch("/api/admin/chat_games/moments.csv", { headers: headers() });
        if (!res.ok) throw new Error((await res.text()) || res.statusText);
        const blob = await res.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "moments.csv";
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      } catch (e) {
        funSay("fun-mom-count", String(e.message || e), false);
      }
    };
  }

  // ------------------------------------------------------------------
  // Page save bar: one "Save changes" bar on every page that has settings.
  // Each section below is a block of settings with its own existing Save button (or save function);
  // the bar tracks which sections have unsaved edits and saves them all, Ctrl/Cmd+S included.
  // The sections' own buttons keep working and clear the "unsaved" mark too. Run / test / action
  // fields (poll question, test chat, alert test, tester, grant shares ...) are not sections.
  // ------------------------------------------------------------------
  var PAGE_SAVER = null;

  /** Leaving `tabId`'s page for another one: ask first if the current page has unsaved edits. */
  function pageCanLeave(nextTab) {
    const cur = document.querySelector(".panel.active");
    const here = cur ? cur.id.replace(/^tab-/, "") : "";
    if (!here || here === nextTab) return true;
    const names = pageUnsavedNames(here);
    if (!names.length) return true;
    const ok = confirm(
      "Unsaved changes on this page: " + names.join(", ") + ".\n\n" +
      "OK = leave without saving (they'll be lost).\nCancel = stay here and save first."
    );
    if (ok) pageDiscard(here);
    return ok;
  }

  function pageUnsavedNames(page) {
    const out = [];
    if (page === "config" && $("cfg-savebar") && $("cfg-savebar").classList.contains("dirty")) out.push("config.yaml settings");
    if (!PAGE_SAVER) return out;
    PAGE_SAVER.sections.forEach((s) => {
      if (s.page === page && s.dirty && !out.includes(s.name)) out.push(s.name);
    });
    return out;
  }

  function pageDiscard(page) {
    if (!PAGE_SAVER) return;
    PAGE_SAVER.sections.forEach((s) => {
      if (s.page === page) s.dirty = false;
    });
    PAGE_SAVER.render();
  }

  (function setupPageSaver() {
    const sections = [
      { key: "fun-settings", page: "fun", sub: "settings", name: "Chat games settings", group: "fun",
        scope: '#tab-fun .acc[data-sub="settings"]', button: "fun-save" },
      { key: "fun-moods", page: "fun", sub: "moods", name: "Emote combos", group: "fun",
        scope: '#tab-fun .acc[data-sub="moods"]', button: "fun-save-moods" },
      { key: "crd-enable", page: "credits", sub: "run", name: "Credits on/off",
        fields: ["crd-enabled"], button: "crd-enable-save" },
      { key: "crd-look", page: "credits", sub: "style", name: "Credits look",
        scope: "#crd-style-editor", clicks: ".cs-motion, .cs-preset", button: "cs-save",
        save: async () => {
          if (!window.CreditsStyleEditor || !$("cs-save")) return;
          const st = document.querySelector("#cs-status");
          try {
            await pushCreditsTheme(CreditsStyleEditor.collect(), true);
            if (st) st.textContent = "Saved";
          } catch (e) {
            if (st) st.textContent = String(e.message || e);
          }
        } },
      { key: "crd-perm", page: "credits", sub: "movie", name: "!credit permission",
        fields: ["crd-cmd-perm"], button: "crd-style-save" },
      { key: "alert-css", page: "alerts", sub: "look", name: "Alert CSS",
        fields: ["alert-css"], button: "alert-css-save" },
      { key: "mkt-mc", page: "market", sub: "minecraft", name: "Minecraft market", group: "mkt-mc",
        scope: '#tab-market .acc[data-sub="minecraft"]', button: "mkt-save" },
      { key: "mkt-inv", page: "market", sub: "investors", name: "Hourly cap + Steam refresh", group: "mkt-mc",
        fields: ["mkt-hour-cap", "mkt-steam-sec"], button: "mkt-save", also: ["mkt-inv-save"] },
      { key: "mkt-fx", page: "market", sub: "factorio", name: "Factorio market",
        scope: '#tab-market .acc[data-sub="factorio"]', button: "mkt-fx-save" },
      { key: "rx", page: "config", sub: "reactions", name: "Reactions",
        scope: "#rx-wrap", ignore: '[id^="rx-test"], #rx-img-name, #rx-img-file',
        clicks: "#rx-add, #rx-del-btn", button: "rx-save", reload: "rx-reload" },
      { key: "grp", page: "config", sub: "groups", name: "Command groups",
        scope: "#cfg-groups-wrap", clicks: "#grp-add, .grp-del", button: "grp-save", reload: "grp-reload" },
      { key: "cmd", page: "config", sub: "commands", name: "Chat commands",
        scope: '#tab-config .acc[data-sub="commands"]', inputMarks: false,
        clicks: "#cmd-add, #cmd-apply, #cmd-delete", button: "cmd-save", reload: "cmd-reload",
        // edits in the command form only count once applied to the list: apply them first
        before: () => {
          if (PAGE_SAVER.cmdFormEdited && $("cmd-apply")) $("cmd-apply").click();
        } },
    ].filter((s) => $("tab-" + s.page) && (s.save || $(s.button)));

    const bars = {};
    PAGE_SAVER = { sections, cmdFormEdited: false, render };

    const inScope = (s, el) => {
      if (!el || !el.closest) return false;
      if (s.fields) return s.fields.includes(el.id);
      const root = document.querySelector(s.scope);
      if (!root || !root.contains(el)) return false;
      if (s.ignore && el.closest(s.ignore)) return false;
      return true;
    };

    function markDirty(s) {
      if (s.dirty) return;
      s.dirty = true;
      render();
    }

    function markClean(sec) {
      sections.forEach((s) => {
        if (s === sec || (sec.group && s.group === sec.group) || s.button === sec.button) s.dirty = false;
      });
      if (sec.key === "cmd") PAGE_SAVER.cmdFormEdited = false;
      const st = bars[sec.page] && bars[sec.page].querySelector(".ps-status");
      if (st) {
        st.textContent = "Saved " + sec.name;
        st.style.color = "";
      }
      render();
    }

    // Only the person's own edits count (form fills from the server don't fire trusted events).
    ["input", "change"].forEach((type) => {
      document.addEventListener(type, (ev) => {
        if (!ev.isTrusted) return;
        const el = ev.target;
        if (el && el.type === "file") return;
        sections.forEach((s) => {
          if (!inScope(s, el)) return;
          if (s.key === "cmd") {
            if ($("cmd-detail") && $("cmd-detail").contains(el)) PAGE_SAVER.cmdFormEdited = true;
            return;
          }
          if (s.inputMarks !== false) markDirty(s);
        });
      }, true);
    });
    document.addEventListener("click", (ev) => {
      if (!ev.isTrusted) return;
      sections.forEach((s) => {
        if (!s.clicks) return;
        const hit = ev.target.closest && ev.target.closest(s.clicks);
        if (hit && inScope(s, hit)) markDirty(s);
      });
    }, true);

    // Runs one section's save. Its own handler shows its status; the call counters say whether it worked.
    async function runSave(s) {
      if (s.before) s.before();
      const writes = apiWrites;
      const fails = apiFails;
      try {
        if (s.save) await s.save();
        else {
          const btn = $(s.button);
          if (btn && typeof btn.onclick === "function") await btn.onclick();
          else if (btn) btn.click();
        }
      } catch (e) {
        return false;
      }
      const ok = apiFails === fails && apiWrites > writes;
      if (ok) markClean(s);
      return ok;
    }

    // A section's own Save button: clear its "unsaved" mark once that save went through.
    sections.forEach((s) => {
      [s.button].concat(s.also || []).forEach((id) => {
        const btn = $(id);
        if (!btn) {
          // drawn later (the credits style editor mounts when Credits opens): watch clicks on it
          document.addEventListener("click", (ev) => {
            if (!ev.target.closest || !ev.target.closest("#" + id)) return;
            const writes = apiWrites;
            const fails = apiFails;
            setTimeout(() => {
              if (apiFails === fails && apiWrites > writes) markClean(s);
            }, 1500);
          });
          return;
        }
        if (btn.dataset.psWired) return;
        btn.dataset.psWired = "1";
        if (id !== s.button) {
          btn.onclick = () => runSave(s);     // extra button (e.g. Investors) runs the section's save
          return;
        }
        if (typeof btn.onclick === "function" && !s.save) {
          const orig = btn.onclick;
          btn.onclick = async (ev) => {
            const writes = apiWrites;
            const fails = apiFails;
            await orig.call(btn, ev);
            if (apiFails === fails && apiWrites > writes) markClean(s);
          };
        } else {
          // handler added with addEventListener (credits look): watch the call counters briefly
          btn.addEventListener("click", () => {
            const writes = apiWrites;
            const fails = apiFails;
            setTimeout(() => {
              if (apiFails === fails && apiWrites > writes) markClean(s);
            }, 1500);
          });
        }
      });
      if (s.reload && $(s.reload)) {
        $(s.reload).addEventListener("click", () => {
          s.dirty = false;
          if (s.key === "cmd") PAGE_SAVER.cmdFormEdited = false;
          render();
        });
      }
    });

    async function savePage(page) {
      const panel = $("tab-" + page);
      const sub = panel ? panel.dataset.sub || "" : "";
      let todo = sections.filter((s) => s.page === page && s.dirty);
      if (!todo.length) todo = sections.filter((s) => s.page === page && s.sub === sub);   // save what's on screen
      const bar = bars[page];
      const status = bar && bar.querySelector(".ps-status");
      if (!todo.length) {
        if (status) status.textContent = "Nothing to save on this page";
        return;
      }
      const seen = new Set();
      const failed = [];
      if (status) status.textContent = "Saving…";
      for (const s of todo) {
        const id = s.group || s.button || s.key;
        if (seen.has(id)) continue;
        seen.add(id);
        if (!(await runSave(s))) failed.push(s.name);
      }
      if (status) {
        status.textContent = failed.length
          ? "Not saved: " + failed.join(", ") + " (see the message by its own Save button)"
          : "Saved " + todo.map((s) => s.name).filter((n, i, a) => a.indexOf(n) === i).join(", ");
        status.style.color = failed.length ? "var(--danger)" : "";
      }
    }

    // One bar per page, under the title (and under the config.yaml bar on Config).
    [...new Set(sections.map((s) => s.page))].forEach((page) => {
      const panel = $("tab-" + page);
      const bar = document.createElement("div");
      bar.className = "config-actions page-savebar";
      bar.dataset.page = page;
      bar.innerHTML =
        '<button type="button" class="primary ps-save" title="Save every unsaved setting on this page (Ctrl+S)">Save changes</button>' +
        '<span class="cfg-dirty ps-dirty" hidden></span>' +
        '<span class="muted ps-status"></span>';
      bar.querySelector(".ps-save").onclick = () => savePage(page);
      const after = page === "config" ? $("cfg-savebar") : panel.querySelector(":scope > .page-head");
      if (after && after.nextSibling) panel.insertBefore(bar, after.nextSibling);
      else panel.prepend(bar);
      bars[page] = bar;
    });

    function render() {
      Object.entries(bars).forEach(([page, bar]) => {
        const names = sections.filter((s) => s.page === page && s.dirty).map((s) => s.name);
        const uniq = names.filter((n, i) => names.indexOf(n) === i);
        bar.classList.toggle("dirty", uniq.length > 0);
        const flag = bar.querySelector(".ps-dirty");
        flag.hidden = !uniq.length;
        flag.textContent = "Unsaved: " + uniq.join(", ");
        if (uniq.length) bar.querySelector(".ps-status").textContent = "";
      });
      // dots on the sidebar items and the sub-page pills
      document.querySelectorAll(".admin-nav .tab").forEach((b) => {
        const t = b.dataset.tab;
        const on = b.dataset.sub
          ? sections.some((s) => s.page === t && s.sub === b.dataset.sub && s.dirty)
          : sections.some((s) => s.page === t && s.dirty);
        b.classList.toggle("unsaved", on);
      });
      document.querySelectorAll(".subtabs").forEach((sb) => {
        const panel = sb.closest(".panel");
        const page = panel ? panel.id.replace(/^tab-/, "") : "";
        sb.querySelectorAll(".subtab[data-sub]").forEach((b) => {
          b.classList.toggle("unsaved", sections.some((s) => s.page === page && s.sub === b.dataset.sub && s.dirty));
        });
      });
    }

    // Ctrl/Cmd+S on any page with a save bar (the config.yaml sub-pages keep their own handler).
    document.addEventListener("keydown", (ev) => {
      if (!(ev.ctrlKey || ev.metaKey) || ev.altKey || String(ev.key).toLowerCase() !== "s") return;
      const panel = document.querySelector(".panel.active");
      if (!panel) return;
      const page = panel.id.replace(/^tab-/, "");
      if (!bars[page] || (page === "config" && panel.classList.contains("yaml-sub"))) return;
      ev.preventDefault();
      savePage(page);
    });

    // Closing / reloading the tab with unsaved edits anywhere: the browser asks first.
    window.addEventListener("beforeunload", (ev) => {
      const cfgDirty = $("cfg-savebar") && $("cfg-savebar").classList.contains("dirty");
      if (!cfgDirty && !sections.some((s) => s.dirty)) return;
      ev.preventDefault();
      ev.returnValue = "";
    });

    render();
  })();

  refreshStats();
  loadUsers();
  // First page: the address (#page/sub), else the last page used, else Live.
  if (!routeFromHash()) {
    const last = loadJson(navStateKey, {}).lastTab;
    activateTab(last && $("tab-" + last) ? last : "live");
  }
})();
