/*
 * Audience looks page of the dashboard (#looks, <section id="tab-looks"> in index.html): how
 * Stream Rooms' chat audience looks, its speech bubbles and the silhouettes chatters sit as.
 * Stream Rooms draws everything; this page only edits the settings, which Core keeps in
 * data/audience_looks.json (core/audience_looks.py) and sends to Stream Rooms over /ws as
 * {"type": "audience_looks"} after every save. Routes: GET / PUT /api/admin/audience-looks,
 * and /api/admin/media for the silhouette pictures (stored files, written "media:<name>").
 *
 * admin.js calls window.AudienceLooksPage.open() when the page is opened (activateTab).
 * Every change saves on its own after a short pause (SAVE_DELAY_MS); there is no Save button.
 *
 * The style keys, presets, shapes and groups below are Stream Rooms' own
 * (core/audience/audience_style.gd there: BUBBLE_DEFAULTS, BUBBLE_PRESETS, FIGURE_DEFAULTS,
 * FIGURE_SHAPES, FIGURE_HEADS, GROUPS) and the preview copies how Stream Rooms draws them
 * (speech_bubble.gd, audience_style.gd _layers). Keep them in sync with Stream Rooms and with
 * BUBBLE_KEYS / FIGURE_KEYS / GROUPS in core/audience_looks.py.
 */
