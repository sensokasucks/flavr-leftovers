/* Shared credits look editor. Host passes theme/play URLs. */
(function (global) {
  "use strict";

  const MOTIONS = [
    { id: "crawl", label: "Crawl up", blurb: "Classic rolling titles", icon: "crawl-up" },
    { id: "crawl-down", label: "Crawl down", blurb: "Start at the top", icon: "crawl-down" },
    { id: "starwars", label: "Star Wars", blurb: "Perspective crawl", icon: "sw" },
    { id: "cards", label: "Cards", blurb: "One block at a time", icon: "cards" },
    { id: "fade", label: "Fade pages", blurb: "Crossfade sections", icon: "fade" },
    { id: "slides", label: "Slides", blurb: "Side-step each block", icon: "slides" },
    { id: "ticker", label: "Ticker", blurb: "Horizontal name tape", icon: "ticker" },
    { id: "typewriter", label: "Typewriter", blurb: "Types each character", icon: "type" },
    { id: "matrix", label: "Matrix", blurb: "Rain + name decode", icon: "matrix" },
  ];

  const PRESETS = [
    {
      id: "classic",
      label: "Classic",
      theme: {
        motion: "crawl",
        name_enter: "none",
        title: "Thanks for watching",
        footer: "See you next stream",
        font_family: '"Palatino Linotype", Palatino, "Times New Roman", Georgia, serif',
        custom_font_url: "",
        title_size_px: 54,
        name_size_px: 22,
        title_color: "#f3e2b0",
        name_color: "#f4f0e6",
        muted_color: "#9a8f78",
        mod_color: "#e8c36a",
        background: "transparent",
        text_shadow: "0 2px 8px rgba(0,0,0,0.85)",
        letter_spacing_em: 0.04,
        columns: 2,
        speed_px_per_sec: 42,
        letterbox: false,
        grain: false,
        vignette: false,
      },
    },
    {
      id: "starwars",
      label: "Star Wars",
      theme: {
        motion: "starwars",
        name_enter: "none",
        title: "Episode IV",
        subtitle: "A New Stream",
        footer: "See you next stream",
        font_family: '"News Cycle", "Franklin Gothic Medium", "Arial Narrow", sans-serif',
        custom_font_url: "https://fonts.googleapis.com/css2?family=News+Cycle:wght@400;700&display=swap",
        title_size_px: 48,
        name_size_px: 22,
        title_color: "#ffe81f",
        name_color: "#ffe81f",
        muted_color: "#c4b31a",
        mod_color: "#fff3a0",
        background: "#000000",
        text_shadow: "none",
        letter_spacing_em: 0.08,
        columns: 1,
        speed_px_per_sec: 28,
        sw_tilt_deg: 32,
        sw_perspective_px: 320,
        letterbox: true,
        grain: false,
        vignette: true,
      },
    },
    {
      id: "gold",
      label: "Gold titles",
      theme: {
        motion: "crawl",
        name_enter: "rise",
        title: "The Company",
        footer: "That's a wrap",
        font_family: "Georgia, serif",
        custom_font_url: "",
        title_color: "#e8c36a",
        name_color: "#f7ecd0",
        muted_color: "#a8946a",
        mod_color: "#ffd978",
        background: "#000000",
        columns: 2,
        speed_px_per_sec: 36,
        letterbox: true,
        grain: true,
        vignette: true,
      },
    },
    {
      id: "neon",
      label: "Neon night",
      theme: {
        motion: "crawl",
        name_enter: "blur",
        title: "NIGHT SHIFT",
        footer: "Stay loud",
        font_family: "Segoe UI, system-ui, sans-serif",
        custom_font_url: "",
        title_color: "#67f0ff",
        name_color: "#e8fbff",
        muted_color: "#6aa0b8",
        mod_color: "#ff4fd8",
        background: "#05060a",
        text_shadow: "0 0 12px rgba(103,240,255,0.45)",
        letter_spacing_em: 0.12,
        columns: 2,
        speed_px_per_sec: 48,
        letterbox: false,
        grain: false,
        vignette: true,
      },
    },
    {
      id: "teletype",
      label: "Teletype",
      theme: {
        motion: "typewriter",
        name_enter: "none",
        typewriter_unit: "line",
        typewriter_cps: 28,
        title: "TRANSMISSION",
        footer: "END OF LINE",
        section_label: "Operators",
        font_family: '"Share Tech Mono", "Courier New", monospace',
        custom_font_url: "https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap",
        title_size_px: 36,
        name_size_px: 20,
        title_color: "#d4c4a0",
        name_color: "#e8dcc4",
        muted_color: "#8a7d64",
        mod_color: "#f0e0a8",
        background: "#12100c",
        text_shadow: "none",
        letter_spacing_em: 0.08,
        columns: 1,
        page_hold_sec: 2.4,
        letterbox: false,
        grain: false,
        vignette: false,
      },
    },
    {
      id: "endcard",
      label: "End card",
      theme: {
        motion: "cards",
        name_enter: "none",
        title: "Thanks for watching",
        footer: "See you next stream",
        font_family: '"Cinzel", Palatino, Georgia, serif',
        custom_font_url: "https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600&display=swap",
        title_size_px: 42,
        name_size_px: 20,
        title_color: "#e6dcc8",
        name_color: "#f4f0e6",
        muted_color: "#9a8f78",
        mod_color: "#e8c36a",
        background: "#000000",
        text_shadow: "0 2px 18px rgba(0,0,0,0.8)",
        letter_spacing_em: 0.22,
        columns: 2,
        page_hold_sec: 4.5,
        page_fade_sec: 0.7,
        letterbox: false,
        grain: false,
        vignette: true,
      },
    },
    {
      id: "nametape",
      label: "Name tape",
      theme: {
        motion: "ticker",
        name_enter: "none",
        title: "TONIGHT'S CHAT",
        footer: "",
        font_family: "Segoe UI, system-ui, sans-serif",
        custom_font_url: "",
        title_color: "#f3e2b0",
        name_color: "#f4f0e6",
        muted_color: "#9a8f78",
        background: "transparent",
        columns: 1,
        speed_px_per_sec: 64,
        letterbox: false,
        grain: false,
        vignette: false,
      },
    },
    {
      id: "matrix",
      label: "Matrix",
      theme: {
        motion: "matrix",
        name_enter: "none",
        title: "WAKE UP",
        footer: "FOLLOW THE WHITE RABBIT",
        section_label: "The One",
        font_family: '"Share Tech Mono", "Courier New", monospace',
        custom_font_url: "https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap",
        title_size_px: 40,
        name_size_px: 20,
        title_color: "#00ff41",
        name_color: "#b8ffb8",
        muted_color: "#1f8a38",
        mod_color: "#9aff9a",
        background: "#000000",
        text_shadow: "0 0 12px #00ff41",
        letter_spacing_em: 0.14,
        columns: 2,
        page_hold_sec: 5.5,
        matrix_density: 1,
        letterbox: false,
        grain: false,
        vignette: false,
      },
    },
    {
      id: "minimal",
      label: "Minimal",
      theme: {
        motion: "fade",
        name_enter: "none",
        title: "Thanks for watching",
        footer: "",
        font_family: "Georgia, serif",
        custom_font_url: "",
        title_size_px: 36,
        name_size_px: 18,
        title_color: "#d9d4c8",
        name_color: "#ece8de",
        muted_color: "#8a8580",
        background: "#000000",
        text_shadow: "none",
        letter_spacing_em: 0.18,
        columns: 1,
        page_hold_sec: 3.6,
        letterbox: false,
        grain: false,
        vignette: false,
      },
    },
  ];

  const FIELDS = [
    ["title", "text"],
    ["subtitle", "text"],
    ["footer", "text"],
    ["section_label", "text"],
    ["motion", "text"],
    ["name_enter", "text"],
    ["typewriter_unit", "text"],
    ["sort", "text"],
    ["font_family", "text"],
    ["custom_font_url", "text"],
    ["title_color", "text"],
    ["name_color", "text"],
    ["muted_color", "text"],
    ["mod_color", "text"],
    ["background", "text"],
    ["text_shadow", "text"],
    ["columns", "num"],
    ["speed_px_per_sec", "num"],
    ["duration_sec", "num"],
    ["gap_after_loop_sec", "num"],
    ["title_size_px", "num"],
    ["name_size_px", "num"],
    ["letter_spacing_em", "num"],
    ["column_gap_px", "num"],
    ["row_gap_px", "num"],
    ["max_width_px", "num"],
    ["page_hold_sec", "num"],
    ["page_fade_sec", "num"],
    ["typewriter_cps", "num"],
    ["sw_tilt_deg", "num"],
    ["sw_perspective_px", "num"],
    ["matrix_density", "num"],
    ["group_by_platform", "bool"],
    ["show_platform", "bool"],
    ["show_message_count", "bool"],
    ["highlight_mods", "bool"],
    ["highlight_vips", "bool"],
    ["letterbox", "bool"],
    ["grain", "bool"],
    ["vignette", "bool"],
    ["announce_roll", "bool"],
    ["clear_when_done", "bool"],
  ];

  function h(html) {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }

  function motionOptions() {
    return MOTIONS.map(function (m) {
      return '<option value="' + m.id + '">' + m.label + "</option>";
    }).join("");
  }

  function motionCards() {
    return MOTIONS.map(function (m) {
      return (
        '<button type="button" class="crd-ed-motion" data-motion="' + m.id + '">' +
          '<span class="crd-ed-motion-ico" data-ico="' + m.icon + '" aria-hidden="true"></span>' +
          '<span class="crd-ed-motion-copy">' +
            '<strong>' + m.label + "</strong>" +
            '<em>' + m.blurb + "</em>" +
          "</span>" +
        "</button>"
      );
    }).join("");
  }

  function template(core) {
    return [
      '<div class="crd-ed">',
      '  <p class="hint crd-ed-lead">Pick a preset to jump, then refine. Motion changes restart the roll.</p>',
      '  <div class="crd-ed-presets" data-role="presets"></div>',
      '  <div class="crd-ed-tabs">',
      '    <button type="button" class="crd-ed-tab on" data-pane="motion">Motion</button>',
      '    <button type="button" class="crd-ed-tab" data-pane="titles">Copy</button>',
      '    <button type="button" class="crd-ed-tab" data-pane="type">Type</button>',
      '    <button type="button" class="crd-ed-tab" data-pane="color">Color</button>',
      '    <button type="button" class="crd-ed-tab" data-pane="layout">Layout</button>',
      '    <button type="button" class="crd-ed-tab" data-pane="list">List</button>',
      "  </div>",
      '  <div class="crd-ed-pane on" data-pane="motion">',
      '    <select class="crd-ed-motion-select" data-k="motion" aria-label="Motion type">' + motionOptions() + "</select>",
      '    <div class="crd-ed-motions" data-role="motions">' + motionCards() + "</div>",
      '    <p class="hint">Typewriter types character by character. Matrix rains glyphs while names decode. Both need Loop / Play — Hold still only shows a frozen first frame.</p>',
      '    <div class="row2">',
      '      <label>Speed (px/s) <input data-k="speed_px_per_sec" type="number" min="8" max="240" /></label>',
      '      <label>Target time (sec) <input data-k="duration_sec" type="number" min="0" max="600" /></label>',
      "    </div>",
      '    <div class="row2">',
      '      <label>Gap after loop (sec) <input data-k="gap_after_loop_sec" type="number" min="0" max="30" step="0.1" /></label>',
      '      <label>Name enter (crawl) <select data-k="name_enter">',
      '        <option value="none">None</option>',
      '        <option value="rise">Rise</option>',
      '        <option value="fade">Fade</option>',
      '        <option value="blur">Blur</option>',
      "      </select></label>",
      "    </div>",
      '    <div class="row2">',
      '      <label>Page hold (sec) <input data-k="page_hold_sec" type="number" min="0.8" max="20" step="0.1" /></label>',
      '      <label>Page fade (sec) <input data-k="page_fade_sec" type="number" min="0.1" max="3" step="0.05" /></label>',
      "    </div>",
      '    <div class="row2">',
      '      <label>Typewriter speed (chars/s) <input data-k="typewriter_cps" type="number" min="8" max="80" /></label>',
      '      <label>Typewriter unit <select data-k="typewriter_unit">',
      '        <option value="line">Line by line</option>',
      '        <option value="card">Card by card</option>',
      '        <option value="page">Page by page</option>',
      "      </select></label>",
      "    </div>",
      '    <div class="row2">',
      '      <label>Star Wars tilt (deg) <input data-k="sw_tilt_deg" type="number" min="20" max="70" /></label>',
      '      <label>Star Wars perspective (px) <input data-k="sw_perspective_px" type="number" min="180" max="900" /></label>',
      "    </div>",
      '    <label>Matrix density <input data-k="matrix_density" type="number" min="0.4" max="2.2" step="0.1" /></label>',
      "  </div>",
      '  <div class="crd-ed-pane" data-pane="titles">',
      '    <p class="hint">Words that appear on the overlay — opening title, chatter heading, and closing line.</p>',
      '    <label>Title <input data-k="title" type="text" /></label>',
      '    <label>Subtitle <input data-k="subtitle" type="text" /></label>',
      '    <label>Footer <input data-k="footer" type="text" /></label>',
      '    <label>Section heading <input data-k="section_label" type="text" /></label>',
      "  </div>",
      '  <div class="crd-ed-pane" data-pane="type">',
      '    <label>Font family <input data-k="font_family" type="text" /></label>',
      '    <label>Custom font URL <input data-k="custom_font_url" type="text" placeholder="https://fonts.googleapis.com/css2?family=…" /></label>',
      '    <div class="row2">',
      '      <label>Title size <input data-k="title_size_px" type="number" min="18" max="96" /></label>',
      '      <label>Name size <input data-k="name_size_px" type="number" min="12" max="48" /></label>',
      "    </div>",
      '    <label>Letter spacing (em) <input data-k="letter_spacing_em" type="number" min="0" max="0.5" step="0.01" /></label>',
      "  </div>",
      '  <div class="crd-ed-pane" data-pane="color">',
      '    <div class="row2">',
      '      <label>Title color <input data-k="title_color" type="text" /></label>',
      '      <label>Name color <input data-k="name_color" type="text" /></label>',
      "    </div>",
      '    <div class="row2">',
      '      <label>Muted color <input data-k="muted_color" type="text" /></label>',
      '      <label>Mod / VIP color <input data-k="mod_color" type="text" /></label>',
      "    </div>",
      '    <label>Background <input data-k="background" type="text" placeholder="transparent or #000" /></label>',
      '    <label>Text shadow <input data-k="text_shadow" type="text" /></label>',
      "  </div>",
      '  <div class="crd-ed-pane" data-pane="layout">',
      '    <div class="row2">',
      '      <label>Columns <select data-k="columns"><option>1</option><option>2</option><option>3</option><option>4</option></select></label>',
      '      <label>Max width (px) <input data-k="max_width_px" type="number" min="320" max="1600" /></label>',
      "    </div>",
      '    <div class="row2">',
      '      <label>Column gap <input data-k="column_gap_px" type="number" min="8" max="120" /></label>',
      '      <label>Row gap <input data-k="row_gap_px" type="number" min="0" max="40" /></label>',
      "    </div>",
      '    <label class="check"><input data-k="letterbox" type="checkbox" /> Letterbox bars</label>',
      '    <label class="check"><input data-k="grain" type="checkbox" /> Film grain</label>',
      '    <label class="check"><input data-k="vignette" type="checkbox" /> Vignette</label>',
      "  </div>",
      '  <div class="crd-ed-pane" data-pane="list">',
      '    <label>Sort <select data-k="sort">',
      '      <option value="first_seen">First seen</option>',
      '      <option value="name">Name</option>',
      '      <option value="messages">Most messages</option>',
      '      <option value="last_seen">Last seen</option>',
      "    </select></label>",
      '    <label class="check"><input data-k="group_by_platform" type="checkbox" /> Group by platform</label>',
      '    <label class="check"><input data-k="show_platform" type="checkbox" /> Platform dots</label>',
      '    <label class="check"><input data-k="show_message_count" type="checkbox" /> Message counts</label>',
      '    <label class="check"><input data-k="highlight_mods" type="checkbox" /> Highlight mods</label>',
      '    <label class="check"><input data-k="highlight_vips" type="checkbox" /> Highlight VIPs</label>',
      core ? '    <label class="check"><input data-k="announce_roll" type="checkbox" /> Chat-announce when rolling</label>' : "",
      core ? '    <label class="check"><input data-k="clear_when_done" type="checkbox" /> Leave the screen empty when the roll finishes</label>' : "",
      "  </div>",
      '  <div class="crd-ed-actions">',
      '    <button type="button" class="primary" data-act="save">Save look</button>',
      '    <button type="button" data-act="restart">Restart roll</button>',
      '    <span class="crd-ed-status" data-role="status"></span>',
      "  </div>",
      "</div>",
    ].join("\n");
  }

  function mount(opts) {
    const root = opts.el;
    if (!root) return;
    root.innerHTML = template(!!opts.core);
    const ed = root.querySelector(".crd-ed");
    const status = ed.querySelector("[data-role=status]");
    const presetWrap = ed.querySelector("[data-role=presets]");
    let theme = {};
    let liveTimer = 0;
    let activePreset = "";

    PRESETS.forEach(function (p) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "crd-ed-chip";
      b.textContent = p.label;
      b.dataset.preset = p.id;
      b.addEventListener("click", function () { applyPreset(p); });
      presetWrap.appendChild(b);
    });

    ed.querySelectorAll(".crd-ed-tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        const pane = tab.getAttribute("data-pane");
        ed.querySelectorAll(".crd-ed-tab").forEach(function (t) { t.classList.toggle("on", t === tab); });
        ed.querySelectorAll(".crd-ed-pane").forEach(function (p) {
          p.classList.toggle("on", p.getAttribute("data-pane") === pane);
        });
      });
    });

    function headers() {
      const hds = { "Content-Type": "application/json" };
      const extra = typeof opts.headers === "function" ? opts.headers() : (opts.headers || {});
      Object.keys(extra).forEach(function (k) { hds[k] = extra[k]; });
      return hds;
    }

    function withAuth(url) {
      const hds = headers();
      const t = hds["X-Admin-Token"] || hds["x-admin-token"] || "";
      if (!t) return url;
      const join = url.indexOf("?") >= 0 ? "&" : "?";
      return url + join + "admin_token=" + encodeURIComponent(t);
    }

    function field(k) {
      return ed.querySelector("[data-k=\"" + k + "\"]");
    }

    function fill(t) {
      theme = t || {};
      FIELDS.forEach(function (pair) {
        const k = pair[0];
        const kind = pair[1];
        const el = field(k);
        if (!el) return;
        if (kind === "bool") el.checked = !!theme[k];
        else if (theme[k] != null) el.value = theme[k];
      });
      if (field("show_platform") && theme.show_platform == null) field("show_platform").checked = true;
      if (field("highlight_mods") && theme.highlight_mods == null) field("highlight_mods").checked = true;
      markPreset();
      markMotion();
    }

    function collect() {
      const body = {};
      FIELDS.forEach(function (pair) {
        const k = pair[0];
        const kind = pair[1];
        const el = field(k);
        if (!el) return;
        if (kind === "bool") body[k] = !!el.checked;
        else if (kind === "num") body[k] = Number(el.value);
        else body[k] = el.value;
      });
      if (!body.name_enter) body.name_enter = "none";
      return body;
    }

    function markPreset() {
      const motion = (theme.motion || (field("motion") && field("motion").value) || "crawl");
      const aliases = {
        typewriter: "teletype",
        matrix: "matrix",
        starwars: "starwars",
        ticker: "nametape",
        cards: "endcard",
        fade: "minimal",
        crawl: "classic",
        "crawl-down": "classic",
      };
      const inferred = aliases[motion] || motion;
      presetWrap.querySelectorAll(".crd-ed-chip").forEach(function (b) {
        b.classList.toggle("on", b.dataset.preset === activePreset || (!activePreset && b.dataset.preset === inferred));
      });
    }

    function markMotion() {
      const motion = (theme.motion || (field("motion") && field("motion").value) || "crawl");
      ed.querySelectorAll(".crd-ed-motion").forEach(function (b) {
        b.classList.toggle("on", b.getAttribute("data-motion") === motion);
      });
    }

    function put(body, persist) {
      body = Object.assign({}, body);
      body.persist = persist !== false;
      return fetch(withAuth(opts.themeUrl), {
        method: "PUT",
        headers: headers(),
        credentials: "same-origin",
        body: JSON.stringify(body),
      }).then(function (r) { return r.json(); });
    }

    function live() {
      clearTimeout(liveTimer);
      liveTimer = setTimeout(function () {
        const body = collect();
        theme = Object.assign({}, theme, body);
        put(body, false).then(function (t) {
          theme = t;
          status.textContent = "Previewing";
        }).catch(function (e) {
          status.textContent = String(e.message || e);
        });
      }, 180);
    }

    ed.querySelectorAll("[data-k]").forEach(function (el) {
      el.addEventListener("change", function () {
        activePreset = "";
        markPreset();
        markMotion();
        live();
        const k = el.getAttribute("data-k");
        if (k === "motion" || k === "typewriter_unit" || k === "typewriter_cps" || k === "matrix_density") {
          restartPlay();
        }
      });
      el.addEventListener("input", function () {
        if (el.type === "checkbox" || el.tagName === "SELECT") return;
        activePreset = "";
        live();
      });
    });

    function restartPlay() {
      if (!opts.playUrl) return Promise.resolve();
      return fetch(withAuth(opts.playUrl), {
        method: "POST",
        headers: headers(),
        credentials: "same-origin",
        body: JSON.stringify({ playing: true, restart: true }),
      }).catch(function () { return null; });
    }

    ed.querySelectorAll(".crd-ed-motion").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const motion = btn.getAttribute("data-motion");
        const sel = field("motion");
        if (sel) sel.value = motion;
        activePreset = motion === "typewriter" ? "teletype" : (motion === "matrix" ? "matrix" : "");
        theme = Object.assign({}, theme, { motion: motion });
        markPreset();
        markMotion();
        live();
        restartPlay();
        status.textContent = btn.querySelector("strong") ? btn.querySelector("strong").textContent : motion;
      });
    });

    function applyPreset(p) {
      activePreset = p.id;
      const body = Object.assign({}, collect(), p.theme, { name_enter: p.theme.name_enter || "none" });
      fill(body);
      markPreset();
      markMotion();
      put(body, true).then(function (t) {
        fill(t);
        status.textContent = p.label + " saved";
        return restartPlay();
      }).catch(function (e) {
        status.textContent = String(e.message || e);
      });
    }

    ed.querySelector("[data-act=save]").addEventListener("click", function () {
      put(collect(), true).then(function (t) {
        fill(t);
        status.textContent = "Saved";
      }).catch(function (e) {
        status.textContent = String(e.message || e);
      });
    });

    ed.querySelector("[data-act=restart]").addEventListener("click", function () {
      fetch(withAuth(opts.playUrl), {
        method: "POST",
        headers: headers(),
        credentials: "same-origin",
        body: JSON.stringify({ playing: true, restart: true }),
      }).then(function () {
        status.textContent = "Restarted";
      }).catch(function (e) {
        status.textContent = String(e.message || e);
      });
    });

    fetch(withAuth(opts.themeUrl), { headers: headers(), credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(fill)
      .catch(function (e) { status.textContent = String(e.message || e); });

    return { fill: fill, collect: collect };
  }

  global.CreditsEditor = { mount: mount, PRESETS: PRESETS, MOTIONS: MOTIONS };
})(window);
