(() => {
  const MOTIONS = [
    { id: "crawl", label: "Crawl up", hint: "Classic rolling titles" },
    { id: "crawl-down", label: "Crawl down", hint: "Start at the top" },
    { id: "starwars", label: "Star Wars", hint: "Perspective crawl" },
    { id: "cards", label: "Cards", hint: "One block at a time" },
    { id: "fade", label: "Fade pages", hint: "Crossfade sections" },
    { id: "slides", label: "Slides", hint: "Side-step each block" },
    { id: "ticker", label: "Ticker", hint: "Horizontal name tape" },
    { id: "typewriter", label: "Typewriter", hint: "Types each character" },
    { id: "matrix", label: "Matrix", hint: "Rain + name decode" },
  ];

  // Older names for motions and presets (standalone Chat Credits, old docs).
  const MOTION_ALIASES = { teletype: "typewriter", tty: "typewriter", nametape: "ticker", "name-tape": "ticker" };
  const PRESET_ALIASES = { teletype: "typewriter", nametape: "ticker" };
  // Every preset starts from this so film looks don't leak from the last preset.
  const PRESET_BASE = { letterbox: false, grain: false, background: "transparent" };

  const FONTS = [
    {
      id: "palatino",
      label: "Palatino — classic",
      family: '"Palatino Linotype", Palatino, "Times New Roman", Georgia, serif',
      url: "",
    },
    { id: "georgia", label: "Georgia", family: "Georgia, serif", url: "" },
    {
      id: "cinzel",
      label: "Cinzel — titling",
      family: '"Cinzel", Palatino, serif',
      url: "https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&display=swap",
    },
    {
      id: "playfair",
      label: "Playfair Display",
      family: '"Playfair Display", Georgia, serif',
      url: "https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&display=swap",
    },
    {
      id: "bebas",
      label: "Bebas Neue",
      family: '"Bebas Neue", Impact, sans-serif',
      url: "https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap",
    },
    {
      id: "oswald",
      label: "Oswald",
      family: '"Oswald", Impact, sans-serif',
      url: "https://fonts.googleapis.com/css2?family=Oswald:wght@400;600&display=swap",
    },
    {
      id: "inter",
      label: "Inter",
      family: '"Inter", system-ui, sans-serif',
      url: "https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap",
    },
    {
      id: "sharetech",
      label: "Share Tech Mono — terminal",
      family: '"Share Tech Mono", "Courier New", monospace',
      url: "https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap",
    },
    {
      id: "courier",
      label: "Courier — teletype",
      family: '"Courier New", Courier, monospace',
      url: "",
    },
    { id: "custom", label: "Custom…", family: "", url: "" },
  ];

  const PRESETS = [
    {
      id: "classic",
      label: "Classic",
      patch: {
        motion: "crawl",
        easing: "linear",
        font_preset: "palatino",
        title_color: "#f3e2b0",
        name_color: "#f4f0e6",
        muted_color: "#9a8f78",
        mod_color: "#e8c36a",
        glow: false,
        title_intro: "none",
        name_enter: "none",
        uppercase_title: true,
        letter_spacing_em: 0.04,
        speed_px_per_sec: 42,
        mask_fade_px: 72,
        vignette: false,
        rule_style: "gradient",
        align: "center",
        shadow_strength: 8,
      },
    },
    {
      id: "starwars",
      label: "Star Wars",
      patch: {
        motion: "starwars",
        easing: "linear",
        font_preset: "oswald",
        font_family: '"Oswald", "Franklin Gothic Medium", "Arial Narrow", sans-serif',
        custom_font_url: "https://fonts.googleapis.com/css2?family=Oswald:wght@400;600&display=swap",
        title_color: "#ffe81f",
        name_color: "#ffe81f",
        muted_color: "#c4b000",
        mod_color: "#fff3a0",
        glow: false,
        title_intro: "fade",
        title_hold_sec: 1.2,
        speed_px_per_sec: 34,
        perspective_px: 320,
        tilt_deg: 32,
        mask_fade_px: 110,
        vignette: true,
        letterbox: true,
        uppercase_title: true,
        letter_spacing_em: 0.08,
        columns: 1,
        job_layout: "stacked",
        align: "center",
      },
    },
    {
      id: "gold",
      label: "Gold titles",
      patch: {
        motion: "crawl",
        font_preset: "cinzel",
        title_color: "#f0d78c",
        name_color: "#f7f1de",
        muted_color: "#b9a56a",
        mod_color: "#ffd978",
        glow: true,
        glow_color: "#e8c36a",
        glow_px: 18,
        title_intro: "scale",
        name_enter: "rise",
        speed_px_per_sec: 32,
        letter_spacing_em: 0.12,
        shadow_strength: 12,
        rule_style: "double",
        letterbox: true,
        grain: true,
      },
    },
    {
      id: "neon",
      label: "Neon night",
      patch: {
        motion: "cards",
        font_preset: "oswald",
        title_color: "#7af0ff",
        name_color: "#f4fbff",
        muted_color: "#7a93b0",
        mod_color: "#ff7ad9",
        vip_color: "#c9a0ff",
        glow: true,
        glow_color: "#5ce1ff",
        glow_px: 20,
        title_intro: "wipe",
        page_duration_sec: 4,
        page_transition_ms: 600,
        uppercase_title: true,
        letter_spacing_em: 0.16,
        rule_style: "solid",
        shadow_strength: 10,
      },
    },
    {
      id: "typewriter",
      label: "Teletype",
      patch: {
        motion: "typewriter",
        typewriter_unit: "line",
        typewriter_cps: 28,
        font_preset: "sharetech",
        title_color: "#d4c4a0",
        name_color: "#e8dcc4",
        muted_color: "#8a7d64",
        mod_color: "#f0e0a8",
        background: "#12100c",
        glow: false,
        type_ms: 48,
        page_duration_sec: 2.4,
        title_intro: "none",
        uppercase_title: false,
        letter_spacing_em: 0,
        columns: 1,
        rule_style: "solid",
        shadow_strength: 0,
        align: "left",
      },
    },
    {
      id: "endcard",
      label: "End card",
      patch: {
        motion: "fade",
        font_preset: "playfair",
        title_color: "#fff6e8",
        name_color: "#f3eee4",
        muted_color: "#a39888",
        page_duration_sec: 5,
        page_transition_ms: 900,
        title_intro: "fade",
        title_hold_sec: 0.4,
        columns: 2,
        mask_fade_px: 0,
        vignette: true,
        rule_style: "gradient",
        letter_spacing_em: 0.06,
      },
    },
    {
      id: "ticker",
      label: "Name tape",
      patch: {
        motion: "ticker",
        font_preset: "bebas",
        title_size_px: 40,
        name_size_px: 28,
        speed_px_per_sec: 64,
        title_intro: "fade",
        uppercase_names: true,
        letter_spacing_em: 0.08,
        show_platform: true,
        columns: 1,
      },
    },
    {
      id: "matrix",
      label: "Matrix",
      patch: {
        motion: "matrix",
        font_preset: "sharetech",
        title_color: "#00ff41",
        name_color: "#b8ffb8",
        muted_color: "#1f8a38",
        mod_color: "#9aff9a",
        vip_color: "#d6ffd6",
        background: "#000000",
        glow: true,
        glow_color: "#00ff41",
        glow_px: 12,
        shadow_strength: 0,
        title_intro: "none",
        uppercase_title: true,
        letter_spacing_em: 0.14,
        columns: 2,
        page_duration_sec: 5.5,
        matrix_density: 1,
        vignette: false,
      },
    },
    {
      id: "minimal",
      label: "Minimal",
      patch: {
        motion: "crawl",
        font_preset: "inter",
        title_color: "#f5f5f5",
        name_color: "#ececec",
        muted_color: "#9a9a9a",
        mod_color: "#ffffff",
        glow: false,
        shadow_strength: 4,
        letter_spacing_em: 0.02,
        uppercase_title: false,
        rule_style: "none",
        name_enter: "fade",
        speed_px_per_sec: 38,
        mask_fade_px: 48,
      },
    },
  ];

  const KEYS = [
    "title", "subtitle", "footer", "section_label",
    "group_by_platform", "sort", "columns",
    "show_platform", "show_message_count", "highlight_mods", "highlight_vips",
    "speed_px_per_sec", "duration_sec", "gap_after_loop_sec", "mode",
    "motion", "easing", "mask_fade_px", "vignette",
    "title_intro", "title_hold_sec", "name_enter", "name_stagger_ms",
    "loop_transition", "perspective_px", "tilt_deg",
    "page_duration_sec", "page_transition_ms", "type_ms",
    "typewriter_unit", "typewriter_cps", "matrix_density",
    "letterbox", "grain", "clear_when_done", "title_own_page",
    "font_family", "font_preset", "custom_font_url",
    "title_size_px", "name_size_px", "subtitle_size_px", "footer_size_px",
    "letter_spacing_em", "uppercase_title", "uppercase_names",
    "title_weight", "name_weight",
    "title_color", "name_color", "muted_color", "mod_color", "vip_color",
    "background", "text_shadow", "shadow_strength",
    "glow", "glow_color", "glow_px", "opacity",
    "column_gap_px", "row_gap_px", "max_width_px",
    "rule_style", "align", "job_layout",
    "style_id",
  ];

  const NUMS = new Set([
    "columns", "speed_px_per_sec", "duration_sec", "gap_after_loop_sec",
    "mask_fade_px", "title_hold_sec", "name_stagger_ms",
    "perspective_px", "tilt_deg", "page_duration_sec", "page_transition_ms",
    "type_ms", "typewriter_cps", "matrix_density", "title_size_px", "name_size_px", "subtitle_size_px",
    "footer_size_px", "letter_spacing_em", "title_weight", "name_weight",
    "shadow_strength", "glow_px", "opacity",
    "column_gap_px", "row_gap_px", "max_width_px",
  ]);

  const BOOLS = new Set([
    "group_by_platform", "show_platform", "show_message_count",
    "highlight_mods", "highlight_vips", "vignette",
    "uppercase_title", "uppercase_names", "glow",
    "letterbox", "grain", "clear_when_done", "title_own_page",
  ]);

  const TABS = [
    { id: "motion", label: "Motion" },
    { id: "copy", label: "Copy" },
    { id: "type", label: "Type" },
    { id: "color", label: "Color" },
    { id: "layout", label: "Layout" },
    { id: "list", label: "List" },
  ];

  let root = null;
  let filling = false;
  let liveTimer = 0;
  let opts = {};
  let currentTab = "motion";
  let styles = [];

  function $(id) {
    return root ? root.querySelector("#" + id) : null;
  }

  function field(id, label, control, extra = "") {
    return `<div class="cs-field ${extra}"><label for="${id}">${label}</label>${control}</div>`;
  }

  function sel(id, pairs) {
    const optsHtml = pairs
      .map(([v, l]) => `<option value="${v}">${l}</option>`)
      .join("");
    return `<select id="${id}">${optsHtml}</select>`;
  }

  function numInput(id, min, max, step) {
    const s = step != null ? ` step="${step}"` : "";
    return `<input id="${id}" type="number" min="${min}" max="${max}"${s} />`;
  }

  function range(id, min, max, step) {
    return `<div class="cs-range-row">
      <input id="${id}" type="range" min="${min}" max="${max}" step="${step}" />
      <output id="${id}-out"></output>
    </div>`;
  }

  function color(id) {
    return `<div class="cs-color">
      <input id="${id}-swatch" type="color" value="#f3e2b0" />
      <input id="${id}" type="text" spellcheck="false" />
    </div>`;
  }

  function check(id, label) {
    return `<label class="cs-check"><input id="${id}" type="checkbox" /> ${label}</label>`;
  }

  function html() {
    const motions = MOTIONS.map(
      (m) =>
        `<button type="button" class="cs-motion" data-motion="${m.id}">
          <span class="cs-motion-ico" aria-hidden="true"></span>
          <b>${m.label}</b><small>${m.hint}</small>
        </button>`
    ).join("");
    const presets = PRESETS.map(
      (p) => `<button type="button" class="cs-preset" data-preset="${p.id}">${p.label}</button>`
    ).join("");
    const tabs = TABS.map(
      (t) => `<button type="button" class="cs-tab" data-tab="${t.id}">${t.label}</button>`
    ).join("");
    const fonts = FONTS.map((f) => `<option value="${f.id}">${f.label}</option>`).join("");

    return `
      <div class="cs-head">
        <h2>Style</h2>
        <div class="cs-head-actions">
          <span class="cs-live" title="Edits push to the overlay immediately. Save look writes them to disk.">
            <i></i> Live preview
          </span>
        </div>
      </div>
      <p class="cs-help">Pick a preset to jump, then refine. Motion changes restart the roll.</p>
      <div class="cs-presets">${presets}</div>
      <div class="cs-tabs">${tabs}</div>

      <div class="cs-pane" data-pane="motion">
        <div class="cs-motions">${motions}</div>
        <div class="cs-grid">
          ${field("cs-easing", "Easing", sel("cs-easing", [
            ["linear", "Linear"],
            ["ease-in", "Ease in"],
            ["ease-out", "Ease out"],
            ["ease-in-out", "Ease in-out"],
            ["smooth", "Smoothstep"],
          ]))}
          ${field("cs-loop-trans", "Loop transition", sel("cs-loop-trans", [
            ["cut", "Cut"],
            ["fade", "Fade"],
            ["wipe", "Wipe up"],
          ]))}
          ${field("cs-speed", "Speed (px/s)", numInput("cs-speed", 8, 240))}
          ${field("cs-duration", "Target time (sec, 0 = speed)", numInput("cs-duration", 0, 900))}
          ${field("cs-gap", "Gap after loop (sec)", numInput("cs-gap", 0, 30, 0.1))}
          ${field("cs-title-hold", "Hold on title (sec)", numInput("cs-title-hold", 0, 12, 0.1))}
          ${field("cs-title-intro", "Title intro", sel("cs-title-intro", [
            ["none", "None"],
            ["fade", "Fade"],
            ["scale", "Scale"],
            ["wipe", "Wipe"],
            ["letters", "Letter by letter"],
          ]))}
          ${field("cs-name-enter", "Name enter", sel("cs-name-enter", [
            ["none", "None"],
            ["fade", "Fade"],
            ["rise", "Rise"],
            ["slide", "Slide"],
            ["blur", "Blur in"],
          ]))}
          ${field("cs-stagger", "Name stagger (ms)", numInput("cs-stagger", 0, 400))}
          ${field("cs-mask", "Edge fade (px)", numInput("cs-mask", 0, 240))}
        </div>
        <div class="cs-ctx" id="cs-ctx-crawl">
          <div class="cs-grid" style="margin-top:8px">
            ${field("cs-perspective", "Perspective (px)", numInput("cs-perspective", 120, 1200))}
            ${field("cs-tilt", "Tilt (deg)", numInput("cs-tilt", 8, 80))}
          </div>
        </div>
        <div class="cs-ctx" id="cs-ctx-pages">
          <div class="cs-grid" style="margin-top:8px">
            ${field("cs-page-dur", "Page duration (sec)", numInput("cs-page-dur", 0.8, 30, 0.1))}
            ${field("cs-page-ms", "Transition (ms)", numInput("cs-page-ms", 80, 2000))}
            ${field("cs-type-unit", "Typewriter types", sel("cs-type-unit", [
              ["line", "Each line, pause between lines"],
              ["card", "Each page in one go"],
              ["page", "Whole page, no pauses"],
              ["name", "Whole names, one at a time"],
            ]))}
            ${field("cs-type-cps", "Typing speed (chars/sec)", numInput("cs-type-cps", 4, 120))}
            ${field("cs-type-ms", "Delay per name (ms)", numInput("cs-type-ms", 10, 400))}
          </div>
          ${check("cs-title-page", "Title gets its own page")}
        </div>
        <div class="cs-ctx" id="cs-ctx-matrix">
          <div class="cs-grid" style="margin-top:8px">
            ${field("cs-matrix-density", "Rain density", numInput("cs-matrix-density", 0.4, 2.2, 0.1))}
            ${field("cs-matrix-hold", "Seconds per screen", numInput("cs-matrix-hold", 0.8, 30, 0.1))}
          </div>
          <p class="cs-help">Rain is drawn on the backdrop colour; with a transparent overlay it falls over your scene.</p>
        </div>
        ${check("cs-vignette", "Vignette")}
        ${check("cs-letterbox", "Letterbox bars")}
        ${check("cs-grain", "Film grain")}
        ${check("cs-clear-done", "Play once: leave the screen empty when the roll ends")}
      </div>

      <div class="cs-pane" data-pane="copy">
        <div class="cs-grid one">
          ${field("cs-title", "Title", `<input id="cs-title" type="text" />`)}
          ${field("cs-subtitle", "Subtitle", `<input id="cs-subtitle" type="text" />`)}
          ${field("cs-footer", "Footer", `<input id="cs-footer" type="text" />`)}
          ${field("cs-section", "Section label (names layout)", `<input id="cs-section" type="text" />`)}
        </div>
      </div>

      <div class="cs-pane" data-pane="type">
        <div class="cs-grid">
          ${field("cs-font", "Font", `<select id="cs-font">${fonts}</select>`)}
          ${field("cs-font-url", "Custom font CSS URL", `<input id="cs-font-url" type="url" placeholder="https://fonts.googleapis.com/css2?family=…" />`, "span2")}
          ${field("cs-font-family", "Font family stack", `<input id="cs-font-family" type="text" />`, "span2")}
          ${field("cs-title-size", "Title size", range("cs-title-size", 20, 120, 1))}
          ${field("cs-name-size", "Name size", range("cs-name-size", 10, 64, 1))}
          ${field("cs-sub-size", "Subtitle size", range("cs-sub-size", 10, 72, 1))}
          ${field("cs-foot-size", "Footer size", range("cs-foot-size", 10, 80, 1))}
          ${field("cs-track", "Letter spacing (em)", range("cs-track", 0, 0.3, 0.01))}
          ${field("cs-title-w", "Title weight", sel("cs-title-w", [
            ["400", "Regular"], ["500", "Medium"], ["600", "Semibold"], ["700", "Bold"], ["800", "Black"],
          ]))}
          ${field("cs-name-w", "Name weight", sel("cs-name-w", [
            ["400", "Regular"], ["500", "Medium"], ["600", "Semibold"], ["700", "Bold"],
          ]))}
        </div>
        ${check("cs-up-title", "Uppercase title + footer")}
        ${check("cs-up-names", "Uppercase names")}
      </div>

      <div class="cs-pane" data-pane="color">
        <div class="cs-grid">
          ${field("cs-title-color", "Title", color("cs-title-color"))}
          ${field("cs-name-color", "Names", color("cs-name-color"))}
          ${field("cs-muted-color", "Muted / jobs", color("cs-muted-color"))}
          ${field("cs-mod-color", "Mods", color("cs-mod-color"))}
          ${field("cs-vip-color", "VIPs", color("cs-vip-color"))}
          ${field("cs-glow-color", "Glow", color("cs-glow-color"))}
          ${field("cs-shadow", "Shadow strength", range("cs-shadow", 0, 24, 1))}
          ${field("cs-glow-px", "Glow radius", range("cs-glow-px", 0, 40, 1))}
          ${field("cs-opacity", "Overall opacity", range("cs-opacity", 0.2, 1, 0.05))}
          ${field("cs-bg-color", "Solid backdrop", color("cs-bg-color"))}
        </div>
        ${check("cs-glow", "Glow on titles and names")}
        ${check("cs-solid-bg", "Opaque backdrop (off = transparent overlay)")}
      </div>

      <div class="cs-pane" data-pane="layout">
        <div class="cs-grid">
          ${field("cs-columns", "Columns", sel("cs-columns", [
            ["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"],
          ]))}
          ${field("cs-align", "Align", sel("cs-align", [
            ["center", "Center"], ["left", "Left"],
          ]))}
          ${field("cs-jobs", "Job rows", sel("cs-jobs", [
            ["dots", "Name ····· Job"],
            ["stacked", "Stacked"],
            ["inline", "Inline"],
          ]))}
          ${field("cs-rule", "Divider", sel("cs-rule", [
            ["gradient", "Gradient"], ["solid", "Solid"], ["double", "Double"], ["none", "None"],
          ]))}
          ${field("cs-col-gap", "Column gap (px)", numInput("cs-col-gap", 8, 160))}
          ${field("cs-row-gap", "Row gap (px)", numInput("cs-row-gap", 0, 48))}
          ${field("cs-maxw", "Max width (px)", numInput("cs-maxw", 320, 1600))}
          ${field("cs-format", "Cast format", `<select id="cs-format"></select>`)}
        </div>
      </div>

      <div class="cs-pane" data-pane="list">
        <div class="cs-grid">
          ${field("cs-sort", "Sort", sel("cs-sort", [
            ["first_seen", "First seen"],
            ["name", "Name"],
            ["messages", "Most messages"],
            ["last_seen", "Last seen"],
          ]))}
        </div>
        ${check("cs-group", "Group by platform")}
        ${check("cs-dots", "Platform dots")}
        ${check("cs-counts", "Message counts")}
        ${check("cs-mods", "Highlight mods")}
        ${check("cs-vips", "Highlight VIPs")}
      </div>

      <div class="cs-actions">
        <button type="button" class="primary" id="cs-save">Save look</button>
        <button type="button" id="cs-restart">Restart roll</button>
        <span class="cs-status" id="cs-status"></span>
      </div>
    `;
  }

  function hexish(v, fallback) {
    const s = String(v || "").trim();
    if (/^#[0-9a-fA-F]{6}$/.test(s)) return s;
    if (/^#[0-9a-fA-F]{3}$/.test(s)) {
      return "#" + s[1] + s[1] + s[2] + s[2] + s[3] + s[3];
    }
    return fallback;
  }

  function bindColorPair(textId, swatchId) {
    const text = $(textId);
    const sw = $(swatchId);
    if (!text || !sw) return;
    sw.addEventListener("input", () => {
      text.value = sw.value;
      emitLive();
    });
    text.addEventListener("input", () => {
      const h = hexish(text.value, sw.value);
      if (h.startsWith("#") && h.length === 7) sw.value = h;
    });
  }

  function bindRange(id) {
    const el = $(id);
    const out = $(id + "-out");
    if (!el || !out) return;
    const sync = () => {
      out.textContent = el.value;
    };
    el.addEventListener("input", sync);
    sync();
  }

  function setVal(id, v) {
    const el = $(id);
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = v == null ? "" : String(v);
    const out = $(id + "-out");
    if (out) out.textContent = el.value;
  }

  function val(id) {
    const el = $(id);
    if (!el) return "";
    if (el.type === "checkbox") return el.checked;
    return el.value;
  }

  function n(id, fallback) {
    const v = Number(val(id));
    return Number.isFinite(v) ? v : fallback;
  }

  function applyFontPreset(id, family, url) {
    const preset = FONTS.find((f) => f.id === id);
    if (!preset) return;
    if (id !== "custom") {
      setVal("cs-font-family", family || preset.family);
      if (preset.url) setVal("cs-font-url", preset.url);
      else if (!url) setVal("cs-font-url", "");
    }
  }

  function syncMotionChrome() {
    const motion = val("cs-motion-hidden") || (root.querySelector(".cs-motion.is-on") || {}).dataset?.motion || "crawl";
    root.querySelectorAll(".cs-motion").forEach((b) => {
      b.classList.toggle("is-on", b.dataset.motion === motion);
    });
    const crawlish = motion === "starwars";
    const pages = ["cards", "fade", "slides", "typewriter"].includes(motion);
    const ctxCrawl = $("cs-ctx-crawl");
    const ctxPages = $("cs-ctx-pages");
    const ctxMatrix = $("cs-ctx-matrix");
    if (ctxCrawl) ctxCrawl.style.display = crawlish ? "" : "none";
    if (ctxPages) ctxPages.style.display = pages ? "" : "none";
    if (ctxMatrix) ctxMatrix.style.display = motion === "matrix" ? "" : "none";
    const unit = val("cs-type-unit") || "line";
    const show = (id, on) => {
      const el = $(id);
      if (el && el.closest(".cs-field")) el.closest(".cs-field").style.display = on ? "" : "none";
    };
    show("cs-type-unit", motion === "typewriter");
    show("cs-type-cps", motion === "typewriter" && unit !== "name");
    show("cs-type-ms", motion === "typewriter" && unit === "name");
    show("cs-page-ms", motion !== "typewriter");
  }

  function currentMotion() {
    const on = root.querySelector(".cs-motion.is-on");
    return (on && on.dataset.motion) || "crawl";
  }

  function motionOf(theme) {
    const m = String((theme && theme.motion) || "crawl").toLowerCase();
    return MOTION_ALIASES[m] || m;
  }

  function collect() {
    const fontId = val("cs-font") || "palatino";
    const preset = FONTS.find((f) => f.id === fontId);
    const solid = !!val("cs-solid-bg");
    const bgColor = val("cs-bg-color") || "#000000";
    const theme = {
      title: val("cs-title"),
      subtitle: val("cs-subtitle"),
      footer: val("cs-footer"),
      section_label: val("cs-section"),
      group_by_platform: !!val("cs-group"),
      sort: val("cs-sort") || "first_seen",
      columns: n("cs-columns", 2),
      show_platform: !!val("cs-dots"),
      show_message_count: !!val("cs-counts"),
      highlight_mods: !!val("cs-mods"),
      highlight_vips: !!val("cs-vips"),
      speed_px_per_sec: n("cs-speed", 42),
      duration_sec: n("cs-duration", 0),
      gap_after_loop_sec: n("cs-gap", 2.5),
      motion: currentMotion(),
      easing: val("cs-easing") || "linear",
      mask_fade_px: n("cs-mask", 72),
      vignette: !!val("cs-vignette"),
      title_intro: val("cs-title-intro") || "none",
      title_hold_sec: n("cs-title-hold", 0),
      name_enter: val("cs-name-enter") || "none",
      name_stagger_ms: n("cs-stagger", 40),
      loop_transition: val("cs-loop-trans") || "cut",
      perspective_px: n("cs-perspective", 420),
      tilt_deg: n("cs-tilt", 52),
      page_duration_sec: n("cs-page-dur", 4.5),
      page_transition_ms: n("cs-page-ms", 700),
      type_ms: n("cs-type-ms", 55),
      typewriter_unit: val("cs-type-unit") || "line",
      typewriter_cps: n("cs-type-cps", 28),
      matrix_density: n("cs-matrix-density", 1),
      title_own_page: !!val("cs-title-page"),
      letterbox: !!val("cs-letterbox"),
      grain: !!val("cs-grain"),
      clear_when_done: !!val("cs-clear-done"),
      font_preset: fontId,
      font_family: val("cs-font-family") || (preset && preset.family) || "Georgia, serif",
      custom_font_url: val("cs-font-url"),
      title_size_px: n("cs-title-size", 54),
      name_size_px: n("cs-name-size", 22),
      subtitle_size_px: n("cs-sub-size", 26),
      footer_size_px: n("cs-foot-size", 28),
      letter_spacing_em: n("cs-track", 0.04),
      uppercase_title: !!val("cs-up-title"),
      uppercase_names: !!val("cs-up-names"),
      title_weight: n("cs-title-w", 600),
      name_weight: n("cs-name-w", 500),
      title_color: val("cs-title-color") || "#f3e2b0",
      name_color: val("cs-name-color") || "#f4f0e6",
      muted_color: val("cs-muted-color") || "#9a8f78",
      mod_color: val("cs-mod-color") || "#e8c36a",
      vip_color: val("cs-vip-color") || "#c9a0ff",
      background: solid ? bgColor : "transparent",
      shadow_strength: n("cs-shadow", 8),
      glow: !!val("cs-glow"),
      glow_color: val("cs-glow-color") || "#e8c36a",
      glow_px: n("cs-glow-px", 16),
      opacity: n("cs-opacity", 1),
      column_gap_px: n("cs-col-gap", 48),
      row_gap_px: n("cs-row-gap", 10),
      max_width_px: n("cs-maxw", 920),
      rule_style: val("cs-rule") || "gradient",
      align: val("cs-align") || "center",
      job_layout: val("cs-jobs") || "dots",
      style_id: val("cs-format") || "names",
    };
    if (theme.motion === "matrix") theme.page_duration_sec = n("cs-matrix-hold", theme.page_duration_sec);
    const s = theme.shadow_strength;
    theme.text_shadow = s <= 0 ? "none" : `0 2px ${s}px rgba(0,0,0,0.85)`;
    return theme;
  }

  function fill(theme) {
    theme = theme || {};
    filling = true;
    setVal("cs-title", theme.title || "");
    setVal("cs-subtitle", theme.subtitle || "");
    setVal("cs-footer", theme.footer || "");
    setVal("cs-section", theme.section_label || "Chatters");
    setVal("cs-group", !!theme.group_by_platform);
    setVal("cs-sort", theme.sort || "first_seen");
    setVal("cs-columns", String(theme.columns || 2));
    setVal("cs-dots", theme.show_platform !== false);
    setVal("cs-counts", !!theme.show_message_count);
    setVal("cs-mods", theme.highlight_mods !== false);
    setVal("cs-vips", !!theme.highlight_vips);
    setVal("cs-speed", theme.speed_px_per_sec ?? 42);
    setVal("cs-duration", theme.duration_sec ?? 0);
    setVal("cs-gap", theme.gap_after_loop_sec ?? 2.5);
    setVal("cs-easing", theme.easing || "linear");
    setVal("cs-mask", theme.mask_fade_px ?? 72);
    setVal("cs-vignette", !!theme.vignette);
    setVal("cs-title-intro", theme.title_intro || "none");
    setVal("cs-title-hold", theme.title_hold_sec ?? 0);
    setVal("cs-name-enter", theme.name_enter || "none");
    setVal("cs-stagger", theme.name_stagger_ms ?? 40);
    setVal("cs-loop-trans", theme.loop_transition || "cut");
    setVal("cs-perspective", theme.perspective_px ?? theme.sw_perspective_px ?? 420);
    setVal("cs-tilt", theme.tilt_deg ?? theme.sw_tilt_deg ?? 52);
    setVal("cs-page-dur", theme.page_duration_sec ?? theme.page_hold_sec ?? 4.5);
    setVal("cs-page-ms", theme.page_transition_ms ?? (theme.page_fade_sec != null ? Math.round(theme.page_fade_sec * 1000) : 700));
    setVal("cs-type-ms", theme.type_ms ?? 55);
    setVal("cs-type-unit", theme.typewriter_unit || "line");
    setVal("cs-type-cps", theme.typewriter_cps ?? 28);
    setVal("cs-matrix-density", theme.matrix_density ?? 1);
    setVal("cs-matrix-hold", theme.page_duration_sec ?? theme.page_hold_sec ?? 4.5);
    setVal("cs-title-page", theme.title_own_page !== false);
    setVal("cs-letterbox", !!theme.letterbox);
    setVal("cs-grain", !!theme.grain);
    setVal("cs-clear-done", !!theme.clear_when_done);
    const fontId = theme.font_preset || matchFont(theme.font_family) || "palatino";
    setVal("cs-font", fontId);
    setVal("cs-font-url", theme.custom_font_url || "");
    setVal("cs-font-family", theme.font_family || "");
    setVal("cs-title-size", theme.title_size_px ?? 54);
    setVal("cs-name-size", theme.name_size_px ?? 22);
    setVal("cs-sub-size", theme.subtitle_size_px ?? 26);
    setVal("cs-foot-size", theme.footer_size_px ?? 28);
    setVal("cs-track", theme.letter_spacing_em ?? 0.04);
    setVal("cs-up-title", theme.uppercase_title !== false);
    setVal("cs-up-names", !!theme.uppercase_names);
    setVal("cs-title-w", String(theme.title_weight || 600));
    setVal("cs-name-w", String(theme.name_weight || 500));
    fillColor("cs-title-color", theme.title_color || "#f3e2b0");
    fillColor("cs-name-color", theme.name_color || "#f4f0e6");
    fillColor("cs-muted-color", theme.muted_color || "#9a8f78");
    fillColor("cs-mod-color", theme.mod_color || "#e8c36a");
    fillColor("cs-vip-color", theme.vip_color || "#c9a0ff");
    fillColor("cs-glow-color", theme.glow_color || "#e8c36a");
    setVal("cs-shadow", theme.shadow_strength ?? 8);
    setVal("cs-glow", !!theme.glow);
    setVal("cs-glow-px", theme.glow_px ?? 16);
    setVal("cs-opacity", theme.opacity ?? 1);
    const bg = theme.background || "transparent";
    const solid = bg && bg !== "transparent";
    setVal("cs-solid-bg", solid);
    fillColor("cs-bg-color", solid ? bg : "#000000");
    setVal("cs-col-gap", theme.column_gap_px ?? 48);
    setVal("cs-row-gap", theme.row_gap_px ?? 10);
    setVal("cs-maxw", theme.max_width_px ?? 920);
    setVal("cs-rule", theme.rule_style || "gradient");
    setVal("cs-align", theme.align || "center");
    setVal("cs-jobs", theme.job_layout || "dots");
    if (theme.style_id) setVal("cs-format", theme.style_id);
    const motion = motionOf(theme);
    root.querySelectorAll(".cs-motion").forEach((b) => {
      b.classList.toggle("is-on", b.dataset.motion === motion);
    });
    syncMotionChrome();
    filling = false;
  }

  function fillColor(id, value) {
    setVal(id, value);
    const sw = $(id + "-swatch");
    if (sw) sw.value = hexish(value, sw.value || "#f3e2b0");
  }

  function matchFont(family) {
    const f = String(family || "").toLowerCase();
    for (const p of FONTS) {
      if (p.id === "custom") continue;
      const token = p.family.split(",")[0].replace(/['"]/g, "").trim().toLowerCase();
      if (token && f.includes(token.toLowerCase())) return p.id;
    }
    return "custom";
  }

  function setTab(id) {
    currentTab = id;
    root.querySelectorAll(".cs-tab").forEach((t) => t.classList.toggle("is-on", t.dataset.tab === id));
    root.querySelectorAll(".cs-pane").forEach((p) => p.classList.toggle("is-on", p.dataset.pane === id));
  }

  function emitLive() {
    if (filling) return;
    syncMotionChrome();
    const status = $("cs-status");
    if (status) status.textContent = "Previewing…";
    clearTimeout(liveTimer);
    liveTimer = setTimeout(() => {
      const theme = collect();
      if (typeof opts.onChange === "function") opts.onChange(theme, { persist: false });
      if (status) status.textContent = "Live";
    }, 180);
  }

  function setStyles(list, styleId) {
    styles = list || [];
    const selEl = $("cs-format");
    if (!selEl) return;
    selEl.innerHTML = styles
      .map((s) => {
        const id = s.id || s;
        const label = s.label ? `${s.label} (${s.style || "names"})` : id;
        return `<option value="${id}">${label}</option>`;
      })
      .join("");
    if (styleId) selEl.value = styleId;
  }

  function applyPreset(id) {
    id = PRESET_ALIASES[id] || id;
    const p = PRESETS.find((x) => x.id === id);
    if (!p) return;
    const cur = collect();
    const next = { ...cur, ...PRESET_BASE, ...p.patch };
    if (p.patch.font_preset) {
      const font = FONTS.find((f) => f.id === p.patch.font_preset);
      if (font) {
        next.font_family = p.patch.font_family || font.family;
        next.custom_font_url = p.patch.custom_font_url != null ? p.patch.custom_font_url : font.url;
      }
    }
    fill(next);
    root.querySelectorAll(".cs-preset").forEach((b) => b.classList.toggle("is-on", b.dataset.preset === id));
    emitLive();
  }

  function mount(el, options) {
    root = typeof el === "string" ? document.getElementById(el) : el;
    opts = options || {};
    if (!root) return;
    root.classList.add("cs-editor");
    root.innerHTML = html();
    setTab("motion");

    [
      "cs-title-size", "cs-name-size", "cs-sub-size", "cs-foot-size",
      "cs-track", "cs-shadow", "cs-glow-px", "cs-opacity",
    ].forEach(bindRange);

    [
      ["cs-title-color", "cs-title-color-swatch"],
      ["cs-name-color", "cs-name-color-swatch"],
      ["cs-muted-color", "cs-muted-color-swatch"],
      ["cs-mod-color", "cs-mod-color-swatch"],
      ["cs-vip-color", "cs-vip-color-swatch"],
      ["cs-glow-color", "cs-glow-color-swatch"],
      ["cs-bg-color", "cs-bg-color-swatch"],
    ].forEach(([a, b]) => bindColorPair(a, b));

    root.addEventListener("input", (e) => {
      // Matrix "seconds per screen" is the same setting as page duration.
      if (e.target && e.target.id === "cs-matrix-hold") setVal("cs-page-dur", e.target.value);
      if (e.target && e.target.id === "cs-page-dur") setVal("cs-matrix-hold", e.target.value);
      if (e.target && e.target.id === "cs-font") {
        const preset = FONTS.find((f) => f.id === e.target.value);
        if (preset) applyFontPreset(preset.id, preset.family, preset.url);
      }
      emitLive();
    });
    root.addEventListener("change", (e) => {
      if (e.target && e.target.id === "cs-format") {
        if (typeof opts.onStyleChange === "function") opts.onStyleChange(e.target.value);
      }
      emitLive();
    });

    root.querySelectorAll(".cs-tab").forEach((btn) => {
      btn.addEventListener("click", () => setTab(btn.dataset.tab));
    });
    root.querySelectorAll(".cs-motion").forEach((btn) => {
      btn.addEventListener("click", () => {
        root.querySelectorAll(".cs-motion").forEach((b) => b.classList.toggle("is-on", b === btn));
        syncMotionChrome();
        emitLive();
      });
    });
    root.querySelectorAll(".cs-preset").forEach((btn) => {
      btn.addEventListener("click", () => applyPreset(btn.dataset.preset));
    });

    const save = $("cs-save");
    if (save) {
      save.addEventListener("click", async () => {
        const theme = collect();
        const status = $("cs-status");
        try {
          if (typeof opts.onSave === "function") await opts.onSave(theme);
          if (status) status.textContent = "Saved";
        } catch (e) {
          if (status) status.textContent = String(e.message || e);
        }
      });
    }
    const restart = $("cs-restart");
    if (restart) {
      restart.addEventListener("click", () => {
        if (typeof opts.onRestart === "function") opts.onRestart();
      });
    }
    syncMotionChrome();
  }

  window.CreditsStyleEditor = {
    KEYS,
    NUMS,
    BOOLS,
    MOTIONS,
    PRESETS,
    FONTS,
    mount,
    fill,
    collect,
    setStyles,
    applyPreset,
  };
})();