(() => {
  const $ = (id) => document.getElementById(id);
  // Same localStorage key as admin.js and plugin-page.js: the admin token saved in this browser.
  const tokenKey = "stream_core_admin_token";
  // Wait after the last change before saving (ms), so a dragged slider saves once.
  const SAVE_DELAY_MS = 450;
  // Silhouette pictures Stream Rooms can read (it can't read GIF).
  const PICTURE_EXTS = ["png", "jpg", "jpeg", "webp", "gif"]; // gif: animated silhouettes (Stream Rooms keeps up to 32 frames)
  const MEDIA = "media:";
  const MIX_SEP = "|";

  // ── Stream Rooms' style keys and presets (audience_style.gd) ──────────────
  // Bubble sizes are bubble pixels; colours "rrggbbaa".
  const BUBBLE_DEFAULTS = {
    shape: -1, fill: "fffffff7", fill_mix: 0.07, text: "141419ff", name_mode: "chatter", name_color: "202020ff",
    outline: 5.0, outline_mode: "chatter", outline_color: "000000ff", text_size: 30, bold: false, roundness: 26.0,
    tail: "left", width: 380, paid: "ffedadf7", highlighted: "dbccfff7",
  };
  const BUBBLE_SHAPES = [[-1, "Each chatter's own"], [0, "Rounded box"], [1, "Oval"], [2, "Slanted box"], [3, "Pinched box"], [4, "Cloud"]];
  const TAIL_SPOTS = { left: 0.2, middle: 0.5, right: 0.8 };
  // Only the keys that differ from BUBBLE_DEFAULTS. Light / Dark are Stream Rooms' exact colours
  // (Color values there, written here as hex).
  const BUBBLE_PRESETS = {
    Light: { fill: "fffffff7", text: "14141aff", paid: "ffedadf7", highlighted: "dbccfff7" },
    Dark: { fill: "1a1a1ff2", text: "ededf2ff", paid: "6b520df5", highlighted: "664fadf5" },
    Comic: { outline: 8.0, outline_mode: "fixed", outline_color: "111111ff", bold: true, fill_mix: 0.0, fill: "ffffffff", text_size: 32 },
    Neon: { fill: "0b0b14e6", fill_mix: 0.12, text: "f4f4ffff", outline: 4.0, bold: true, paid: "4d3a00eb", highlighted: "3a1f70eb", roundness: 40.0 },
    Glass: { fill: "1e2230a0", fill_mix: 0.2, text: "ffffffff", outline: 2.0, tail: "middle", paid: "6b5410b4", highlighted: "4c3a8cb4" },
    Paper: { shape: 0, fill: "f6eed8fa", fill_mix: 0.0, text: "3b2a1aff", outline: 3.0, outline_mode: "fixed", outline_color: "6b4f2eff",
      roundness: 6.0, name_mode: "fixed", name_color: "7a3b12ff" },
    Minimal: { shape: 0, fill: "ffffffe6", fill_mix: 0.0, outline: 0.0, tail: "middle", roundness: 16.0, text_size: 28 },
    "Thought cloud": { shape: 4, fill_mix: 0.04, outline: 4.0 },
  };
  const FIGURE_DEFAULTS = {
    shape: "classic", file: "", paint: "chatter", color: "8fa3c8ff", brightness: 1.0, size: 1.0,
    head_x: 0.5, head_y: 0.3, head_r: 0.2, crowd: true,
  };
  const FIGURE_SHAPES = { classic: "Classic", round: "Big head", broad: "Broad shoulders", hood: "Hoodie", ears: "Cat ears", bun: "Hair bun", bot: "Robot" };
  // Head centre x, y and radius (pixels in the 256 x 320 picture) of each built-in shape.
  const FIGURE_HEADS = { classic: [128, 94, 56], round: [128, 100, 70], broad: [128, 96, 46], hood: [128, 116, 46],
    ears: [128, 108, 52], bun: [128, 108, 50], bot: [128, 104, 46] };
  const FIG_W = 256;
  const FIG_H = 320;
  const RIM_PX = 5;
  const BODY_GREY = 40 / 255;
  // In the order they win: the first of a chatter's groups with a look set is used.
  const GROUPS = [["mod", "Mods"], ["vip", "VIPs"], ["sub", "Subscribers"], ["kick", "Kick"], ["twitch", "Twitch"],
    ["youtube", "YouTube"], ["other", "Other chat"], ["all", "Everyone else"]];
  // The preview's made-up chatters: name, colour, message, how it stands out.
  const SAMPLES = [
    ["Nova", "#f26666", "Hi chat! The new room looks great", ""],
    ["Pixel_Pete", "#59b3ff", "Super Chat: keep it up!", "paid"],
    ["Mia", "#80f273", "Hello hello", "highlighted"],
  ];

  let looks = null;        // what GET /api/admin/audience-looks gave, edited in place
  let pictures = {};       // stored picture name -> {url, version}, from the last load / save
  let library = [];        // stored files that can be silhouettes ({name, url, ext, ...})
  let saveTimer = 0;
  let built = false;

  // ── Helpers ──────────────────────────────────────────────────────────────
  function token() {
    try { return localStorage.getItem(tokenKey) || ($("token") ? $("token").value.trim() : ""); } catch (_) { return ""; }
  }

  /** fetch with the admin token; JSON back; an Error with Core's message on a failure. */
  async function api(path, opts = {}) {
    const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Admin-Token": token() } });
    const ct = res.headers.get("content-type") || "";
    const body = ct.includes("application/json") ? await res.json() : await res.text();
    if (!res.ok) {
      const d = body && typeof body === "object" ? body.detail : body;
      throw new Error(typeof d === "string" && d ? d : "HTTP " + res.status);
    }
    return body;
  }

  function status(msg, ok = true) {
    const el = $("looks-status");
    if (!el) return;
    el.textContent = msg;
    el.style.color = ok ? "" : "#ff5c5c";
  }

  function el(tag, attrs = {}, kids = []) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "text") e.textContent = v;
      else if (k === "on") Object.entries(v).forEach(([ev, fn]) => e.addEventListener(ev, fn));
      else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
    }
    (Array.isArray(kids) ? kids : [kids]).forEach((c) => c && e.append(c));
    return e;
  }

  /** "rrggbbaa" (or "rrggbb") -> [r, g, b, a] in 0..1. */
  function rgba(hex) {
    const h = String(hex || "").replace("#", "");
    const n = (i) => parseInt(h.substr(i, 2), 16) / 255;
    if (!/^[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(h)) return [0, 0, 0, 1];
    return [n(0), n(2), n(4), h.length === 8 ? n(6) : 1];
  }
  function hex2(v) { return Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, "0"); }
  function toHex(c) { return hex2(c[0]) + hex2(c[1]) + hex2(c[2]) + hex2(c[3] == null ? 1 : c[3]); }
  function css(c) { return `rgba(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)},${c[3] == null ? 1 : c[3]})`; }
  function lerp(a, b, t) { return a + (b - a) * t; }
  // Godot's Color.lightened / darkened / get_luminance, as Stream Rooms uses them for names.
  function lightened(c, a) { return [c[0] + (1 - c[0]) * a, c[1] + (1 - c[1]) * a, c[2] + (1 - c[2]) * a, c[3]]; }
  function darkened(c, a) { return [c[0] * (1 - a), c[1] * (1 - a), c[2] * (1 - a), c[3]]; }
  function luminance(c) { return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; }

  function bubbleStyle(over) { return { ...BUBBLE_DEFAULTS, ...(over || {}) }; }
  function figureStyle(over) { return { ...FIGURE_DEFAULTS, ...(over || {}) }; }
  function saved(kind) { return (looks.saved && looks.saved[kind]) || {}; }
  /** The bubble style Stream Rooms uses now (Light / Dark presets, or the custom one). */
  function bubbleInUse() {
    if (looks.bubble_theme === "custom") return bubbleStyle(looks.bubble);
    return bubbleStyle(BUBBLE_PRESETS[looks.bubble_theme === "dark" ? "Dark" : "Light"]);
  }

  // ── Saving ───────────────────────────────────────────────────────────────
  /** Called after every change: redraws the preview now, saves after SAVE_DELAY_MS. */
  function changed() {
    drawPreview();
    status("Saving…");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, SAVE_DELAY_MS);
  }

  async function save() {
    try {
      const body = { bubble_theme: looks.bubble_theme, bubble: looks.bubble, silhouette: looks.silhouette, saved: looks.saved, groups: looks.groups };
      const res = await api("/api/admin/audience-looks", { method: "PUT", body: JSON.stringify(body) });
      pictures = res.pictures || {};
      status("Saved. Stream Rooms shows it straight away while it's connected to Core.");
    } catch (e) {
      status("Couldn't save: " + e.message, false);
    }
  }

  // ── Loading ──────────────────────────────────────────────────────────────
  async function open() {
    if (!built) build();
    try {
      const [got, media] = await Promise.all([api("/api/admin/audience-looks"), api("/api/admin/media")]);
      looks = got;
      pictures = got.pictures || {};
      delete looks.pictures;
      library = (media.files || []).filter((f) => f.kind === "image" && PICTURE_EXTS.includes(String(f.ext).toLowerCase()));
      refresh();
      status("");
    } catch (e) {
      status("Couldn't load the looks: " + e.message, false);
    }
  }

  /** Re-read every control from `looks` (after loading, picking a preset, or a list change). */
  function refresh() {
    if (!looks) return;
    refreshBubbles();
    refreshFigures();
    refreshGroups();
    drawPreview();
  }

  // ── Building the controls ────────────────────────────────────────────────
  // Every control gets a title (the dashboard's tooltip), like the rest of the dashboard.
  function row(label, input, tip) {
    input.title = tip;
    return el("label", { class: "looks-row", title: tip }, [el("span", { text: label }), input]);
  }

  /** A slider bound to a key of a style. get(): the style object being edited; scale: shown value = value x scale. */
  function slider(get, key, label, lo, hi, step, unit, tip, scale = 1) {
    const r = el("input", { type: "range", min: lo, max: hi, step });
    const out = el("output", { class: "looks-val" });
    const show = () => { out.textContent = Math.round(Number(r.value) * scale * 10) / 10 + unit; };
    r.addEventListener("input", () => { get()[key] = Number(r.value); show(); changed(); });
    const wrap = el("span", { class: "looks-slider" }, [r, out]);
    wrap.sync = (style) => { r.value = style[key]; show(); };
    const line = row(label, wrap, tip);
    r.title = tip;
    line.sync = wrap.sync;
    return line;
  }

  function select(get, key, label, options, tip, number = false) {
    const s = el("select");
    options.forEach(([v, t]) => s.append(el("option", { value: String(v), text: t })));
    s.addEventListener("change", () => { get()[key] = number ? Number(s.value) : s.value; changed(); refreshEnabled(); });
    const line = row(label, s, tip);
    line.sync = (style) => { s.value = String(style[key]); };
    return line;
  }

  function check(get, key, label, tip) {
    const c = el("input", { type: "checkbox" });
    c.addEventListener("change", () => { get()[key] = c.checked; changed(); });
    const line = el("label", { class: "check looks-check", title: tip }, [c, " " + label]);
    c.title = tip;
    line.sync = (style) => { c.checked = !!style[key]; };
    return line;
  }

  /** A colour picker, with a see-through slider when alpha is true. */
  function color(get, key, label, alpha, tip) {
    const pick = el("input", { type: "color" });
    const a = el("input", { type: "range", min: 0, max: 1, step: 0.01, class: "looks-alpha", title: "How solid it is (left = see-through)." });
    const write = () => { get()[key] = pick.value.slice(1) + hex2(alpha ? Number(a.value) : 1); changed(); };
    pick.addEventListener("input", write);
    a.addEventListener("input", write);
    const wrap = el("span", { class: "looks-color" }, alpha ? [pick, a] : [pick]);
    const line = row(label, wrap, tip);
    pick.title = tip;
    line.sync = (style) => { const c = rgba(style[key]); pick.value = "#" + toHex(c).slice(0, 6); a.value = c[3]; };
    return line;
  }

  function button(text, tip, fn) {
    return el("button", { type: "button", title: tip, text, on: { click: fn } });
  }

  const bubbleCtrls = [];
  const figureCtrls = [];
  let bubblePresetSel;
  let themeSel;
  let figPresetSel;
  let pictureSel;
  let groupRows = [];

  function build() {
    built = true;
    buildBubbles($("looks-bubbles"));
    buildFigures($("looks-figures"));
    buildGroupsHead($("looks-groups"));
  }

  // ── Bubbles ──────────────────────────────────────────────────────────────
  function buildBubbles(box) {
    // Editing any bubble control switches Stream Rooms to the custom style (as its editor did).
    const edit = () => {
      if (looks.bubble_theme !== "custom") {
        looks.bubble = { ...bubbleInUse() };
        looks.bubble_theme = "custom";
        themeSel.value = "custom";
      }
      return looks.bubble;
    };
    themeSel = el("select");
    [["light", "Light"], ["dark", "Dark"], ["custom", "My own style (below)"]].forEach(([v, t]) => themeSel.append(el("option", { value: v, text: t })));
    themeSel.addEventListener("change", () => {
      if (themeSel.value === "custom" && !Object.keys(looks.bubble || {}).length) looks.bubble = { ...bubbleInUse() };
      looks.bubble_theme = themeSel.value;
      refreshBubbles();
      changed();
    });
    box.append(row("Bubble colours", themeSel,
      "Light and Dark are the ready-made looks. My own style uses the settings below; changing any of them switches to it."));

    bubblePresetSel = el("select");
    bubblePresetSel.addEventListener("change", () => {
      const name = bubblePresetSel.value;
      if (!name) return;
      const own = saved("bubble")[name];
      if (!own && (name === "Light" || name === "Dark")) {
        looks.bubble_theme = name.toLowerCase();     // the plain Light / Dark looks
      } else {
        looks.bubble = bubbleStyle(own || BUBBLE_PRESETS[name]);
        looks.bubble_theme = "custom";
      }
      refreshBubbles();
      changed();
    });
    box.append(el("div", { class: "looks-presets" }, [
      row("Start from", bubblePresetSel, "Start from a ready-made look or one you saved. You can change anything afterwards."),
      button("Save as…", "Keep the look you have now as a preset of your own, under a name you pick.", () => savePreset("bubble")),
      button("Delete", "Delete the picked preset of your own (asks first). The ready-made ones can't be deleted.", () => deletePreset("bubble")),
    ]));

    const g = edit;
    const add = (c) => { bubbleCtrls.push(c); box.append(c); };
    add(select(g, "shape", "Shape", BUBBLE_SHAPES, "Each chatter's own: everyone keeps the shape picked from their name (so the bubbles differ). Or one shape for everyone.", true));
    add(slider(g, "roundness", "Corner roundness", 0, 60, 1, "", "How round the corners of the box shapes are. 0 = square corners."));
    add(select(g, "tail", "Tail", [["left", "Left"], ["middle", "Middle"], ["right", "Right"], ["none", "No tail"]], "Where the pointer under the bubble sits."));
    box.append(el("h4", { class: "looks-head", text: "Colours" }));
    add(color(g, "fill", "Fill", true, "The bubble's colour. The second slider makes it see-through."));
    add(slider(g, "fill_mix", "Chatter colour in fill", 0, 0.6, 0.01, "%", "How much of each chatter's colour mixes into the fill. 0 = the same fill for everyone.", 100));
    add(color(g, "text", "Text", false, "The colour of the message."));
    add(select(g, "name_mode", "Name", [["chatter", "Chatter's colour"], ["fixed", "One colour (below)"]], "The chatter's name on top: in their own colour (made darker or lighter so it reads on the fill), or one colour for everyone."));
    add(color(g, "name_color", "Name colour", false, "The name colour when Name is One colour."));
    add(select(g, "outline_mode", "Outline", [["chatter", "Chatter's colour"], ["fixed", "One colour (below)"]], "The line around the bubble: in the chatter's colour, or one colour for everyone."));
    add(color(g, "outline_color", "Outline colour", false, "The outline colour when Outline is One colour."));
    add(slider(g, "outline", "Outline width", 0, 16, 0.5, "", "How thick the line around the bubble is. 0 = no line."));
    add(color(g, "paid", "Paid", true, "Super Chats, Kicks and Bits (with Stream Rooms' Colour paid and highlighted messages on)."));
    add(color(g, "highlighted", "Highlighted", true, "Twitch messages highlighted with channel points (with Colour paid and highlighted messages on)."));
    box.append(el("h4", { class: "looks-head", text: "Text" }));
    add(slider(g, "text_size", "Text size", 16, 56, 1, "", "Size of the message text. The name, replies and emotes grow and shrink with it."));
    add(check(g, "bold", "Bold letters", "Thicker letters, easier to read from far away."));
    add(slider(g, "width", "Text width", 200, 640, 10, "", "How wide the text gets before it wraps to a new line. Narrower = taller bubbles."));
  }

  function refreshBubbles() {
    themeSel.value = looks.bubble_theme;
    const st = bubbleInUse();
    bubbleCtrls.forEach((c) => c.sync(st));
    bubblePresetSel.innerHTML = "";
    bubblePresetSel.append(el("option", { value: "", text: "Pick a preset…" }));
    const names = Object.keys(BUBBLE_PRESETS).concat(Object.keys(saved("bubble")).filter((n) => !BUBBLE_PRESETS[n]));
    names.forEach((n) => bubblePresetSel.append(el("option", { value: n, text: saved("bubble")[n] ? n + " (mine)" : n })));
    refreshEnabled();
  }

  // ── Silhouettes ──────────────────────────────────────────────────────────
  function buildFigures(box) {
    const g = () => (looks.silhouette = looks.silhouette || {});
    figPresetSel = el("select");
    figPresetSel.addEventListener("change", () => {
      const own = saved("silhouette")[figPresetSel.value];
      if (!own) return;
      looks.silhouette = figureStyle(own);
      refreshFigures();
      changed();
    });
    box.append(el("div", { class: "looks-presets" }, [
      row("Saved", figPresetSel, "Silhouette looks you saved. Picking one makes it everyone's silhouette."),
      button("Save as…", "Keep this silhouette look as a preset of your own, under a name you pick (for the Groups page too).", () => savePreset("silhouette")),
      button("Delete", "Delete the picked saved look (asks first).", () => deletePreset("silhouette")),
    ]));

    const shapes = Object.entries(FIGURE_SHAPES).concat([["custom", "My own picture"]]);
    const add = (c) => { figureCtrls.push(c); box.append(c); };
    add(select(g, "shape", "Shape", shapes, "The figure everyone sits as. My own picture uses the picture picked below."));

    // Picture: a stored file. Picking or uploading one switches the shape to My own picture.
    pictureSel = el("select");
    pictureSel.addEventListener("change", () => usePicture(pictureSel.value));
    const one = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif", hidden: true });
    one.addEventListener("change", async () => {
      const files = [...one.files];
      one.value = "";
      if (!files.length) return;
      const entry = await upload(files[0]);
      if (entry) await usePicture(entry.name);
    });
    const many = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif", multiple: true, hidden: true });
    many.addEventListener("change", async () => {
      const files = [...many.files];
      many.value = "";
      if (files.length) addMany(files);
    });
    box.append(row("Picture", pictureSel, "Your own silhouette picture, from Stored files. A see-through PNG works best; a picture with no see-through parts is read as a dark shape on a light background."));
    box.append(el("div", { class: "asset-actions looks-buttons" }, [
      button("Upload a picture…", "Pick a picture (PNG, JPG, WebP or an animated GIF) from this PC. It goes to Stored files and becomes everyone's silhouette. A GIF moves in Stream Rooms when Paint is the picture itself.", () => one.click()),
      button("Add many pictures…", "Pick several pictures at once. Each one is saved as a look of your own (named after its file), ready for the Groups page's Random mix. The audience doesn't change until you use them.", () => many.click()),
      button("Back to classic", "The original head-and-shoulders silhouette, in the chatter's colour.", () => {
        looks.silhouette = {};
        refreshFigures();
        changed();
      }),
      one, many,
    ]));
    add(select(g, "paint", "Painted", [["chatter", "In the chatter's colour"], ["fixed", "One colour for everyone"], ["picture", "The picture's own colours"]],
      "In the chatter's colour: a dark body with an outline in their colour (like the classic look). One colour: the same, in the colour below. The picture's own colours: only for your own picture, shown as it is."));
    add(color(g, "color", "Colour", false, "The colour for Painted: One colour for everyone."));
    add(slider(g, "brightness", "Brightness", 0.4, 1.6, 0.05, "%", "Darker or brighter silhouettes (name tags keep their colour).", 100));
    add(slider(g, "size", "Size", 0.7, 1.4, 0.05, "%", "How big the silhouettes are. Name tags and bubbles move up with them.", 100));
    add(check(g, "crowd", "The filler crowd uses it too", "Filler people (Lecture Hall tiers, balcony, gallery) take the same shape and size. Off: they stay the classic silhouette."));
    box.append(el("h4", { class: "looks-head", text: "Where the chatter's picture sits (your own picture)" }));
    add(slider(g, "head_x", "Across", 0, 1, 0.01, "%", "Left to right: where the middle of the chatter's profile picture goes on your picture.", 100));
    add(slider(g, "head_y", "Down", 0, 1, 0.01, "%", "Top to bottom: where the middle of the chatter's profile picture goes.", 100));
    add(slider(g, "head_r", "Picture size", 0.05, 0.5, 0.01, "%", "How big the chatter's round profile picture is (a share of the picture's width).", 100));
    box.append(el("p", { class: "hint", text: "Chatter pictures only show with Stream Rooms' Chatter pictures on (Audience tab)." }));
  }

  function refreshFigures() {
    const f = figureStyle(looks.silhouette);
    figureCtrls.forEach((c) => c.sync(f));
    figPresetSel.innerHTML = "";
    const own = Object.keys(saved("silhouette"));
    figPresetSel.append(el("option", { value: "", text: own.length ? "Pick a saved look…" : "(none saved yet)" }));
    own.forEach((n) => figPresetSel.append(el("option", { value: n, text: n })));
    pictureSel.innerHTML = "";
    pictureSel.append(el("option", { value: "", text: library.length ? "Pick a stored picture…" : "(no pictures stored yet: upload one)" }));
    library.forEach((m) => pictureSel.append(el("option", { value: m.name, text: m.name })));
    const file = String(f.file || "");
    pictureSel.value = file.startsWith(MEDIA) && library.some((m) => m.name === file.slice(MEDIA.length)) ? file.slice(MEDIA.length) : "";
    refreshEnabled();
  }

  /** Grey out controls that do nothing with the current choices. */
  function refreshEnabled() {
    if (!looks) return;
    const b = bubbleInUse();
    const f = figureStyle(looks.silhouette);
    const on = (ctrl, yes) => ctrl.querySelectorAll("input,select").forEach((i) => { i.disabled = !yes; });
    const find = (list, label) => list.find((c) => c.textContent.startsWith(label));
    const nameCol = find(bubbleCtrls, "Name colour");
    const outCol = find(bubbleCtrls, "Outline colour");
    const round = find(bubbleCtrls, "Corner roundness");
    if (nameCol) on(nameCol, b.name_mode === "fixed");
    if (outCol) on(outCol, b.outline_mode === "fixed");
    if (round) on(round, Number(b.shape) <= 0);
    const own = f.shape === "custom";
    ["Across", "Down", "Picture size"].forEach((l) => { const c = find(figureCtrls, l); if (c) on(c, own); });
    const col = find(figureCtrls, "Colour");
    if (col) on(col, f.paint === "fixed");
  }

  /** A stored picture as everyone's silhouette, with the chatter-picture spot guessed from it. */
  async function usePicture(name) {
    if (!name) return;
    const entry = library.find((m) => m.name === name);
    if (!entry) return;
    const f = (looks.silhouette = { ...figureStyle(looks.silhouette), shape: "custom", file: MEDIA + name });
    const fit = await fitted(entry.url);
    if (fit) Object.assign(f, guessHead(fit));
    if (f.paint === "picture" && !fit) f.paint = "chatter";
    refreshFigures();
    changed();
  }

  /** Upload one picture to Stored files; returns its entry (or null, with the reason on the status line). */
  async function upload(file) {
    try {
      const data = await new Promise((ok, bad) => {
        const r = new FileReader();
        r.onload = () => ok(r.result);
        r.onerror = () => bad(new Error("couldn't read the file"));
        r.readAsDataURL(file);
      });
      const res = await api("/api/admin/media", { method: "POST", body: JSON.stringify({ data, filename: file.name }) });
      library = (res.files || []).filter((f) => f.kind === "image" && PICTURE_EXTS.includes(String(f.ext).toLowerCase()));
      return res.file;
    } catch (e) {
      status(`Couldn't upload ${file.name}: ${e.message}`, false);
      return null;
    }
  }

  /** "Add many pictures…": each picture to Stored files and a saved look named after it. */
  async function addMany(files) {
    let added = 0;
    looks.saved = looks.saved || {};
    looks.saved.silhouette = looks.saved.silhouette || {};
    for (const file of files) {
      status(`Adding ${file.name}…`);
      const entry = await upload(file);
      if (!entry) continue;
      const fit = await fitted(entry.url);
      const name = entry.name.replace(/[|]/g, " ").slice(0, 40);
      looks.saved.silhouette[name] = { ...figureStyle({}), shape: "custom", file: MEDIA + entry.name, ...(fit ? guessHead(fit) : {}) };
      added += 1;
    }
    refresh();
    changed();
    if (added) setTimeout(() => status(`Added ${added} of ${files.length} pictures as saved looks. Use them on the Groups page (Random mix).`), SAVE_DELAY_MS + 600);
  }

  // ── Saved presets ────────────────────────────────────────────────────────
  function savePreset(kind) {
    const name = String(prompt("Name for this look (saving under a name that's already yours replaces it):") || "").replace(/[|]/g, " ").trim().slice(0, 40);
    if (!name) return;
    looks.saved = looks.saved || {};
    looks.saved[kind] = looks.saved[kind] || {};
    looks.saved[kind][name] = kind === "bubble" ? { ...bubbleInUse() } : { ...figureStyle(looks.silhouette) };
    refresh();
    changed();
  }

  function deletePreset(kind) {
    const sel = kind === "bubble" ? bubblePresetSel : figPresetSel;
    const name = sel.value;
    if (!name || !saved(kind)[name]) {
      status("Pick one of your own saved looks first.", false);
      return;
    }
    if (!confirm(`Delete the look "${name}"? Groups using it go back to the main style.`)) return;
    delete looks.saved[kind][name];
    // groups that used it go back to the main style (a mix just loses that one)
    for (const [gid, g] of Object.entries(looks.groups || {})) {
      if (kind === "bubble" && g.bubble === name) delete g.bubble;
      if (kind === "silhouette" && g.silhouette) {
        const left = g.silhouette.split(MIX_SEP).filter((n) => n && n !== name);
        if (left.length) g.silhouette = left.join(MIX_SEP);
        else delete g.silhouette;
      }
      if (!g.bubble && !g.silhouette) delete looks.groups[gid];
    }
    refresh();
    changed();
  }

  // ── Groups ───────────────────────────────────────────────────────────────
  function buildGroupsHead(box) {
    box.append(el("p", { class: "hint", text: "Give mods, VIPs, subscribers or one platform their own look. Save a look on the Bubbles or Silhouettes page first (Save as…, or Add many pictures…), then pick it here. Someone in more than one group gets the first one in this list that has a look set (a mod who subscribes gets the Mods look). Everyone else covers whoever is left. Random mix gives each chatter in the group one of several silhouettes, and they keep it every time they chat." }));
    box.append(el("div", { id: "looks-group-grid", class: "looks-groups" }));
  }

  function refreshGroups() {
    const grid = $("looks-group-grid");
    grid.innerHTML = "";
    grid.append(el("strong", { text: "Group" }), el("strong", { text: "Bubble" }), el("strong", { text: "Silhouette" }));
    groupRows = [];
    const bubbleNames = Object.keys(BUBBLE_PRESETS).concat(Object.keys(saved("bubble")).filter((n) => !BUBBLE_PRESETS[n]));
    const figNames = Object.keys(FIGURE_SHAPES).map((id) => [id, FIGURE_SHAPES[id]])
      .concat(Object.keys(saved("silhouette")).map((n) => [n, n]));
    for (const [gid, label] of GROUPS) {
      const cur = (looks.groups || {})[gid] || {};
      const set = (kind, value) => {
        looks.groups = looks.groups || {};
        const g = { ...(looks.groups[gid] || {}) };
        if (value) g[kind] = value;
        else delete g[kind];
        if (Object.keys(g).length) looks.groups[gid] = g;
        else delete looks.groups[gid];
        changed();
      };
      const bs = el("select", { title: `The bubble look for ${label}. Main style = the same as everyone else.` });
      bs.append(el("option", { value: "", text: "Main style" }));
      bubbleNames.forEach((n) => bs.append(el("option", { value: n, text: n })));
      if (cur.bubble && !bubbleNames.includes(cur.bubble)) bs.append(el("option", { value: cur.bubble, text: cur.bubble + " (missing)" }));
      bs.value = cur.bubble || "";
      bs.addEventListener("change", () => set("bubble", bs.value));

      const fs = el("select", { title: `The silhouette for ${label}. Main style = the same as everyone else. Random mix gives each chatter one of several.` });
      fs.append(el("option", { value: "", text: "Main style" }));
      figNames.forEach(([v, t]) => fs.append(el("option", { value: v, text: t })));
      const isMix = String(cur.silhouette || "").includes(MIX_SEP);
      if (isMix) fs.append(el("option", { value: cur.silhouette, text: `Mix of ${cur.silhouette.split(MIX_SEP).filter(Boolean).length}` }));
      else if (cur.silhouette && !figNames.some(([v]) => v === cur.silhouette)) fs.append(el("option", { value: cur.silhouette, text: cur.silhouette + " (missing)" }));
      fs.append(el("option", { value: "|mix|", text: "Random mix…" }));
      fs.value = cur.silhouette || "";
      const mixBox = el("div", { class: "looks-mix", hidden: !isMix });
      fs.addEventListener("change", () => {
        if (fs.value === "|mix|") {
          mixBox.hidden = false;
          showMix(((looks.groups || {})[gid] || {}).silhouette || "");
          return;
        }
        mixBox.hidden = !fs.value.includes(MIX_SEP);
        set("silhouette", fs.value);
      });
      // Random mix: a tick per silhouette look; two or more ticked make the mix.
      const picked = new Set(isMix ? cur.silhouette.split(MIX_SEP).filter(Boolean) : []);
      // the list shows a mix as "Mix of N" (an option that holds the joined value)
      const showMix = (value) => {
        [...fs.options].filter((o) => o.value.includes(MIX_SEP) && o.value !== "|mix|").forEach((o) => o.remove());
        if (value.includes(MIX_SEP)) fs.insertBefore(el("option", { value, text: `Mix of ${value.split(MIX_SEP).length}` }), fs.lastChild);
        fs.value = value;
      };
      mixBox.append(el("p", { class: "hint", text: `Tick the silhouettes to mix for ${label}. Each chatter gets one of them and keeps it.` }));
      figNames.forEach(([v, t]) => {
        const c = el("input", { type: "checkbox", title: "Put this silhouette in the mix." });
        c.checked = picked.has(v);
        c.addEventListener("change", () => {
          if (c.checked) picked.add(v);
          else picked.delete(v);
          const list = figNames.map(([n]) => n).filter((n) => picked.has(n));
          const value = list.length >= 2 ? list.join(MIX_SEP) : list.length === 1 ? list[0] : "";
          set("silhouette", value);
          showMix(value);
        });
        mixBox.append(el("label", { class: "check", title: "Put this silhouette in the mix." }, [c, " " + t]));
      });
      grid.append(el("span", { class: "looks-group-name", text: label }), bs, el("div", {}, [fs, mixBox]));
      groupRows.push(gid);
    }
  }

  // ── Pictures: fitting and the silhouette version ─────────────────────────
  const fitCache = {};   // url -> Promise of {canvas (256 x 320 fitted picture), shape (its silhouette version), top}

  /**
   * A stored picture fitted the way Stream Rooms imports it (AudienceStyle.import_picture): cut
   * to its visible part, scaled into 256 x 320 standing on the bottom edge. A picture without
   * see-through pixels is read as a dark shape on a light background.
   */
  function fitted(url) {
    if (!fitCache[url]) {
      fitCache[url] = new Promise((done) => {
        const img = new Image();
        img.onload = () => {
          try { done(fitImage(img)); } catch (_) { done(null); }
        };
        img.onerror = () => done(null);
        img.src = url;
      });
    }
    return fitCache[url];
  }

  function fitImage(img) {
    let w = img.naturalWidth;
    let h = img.naturalHeight;
    const k0 = Math.min(1, 1024 / Math.max(w, h));
    w = Math.max(1, Math.round(w * k0));
    h = Math.max(1, Math.round(h * k0));
    const src = el("canvas", { width: w, height: h });
    const sc = src.getContext("2d");
    sc.drawImage(img, 0, 0, w, h);
    const d = sc.getImageData(0, 0, w, h);
    const px = d.data;
    let seeThrough = false;
    for (let i = 3; i < px.length; i += 4) if (px[i] < 255) { seeThrough = true; break; }
    if (!seeThrough) {
      for (let i = 0; i < px.length; i += 4) {
        const l = (0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]) / 255;
        px[i + 3] = Math.round(Math.max(0, Math.min(1, (0.75 - l) * 4)) * 255);
      }
      sc.putImageData(d, 0, 0);
    }
    let x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      if (px[(y * w + x) * 4 + 3] > 0) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    }
    if (x1 - x0 < 3 || y1 - y0 < 3) return null;
    const uw = x1 - x0 + 1;
    const uh = y1 - y0 + 1;
    const k = Math.min(FIG_W / uw, FIG_H / uh);
    const pw = Math.max(1, Math.round(uw * k));
    const ph = Math.max(1, Math.round(uh * k));
    const canvas = el("canvas", { width: FIG_W, height: FIG_H });
    const c = canvas.getContext("2d");
    c.drawImage(src, x0, y0, uw, uh, Math.floor((FIG_W - pw) / 2), FIG_H - ph, pw, ph);
    return { canvas, shape: outlineVersion(canvas), top: FIG_H - ph };
  }

  /** Dark body with a white rim RIM_PX wide inside the edge (AudienceStyle._outline_version). */
  function outlineVersion(canvas) {
    const c = canvas.getContext("2d");
    const d = c.getImageData(0, 0, FIG_W, FIG_H);
    const px = d.data;
    const solid = new Uint8Array(FIG_W * FIG_H);
    for (let i = 0; i < solid.length; i++) solid[i] = px[i * 4 + 3] > 127 ? 1 : 0;
    const across = new Uint8Array(FIG_W * FIG_H);
    for (let y = 0; y < FIG_H; y++) for (let x = 0; x < FIG_W; x++) {
      let ok = 1;
      for (let dx = -RIM_PX; dx <= RIM_PX; dx++) {
        const xx = x + dx;
        if (xx < 0 || xx >= FIG_W || !solid[y * FIG_W + xx]) { ok = 0; break; }
      }
      across[y * FIG_W + x] = ok;
    }
    const out = new ImageData(FIG_W, FIG_H);
    for (let y = 0; y < FIG_H; y++) for (let x = 0; x < FIG_W; x++) {
      const i = (y * FIG_W + x) * 4;
      if (px[i + 3] <= 0) continue;
      let inner = true;
      for (let dy = -RIM_PX; dy <= RIM_PX; dy++) {
        const yy = y + dy;
        if (yy < 0 || yy >= FIG_H || !across[yy * FIG_W + x]) { inner = false; break; }
      }
      const g = Math.round((inner ? BODY_GREY : 1) * 255);
      out.data[i] = out.data[i + 1] = out.data[i + 2] = g;
      out.data[i + 3] = px[i + 3];
    }
    const res = el("canvas", { width: FIG_W, height: FIG_H });
    res.getContext("2d").putImageData(out, 0, 0);
    return res;
  }

  /** Where the head probably is on a fitted picture: the middle of its top part (AudienceStyle.guess_head). */
  function guessHead(fit) {
    const r = 0.19 * FIG_W;
    return { head_x: 0.5, head_y: Math.round(((fit.top + r * 1.15) / FIG_H) * 100) / 100, head_r: 0.19 };
  }

  // ── Built-in silhouettes (AudienceStyle._layers / _draw_shape) ───────────
  const shapeCache = {};
  const len = (x, y) => Math.hypot(x, y);
  const circle = (px, py, cx, cy, r) => len(px - cx, py - cy) - r;
  const ellipse = (px, py, cx, cy, rx, ry) => (len((px - cx) / rx, (py - cy) / ry) - 1) * Math.min(rx, ry);
  function roundBox(px, py, cx, cy, hx, hy, rad) {
    const qx = Math.abs(px - cx) - hx + rad;
    const qy = Math.abs(py - cy) - hy + rad;
    return len(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - rad;
  }
  function smoothUnion(a, b, k) {
    const h = Math.max(0, Math.min(1, 0.5 + 0.5 * (b - a) / k));
    return lerp(b, a, h) - k * h * (1 - h);
  }
  function polygon(px, py, v) {
    let d = (px - v[0][0]) ** 2 + (py - v[0][1]) ** 2;
    let s = 1;
    for (let i = 0, j = v.length - 1; i < v.length; j = i, i++) {
      const ex = v[j][0] - v[i][0], ey = v[j][1] - v[i][1];
      const wx = px - v[i][0], wy = py - v[i][1];
      const t = Math.max(0, Math.min(1, (wx * ex + wy * ey) / (ex * ex + ey * ey)));
      d = Math.min(d, (wx - ex * t) ** 2 + (wy - ey * t) ** 2);
      const c1 = py >= v[i][1], c2 = py < v[j][1], c3 = ex * wy > ey * wx;
      if ((c1 && c2 && c3) || (!c1 && !c2 && !c3)) s = -s;
    }
    return s * Math.sqrt(d);
  }
  function layers(shape, x, y) {
    const shoulders = ellipse(x, y, 128, 352, 122, 160);
    switch (shape) {
      case "round": return [ellipse(x, y, 128, 362, 100, 150), circle(x, y, 128, 100, 76)];
      case "broad": return [roundBox(x, y, 128, 300, 128, 110, 70), circle(x, y, 128, 96, 52)];
      case "hood": return [smoothUnion(ellipse(x, y, 128, 112, 82, 94), shoulders, 22), circle(x, y, 128, 118, 52)];
      case "ears": {
        const head = circle(x, y, 128, 110, 58);
        const l = polygon(x, y, [[76, 92], [78, 26], [124, 58]]);
        const r = polygon(x, y, [[180, 92], [178, 26], [132, 58]]);
        return [shoulders, smoothUnion(head, Math.min(l, r), 10)];
      }
      case "bun": return [shoulders, smoothUnion(circle(x, y, 128, 110, 56), circle(x, y, 128, 42, 28), 18)];
      case "bot": {
        const head = roundBox(x, y, 128, 104, 62, 56, 14);
        const stick = roundBox(x, y, 128, 36, 4, 16, 2);
        const ball = circle(x, y, 128, 18, 12);
        return [roundBox(x, y, 128, 292, 112, 96, 30), Math.min(head, Math.min(stick, ball))];
      }
      default: return [shoulders, circle(x, y, 128, 94, 61)];
    }
  }

  /** A built-in shape as a 256 x 320 canvas: dark body, white rim (drawn once, then kept). */
  function shapeCanvas(shape) {
    if (shapeCache[shape]) return shapeCache[shape];
    const out = new ImageData(FIG_W, FIG_H);
    for (let y = 0; y < FIG_H; y++) for (let x = 0; x < FIG_W; x++) {
      const px = x + 0.5, py = y + 0.5;
      let col = 0, alpha = 0;
      const ds = layers(shape, px, py);
      for (let l = 0; l < ds.length; l++) {
        let d = ds[l];
        if (d > 1) continue;
        if (d > -RIM_PX - 2) {
          const gx = layers(shape, px + 1, py)[l] - d;
          const gy = layers(shape, px, py + 1)[l] - d;
          d /= Math.max(0.3, Math.min(3, len(gx, gy)));
        }
        const a = Math.max(0, Math.min(1, 0.5 - d));
        if (a <= 0) continue;
        const rim = Math.max(0, Math.min(1, d + RIM_PX + 0.5));
        const g = lerp(BODY_GREY, 1, rim);
        col = alpha > 0 ? lerp(col, g, a) : g;
        alpha = Math.max(alpha, a);
      }
      if (alpha > 0) {
        const i = (y * FIG_W + x) * 4;
        out.data[i] = out.data[i + 1] = out.data[i + 2] = Math.round(col * 255);
        out.data[i + 3] = Math.round(alpha * 255);
      }
    }
    const c = el("canvas", { width: FIG_W, height: FIG_H });
    c.getContext("2d").putImageData(out, 0, 0);
    return (shapeCache[shape] = c);
  }

  /** A silhouette picture multiplied by a colour (Stream Rooms' sprite modulate). */
  function tinted(src, c) {
    const out = el("canvas", { width: FIG_W, height: FIG_H });
    const x = out.getContext("2d");
    x.drawImage(src, 0, 0);
    x.globalCompositeOperation = "multiply";
    x.fillStyle = css([c[0], c[1], c[2], 1]);
    x.fillRect(0, 0, FIG_W, FIG_H);
    x.globalCompositeOperation = "destination-in";
    x.drawImage(src, 0, 0);
    return out;
  }

  // ── Preview ──────────────────────────────────────────────────────────────
  let drawToken = 0;

  /** Three made-up chatters with the bubble and silhouette looks as they are now. */
  async function drawPreview() {
    const cv = $("looks-preview");
    if (!cv || !looks) return;
    const me = ++drawToken;
    const f = figureStyle(looks.silhouette);
    let fit = null;
    if (f.shape === "custom") {
      const name = String(f.file || "").slice(MEDIA.length);
      const entry = library.find((m) => m.name === name);
      fit = entry ? await fitted(entry.url) : null;
      if (me !== drawToken) return;      // a newer draw started while the picture loaded
    }
    const ctx = cv.getContext("2d");
    const W = cv.width, H = cv.height;
    ctx.clearRect(0, 0, W, H);
    const bg = ctx.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, "#2a3140");
    bg.addColorStop(1, "#141821");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);
    const st = bubbleInUse();
    const slot = W / SAMPLES.length;
    SAMPLES.forEach(([name, hex, text, tint], i) => {
      const chatter = rgba(hex.slice(1));
      // silhouette: 190 preview pixels tall at size 1, standing on the bottom edge
      const scale = (190 / FIG_H) * Number(f.size);
      const fw = FIG_W * scale, fh = FIG_H * scale;
      const fx = slot * i + slot / 2 - fw / 2, fy = H - fh;
      let pic = null;
      let head = FIGURE_HEADS[f.shape] || FIGURE_HEADS.classic;
      if (f.shape === "custom" && fit) {
        pic = f.paint === "picture" ? fit.canvas : fit.shape;
        head = [f.head_x * FIG_W, f.head_y * FIG_H, f.head_r * FIG_W];
      } else if (f.shape !== "custom") {
        pic = shapeCanvas(f.shape);
      } else {
        pic = shapeCanvas("classic");
      }
      const b = Number(f.brightness);
      let paint = chatter;
      if (f.paint === "fixed") paint = rgba(f.color);
      if (f.paint === "picture" && f.shape === "custom" && fit) paint = [1, 1, 1, 1];
      const lit = [Math.min(1, paint[0] * b), Math.min(1, paint[1] * b), Math.min(1, paint[2] * b), 1];
      ctx.drawImage(lit[0] === 1 && lit[1] === 1 && lit[2] === 1 ? pic : tinted(pic, lit), fx, fy, fw, fh);
      // the light circle: where the chatter's profile picture goes
      ctx.beginPath();
      ctx.arc(fx + head[0] * scale, fy + head[1] * scale, head[2] * scale, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(255,255,255,0.35)";
      ctx.fill();
      drawBubble(ctx, st, name, text, chatter, tint, i, slot * i + slot / 2, fy - 6, slot - 12);
    });
    const note = $("looks-preview-note");
    if (note) note.textContent = f.shape === "custom" && !fit ? "That picture isn't in Stored files any more: Stream Rooms shows the classic silhouette." : "";
  }

  /** One speech bubble, laid out like SpeechBubble.set_content and drawn like its _draw. */
  function drawBubble(ctx, st, speaker, text, chatter, tint, index, tipX, tipY, maxW) {
    const k = 0.6;                  // bubble pixels -> preview pixels (made smaller to fit a slot)
    const size = Number(st.text_size);
    const nameSize = Math.round(24 * size / 30);
    const font = (px) => `${st.bold ? "700" : "400"} ${px}px system-ui, "Segoe UI", sans-serif`;
    // measure and wrap the text at the style's width
    const m = document.createElement("canvas").getContext("2d");
    m.font = font(size);
    const lines = [];
    let line = "";
    text.split(" ").forEach((w) => {
      const t = line ? line + " " + w : w;
      if (m.measureText(t).width > Number(st.width) && line) { lines.push(line); line = w; } else line = t;
    });
    if (line) lines.push(line);
    let usedW = Math.max(...lines.map((l) => m.measureText(l).width));
    m.font = font(nameSize);
    usedW = Math.min(Number(st.width), Math.max(60, usedW, m.measureText(speaker).width));
    const innerW = usedW + 2;
    const innerH = nameSize * 1.25 + lines.length * size * 1.25;
    const shape = Number(st.shape) < 0 ? index % 4 : Number(st.shape);
    const grow = shape === 1 ? [1.36, 1.42] : shape === 4 ? [1.42, 1.5] : [1, 1];
    const bw = innerW * grow[0] + 40, bh = innerH * grow[1] + 40;
    const tailAt = st.tail in TAIL_SPOTS ? TAIL_SPOTS[st.tail] : -1;
    const tailH = tailAt >= 0 ? 30 : 4;
    // fit the bubble into its slot in the preview
    const s = Math.min(k, maxW / (bw + 12));
    ctx.save();
    const left = tipX - (tailAt >= 0 ? bw * tailAt : bw / 2) * s;
    ctx.translate(Math.max(4, Math.min(ctx.canvas.width - bw * s - 4, left)), tipY - (bh + tailH) * s);
    ctx.scale(s, s);
    const base = rgba(st.fill);
    const dark = luminance(base) < 0.5;
    let fill = [lerp(base[0], chatter[0], st.fill_mix), lerp(base[1], chatter[1], st.fill_mix), lerp(base[2], chatter[2], st.fill_mix), base[3]];
    if (tint) fill = rgba(st[tint]);
    const outline = Number(st.outline);
    const outCol = st.outline_mode === "chatter" ? chatter : rgba(st.outline_color);
    const pts = bodyPoints(shape, 0, 0, bw, bh, Number(st.roundness));
    const path = new Path2D();
    pts.forEach(([x, y], i) => (i ? path.lineTo(x, y) : path.moveTo(x, y)));
    path.closePath();
    let tail = null;
    if (tailAt >= 0) {
      let l = bw * Math.max(0.08, Math.min(0.78, tailAt + 0.04));
      let r = bw * Math.max(0.22, Math.min(0.92, tailAt + 0.22));
      if (tailAt > 0.6) { l = bw * Math.max(0.08, Math.min(0.78, tailAt - 0.22)); r = bw * Math.max(0.22, Math.min(0.92, tailAt - 0.04)); }
      tail = [[l, bh - outline - 10], [r, bh - outline - 10], [bw * tailAt, bh + 30]];
    }
    if (outline > 0) {
      ctx.lineWidth = outline * 2;
      ctx.lineJoin = "round";
      ctx.strokeStyle = css(outCol);
      ctx.stroke(path);
      if (tail) {
        ctx.beginPath();
        ctx.moveTo(tail[0][0] - 2, tail[0][1] + 6);
        ctx.lineTo(tail[2][0], tail[2][1]);
        ctx.lineTo(tail[1][0] + 2, tail[1][1] + 6);
        ctx.stroke();
      }
    }
    ctx.fillStyle = css(fill);
    ctx.fill(path);
    if (tail) {
      ctx.beginPath();
      tail.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.closePath();
      ctx.fill();
    }
    // name, then the message
    let nameCol = dark ? lightened(chatter, 0.4) : darkened(chatter, 0.45);
    if (st.name_mode === "fixed") nameCol = rgba(st.name_color);
    const tx = bw / 2 - innerW / 2, ty = bh / 2 - innerH / 2;
    ctx.textBaseline = "top";
    ctx.font = font(nameSize);
    ctx.fillStyle = css(nameCol);
    ctx.fillText(speaker, tx, ty);
    ctx.font = font(size);
    ctx.fillStyle = css(rgba(st.text));
    lines.forEach((l, i) => ctx.fillText(l, tx, ty + nameSize * 1.25 + i * size * 1.25));
    ctx.restore();
  }

  /** The bubble body's outline for each shape (SpeechBubble._shape_points). */
  function bodyPoints(shape, x0, y0, w, h, roundness) {
    const cx = x0 + w / 2, cy = y0 + h / 2, x1 = x0 + w, y1 = y0 + h;
    const pts = [];
    if (shape === 1) {
      for (let i = 0; i < 48; i++) { const a = (Math.PI * 2 * i) / 48; pts.push([cx + Math.cos(a) * w / 2, cy + Math.sin(a) * h / 2]); }
    } else if (shape === 2) {
      const tilt = Math.min(h * 0.12, 14);
      pts.push([x0, y0 + tilt], [x1, y0], [x1, y1], [x0, y1]);
    } else if (shape === 3) {
      const n = 10, bow = Math.min(h, w) * 0.06;
      for (let i = 0; i <= n; i++) { const t = i / n; pts.push([lerp(x0, x1, t), y0 + Math.sin(t * Math.PI) * bow]); }
      for (let i = 1; i <= n; i++) { const t = i / n; pts.push([x1 - Math.sin(t * Math.PI) * bow * 0.6, lerp(y0, y1, t)]); }
      for (let i = 1; i <= n; i++) { const t = i / n; pts.push([lerp(x1, x0, t), y1 - Math.sin(t * Math.PI) * bow]); }
      for (let i = 1; i < n; i++) { const t = i / n; pts.push([x0 + Math.sin(t * Math.PI) * bow * 0.6, lerp(y1, y0, t)]); }
    } else if (shape === 4) {
      for (let i = 0; i < 120; i++) {
        const a = (Math.PI * 2 * i) / 120;
        const bump = (1 + 0.07 * Math.abs(Math.sin(a * 6))) / 1.07;
        pts.push([cx + Math.cos(a) * w / 2 * bump, cy + Math.sin(a) * h / 2 * bump]);
      }
    } else {
      const rad = Math.min(roundness, Math.min(w, h) * 0.45);
      if (rad < 1) return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
      const corners = [[x0 + rad, y0 + rad, Math.PI], [x1 - rad, y0 + rad, Math.PI * 1.5], [x1 - rad, y1 - rad, 0], [x0 + rad, y1 - rad, Math.PI * 0.5]];
      corners.forEach(([ccx, ccy, a0]) => {
        for (let k = 0; k < 7; k++) { const a = a0 + (Math.PI / 2) * (k / 6); pts.push([ccx + Math.cos(a) * rad, ccy + Math.sin(a) * rad]); }
      });
    }
    return pts;
  }

  window.AudienceLooksPage = { open };
})();
