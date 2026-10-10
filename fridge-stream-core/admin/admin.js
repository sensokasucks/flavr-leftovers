(() => {
  const $ = (id) => document.getElementById(id);
  const tokenKey = "stream_core_admin_token";
  // Game plugins' Market sub-pages are drawn after the page loads: remember which one the link asked for
  let marketPluginSub = (/^#market\/(plg-[\w-]+)/.exec(location.hash) || [])[1] || "";

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
      setStatus("Paste the admin token, or open the dashboard with the \"Open dashboard\" shortcut in Stream Core's data folder (it signs you in). The token is points.admin_token in config.yaml, or data/admin_token.txt.", false);
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
  // A sign-in link (…/admin/#token=…, made by Core at start) stores the token and drops it
  // from the address bar, so it doesn't stay on screen or in history.
  (function tokenFromLink() {
    const m = /(?:^#|&)token=([^&]+)/.exec(location.hash || "");
    if (!m) return;
    try {
      localStorage.setItem(tokenKey, decodeURIComponent(m[1]).trim());
    } catch (e) { /* storage blocked: the box below still works */ }
    const rest = (location.hash || "").replace(/(^#|&)token=[^&]+/, "$1").replace(/^#&/, "#").replace(/^#$/, "");
    history.replaceState(null, "", location.pathname + location.search + rest);
  })();
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
      bar.querySelectorAll(".subtab[data-sub]").forEach((b) => {
        const on = b.dataset.sub === pick;
        b.classList.toggle("active", on);
        b.setAttribute("aria-selected", on ? "true" : "false");
        b.tabIndex = on ? 0 : -1;
      });
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
    if (tabId === "chatlook") {
      loadChatStyle();
      loadOverlayAssets("chat");
    }
    if (tabId === "integrations") initIntegrationsTab();
    if (tabId === "credits") initCreditsTab();
    if (tabId === "market") initMarketTab();
    if (tabId === "chat") {
      loadChat();
      refreshChatLogBanner();
    }
    if (tabId === "redflags") {
      if (!(PAGE_SAVER && PAGE_SAVER.isDirty("rf"))) loadRedFlags();
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
    bar.setAttribute("role", "tablist");
    bar.querySelectorAll(".subtab[data-sub]").forEach((b) => {
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", b.classList.contains("active") ? "true" : "false");
    });
    bar.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".subtab[data-sub]");
      if (btn && panel) go(panel.id.replace(/^tab-/, ""), btn.dataset.sub);
    });
    // Left / Right / Home / End move between the pills, like any tab list
    bar.addEventListener("keydown", (ev) => {
      const tabs = [...bar.querySelectorAll(".subtab[data-sub]")].filter((b) => !b.hidden);
      const i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[ev.key];
      if (next == null) return;
      ev.preventDefault();
      const t = tabs[(next + tabs.length) % tabs.length];
      t.focus();
      t.click();
    });
  });
  window.addEventListener("popstate", routeFromHash);
  window.addEventListener("hashchange", () => {
    const m = /^#market\/(plg-[\w-]+)/.exec(location.hash);
    if (m && !document.querySelector(`#tab-market .acc[data-sub="${m[1]}"]`)) marketPluginSub = m[1];
  });
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
      const problems = [];
      for (const [name, p] of Object.entries(s.platforms || {})) {
        if (!p.configured_enabled && !p.running) continue;
        const word = p.running ? "" : p.state === "retrying" ? " retrying" : " stopped";
        const line = platformLine(name, p, s.server_time);
        chips.push(`<span title="${escapeHtml(line.text)}">${pill(!!p.running, escapeHtml(name) + word)}</span>`);
        if (!p.running || line.quiet) problems.push(`<li>${line.html}</li>`);
      }
      for (const [name, g] of Object.entries(s.games || {})) {
        if (!g.configured_enabled && !g.running) continue;
        chips.push(pill(!!g.running, escapeHtml(name) + (g.running ? "" : " stopped")));
      }
      if (!chips.length) chips.push(firstRunHint());
      renderRestartBanner(s);
      renderYouTubeBox(s);
      const m = s.metrics || {};
      const cr = s.credits || {};
      const rx = s.reactions || {};
      if ($("live-stage-state")) {
        const cur = (rx.stage || {}).curtain;
        $("live-stage-state").textContent = !rx.game_connected ? "Stream Rooms not connected" : cur ? "curtain " + cur : "";
      }
      box.innerHTML =
        `<div class="live-chips">${chips.join("")}</div>` +
        (problems.length ? `<ul class="status-list live-problems">${problems.join("")}</ul>` : "") +
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
      creditsEnabled = !!data.enabled;
      renderCreditsOnOff();
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

  /** "14 s ago" / "3 min ago" from two epoch-second stamps. */
  function agoText(then, now) {
    const sec = Math.max(0, Math.round((now || Date.now() / 1000) - then));
    if (sec < 60) return sec + " s ago";
    if (sec < 3600) return Math.round(sec / 60) + " min ago";
    return Math.round(sec / 3600) + " h ago";
  }

  /**
   * One plain line on how a chat platform is doing:
   * "Connected · last message 14 s ago", or why it isn't connected with a link to fix it.
   * quiet = connected, but nothing has arrived for a while (worth a look, not an error).
   */
  function platformLine(name, p, now) {
    const label = name.charAt(0).toUpperCase() + name.slice(1);
    const fixAt = /Advanced/i.test(p.last_error || "") ? "#config/advanced" : "#config/core";
    const go = ` <a href="${fixAt}">Fix in Settings →</a>`;
    if (!p.configured_enabled) return { text: label + ": off", html: `${label}: off`, quiet: false };
    if (p.running && p.connected) {
      let text = "Connected";
      let quiet = false;
      if (p.last_message_at) {
        text += " · last message " + agoText(p.last_message_at, now);
        quiet = (now || Date.now() / 1000) - p.last_message_at > 600;
      } else {
        text += " · no chat yet";
      }
      return { text: label + ": " + text, html: `<strong>${label}</strong> <span class="platform-ok">${escapeHtml(text)}</span>`, quiet };
    }
    if (p.running) {
      return { text: label + ": connecting…", html: `<strong>${label}</strong> <span class="platform-ok">connecting…</span>`, quiet: false };
    }
    const why = p.last_error || (p.state === "retrying"
      ? "Not connected yet; Core keeps trying."
      : "Switched on but not connected. Check the channel name, then Reconnect.");
    const cls = p.state === "retrying" ? "platform-why warn" : "platform-why";
    return {
      text: label + ": " + why,
      html: `<strong>${label}</strong> <span class="${cls}">${escapeHtml(why)}${go}</span>`,
      quiet: false,
    };
  }

  /** Nothing switched on yet (first run): say what to do next instead of an empty page. */
  function firstRunHint() {
    return '<span class="muted">No chat platforms on yet. <a href="#config/core">Connect Kick, Twitch or YouTube →</a> ' +
      'Then add the chat overlay to OBS from <a href="#sources">Sources &amp; overlays</a>.</span>';
  }

  /** "Restart Core to apply: …" with a Restart button, only while a saved setting needs it. */
  function renderRestartBanner(s) {
    const box = $("restart-banner");
    if (!box) return;
    const pending = (s && s.restart_needed) || [];
    box.hidden = !pending.length;
    if (!pending.length) return;
    $("restart-why").textContent = "Restart Stream Core to apply: " + pending.join("; ") + ".";
    $("restart-now").hidden = !s.can_restart;
    $("restart-how").textContent = s.can_restart
      ? ""
      : "Close the Stream Core window and double-click START Stream Core.bat again.";
  }

  async function restartCore() {
    const btn = $("restart-now");
    if (!confirm("Restart Stream Core now? Overlays and Stream Rooms reconnect by themselves in a few seconds.")) return;
    btn.disabled = true;
    $("restart-how").textContent = "Restarting…";
    try {
      const res = await api("/api/admin/restart", { method: "POST", body: "{}" });
      $("restart-how").textContent = res.message || "Restarting…";
      // wait for Core to go away and come back, then reload what's on screen
      let back = false;
      await new Promise((r) => setTimeout(r, 2500));
      for (let i = 0; i < 40 && !back; i++) {
        try {
          await api("/api/admin/status");
          back = true;
        } catch (_) {
          await new Promise((r) => setTimeout(r, 1000));
        }
      }
      $("restart-how").textContent = back ? "Stream Core restarted." : "Core hasn't come back yet. Check its window.";
      if (back) {
        loadStatus();
        loadLiveStatus();
      }
    } catch (e) {
      $("restart-how").textContent = readableActionError(e);
    } finally {
      btn.disabled = false;
    }
  }
  if ($("restart-now")) $("restart-now").onclick = restartCore;

  /** Live controls: the YouTube live video box (only while YouTube is switched on). */
  function renderYouTubeBox(s) {
    const card = $("live-yt-card");
    if (!card) return;
    const yt = (s.platforms || {}).youtube || {};
    card.hidden = !yt.configured_enabled;
    if (!yt.configured_enabled) return;
    const cur = $("live-yt-current");
    if (cur) {
      const line = platformLine("youtube", yt, s.server_time);
      cur.innerHTML = (yt.detail ? `Video <code>${escapeHtml(yt.detail)}</code> · ` : "No video set · ") + line.html.replace(/^<strong>Youtube<\/strong> /, "");
    }
  }
  async function connectYouTubeVideo() {
    const input = $("live-yt-video");
    const msg = $("live-yt-msg");
    const raw = (input.value || "").trim();
    const say = (t, ok = true) => {
      msg.textContent = t;
      msg.classList.toggle("bad", !ok);
    };
    const id = cleanYouTube(raw);
    if (!id) return say("Paste the link of your live stream (youtube.com/watch?v=…, youtu.be/…, /live/… or a Studio link).", false);
    $("live-yt-connect").disabled = true;
    say("Connecting…");
    try {
      const res = await api("/api/admin/platforms/youtube/video", { method: "POST", body: JSON.stringify({ video: raw }) });
      say(res.message || "Saved.");
      input.value = "";
      loadLiveStatus();
    } catch (e) {
      say(readableActionError(e), false);
    } finally {
      $("live-yt-connect").disabled = false;
    }
  }
  if ($("live-yt-connect")) $("live-yt-connect").onclick = connectYouTubeVideo;
  // Settings boxes tidy a pasted link as soon as you leave them (kick.com/name → name)
  [["cfg-kick-slug", (v) => cleanKick(v)], ["cfg-tw-channel", (v) => cleanTwitch(v)], ["cfg-yt-video", (v) => cleanYouTube(v)]]
    .forEach(([id, fn]) => {
      const el = $(id);
      if (!el) return;
      el.addEventListener("change", () => {
        const clean = fn(el.value);
        if (clean && clean !== el.value.trim()) el.value = clean;
      });
    });
  if ($("live-yt-video")) {
    $("live-yt-video").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") connectYouTubeVideo();
    });
  }

  // Pasted links → what each platform needs (same rules as core/platform_links.py).
  function cleanYouTube(raw) {
    const text = String(raw || "").trim();
    if (/^[A-Za-z0-9_-]{11}$/.test(text)) return text;
    let url;
    try {
      url = new URL(/^[a-z]+:\/\//i.test(text) ? text : "https://" + text);
    } catch (_) {
      return "";
    }
    const host = url.hostname.toLowerCase();
    if (!/(youtube\.com|youtu\.be|youtube-nocookie\.com)$/.test(host)) return "";
    const v = url.searchParams.get("v") || "";
    if (/^[A-Za-z0-9_-]{11}$/.test(v)) return v;
    if (host.endsWith("youtu.be")) {
      const first = url.pathname.split("/").filter(Boolean)[0] || "";
      return /^[A-Za-z0-9_-]{11}$/.test(first) ? first : "";
    }
    const m = /\/(?:live|shorts|embed|v|video)\/([A-Za-z0-9_-]{11})(?:[/?#]|$)/.exec(url.pathname);
    return m ? m[1] : "";
  }
  function cleanChannel(raw, host) {
    let text = String(raw || "").trim();
    if (text.toLowerCase().includes(host)) {
      try {
        const parts = new URL(/^[a-z]+:\/\//i.test(text) ? text : "https://" + text).pathname.split("/").filter(Boolean);
        if (parts[0] && parts[0].toLowerCase() === "popout" && parts.length > 1) parts.shift();
        text = parts[0] || "";
      } catch (_) {
        return text;
      }
    }
    return text.replace(/^[@#]+/, "").trim();
  }
  const cleanKick = (raw) => cleanChannel(raw, "kick.com");
  const cleanTwitch = (raw) => cleanChannel(raw, "twitch.tv").toLowerCase();

  // An error thrown by api() already reads well; network failures get plain words.
  function readableActionError(e) {
    const msg = String((e && e.message) || e || "");
    if (/Failed to fetch|NetworkError|Load failed/i.test(msg)) return "Can't reach Stream Core. Is it running?";
    return msg || "Something went wrong.";
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
      renderRestartBanner(s);
      const m = s.metrics || {};
      let html = "";
      html += `<section class="cfg-card"><h3 class="card-legend">Core</h3>
        <p>Listening on <code>${s.core.host}:${s.core.port}</code> · prefix <code>${s.core.command_prefix}</code></p>
        <p>Active command groups: <strong>${(s.command_groups_active || []).join(", ") || "—"}</strong>
        · ${s.commands_loaded || 0} command defs loaded</p>
        <p>Points system: ${s.points_enabled ? pill(true, "on") : pill(false, "off")}
        · Chat log: ${s.chat_log_enabled ? pill(true, "on") : pill(false, "off")}
        · Credits: ${s.credits && s.credits.running ? pill(true, "on") : pill(false, "off")}
          ${s.credits ? `<span class="muted">${s.credits.count || 0} unique</span>` : ""}</p>
      </section>`;

      html += `<section class="cfg-card"><h3 class="card-legend">Chat platforms</h3><ul class="status-list">`;
      for (const [name, p] of Object.entries(s.platforms || {})) {
        const run = p.running;
        const want = p.configured_enabled;
        const state = run ? pill(true, p.connected ? "connected" : "connecting") : p.state === "retrying" ? pill(false, "retrying") : pill(false, want ? "not connected" : "off");
        const line = platformLine(name, p, s.server_time);
        html += `<li><strong>${name}</strong> ${state}
          ${want ? pill(true, "config on") : pill(false, "config off")}
          ${p.detail ? `<span class="muted">${escapeHtml(p.detail)}</span>` : ""}
          ${want ? `<button class="platform-reconnect" data-platform="${name}">Reconnect</button>` : ""}
          ${want ? `<span class="platform-line">${line.html.replace(/^<strong>[^<]*<\/strong> /, "")}</span>` : ""}</li>`;
      }
      html += `</ul></section>`;

      html += `<section class="cfg-card"><h3 class="card-legend">Game plugins</h3><ul class="status-list">`;
      const gameRows = Object.entries(s.games || {});
      for (const [name, g] of gameRows) {
        html += `<li><strong>${escapeHtml(g.name || name)}</strong> ${g.running ? pill(true, "running") : pill(false, "stopped")}
          ${g.configured_enabled ? pill(true, "config on") : pill(false, "config off")}
          ${g.detail ? `<span class="muted">${escapeHtml(g.detail)}</span>` : g.player_name ? `<span class="muted">player ${escapeHtml(g.player_name)}</span>` : ""}
          ${g.error ? `<span class="muted" style="color:var(--danger)">${escapeHtml(g.error)}</span>` : ""}</li>`;
      }
      if (!gameRows.length) html += `<li class="muted">No game plugins installed (get them from flavr-game-plugins, folders go in plugins\\)</li>`;
      html += `</ul>
        <p class="hint">Commands are grouped by game. Stopped games hide their command group. Factorio and Granvir start as stats/overlay only; Granvir chat commands stay host-only in the BepInEx plugin.</p>
      </section>`;

      html += `<section class="cfg-card"><h3 class="card-legend">Live metrics</h3>
        <p>Viewers <strong>${m.viewers ?? 0}</strong>
        · CPM <strong>${(m.cpm ?? 0).toFixed ? m.cpm.toFixed(1) : m.cpm}</strong>
        · Power <strong>${m.power_level ?? 0}</strong>/15
        · Cmd rate <strong>${m.command_rate ?? 0}</strong></p>
      </section>`;

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

  // ── Sources & overlays: the list, and a Customise panel per overlay ──
  // Each row's switches come from Core (core/overlay_catalog.py, or a plugin's manifest). The
  // panel draws one control per switch and rewrites the address as you change them; nothing is
  // saved in Core, the address is the setting, so two OBS sources can differ.
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  // The Customise panels remember what you picked (and which were open) for this browser tab,
  // so following a "More for this overlay" link or pressing Refresh list doesn't reset them.
  const SRC_STATE_KEY = "fridge-admin-src-panels";
  function srcState() {
    try {
      return JSON.parse(sessionStorage.getItem(SRC_STATE_KEY) || "{}") || {};
    } catch {
      return {};
    }
  }
  function saveSrcState(st) {
    try {
      sessionStorage.setItem(SRC_STATE_KEY, JSON.stringify(st));
    } catch {}
  }
  const openSourcePanels = new Set(srcState().open || []);
  function rememberOpenPanels() {
    saveSrcState({ ...srcState(), open: [...openSourcePanels] });
  }

  /** "Copied ✓" on the button itself for a moment (the top-bar status is often off-screen). */
  async function copyWithFeedback(btn, text) {
    const label = btn.dataset.label || btn.textContent;
    btn.dataset.label = label;
    let ok = true;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      ok = false;
    }
    btn.textContent = ok ? "Copied ✓" : "Copy failed: select the address by hand";
    btn.classList.toggle("copied", ok);
    clearTimeout(btn._copyTimer);
    btn._copyTimer = setTimeout(() => {
      btn.textContent = label;
      btn.classList.remove("copied");
    }, ok ? 1500 : 4000);
    return ok;
  }

  function applyParamValues(panel, params, values) {
    for (const p of params) {
      if (!(p.key in values)) continue;
      const box = panel.querySelector(`.src-param[data-key="${CSS.escape(p.key)}"]`);
      if (!box) continue;
      const v = values[p.key];
      if (p.type === "bool") box.querySelector("input").checked = !!v;
      else if (p.type === "multi") {
        const list = Array.isArray(v) ? v.map(String) : [];
        box.querySelectorAll("input").forEach((i) => { i.checked = list.includes(i.value); });
      } else {
        const el = box.querySelector("select, input");
        if (el) el.value = v == null ? "" : String(v);
      }
    }
  }

  function buildOverlayUrl(page, params, values) {
    const q = new URLSearchParams();
    for (const p of params) {
      const v = values[p.key];
      if (p.type === "bool") {
        if (!!v !== !!p.default) q.set(p.key, v ? (p.on || "1") : (p.off || "0"));
      } else if (p.type === "multi") {
        const list = Array.isArray(v) ? v : [];
        if (list.length) q.set(p.key, list.join(","));
      } else {
        const s = v == null ? "" : String(v).trim();
        if (s !== "" && s !== String(p.default == null ? "" : p.default)) q.set(p.key, s);
        else if (s !== "" && p.type === "text" && p.default) q.set(p.key, s);   // a chart's ticker is always written
      }
    }
    const qs = q.toString().replace(/%2C/g, ",");
    return page + (qs ? "?" + qs : "");
  }

  function paramControl(id, p) {
    const name = `${id}-${p.key}`;
    const help = p.help ? `<span class="field-help">${esc(p.help)}</span>` : "";
    if (p.type === "bool") {
      return `<label class="check src-param" data-key="${esc(p.key)}"><input type="checkbox" ${p.default ? "checked" : ""} /> ${esc(p.label)}${help}</label>`;
    }
    if (p.type === "tri" || p.type === "select") {
      const opts = (p.options || []).map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(p.default ?? "") ? "selected" : ""}>${esc(l)}</option>`).join("");
      return `<label class="src-param" data-key="${esc(p.key)}">${esc(p.label)}${help}<select>${opts}</select></label>`;
    }
    if (p.type === "multi") {
      const boxes = (p.options || []).map(([v, l]) => `<label class="check"><input type="checkbox" value="${esc(v)}" /> ${esc(l)}</label>`).join("");
      return `<div class="src-param src-multi" data-key="${esc(p.key)}"><div class="src-param-title">${esc(p.label)}${help}</div><div class="src-multi-boxes">${boxes}</div></div>`;
    }
    if (p.type === "number") {
      const attrs = ["min", "max", "step"].filter((k) => p[k] != null).map((k) => `${k}="${esc(p[k])}"`).join(" ");
      return `<label class="src-param" data-key="${esc(p.key)}">${esc(p.label)}${help}<input type="number" ${attrs} value="${esc(p.default ?? "")}" /></label>`;
    }
    return `<label class="src-param" data-key="${esc(p.key)}">${esc(p.label)}${help}<input type="text" value="${esc(p.default ?? "")}" placeholder="${esc(p.placeholder || "")}" /></label>`;
  }

  function readParamValues(panel, params) {
    const values = {};
    for (const p of params) {
      const box = panel.querySelector(`.src-param[data-key="${CSS.escape(p.key)}"]`);
      if (!box) continue;
      if (p.type === "bool") values[p.key] = box.querySelector("input").checked;
      else if (p.type === "multi") values[p.key] = [...box.querySelectorAll("input:checked")].map((i) => i.value);
      else values[p.key] = box.querySelector("select, input").value;
    }
    return values;
  }

  function configControl(c) {
    if (c.type === "bool") return `<label class="check src-config" data-key="${esc(c.key)}"><input type="checkbox" /> ${esc(c.label)}</label>`;
    const attrs = ["min", "max", "step"].filter((k) => c[k] != null).map((k) => `${k}="${esc(c[k])}"`).join(" ");
    return `<label class="src-config" data-key="${esc(c.key)}">${esc(c.label)}<input type="number" ${attrs} /></label>`;
  }

  function getPath(obj, key) {
    return key.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), obj);
  }

  function setPath(obj, key, value) {
    const parts = key.split(".");
    let o = obj;
    for (const k of parts.slice(0, -1)) {
      if (!o[k] || typeof o[k] !== "object") o[k] = {};
      o = o[k];
    }
    o[parts[parts.length - 1]] = value;
  }

  async function fillConfigControls(panel, fields) {
    if (!fields.length) return;
    try {
      const data = await api("/api/admin/config");
      const cfg = data.config || {};
      for (const c of fields) {
        const box = panel.querySelector(`.src-config[data-key="${CSS.escape(c.key)}"] input`);
        if (!box) continue;
        const v = getPath(cfg, c.key);
        if (c.type === "bool") box.checked = !!v;
        else box.value = v ?? "";
      }
    } catch (_) {}
  }

  async function saveConfigControls(panel, fields, statusEl) {
    try {
      const data = await api("/api/admin/config");
      const cfg = data.config || {};
      for (const c of fields) {
        const box = panel.querySelector(`.src-config[data-key="${CSS.escape(c.key)}"] input`);
        if (!box) continue;
        setPath(cfg, c.key, c.type === "bool" ? box.checked : num(box.value, getPath(cfg, c.key)));
      }
      const res = await api("/api/admin/config", { method: "PUT", body: JSON.stringify({ config: cfg }) });
      statusEl.textContent = res.message || "Saved";
    } catch (e) {
      statusEl.textContent = String(e.message || e);
    }
  }

  function sourcePanel(src, idx) {
    const id = `src${idx}`;
    const params = src.params || [];
    const settings = src.settings || [];
    const config = src.config || [];
    const page = src.page || src.url.split("?")[0];
    let html = `<div class="src-panel" data-page="${esc(page)}">`;
    if (params.length) html += `<div class="src-params">${params.map((p) => paramControl(id, p)).join("")}</div>`;
    else html += `<p class="hint">This overlay has no switches on its address.</p>`;
    html += `<div class="src-url-row"><code class="src-url">${esc(src.url)}</code><button type="button" class="src-copy">Copy</button><button type="button" class="src-preview-btn">Preview</button>` +
      (params.length ? `<button type="button" class="src-reset link-btn" title="Back to the overlay's defaults">Reset switches</button>` : "") + `</div>`;
    html += `<div class="src-preview" hidden></div>`;
    if (config.length) {
      html += `<div class="src-config-box"><div class="src-param-title">Saved settings (config.yaml)</div>${config.map(configControl).join("")}<div class="form-row"><button type="button" class="src-config-save">Save settings</button><span class="muted src-config-status"></span></div></div>`;
    }
    if (settings.length) {
      html += `<p class="hint">More for this overlay: ${settings.map((s) => `<a href="${esc(s.hash)}">${esc(s.label)}</a>`).join(" · ")}</p>`;
    }
    html += `</div>`;
    return html;
  }

  function wireSourcePanel(tr, src) {
    const panel = tr.querySelector(".src-panel");
    const params = src.params || [];
    const page = panel.dataset.page;
    const urlEl = panel.querySelector(".src-url");
    const previewBox = panel.querySelector(".src-preview");
    const refresh = (remember = true) => {
      const values = readParamValues(panel, params);
      urlEl.textContent = buildOverlayUrl(page, params, values);
      if (remember && params.length) {
        const st = srcState();
        saveSrcState({ ...st, values: { ...(st.values || {}), [page]: values } });
      }
      if (!previewBox.hidden) showPreview();
    };
    const showPreview = () => {
      previewBox.hidden = false;
      previewBox.innerHTML = `<iframe title="Overlay preview" src="${esc(urlEl.textContent)}"></iframe><p class="hint">Transparent parts show the checkerboard. The source in OBS has your scene behind it instead.</p>`;
    };
    panel.querySelectorAll(".src-param input, .src-param select").forEach((el) => { el.oninput = refresh; el.onchange = refresh; });
    const copyBtn = panel.querySelector(".src-copy");
    copyBtn.onclick = () => copyWithFeedback(copyBtn, urlEl.textContent);
    const resetBtn = panel.querySelector(".src-reset");
    if (resetBtn) {
      resetBtn.onclick = () => {
        const defaults = {};
        for (const p of params) defaults[p.key] = p.type === "multi" ? [] : p.default ?? (p.type === "bool" ? false : "");
        applyParamValues(panel, params, defaults);
        const st = srcState();
        const values = { ...(st.values || {}) };
        delete values[page];
        saveSrcState({ ...st, values });
        refresh(false);
      };
    }
    panel.querySelector(".src-preview-btn").onclick = () => {
      if (previewBox.hidden) showPreview();
      else { previewBox.hidden = true; previewBox.innerHTML = ""; }
    };
    const save = panel.querySelector(".src-config-save");
    if (save) {
      fillConfigControls(panel, src.config || []);
      save.onclick = () => saveConfigControls(panel, src.config || [], panel.querySelector(".src-config-status"));
    }
    const kept = (srcState().values || {})[page];
    if (kept && params.length) applyParamValues(panel, params, kept);
    refresh(false);
  }

  async function loadSources() {
    const tb = $("sources-table") && $("sources-table").querySelector("tbody");
    if (!tb) return;
    try {
      const s = await api("/api/admin/status");
      tb.innerHTML = "";
      (s.sources || []).forEach((src, idx) => {
        const canCustomise = Array.isArray(src.params) || (src.settings && src.settings.length) || (src.config && src.config.length);
        const tr = document.createElement("tr");
        tr.innerHTML =
          `<td><strong>${esc(src.name)}</strong></td>` +
          `<td><code class="url-cell">${esc(src.url)}</code></td>` +
          `<td class="muted">${esc(src.notes || "")}</td>` +
          `<td class="src-actions"><button type="button" class="copy-url" data-url="${esc(src.url)}">Copy</button>` +
          (canCustomise ? `<button type="button" class="src-customise" data-idx="${idx}">Customise</button>` : "") + `</td>`;
        tb.appendChild(tr);
        if (canCustomise) {
          const ptr = document.createElement("tr");
          ptr.className = "src-panel-row";
          ptr.hidden = !openSourcePanels.has(src.name);
          ptr.innerHTML = `<td colspan="4">${sourcePanel(src, idx)}</td>`;
          tb.appendChild(ptr);
          wireSourcePanel(ptr, src);
          tr.querySelector(".src-customise").onclick = () => {
            ptr.hidden = !ptr.hidden;
            if (ptr.hidden) openSourcePanels.delete(src.name); else openSourcePanels.add(src.name);
            rememberOpenPanels();
            tr.querySelector(".src-customise").setAttribute("aria-expanded", ptr.hidden ? "false" : "true");
          };
          tr.querySelector(".src-customise").setAttribute("aria-expanded", ptr.hidden ? "false" : "true");
        }
      });
      tb.querySelectorAll(".copy-url").forEach((btn) => {
        btn.onclick = () => copyWithFeedback(btn, btn.dataset.url);
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
      loadAlertAssets();
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

  // ── Chat overlay look (skin, behaviour, custom CSS) ──────────
  function setChatStatus(id, msg, ok = true) {
    const el = $(id);
    if (!el) return;
    el.textContent = msg;
    el.style.color = ok ? "#53fc18" : "#ff5c5c";
  }

  function selectedChatSkin() {
    const el = document.querySelector('input[name="chat-skin"]:checked');
    return (el && el.value) || "classic";
  }

  function applyChatPreviewSkin(skin) {
    const iframe = $("chat-preview");
    if (!iframe) return;
    iframe.src = "/overlay/chat.html?preview=1&skin=" + encodeURIComponent(skin || "classic") + "&t=" + Date.now();
  }

  function chatOptionsFromForm() {
    return {
      hide_after_sec: num($("chat-opt-hide").value, 0),
      max_messages: num($("chat-opt-max").value, 30),
      newest_on_top: $("chat-opt-top").checked,
      show_avatars: $("chat-opt-avatars").checked,
      sound_volume: num($("chat-opt-volume").value, 60) / 100,
      sound_min_gap_sec: num($("chat-opt-gap").value, 2),
    };
  }

  function fillChatOptions(o) {
    if (!o || !$("chat-opt-hide")) return;
    $("chat-opt-hide").value = o.hide_after_sec ?? 0;
    $("chat-opt-max").value = o.max_messages ?? 30;
    $("chat-opt-top").checked = !!o.newest_on_top;
    $("chat-opt-avatars").checked = !!o.show_avatars;
    $("chat-opt-volume").value = Math.round((o.sound_volume ?? 0.6) * 100);
    $("chat-opt-volume-val").textContent = $("chat-opt-volume").value;
    $("chat-opt-gap").value = o.sound_min_gap_sec ?? 2;
  }

  async function loadChatStyle() {
    if (!$("chat-css")) return;
    try {
      const data = await api("/api/admin/chat/style");
      const skin = data.skin || "classic";
      const radio = $("chat-skin-" + skin);
      if (radio) radio.checked = true;
      $("chat-css").value = data.css || "";
      fillChatOptions(data.options);
      applyChatPreviewSkin(skin);
      setChatStatus("chat-css-status", "Loaded");
    } catch (e) {
      setChatStatus("chat-css-status", String(e.message || e), false);
    }
  }

  async function saveChatStyle(part) {
    const body = {};
    if (part === "skin") body.skin = selectedChatSkin();
    if (part === "css") body.css = $("chat-css").value;
    if (part === "options") body.options = chatOptionsFromForm();
    const statusId = part === "options" ? "chat-opt-status" : "chat-css-status";
    try {
      const res = await api("/api/admin/chat/style", { method: "PUT", body: JSON.stringify(body) });
      applyChatPreviewSkin(res.skin || selectedChatSkin());
      setChatStatus(statusId, res.message || "Saved");
    } catch (e) {
      setChatStatus(statusId, String(e.message || e), false);
    }
  }

  document.querySelectorAll('input[name="chat-skin"]').forEach((el) => {
    el.onchange = () => saveChatStyle("skin");
  });
  if ($("chat-css-save")) $("chat-css-save").onclick = () => saveChatStyle("css");
  if ($("chat-css-reload")) $("chat-css-reload").onclick = () => applyChatPreviewSkin(selectedChatSkin());
  if ($("chat-opt-save")) $("chat-opt-save").onclick = () => saveChatStyle("options");
  if ($("chat-opt-volume")) {
    $("chat-opt-volume").oninput = () => { $("chat-opt-volume-val").textContent = $("chat-opt-volume").value; };
  }
  if ($("alert-opt-volume")) {
    $("alert-opt-volume").oninput = () => { $("alert-opt-volume-val").textContent = $("alert-opt-volume").value; };
    $("alert-opt-volume").onchange = async () => {
      try {
        await api("/api/admin/alerts/style", {
          method: "PUT",
          body: JSON.stringify({ options: { sound_volume: num($("alert-opt-volume").value, 80) / 100 } }),
        });
        const st = $("alerts-assets-status");
        if (st) st.textContent = "Volume saved";
      } catch (e) {
        const st = $("alerts-assets-status");
        if (st) st.textContent = String(e.message || e);
      }
    };
  }

  // ── Overlay pictures and sounds (alerts + chat), uploaded as base64 JSON ──
  const ASSET_LABELS = {
    alerts: {
      follow: "Follow", subscribe: "Subscribe", resub: "Resub", gift: "Gifted sub", raid: "Raid", host: "Host",
      bits: "Bits / cheer", superchat: "Super Chat", donation: "Donation",
    },
    chat: {
      background: "Background picture", "badge-broadcaster": "Host badge", "badge-mod": "Mod badge",
      "badge-vip": "VIP badge", "badge-sub": "Sub badge", "badge-og": "OG badge", "badge-founder": "Founder badge",
      message: "New message sound", paid: "Paid message sound (Super Chat, Kicks)",
    },
  };

  function assetRow(name, slot, kind, url) {
    const label = (ASSET_LABELS[name] || {})[slot] || slot;
    const accept = kind === "sound" ? "audio/*" : "image/*,video/webm";
    let current = '<span class="muted">none</span>';
    if (url) {
      const src = "/overlay/" + url + "?t=" + Date.now();
      if (kind === "sound") current = `<audio controls preload="none" src="${src}"></audio>`;
      else if (/\.webm$/i.test(url)) current = `<video class="asset-thumb" muted loop autoplay playsinline src="${src}"></video>`;
      else current = `<img class="asset-thumb" src="${src}" alt="" />`;
    }
    return `<div class="asset-row" data-slot="${slot}" data-kind="${kind}">
      <div class="asset-label"><strong>${label}</strong><span class="muted">${kind === "sound" ? "sound" : "picture"} · <code>${slot}</code></span></div>
      <div class="asset-current">${current}</div>
      <div class="asset-actions">
        <input type="file" accept="${accept}" />
        <button type="button" class="asset-upload">Upload</button>
        ${url ? '<button type="button" class="asset-remove">Remove</button>' : ""}
      </div>
    </div>`;
  }

  async function loadOverlayAssets(name) {
    const box = $(name + "-assets");
    if (!box) return;
    try {
      const data = await api(`/api/admin/overlays/${name}/assets`);
      let html = "";
      for (const slot of data.image_slots || []) html += assetRow(name, slot, "image", (data.media || {})[slot]);
      for (const slot of data.sound_slots || []) html += assetRow(name, slot, "sound", (data.sounds || {})[slot]);
      box.innerHTML = html;
      box.querySelectorAll(".asset-row").forEach((row) => {
        const slot = row.dataset.slot;
        const st = $(name + "-assets-status");
        row.querySelector(".asset-upload").onclick = async () => {
          const f = row.querySelector('input[type="file"]').files[0];
          if (!f) { if (st) st.textContent = "Pick a file first."; return; }
          if (st) st.textContent = "Uploading…";
          try {
            const dataUrl = await new Promise((resolve, reject) => {
              const rd = new FileReader();
              rd.onload = () => resolve(rd.result);
              rd.onerror = () => reject(new Error("Couldn't read the file"));
              rd.readAsDataURL(f);
            });
            await api(`/api/admin/overlays/${name}/assets/${encodeURIComponent(slot)}`, {
              method: "POST",
              body: JSON.stringify({ data: dataUrl }),
            });
            if (st) st.textContent = `Saved ${slot}. Open overlays pick it up within a few seconds.`;
            loadOverlayAssets(name);
          } catch (e) {
            if (st) st.textContent = String(e.message || e);
          }
        };
        const rm = row.querySelector(".asset-remove");
        if (rm) {
          rm.onclick = async () => {
            if (!confirm(`Remove the ${slot} file?`)) return;
            try {
              await api(`/api/admin/overlays/${name}/assets/${encodeURIComponent(slot)}?kind=${row.dataset.kind}`, { method: "DELETE" });
              if (st) st.textContent = `Removed ${slot}.`;
              loadOverlayAssets(name);
            } catch (e) {
              if (st) st.textContent = String(e.message || e);
            }
          };
        }
      });
    } catch (e) {
      box.innerHTML = `<span class="muted">${String(e.message || e)}</span>`;
    }
  }

  async function loadAlertAssets() {
    await loadOverlayAssets("alerts");
    try {
      const data = await api("/api/admin/alerts/style");
      if ($("alert-opt-volume") && data.options && data.options.sound_volume != null) {
        $("alert-opt-volume").value = Math.round(Number(data.options.sound_volume) * 100);
        $("alert-opt-volume-val").textContent = $("alert-opt-volume").value;
      }
    } catch (_) {}
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
        ? `<p class="integ-empty">No commands in group <code>${escapeHtml(game.command_group)}</code>. Add them under Settings → Chat commands (group: ${escapeHtml(game.id)}).</p>`
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
        host.innerHTML = `<p class="integ-empty">No game plugins installed. Copy a game's folder from the game plugins download into the plugins folder, switch a game on under Settings → Game plugins and restart Core.</p>`;
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
        btn.onclick = () => copyWithFeedback(btn, btn.dataset.url || "");
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
        <p id="user-action-msg" class="action-msg" role="status" aria-live="polite"></p>
        <h3>Linked accounts</h3>
        <ul class="identities">${idents || "<li class='muted'>None</li>"}</ul>

        <h3>Adjust points</h3>
        <div class="form-row">
          <input type="number" id="pts-delta" placeholder="e.g. 50 or -20" />
          <input id="pts-reason" placeholder="Reason" value="admin adjust" />
          <button class="primary" id="pts-apply">Apply</button>
        </div>

        <h3>Chat</h3>
        <div class="form-row">
          <button type="button" id="user-chatlog" title="Chat history, only this person">Chat log</button>
          <button type="button" id="user-csv" title="Everything this person wrote, as a CSV file">Download CSV</button>
          <button type="button" class="danger" id="user-flag" title="Hide them from every overlay and Stream Rooms (Red flags page)">Red-flag</button>
        </div>

        <h3>Link another platform account</h3>
        <div class="form-row">
          <label for="link-platform" class="visually-hidden">Platform</label>
          <select id="link-platform">
            <option value="kick">kick</option>
            <option value="twitch">twitch</option>
            <option value="youtube">youtube</option>
          </select>
          <label for="link-user" class="visually-hidden">Their name on that platform</label>
          <input id="link-user" placeholder="Their name on that platform" autocomplete="off" />
          <button type="button" id="link-btn">Link</button>
        </div>
        <p class="muted">If Core already knows that name on that platform, the two become one person and their points add up. If not, their first chat line there joins this person.</p>

        <h3>Merge another person into this one</h3>
        <div class="form-row">
          <label for="merge-q" class="visually-hidden">Find the person to merge in</label>
          <input id="merge-q" type="search" placeholder="Find them by name…" autocomplete="off" />
          <button type="button" id="merge-find">Find</button>
        </div>
        <div id="merge-results" class="merge-results"></div>

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

      const who = u.display_name || "user #" + u.id;
      // every button answers on the line under the name, also after the panel redraws
      const userMsg = (text, ok = true) => {
        const el = $("user-action-msg");
        if (!el) return;
        el.textContent = text;
        el.classList.toggle("bad", !ok);
      };
      const act = async (btn, work) => {
        btn.disabled = true;
        userMsg("Working…");
        try {
          const done = await work();
          if (!done || !done.msg) userMsg("");
          if (done && done.redraw) await selectUser(id);
          if (done && done.msg) userMsg(done.msg, true);
        } catch (e) {
          userMsg(readableActionError(e), false);
        } finally {
          const live = btn.id ? $(btn.id) : btn;
          if (live) live.disabled = false;
        }
      };
      $("pts-apply").onclick = () => act($("pts-apply"), async () => {
        const delta = parseInt($("pts-delta").value, 10);
        if (Number.isNaN(delta) || !delta) throw new Error("Type how many points, like 50 or -20.");
        const res = await api("/api/admin/users/" + id + "/points", {
          method: "POST",
          body: JSON.stringify({
            delta,
            reason: $("pts-reason").value || "admin adjust",
          }),
        });
        refreshStats();
        const bal = res && res.balance != null ? Number(res.balance).toLocaleString() : "?";
        return {
          redraw: true,
          msg: (delta > 0 ? `Gave ${delta} points to ${who}` : `Took ${-delta} points from ${who}`) + ` (now ${bal}).`,
        };
      });
      const pts = (n) => Number(n || 0).toLocaleString() + " pts";
      $("user-chatlog").onclick = () => {
        setChatPerson({ id: u.id, name: who });
        $("chat-q").value = "";
        $("chat-platform").value = "";
        $("chat-flagged").checked = false;
        go("chat");
        loadChat();
      };
      $("user-csv").onclick = () => {
        downloadCsv(new URLSearchParams({ user_id: String(u.id) }), $("user-action-msg"));
      };
      $("user-flag").onclick = () => act($("user-flag"), async () => {
        const accounts = (u.identities || []).filter((i) => i.username || i.display_name);
        if (!accounts.length) throw new Error("No chat account to flag yet.");
        if (!confirm(`Red-flag ${who}? Core hides them from every overlay and Stream Rooms. Unflag them on the Red flags page.`)) return null;
        for (const i of accounts) {
          await api("/api/admin/red-flags/flag", {
            method: "POST",
            body: JSON.stringify({
              name: i.username || i.display_name,
              display_name: i.display_name || i.username,
              platform: i.platform,
              platform_user_id: i.platform_user_id || "",
            }),
          });
        }
        return { msg: `${who} red-flagged. The Red flags page lists them.` };
      });
      $("link-user").addEventListener("keydown", (e) => {
        if (e.key === "Enter") $("link-btn").click();
      });
      $("link-btn").onclick = () => act($("link-btn"), async () => {
        const name = $("link-user").value.trim().replace(/^@/, "");
        const plat = $("link-platform").value;
        if (!name) throw new Error(`Type their name on ${plat}.`);
        const res = await api("/api/admin/users/" + id + "/link", {
          method: "POST",
          body: JSON.stringify({ platform: plat, username: name }),
        });
        loadUsers();
        refreshStats();
        return {
          redraw: true,
          msg: res && res.merged
            ? `${name} on ${plat} is now part of ${who}; their points were added.`
            : res && res.waiting_for_chat
              ? `Linked. Core hasn't seen ${name} on ${plat} yet; their first chat line there joins ${who}.`
              : `Linked ${name} on ${plat} to ${who}.`,
        };
      });
      const findToMerge = () => act($("merge-find"), async () => {
        const q = $("merge-q").value.trim();
        const box = $("merge-results");
        box.innerHTML = "";
        if (!q) throw new Error("Type part of their name.");
        const found = (await api("/api/admin/users?q=" + encodeURIComponent(q))).filter((x) => x.id !== u.id);
        if (!found.length) return { msg: `Nobody else called "${q}".` };
        for (const other of found.slice(0, 10)) {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "merge-pick";
          const name = other.display_name || "someone";
          b.innerHTML = `<strong>${escapeHtml(name)}</strong> <span class="muted">${escapeHtml(other.accounts || "")} · ${pts(other.points)}</span>`;
          b.onclick = () => act(b, async () => {
            if (!confirm(`Merge ${name} (${pts(other.points)}${other.accounts ? "; " + other.accounts : ""}) into ${who} (${pts(u.points)})?\n\nTheir points, accounts and chat move to ${who}. This can't be undone.`)) return null;
            const res = await api("/api/admin/users/" + id + "/merge", {
              method: "POST",
              body: JSON.stringify({ absorb_user_id: other.id }),
            });
            loadUsers();
            refreshStats();
            const bal = res && res.balance != null ? Number(res.balance).toLocaleString() : "?";
            return { redraw: true, msg: `Merged ${name} into ${who} (now ${bal} points).` };
          });
          box.appendChild(b);
        }
        return { msg: found.length > 10 ? "Showing 10; type more of the name to narrow it down." : "" };
      });
      $("merge-find").onclick = findToMerge;
      $("merge-q").addEventListener("keydown", (e) => {
        if (e.key === "Enter") findToMerge();
      });
      $("notes-btn").onclick = () => act($("notes-btn"), async () => {
        await api("/api/admin/users/" + id + "/notes", {
          method: "POST",
          body: JSON.stringify({ notes: $("user-notes").value }),
        });
        return { msg: "Notes saved." };
      });
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }

  /** Open a person's page (from a name in Chat history). */
  function openPerson(userId) {
    if (!userId) return;
    go("users");
    selectUser(Number(userId));
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
      if ($("chat-log-only-flagged")) $("chat-log-only-flagged").hidden = !(s.chat_log_enabled && s.chat_log_only_flagged);
    } catch {
      banner.hidden = true;
    }
  }

  // Chat history for one person: set from their page (Chat log) or cleared with ×
  function setChatPerson(person) {
    $("chat-user-id").value = person ? String(person.id) : "";
    const chip = $("chat-person");
    if (!chip) return;
    chip.hidden = !person;
    chip.innerHTML = "";
    if (!person) return;
    const label = document.createElement("span");
    label.textContent = "Only " + (person.name || "this person");
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "link-btn";
    clear.setAttribute("aria-label", "Show everyone");
    clear.title = "Show everyone";
    clear.textContent = "×";
    clear.onclick = () => {
      setChatPerson(null);
      loadChat();
    };
    chip.append(label, clear);
  }

  function chatFilters() {
    const params = new URLSearchParams();
    const uid = $("chat-user-id").value.trim();
    if (uid) params.set("user_id", uid);
    const plat = $("chat-platform").value;
    if (plat) params.set("platform", plat);
    const q = $("chat-q").value.trim();
    if (q) params.set("q", q);
    if ($("chat-flagged") && $("chat-flagged").checked) params.set("flagged", "1");
    return params;
  }

  const CHAT_ROWS = 200;
  async function loadChat() {
    try {
      const params = chatFilters();
      const filtered = [...params.keys()].length > 0;
      params.set("limit", String(CHAT_ROWS));
      const rows = await api("/api/admin/chat?" + params.toString());
      const tb = $("chat-table").querySelector("tbody");
      tb.innerHTML = "";
      if ($("chat-count")) {
        $("chat-count").textContent = !rows.length
          ? (filtered ? "No saved lines match these filters." : "No chat saved yet.")
          : rows.length >= CHAT_ROWS
            ? `Showing the newest ${CHAT_ROWS} lines. Search or filter to find older ones, or Download CSV for all of them.`
            : `${rows.length} line${rows.length === 1 ? "" : "s"}.`;
      }
      for (const r of rows) {
        const tr = document.createElement("tr");
        if (r.flagged) {
          tr.className = "rf-row";
          tr.title = "Red-flagged: hidden from the overlays and Stream Rooms";
        }
        tr.innerHTML =
          `<td>${fmtTime(r.timestamp)}</td>` +
          `<td>${r.flagged ? '<span class="rf-mark" aria-label="red-flagged">🚩</span> ' : ""}` +
          (r.user_id
            ? `<button type="button" class="link-btn chat-who" title="Open their page (points, accounts, notes)">${escapeHtml(r.display_name || r.username)}</button>`
            : escapeHtml(r.display_name || r.username)) +
          `</td>` +
          `<td>${escapeHtml(r.platform)}</td>` +
          `<td>${escapeHtml(r.message)}</td>`;
        const who = tr.querySelector(".chat-who");
        if (who) who.onclick = () => openPerson(r.user_id);
        tb.appendChild(tr);
      }
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }

  $("chat-search").onclick = loadChat;
  if ($("chat-flagged")) $("chat-flagged").onchange = loadChat;

  // ── Red flags (phrases + flagged chatters): own endpoint, Save button + page save bar ──
  let rfLoaded = false;
  function fillRedFlags(d) {
    if (!$("rf-card") || !d) return;
    $("rf-enabled").checked = d.enabled !== false;
    $("rf-skip-mods").checked = d.skip_mods !== false;
    $("rf-phrases").value = (d.phrases || []).join("\n");
    const list = d.flagged || [];
    $("rf-count").textContent = list.length ? `(${list.length})` : "(nobody yet)";
    const tb = $("rf-table").querySelector("tbody");
    tb.innerHTML = "";
    for (const f of list) {
      const tr = document.createElement("tr");
      const why = f.source === "manual"
        ? '<span class="muted">flagged by hand</span>'
        : `said <strong>${escapeHtml(f.phrase)}</strong>${f.source === "past" ? " (found in past chat)" : ""}: <span class="muted">${escapeHtml(f.message)}</span>`;
      const name = f.display_name || f.username;
      tr.innerHTML =
        `<td>${escapeHtml(name)}</td>` +
        `<td>${escapeHtml(f.platform || "every")}</td>` +
        `<td class="rf-msg">${why}</td>` +
        `<td>${fmtTime(f.flagged_at)}</td>` +
        `<td class="rf-actions">` +
        `<button type="button" class="rf-show" title="Show what they wrote in the chat log below">Messages${f.messages ? " (" + f.messages + ")" : ""}</button> ` +
        `<button type="button" class="rf-unflag" title="Take them off the list: their new chat shows again">Unflag</button></td>`;
      tr.querySelector(".rf-show").onclick = () => {
        setChatPerson(null);
        $("chat-q").value = "";
        $("chat-platform").value = f.platform || "";
        $("chat-flagged").checked = true;
        go("chat");
        loadChat();
      };
      tr.querySelector(".rf-unflag").onclick = async () => {
        try {
          const d = await api(`/api/admin/red-flags/${f.id}`, { method: "DELETE" });
          fillRedFlags(d);
          $("rf-status").textContent = `${name} unflagged: their new chat shows again.`;
          // a misclick mid-stream must not let a troll back in for good
          undoToast(`${name} unflagged.`, async () => {
            try {
              fillRedFlags(await api("/api/admin/red-flags/restore", {
                method: "POST",
                body: JSON.stringify({ removed: d.removed || f }),
              }));
              $("rf-status").textContent = `${name} is red-flagged again.`;
            } catch (e) {
              $("rf-status").textContent = String(e.message || e);
            }
          });
        } catch (e) {
          $("rf-status").textContent = String(e.message || e);
        }
      };
      tb.appendChild(tr);
    }
    rfLoaded = true;
  }

  async function loadRedFlags() {
    if (!$("rf-card")) return;
    try {
      fillRedFlags(await api("/api/admin/red-flags"));
    } catch (e) {
      $("rf-status").textContent = String(e.message || e);
    }
  }

  async function saveRedFlags() {
    if (!rfLoaded || !$("rf-card")) return;
    try {
      fillRedFlags(await api("/api/admin/red-flags", {
        method: "PUT",
        body: JSON.stringify({
          enabled: $("rf-enabled").checked,
          skip_mods: $("rf-skip-mods").checked,
          phrases: $("rf-phrases").value,
        }),
      }));
      $("rf-status").textContent = "Saved. New chat is checked against these phrases.";
    } catch (e) {
      $("rf-status").textContent = String(e.message || e);
      throw e;
    }
  }

  // "Check past chat": the saved phrases over the saved chat log; nobody is flagged until confirmed
  let rfPast = [];
  function fillPastChat(d) {
    rfPast = d.people || [];
    const tb = $("rf-past-table").querySelector("tbody");
    tb.innerHTML = "";
    const lines = Number(d.scanned || 0).toLocaleString();
    $("rf-past-count").textContent = rfPast.length ? `(${rfPast.length}${d.more ? "+" : ""})` : "";
    const onlyFlagged = $("chat-log-only-flagged") && !$("chat-log-only-flagged").hidden;
    $("rf-past-hint").textContent = (rfPast.length
      ? `Read ${lines} saved chat lines. Untick anyone who should not be flagged (a mod quoting a phrase, say), then press Red-flag ticked chatters.`
      : `Read ${lines} saved chat lines: nobody new said one of these phrases.`) +
      (d.more ? " The list stops here; flag these, then check again for the rest." : "") +
      (onlyFlagged ? " Chat history is saved only for red-flagged chatters, so other people's old lines are not there to check." : "") +
      ($("rf-skip-mods").checked ? " Mods and the streamer are left out when Core knows them (your mod list, your channel, or seen with a mod badge since Core started)." : "");
    rfPast.forEach((p, i) => {
      const tr = document.createElement("tr");
      const more = (p.examples || []).slice(1)
        .map((x) => `<span class="muted">${escapeHtml(x.message)}</span>`).join("");
      tr.innerHTML =
        `<td><input type="checkbox" class="rf-past-pick" data-i="${i}" checked /></td>` +
        `<td>${escapeHtml(p.display_name || p.username)}</td>` +
        `<td>${escapeHtml(p.platform)}</td>` +
        `<td class="rf-msg"><strong>${escapeHtml(p.phrase)}</strong>: ${escapeHtml(p.message)}${more}</td>` +
        `<td>${p.count}</td>` +
        `<td>${fmtTime(p.timestamp)}</td>`;
      tb.appendChild(tr);
    });
    $("rf-past-all").checked = true;
    $("rf-past-apply").disabled = !rfPast.length;
    $("rf-past-table").hidden = !rfPast.length;
    $("rf-past-box").hidden = false;
  }

  if ($("rf-card")) {
    $("rf-save").onclick = () => saveRedFlags().catch(() => {});
    $("rf-past").onclick = async () => {
      $("rf-past").disabled = true;
      try {
        await saveRedFlags();
        $("rf-status").textContent = "Checking past chat…";
        fillPastChat(await api("/api/admin/red-flags/check-past", { method: "POST" }));
        $("rf-status").textContent = "";
        $("rf-past-box").scrollIntoView({ behavior: "smooth", block: "nearest" });
      } catch (e) {
        $("rf-status").textContent = String(e.message || e);
      } finally {
        $("rf-past").disabled = false;
      }
    };
    $("rf-past-all").onchange = () => {
      for (const box of document.querySelectorAll(".rf-past-pick")) box.checked = $("rf-past-all").checked;
    };
    $("rf-past-close").onclick = () => {
      $("rf-past-box").hidden = true;
      rfPast = [];
    };
    $("rf-past-apply").onclick = async () => {
      const people = [...document.querySelectorAll(".rf-past-pick")]
        .filter((box) => box.checked)
        .map((box) => rfPast[Number(box.dataset.i)]);
      if (!people.length) {
        $("rf-status").textContent = "Nobody ticked.";
        return;
      }
      try {
        const d = await api("/api/admin/red-flags/apply-past", { method: "POST", body: JSON.stringify({ people }) });
        fillRedFlags(d);
        $("rf-past-box").hidden = true;
        rfPast = [];
        $("rf-status").textContent = `${d.flagged_now} red-flagged from past chat.`;
        loadChat();
      } catch (e) {
        $("rf-status").textContent = String(e.message || e);
      }
    };
    $("rf-flag").onclick = async () => {
      const name = $("rf-name").value.trim();
      if (!name) return;
      try {
        fillRedFlags(await api("/api/admin/red-flags/flag", {
          method: "POST",
          body: JSON.stringify({ name, platform: $("rf-platform").value }),
        }));
        $("rf-name").value = "";
        $("rf-status").textContent = `${name} red-flagged.`;
        loadChat();
      } catch (e) {
        $("rf-status").textContent = String(e.message || e);
      }
    };
    $("rf-name").addEventListener("keydown", (e) => {
      if (e.key === "Enter") $("rf-flag").click();
    });
  }
  $("chat-export").onclick = () => downloadCsv(chatFilters(), $("chat-export-msg"));

  /** The chat log as CSV: the Chat history filters, or user_id alone from a person's page. */
  async function downloadCsv(params, msg) {
    const userId = params.get("user_id");
    const url = "/api/admin/chat/export?" + params.toString();
    const say = (text, ok = true) => {
      if (!msg) return;
      msg.textContent = text;
      msg.classList.toggle("bad", !ok);
    };
    say("Preparing the file…");
    try {
      await downloadFile(url, userId ? `chat_user_${userId}.csv` : "chat_all.csv");
      say("Downloaded.");
    } catch (e) {
      say("Download failed: " + readableActionError(e), false);
    }
  }

  /** GET a file from Core and save it; errors come back in plain words (like api()). */
  async function downloadFile(url, fallbackName) {
    const res = await fetch(url, { headers: { "X-Admin-Token": token() } });
    if (!res.ok) {
      if (res.status === 401) needToken();
      throw new Error(readableError(await res.text(), res.status, res.statusText));
    }
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    const m = cd.match(/filename="?([^";]+)"?/);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = m ? m[1] : fallbackName;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 1000);
  }

  // ------------------------------------------------------------------
  // Game plugins (plugins/<id>/plugin.json): Settings cards + Market sub-pages, drawn from
  // each manifest's "settings" and "market.fields". Card fields save with config.yaml;
  // market fields save on the Market page (PUT /api/admin/plugins/<id>/settings).
  // ------------------------------------------------------------------
  let pluginsInfo = [];

  async function loadPlugins() {
    try {
      const data = await api("/api/admin/plugins");
      pluginsInfo = data.plugins || [];
      if ($("plugin-folder") && data.folder) $("plugin-folder").textContent = data.folder;
    } catch (e) {
      pluginsInfo = [];
    }
    return pluginsInfo;
  }

  function pathGet(obj, key) {
    return String(key).split(".").reduce((cur, part) => (cur && typeof cur === "object" ? cur[part] : undefined), obj);
  }

  function pathSet(obj, key, value) {
    const parts = String(key).split(".");
    let cur = obj;
    parts.slice(0, -1).forEach((part) => {
      if (!cur[part] || typeof cur[part] !== "object") cur[part] = {};
      cur = cur[part];
    });
    cur[parts[parts.length - 1]] = value;
  }

  function slug(text) {
    return String(text).replace(/[^a-z0-9_]+/gi, "-");
  }

  /** One manifest field as a form control. prefix: "cfg" (Settings card) or "mkt" (Market page). */
  function pluginFieldHtml(prefix, pid, f, value) {
    const type = f.type || "text";
    const id = `${prefix}-plg-${slug(pid)}-${slug(f.key)}`;
    const attrs = `id="${id}" class="plg-field" data-key="${escapeHtml(f.key)}" data-type="${escapeHtml(type)}"` +
      (f.upper ? ' data-upper="1"' : "");
    const label = escapeHtml(f.label || f.key);
    const help = f.help ? ` <span class="field-help">${escapeHtml(f.help)}</span>` : "";
    const ph = f.placeholder != null ? ` placeholder="${escapeHtml(String(f.placeholder))}"` : "";
    if (type === "checkbox") {
      return `<label class="check"><input type="checkbox" ${attrs} ${value ? "checked" : ""} /> ${label}${help}</label>`;
    }
    if (type === "map") {
      const text = Object.entries(value || {}).map(([k, v]) => k + ":" + v).join("\n");
      return `<label>${label}${help}<textarea ${attrs} rows="6"${ph}>${escapeHtml(text)}</textarea></label>`;
    }
    if (type === "lines") {
      return `<label>${label}${help}<textarea ${attrs} rows="4"${ph}>${escapeHtml((value || []).join("\n"))}</textarea></label>`;
    }
    if (type === "select") {
      const opts = (f.options || []).map((o) =>
        `<option value="${escapeHtml(String(o))}" ${String(o) === String(value ?? "") ? "selected" : ""}>${escapeHtml(String(o))}</option>`).join("");
      return `<label>${label}${help}<select ${attrs}>${opts}</select></label>`;
    }
    let shown = value ?? "";
    if (type === "list") shown = Array.isArray(value) ? value.join(", ") : String(value ?? "");
    const inputType = type === "number" ? "number" : type === "password" ? "password" : "text";
    const extra = (type === "number" ? ["min", "max", "step"].filter((k) => f[k] != null).map((k) => ` ${k}="${escapeHtml(String(f[k]))}"`).join("") : "") +
      (type === "password" ? ' autocomplete="off"' : "");
    return `<label>${label}${help}<input type="${inputType}" ${attrs} value="${escapeHtml(String(shown))}"${ph}${extra} /></label>`;
  }

  /** A form control back to a config value (Settings cards; the server coerces Market fields itself). */
  function readPluginField(el, prev) {
    const type = el.dataset.type || "text";
    const upper = (t) => (el.dataset.upper ? t.toUpperCase() : t);
    if (type === "checkbox") return el.checked;
    if (type === "number") {
      if (String(el.value).trim() === "") return prev;
      const n = Number(el.value);
      return Number.isFinite(n) ? n : prev;
    }
    if (type === "list") return el.value.split(/[,\n]/).map((x) => upper(x.trim())).filter(Boolean);
    if (type === "lines") return el.value.split(/\n/).map((x) => upper(x.trim())).filter(Boolean);
    if (type === "map") {
      const out = {};
      el.value.split(/[\n,]/).forEach((line) => {
        line = line.trim();
        const sep = line.includes("=") ? "=" : ":";
        const at = line.lastIndexOf(sep);
        if (at <= 0) return;
        const v = Number(line.slice(at + 1).trim());
        if (Number.isFinite(v)) out[line.slice(0, at).trim()] = v;
      });
      return out;
    }
    return type === "password" ? el.value : upper(el.value.trim());
  }

  function pluginLinks(p) {
    const links = (p.links || []).filter((l) => l && l.url);
    if (!links.length) return "";
    return `<p class="hint">Needs: ${links.map((l) =>
      `<a href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.name || l.url)}</a>`).join(" · ")}</p>`;
  }

  function renderPluginCards(cfg) {
    const host = $("plugin-cards");
    if (!host) return;
    if (!pluginsInfo.length) {
      host.innerHTML = `<p class="integ-empty">No game plugins installed. Stream Core works without them.
        To add Minecraft, Factorio, Granvir or OpenTTD, get them from
        <a href="https://github.com/sensokasucks/flavr-game-plugins" target="_blank" rel="noopener">flavr-game-plugins</a>: copy the game's folder into
        <code>fridge-stream-core\\plugins\\</code> and restart Core.</p>`;
      return;
    }
    host.innerHTML = pluginsInfo.map((p) => {
      const section = (cfg || {})[p.id] || {};
      const state = p.error
        ? pill(false, "error")
        : p.running ? pill(true, "running") : pill(false, section.enabled ? "restart to start" : "off");
      const err = p.error ? `<p class="hint" style="color:var(--danger)">${escapeHtml(p.error)}</p>` : "";
      if (p.error && !(p.settings || []).length) {
        return `<fieldset class="cfg-card plugin-card" data-plugin="${escapeHtml(p.id)}"><legend>${escapeHtml(p.name)} ${state}</legend>${err}</fieldset>`;
      }
      const fields = [{ key: "enabled", label: "Enabled (opt-in)", type: "checkbox" }].concat(p.settings || []);
      return `<fieldset class="cfg-card plugin-card" data-plugin="${escapeHtml(p.id)}">
        <legend>${escapeHtml(p.name)} ${state}</legend>
        ${p.description ? `<p class="hint">${escapeHtml(p.description)}</p>` : ""}
        ${err}
        ${fields.map((f) => pluginFieldHtml("cfg", p.id, f, pathGet(section, f.key))).join("")}
        ${p.market ? `<p class="hint">Stock / vault rates live on the <strong>Market</strong> page.</p>` : ""}
        ${pluginLinks(p)}
      </fieldset>`;
    }).join("");
  }

  /** {plugin id: section} for the config.yaml save (sections merged over the loaded ones). */
  function collectPluginSections() {
    const out = {};
    document.querySelectorAll("#plugin-cards .plugin-card[data-plugin]").forEach((card) => {
      const pid = card.dataset.plugin;
      const fields = card.querySelectorAll(".plg-field");
      if (!fields.length) return;
      const section = JSON.parse(JSON.stringify(((lastLoadedConfig || {})[pid]) || {}));
      fields.forEach((el) => pathSet(section, el.dataset.key, readPluginField(el, pathGet(section, el.dataset.key))));
      out[pid] = section;
    });
    return out;
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
    loadAvatarSettings();

    renderPluginCards(cfg);

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
    if ($("cfg-chatlog-only-flagged")) {
      $("cfg-chatlog-only-flagged").checked = !!clog.only_flagged;
    }
    const crd = cfg.credits || {};
    if ($("cfg-credits-onoff")) $("cfg-credits-onoff").textContent = crd.enabled ? "on" : "off";
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

  // ── Chatter profile pictures (save in Core + hide list): own endpoint, saved with this page ──
  let avLoaded = false;
  function fillAvatarSettings(d) {
    if (!$("cfg-av-save-local") || !d) return;
    $("cfg-av-save-local").checked = d.save_local !== false;
    $("cfg-av-hide").value = (d.hide || []).join("\n");
    const n = Number(d.saved) || 0;
    $("av-info").textContent = n + (n === 1 ? " picture" : " pictures") + " saved." +
      (d.png ? "" : " Pictures are kept as the platform sends them; run install.bat once so Core can turn them into tidy PNGs.");
    avLoaded = true;
  }

  async function loadAvatarSettings() {
    if (!$("cfg-av-save-local")) return;
    try {
      fillAvatarSettings(await api("/api/admin/avatars"));
    } catch (e) {
      $("av-info").textContent = String(e.message || e);
    }
    // the chat overlay's own switch lives on its page; say here whether it is on
    if ($("av-chat-state")) {
      try {
        const st = await api("/api/admin/chat/style");
        $("av-chat-state").textContent = (st.options || {}).show_avatars ? "on" : "off";
      } catch {
        $("av-chat-state").textContent = "?";
      }
    }
  }

  async function saveAvatarSettings() {
    if (!avLoaded || !$("cfg-av-save-local")) return;
    fillAvatarSettings(await api("/api/admin/avatars", {
      method: "PUT",
      body: JSON.stringify({ save_local: $("cfg-av-save-local").checked, hide: $("cfg-av-hide").value }),
    }));
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
      channel_slug: cleanKick($("cfg-kick-slug").value),
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
        channel: cleanTwitch($("cfg-tw-channel").value),
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
        video_id: cleanYouTube($("cfg-yt-video").value) || $("cfg-yt-video").value.trim(),
        live_chat_id: $("cfg-yt-livechat").value.trim(),
      },
      ...collectPluginSections(),
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
        // empty = keep the token in use (Core never blanks or resets it from this form)
        admin_token: $("cfg-pts-token").value.trim(),
      },
      chat_log: {
        enabled: $("cfg-chatlog-enabled") ? $("cfg-chatlog-enabled").checked : false,
        only_flagged: $("cfg-chatlog-only-flagged") ? $("cfg-chatlog-only-flagged").checked : false,
      },
      credits: creditsConfigBlock(),
    };
    return next;
  }

  // Merge onto what was loaded so the look keys (Admin → Credits → Style) are kept.
  function creditsConfigBlock() {
    const block = { ...((lastLoadedConfig || {}).credits || {}) };
    // on/off is the Credits page's switch (Core keeps the live value on save)
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
      await loadPlugins();
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
    // the admin token is not a setting to reset: resetting it would lock every page out
    const keepToken = $("cfg-pts-token").value;
    fillConfigForm(lastDefaults, lastDefaults);
    $("cfg-pts-token").value = keepToken;
    syncTokenHint();
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
      const oldPort = Number(((lastLoadedConfig || {}).core || {}).port || 3850);
      const newPort = Number((config.core || {}).port || 3850);
      if (newPort !== oldPort && !confirm(
        `Change Core's port from ${oldPort} to ${newPort}?\n\nAfter the restart every OBS browser source, ` +
        `Stream Rooms and this dashboard must use http://127.0.0.1:${newPort}/ instead.`)) return;
      const newToken = String(((config.points || {}).admin_token) || "").trim();
      const res = await api("/api/admin/config", {
        method: "PUT",
        body: JSON.stringify({ config }),
      });
      await saveAvatarSettings();     // its own endpoint; the config.yaml save leaves it alone
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
      renderRestartBanner(res);
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
      ? "Not set: Stream Core uses the random token it made for you (in data/admin_token.txt). Type your own here to replace it; saving switches this page to it. Leaving it empty keeps the current one."
      : "Your own token. Saving applies it at once and switches this page to it. Clearing the box keeps it (the token can't be removed from here).";
  }
  if ($("cfg-pts-token")) $("cfg-pts-token").addEventListener("input", syncTokenHint);
  // hidden by default: streamers often share the dashboard on screen
  if ($("cfg-pts-token-show")) {
    $("cfg-pts-token-show").onclick = () => {
      const f = $("cfg-pts-token");
      const show = f.type === "password";
      f.type = show ? "text" : "password";
      $("cfg-pts-token-show").textContent = show ? "Hide" : "Show";
      $("cfg-pts-token-show").setAttribute("aria-pressed", show ? "true" : "false");
    };
  }

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
        setGrpStatus("Reloaded from disk · groups: " + (data.groups_active || []).join(", "), true);
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
      bits.push(`<span class="pill ok">Stream Rooms connected</span>${escapeHtml(names)}`);
      const room = st.room_state;
      if (room) {
        const t = (room.targets || []).map((x) => x.id).concat((room.guests || []).map((g) => g.name || g.id));
        bits.push(` · room <strong>${escapeHtml(room.room || "?")}</strong>` +
          (t.length ? ` · targets: ${escapeHtml(t.join(", "))}` : "") +
          (room.seated ? ` · ${room.seated.length} seated` : ""));
      }
    } else {
      bits.push(`<span class="pill off">Stream Rooms not connected</span>the reactions overlay plays what it can`);
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
        (eff.in_game === false ? " (Stream Rooms doesn't list this effect)" : "") +
        (eff.overlay ? " Reactions overlay: yes." : " Reactions overlay: no.")
      : "Unknown effect id: Stream Rooms decides what to do.";
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
        <label>Game template (Minecraft: console command)
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

  // Credits on/off as Core last said (null = not known yet)
  let creditsEnabled = null;
  function renderCreditsOnOff(enabled) {
    if (typeof enabled === "boolean") creditsEnabled = enabled;
    for (const id of ["crd-off", "live-crd-off"]) {
      if ($(id)) $(id).hidden = creditsEnabled !== false;
    }
    renderCreditsPlay();
  }
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest(".crd-turn-on");
    if (!btn) return;
    btn.disabled = true;
    try {
      const res = await api("/api/admin/credits/enabled", { method: "PUT", body: JSON.stringify({ enabled: true }) });
      if ($("crd-enabled")) $("crd-enabled").checked = !!res.enabled;
      renderCreditsOnOff(!!res.enabled);
    } catch (e) {
      setStatus("Credits: " + readableActionError(e), false);
    } finally {
      btn.disabled = false;
    }
  });

  function renderCreditsPlay(p) {
    creditsPlay = { ...creditsPlay, ...(p || {}) };
    if (p && typeof p.credits_enabled === "boolean" && p.credits_enabled !== creditsEnabled) {
      renderCreditsOnOff(p.credits_enabled);
      return;
    }
    const mode = { loop: "Looping", once: "Play once", hold: "Holding still", clear: "Play once, then clear" }[creditsPlay.mode] || creditsPlay.mode;
    // while off, say so instead of "Looping": the roll only has the names it already had
    const text = creditsEnabled === false
      ? "Off: no names are being collected."
      : (creditsPlay.playing === false ? "Paused · " : "") + mode +
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
      creditsWs = new WebSocket(`${proto}://${location.host}/ws?credits=1`);
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
      creditsEnabled = !!data.enabled;
      renderCreditsOnOff();
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
        renderCreditsOnOff(!!res.enabled);
      } catch (e) {
        $("crd-enable-status").textContent = String(e.message || e);
      }
    };
  }
  if ($("crd-copy")) {
    $("crd-copy").onclick = () => copyWithFeedback($("crd-copy"), location.origin + "/overlay/credits.html");
  }
  async function crdPlay(body) {
    // also pressed from Live controls mid-stream: never fail silently
    try {
      const res = await api("/api/admin/credits/play", { method: "POST", body: JSON.stringify(body) });
      renderCreditsPlay(res);
      return res;
    } catch (e) {
      const text = "Credits: " + readableActionError(e);
      for (const id of ["crd-play-state", "live-crd-state"]) {
        if ($(id)) $(id).textContent = text;
      }
      setStatus(text, false);
      return null;
    }
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
        await downloadFile("/api/admin/credits/roster.csv", "chatters.csv");
      } catch (e) {
        if ($("crd-play-state")) $("crd-play-state").textContent = "Download failed: " + readableActionError(e);
      }
    };
  }
  if ($("crd-pause")) $("crd-pause").onclick = () => crdPlay({ playing: creditsPlay.playing === false });
  if ($("crd-reset")) {
    $("crd-reset").onclick = async () => {
      if (!confirm("Clear unique chatters for this session?")) return;
      try {
        await api("/api/admin/credits/reset", { method: "POST", body: "{}" });
        initCreditsTab(true);
      } catch (e) {
        if ($("crd-play-state")) $("crd-play-state").textContent = "Clear failed: " + readableActionError(e);
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
    const mkt = data.market || {};
    if ($("mkt-enabled")) $("mkt-enabled").checked = !!mkt.enabled;
    if ($("mkt-hour-cap")) $("mkt-hour-cap").value = mkt.hourly_cap_points ?? 500;
    if ($("mkt-steam-sec")) $("mkt-steam-sec").value = mkt.steam_poll_sec ?? 1800;
    if ($("mkt-trade-impact")) $("mkt-trade-impact").checked = mkt.trade_impact !== false;
    if ($("mkt-trade-bps")) $("mkt-trade-bps").value = mkt.trade_impact_bps_per_100 ?? 40;
    const bookSel = $("mkt-new-book");
    if (bookSel && Array.isArray(data.books)) {
      const keep = bookSel.value;
      bookSel.innerHTML = data.books.map((b) => `<option value="${escapeHtml(b)}">${escapeHtml(b)}</option>`).join("");
      if (data.books.includes(keep)) bookSel.value = keep;
    }
    renderMarketPlugins(data.plugins || []);
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

  /** One Market sub-page per game plugin with "market" fields in its plugin.json. */
  function renderMarketPlugins(plugins) {
    const panel = $("tab-market");
    const stack = panel && panel.querySelector('.acc-stack[data-acc="market"]');
    const bar = panel && panel.querySelector('.subtabs[data-subtabs="market"]');
    if (!stack || !bar) return;
    let added = false;
    plugins.forEach((p) => {
      const sub = "plg-" + p.id;
      const m = p.market || {};
      let acc = stack.querySelector(`:scope > .acc[data-sub="${sub}"]`);
      if (!acc) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "subtab";
        btn.dataset.sub = sub;
        btn.textContent = p.name;
        bar.insertBefore(btn, bar.querySelector('.subtab[data-sub="investors"]'));
        acc = document.createElement("details");
        acc.className = "acc";
        acc.dataset.sub = sub;
        acc.open = true;
        stack.insertBefore(acc, stack.querySelector(':scope > .acc[data-sub="investors"]'));
        added = true;
      }
      const groups = [];
      (m.fields || []).forEach((f) => {
        const g = f.group || m.title || p.name;
        let row = groups.find((x) => x.name === g);
        if (!row) groups.push((row = { name: g, fields: [] }));
        row.fields.push(f);
      });
      const saveId = "plg-mkt-save-" + slug(p.id);
      const statusId = "plg-mkt-status-" + slug(p.id);
      if (PAGE_SAVER && PAGE_SAVER.isDirty && PAGE_SAVER.isDirty("mkt-" + sub) && $(saveId)) {
        // unsaved edits here: only refresh the live numbers, keep what was typed
        const pre = acc.querySelector(".integ-result");
        if (pre) pre.textContent = (p.market_status || []).join("\n") || pre.textContent;
        return;
      }
      acc.innerHTML =
        `<summary>${escapeHtml(m.title || p.name)}</summary>` +
        `<div class="acc-body market-mc-grid">` +
        (m.hint ? `<p class="hint">${escapeHtml(m.hint)}</p>` : "") +
        groups.map((g, i) =>
          `<fieldset class="cfg-card"><legend>${escapeHtml(g.name)}</legend>` +
          g.fields.map((f) => pluginFieldHtml("mkt", p.id, f, pathGet(p.values || {}, f.key))).join("") +
          (i === 0
            ? `<pre class="integ-result">${escapeHtml((p.market_status || []).join("\n") ||
                (p.running ? "(no live numbers yet)" : p.name + " is not running: live numbers show while it runs"))}</pre>` +
              `<div class="form-row" style="gap:8px;flex-wrap:wrap">` +
              `<button type="button" class="primary" id="${saveId}">Save ${escapeHtml(p.name)} market</button>` +
              `<span class="muted" id="${statusId}"></span></div>`
            : "") +
          `</fieldset>`).join("") +
        `</div>`;
      const sum = acc.querySelector(":scope > summary");
      if (sum) sum.addEventListener("click", (ev) => ev.preventDefault());
      $(saveId).onclick = async () => {
        const values = {};
        acc.querySelectorAll(".plg-field").forEach((el) => {
          values[el.dataset.key] = el.dataset.type === "checkbox" ? el.checked : el.value;
        });
        try {
          const res = await api("/api/admin/plugins/" + encodeURIComponent(p.id) + "/settings", {
            method: "PUT",
            body: JSON.stringify({ values }),
          });
          if (lastLoadedConfig) lastLoadedConfig[p.id] = res.values;   // a later config.yaml save keeps these
          await initMarketTab(true);
          if ($(statusId)) $(statusId).textContent = "Saved";
          if ($("mkt-status")) $("mkt-status").textContent = p.name + " market saved";
        } catch (e) {
          if ($(statusId)) $(statusId).textContent = String(e.message || e);
        }
      };
      if (PAGE_SAVER && PAGE_SAVER.add) {
        PAGE_SAVER.add({ key: "mkt-" + sub, page: "market", sub, name: p.name + " market",
          scope: `#tab-market .acc[data-sub="${sub}"]`, button: saveId });
      }
    });
    if (added && panel.classList.contains("active")) {
      const want = marketPluginSub || (location.hash.split("/")[1] || "").trim();
      marketPluginSub = "";
      if (want.startsWith("plg-") && stack.querySelector(`:scope > .acc[data-sub="${want}"]`)) {
        showSub("market", want);
        markNav("market", want);
        if (location.hash !== "#market/" + want) history.replaceState(null, "", "#market/" + want);
      } else showSub("market", panel.dataset.sub || "");
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
        await api("/api/admin/market/settings", {
          method: "PUT",
          body: JSON.stringify({
            enabled: $("mkt-enabled") ? $("mkt-enabled").checked : false,
            hourly_cap_points: Number($("mkt-hour-cap").value),
            steam_poll_sec: Number($("mkt-steam-sec") ? $("mkt-steam-sec").value : 1800),
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
            symbol: ($("mkt-hold-sym") && $("mkt-hold-sym").value.trim().toUpperCase()) || "FRG",
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
      if (key === "stream/new" &&
          !confirm("Start a new stream now?\n\nStreaks, !claim and moment times start counting again from now. Only do this if you went live again before chat had been quiet for the streak gap.")) return;
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

  // "Reload from disk" buttons throw away what you typed: ask first when something is unsaved.
  // (Capture phase, so a Cancel stops the button's own handler.)
  const RELOAD_BUTTONS = {
    "cfg-reload": () => !!($("cfg-savebar") && $("cfg-savebar").classList.contains("dirty")),
    "rx-reload": () => sectionDirty((s) => s.reload === "rx-reload"),
    "grp-reload": () => sectionDirty((s) => s.reload === "grp-reload"),
    "cmd-reload": () => sectionDirty((s) => s.reload === "cmd-reload") || !!(PAGE_SAVER && PAGE_SAVER.cmdFormEdited),
    "fun-reload": () => sectionDirty((s) => s.page === "fun"),
  };
  function sectionDirty(match) {
    return !!(PAGE_SAVER && PAGE_SAVER.sections.some((s) => s.dirty && match(s)));
  }
  document.addEventListener("click", (ev) => {
    const btn = ev.target && ev.target.closest && ev.target.closest("button");
    const check = btn && RELOAD_BUTTONS[btn.id];
    if (!check || !check()) return;
    if (confirm("You have unsaved changes here. Reload from disk and throw them away?")) return;
    ev.stopImmediatePropagation();
    ev.preventDefault();
  }, true);

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
      { key: "chat-css", page: "chatlook", sub: "look", name: "Chat overlay CSS",
        fields: ["chat-css"], button: "chat-css-save" },
      { key: "chat-opts", page: "chatlook", sub: "look", name: "Chat overlay behaviour",
        fields: ["chat-opt-hide", "chat-opt-max", "chat-opt-top", "chat-opt-avatars", "chat-opt-volume", "chat-opt-gap"],
        button: "chat-opt-save" },
      { key: "rf", page: "redflags", sub: "", name: "Red flags",
        fields: ["rf-enabled", "rf-skip-mods", "rf-phrases"], button: "rf-save", save: saveRedFlags },
      { key: "mkt-set", page: "market", sub: "listings", name: "Market settings", group: "mkt-set",
        scope: "#mkt-switches", button: "mkt-save" },
      { key: "mkt-inv", page: "market", sub: "investors", name: "Hourly cap + Steam refresh", group: "mkt-set",
        fields: ["mkt-hour-cap", "mkt-steam-sec"], button: "mkt-save", also: ["mkt-inv-save"] },
      // game plugins' market sub-pages add themselves with PAGE_SAVER.add (renderMarketPlugins)
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
    function wire(s) {
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
    }
    sections.forEach(wire);

    // Sections drawn later (game plugins' Market sub-pages): added, or re-wired after a redraw.
    PAGE_SAVER.add = (sec) => {
      if (!$("tab-" + sec.page)) return;
      const i = sections.findIndex((s) => s.key === sec.key);
      if (i >= 0) sections.splice(i, 1);
      sections.push(sec);
      wire(sec);
      render();
    };
    PAGE_SAVER.isDirty = (key) => sections.some((s) => s.key === key && s.dirty);

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
