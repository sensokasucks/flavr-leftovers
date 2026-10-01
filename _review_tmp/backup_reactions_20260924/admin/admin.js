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

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      ...opts,
      headers: { ...headers(), ...(opts.headers || {}) },
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(t || res.statusText);
    }
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

  // Accordion nav + collapsible subtabs (state in localStorage)
  const navStateKey = "stream_core_admin_nav";
  const accStateKey = "stream_core_admin_acc";

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

  function markNavActive(tabId) {
    document.querySelectorAll(".nav-group").forEach((g) => {
      const hit = !!g.querySelector('.tab[data-tab="' + tabId + '"]');
      g.classList.toggle("has-active", hit);
      if (hit) g.open = true;
    });
  }

  function persistNavGroups() {
    const open = {};
    document.querySelectorAll(".nav-group").forEach((g) => {
      if (g.dataset.group) open[g.dataset.group] = !!g.open;
    });
    const prev = loadJson(navStateKey, {});
    saveJson(navStateKey, { ...prev, groups: open });
  }

  function restoreNavGroups() {
    const saved = loadJson(navStateKey, {});
    const groups = saved.groups || {};
    document.querySelectorAll(".nav-group").forEach((g) => {
      if (g.dataset.group && Object.prototype.hasOwnProperty.call(groups, g.dataset.group)) {
        g.open = !!groups[g.dataset.group];
      }
    });
  }

  function accKey(stack, sub) {
    return (stack.dataset.acc || "acc") + ":" + sub;
  }

  function persistAcc(stack) {
    const map = loadJson(accStateKey, {});
    stack.querySelectorAll(":scope > .acc[data-sub]").forEach((el) => {
      map[accKey(stack, el.dataset.sub)] = !!el.open;
    });
    saveJson(accStateKey, map);
  }

  function restoreAcc(stack) {
    const map = loadJson(accStateKey, {});
    stack.querySelectorAll(":scope > .acc[data-sub]").forEach((el) => {
      const k = accKey(stack, el.dataset.sub);
      if (Object.prototype.hasOwnProperty.call(map, k)) el.open = !!map[k];
    });
    syncSubtabs(stack);
  }

  function syncSubtabs(stack) {
    const name = stack.dataset.acc;
    if (!name) return;
    const bar = document.querySelector('.subtabs[data-subtabs="' + name + '"]');
    if (!bar) return;
    const openFirst = stack.querySelector(":scope > .acc[data-sub][open]");
    bar.querySelectorAll(".subtab[data-sub]").forEach((btn) => {
      btn.classList.toggle("active", openFirst && btn.dataset.sub === openFirst.dataset.sub);
    });
  }

  function openSub(stack, sub, exclusive) {
    const items = [...stack.querySelectorAll(":scope > .acc[data-sub]")];
    items.forEach((el) => {
      if (el.dataset.sub === sub) el.open = true;
      else if (exclusive) el.open = false;
    });
    persistAcc(stack);
    syncSubtabs(stack);
    const target = stack.querySelector(':scope > .acc[data-sub="' + sub + '"]');
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function bindAccordions() {
    restoreNavGroups();
    document.querySelectorAll(".nav-group").forEach((g) => {
      g.addEventListener("toggle", persistNavGroups);
    });
    const collapseNav = $("nav-collapse-all");
    if (collapseNav) {
      collapseNav.onclick = () => {
        document.querySelectorAll(".nav-group").forEach((g) => { g.open = false; });
        persistNavGroups();
      };
    }

    document.querySelectorAll(".acc-stack").forEach((stack) => restoreAcc(stack));

    document.querySelectorAll(".subtabs").forEach((bar) => {
      const name = bar.dataset.subtabs;
      const stack = document.querySelector('.acc-stack[data-acc="' + name + '"]');
      if (!stack) return;
      bar.addEventListener("click", (ev) => {
        const btn = ev.target.closest("button");
        if (!btn) return;
        if (btn.classList.contains("subtab") && btn.dataset.sub) {
          openSub(stack, btn.dataset.sub, true);
        } else if (btn.dataset.action === "expand") {
          stack.querySelectorAll(":scope > .acc[data-sub]").forEach((el) => { el.open = true; });
          persistAcc(stack);
          syncSubtabs(stack);
        } else if (btn.dataset.action === "collapse") {
          stack.querySelectorAll(":scope > .acc[data-sub]").forEach((el) => { el.open = false; });
          persistAcc(stack);
          syncSubtabs(stack);
        }
      });
    });

    document.querySelectorAll(".acc-stack").forEach((stack) => {
      stack.addEventListener("toggle", (ev) => {
        if (ev.target.classList.contains("acc")) {
          persistAcc(stack);
          syncSubtabs(stack);
        }
      });
    });
  }

  function activateTab(tabId) {
    const panel = $("tab-" + tabId);
    if (!panel) return;
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    const btn = document.querySelector('.tab[data-tab="' + tabId + '"]');
    if (btn) btn.classList.add("active");
    panel.classList.add("active");
    markNavActive(tabId);
    const nav = loadJson(navStateKey, {});
    nav.lastTab = tabId;
    saveJson(navStateKey, nav);
    if (tabId === "config") {
      loadConfigForm();
      loadGroups();
      loadCommands();
    }
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

  bindAccordions();

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.onclick = () => activateTab(btn.dataset.tab);
  });

  const savedTab = (loadJson(navStateKey, {}).lastTab || "status");
  if (savedTab && savedTab !== "status") activateTab(savedTab);
  else markNavActive("status");

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
        if (want && !run) note = " (enabled in config but not running — restart?)";
        if (!want && !run) note = " (disabled)";
        html += `<li><strong>${name}</strong> ${run ? pill(true, "running") : pill(false, "stopped")}
          ${want ? pill(true, "config on") : pill(false, "config off")}
          ${p.detail ? `<span class="muted">${p.detail}</span>` : ""}
          <span class="muted">${note}</span></li>`;
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
    $("cfg-pts-token").value = pts.admin_token ?? "";

    const clog = cfg.chat_log || {};
    if ($("cfg-chatlog-enabled")) {
      $("cfg-chatlog-enabled").checked = !!clog.enabled;
    }
    if ($("cfg-credits-enabled")) {
      $("cfg-credits-enabled").checked = !!(cfg.credits || {}).enabled;
    }

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
        admin_token: $("cfg-pts-token").value.trim() || "change-me",
      },
      chat_log: {
        enabled: $("cfg-chatlog-enabled") ? $("cfg-chatlog-enabled").checked : false,
      },
      credits: {
        ...((lastLoadedConfig || {}).credits || {}),
        enabled: $("cfg-credits-enabled") ? $("cfg-credits-enabled").checked : false,
      },
    };
    return next;
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
    if (!confirm("Fill the form with built-in defaults? (not saved yet)")) return;
    fillConfigForm(lastDefaults, lastDefaults);
    setCfgStatus("Form reset to defaults — click Save to write disk");
  };

  $("cfg-save").onclick = async () => {
    try {
      const config = collectConfigFromForm();
      const res = await api("/api/admin/config", {
        method: "PUT",
        body: JSON.stringify({ config }),
      });
      setCfgStatus(res.message || "Saved — restart Core", true);
      setStatus("Config saved — restart Stream Core", true);
    } catch (e) {
      setCfgStatus(String(e.message || e), false);
    }
  };

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
          groupsState = groupsState.filter((x) => x.id !== g.id);
          renderGroupsTable();
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
      if (!confirm("Delete command !" + name + "?")) return;
      delete commandsState[name];
      selectedCmd = null;
      $("cmd-detail").innerHTML = `<p class="muted">Select a command or click Add</p>`;
      renderCmdTable();
      setCmdStatus("Removed from list — save to write disk");
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
          .map(
            (c) =>
              `<div>${escapeHtml(c.display_name)} <span class="muted">${escapeHtml(c.platform)}</span></div>`
          )
          .join("")
      : "<div>No chatters yet — enable credits and chat, or add a test name.</div>";
  }

  async function initCreditsTab(force) {
    if (!$("tab-credits")) return;
    if ($("tab-credits").dataset.ready && !force) return;
    try {
      const data = await api("/api/admin/credits");
      $("tab-credits").dataset.ready = "1";
      if ($("crd-enabled")) $("crd-enabled").checked = !!data.enabled;
      fillCreditsTheme(data.theme);
      creditsPlay = data.play || creditsPlay;
      renderCreditsRoster(data.roster);
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
  function crdPlay(body) {
    return api("/api/admin/credits/play", { method: "POST", body: JSON.stringify(body) });
  }
  if ($("crd-roll")) $("crd-roll").onclick = () => crdPlay({ playing: true, mode: "loop", freeze: true, restart: true });
  if ($("crd-live")) $("crd-live").onclick = () => crdPlay({ freeze: false, playing: true });
  if ($("crd-loop")) $("crd-loop").onclick = () => crdPlay({ mode: "loop", playing: true, restart: true });
  if ($("crd-once")) $("crd-once").onclick = () => crdPlay({ mode: "once", playing: true, freeze: true, restart: true });
  if ($("crd-hold")) $("crd-hold").onclick = () => crdPlay({ mode: "hold", playing: true });
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

  refreshStats();
  loadUsers();
  if (token()) {
    loadStatus();
  }
})();
