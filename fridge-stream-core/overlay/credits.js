/* Stream Core credits overlay engine (merged with the standalone Chat Credits engine).
   Every motion runs on one requestAnimationFrame loop (OBS/CEF drops CSS keyframe crawls).
   Star Wars: perspective + rotateX on #sw-world, translateY on #sw-track.
   Motion changes and Restart hard-reset so leftover transforms can't black-screen.
   Look / roster changes that don't change the motion re-render in place (no restart). */
(function () {
  "use strict";

  const PLATFORM_ORDER = ["twitch", "kick", "youtube", "manual"];
  const PLATFORM_LABEL = { twitch: "Twitch", kick: "Kick", youtube: "YouTube", manual: "Chat" };
  const CRAWL_MOTIONS = { crawl: 1, "crawl-down": 1, starwars: 1 };
  const PAGE_MOTIONS = { cards: 1, fade: 1, slides: 1, typewriter: 1 };
  const MOTION_ALIASES = { teletype: "typewriter", tty: "typewriter", nametape: "ticker", "name-tape": "ticker" };
  const MATRIX_GLYPHS = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789";

  const qs = new URLSearchParams(location.search);
  // Stream Core paths first; the standalone paths let this file also run under Chat Credits.
  const API_THEME = ["/api/credits/theme", "/api/theme"];
  const API_ROSTER = ["/api/credits/roster", "/api/roster"];
  const API_PLAY = ["/api/credits/play", "/api/play"];

  let theme = {};
  let roster = { chatters: [], count: 0 };
  let play = { playing: true, mode: "loop", freeze: false, generation: 0 };
  let rebuildTimer = 0;
  let lastRosterKey = "";
  let lastThemeKey = "";
  let lastMotion = "";
  let lastMotionFp = "";
  let castCache = null;
  let lastMode = "";

  const engine = {
    raf: 0,
    timers: [],
    y: 0,
    x: 0,
    startY: 0,
    endY: 0,
    linear: 0,
    lastTs: 0,
    running: false,
    gapUntil: 0,
    generation: -1,
    started: false,
    phase: "idle",
    motion: "crawl",
    cardIndex: 0,
    cardUntil: 0,
    endUntil: 0,
    loopGap: false,
    pageIndex: 0,
    pages: [],
    fading: false,
    typeLines: [],
    typeLine: 0,
    typeCol: 0,
    typeHoldUntil: 0,
    typeState: "idle",
    typeAcc: 0,
    matrix: null,
    observer: null,
  };

  // ---------------------------------------------------------------- helpers

  function $(id) {
    return document.getElementById(id);
  }

  function num(v, fallback) {
    if (v === null || v === undefined || v === "") return fallback;
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  function bool(v, fallback) {
    if (v === true || v === false) return v;
    if (v === "true") return true;
    if (v === "false") return false;
    return fallback;
  }

  function pick(a, b) {
    return a !== undefined && a !== null && a !== "" ? a : b;
  }

  function ease(t, kind) {
    const x = Math.max(0, Math.min(1, t));
    if (kind === "ease-in") return x * x;
    if (kind === "ease-out") return 1 - (1 - x) * (1 - x);
    if (kind === "ease-in-out") return x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;
    if (kind === "smooth") return x * x * (3 - 2 * x);
    return x;
  }

  function motionId(t) {
    t = t || theme;
    let m = String(t.motion || "crawl").toLowerCase();
    m = MOTION_ALIASES[m] || m;
    return CRAWL_MOTIONS[m] || PAGE_MOTIONS[m] || m === "ticker" || m === "matrix" ? m : "crawl";
  }

  // Core key first, standalone key as the fallback.
  function tiltDeg() {
    return num(pick(theme.tilt_deg, theme.sw_tilt_deg), 52);
  }

  function perspectivePx() {
    return num(pick(theme.perspective_px, theme.sw_perspective_px), 420);
  }

  function pageHoldMs() {
    return Math.max(800, num(pick(theme.page_duration_sec, theme.page_hold_sec), 4.5) * 1000);
  }

  function pageFadeMs() {
    const ms = theme.page_transition_ms != null
      ? num(theme.page_transition_ms, 700)
      : num(theme.page_fade_sec, 0.7) * 1000;
    return Math.max(80, ms);
  }

  function titleHoldMs() {
    return Math.max(0, num(theme.title_hold_sec, 0)) * 1000;
  }

  function loopGapMs() {
    return Math.max(0, num(theme.gap_after_loop_sec, 2.5)) * 1000;
  }

  function currentMode() {
    return play.mode || theme.mode || "loop";
  }

  function later(fn, ms) {
    const id = setTimeout(fn, ms);
    engine.timers.push(id);
    return id;
  }

  function clearTimers() {
    for (const id of engine.timers) clearTimeout(id);
    engine.timers = [];
  }

  function stopRaf() {
    engine.running = false;
    engine.lastTs = 0;
    if (engine.raf) {
      cancelAnimationFrame(engine.raf);
      engine.raf = 0;
    }
  }

  function stopObserver() {
    if (engine.observer) {
      engine.observer.disconnect();
      engine.observer = null;
    }
  }

  function stopMatrix() {
    engine.matrix = null;
    const canvas = $("matrix");
    if (canvas) {
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
      canvas.classList.add("hidden");
    }
  }

  function hideCards() {
    $("cards").classList.add("hidden");
  }

  function hideStinger() {
    $("stinger").classList.add("hidden");
  }

  function hidePages() {
    const el = $("pages");
    el.classList.add("hidden");
    el.innerHTML = "";
  }

  function hideTicker() {
    const el = $("ticker");
    el.classList.add("hidden");
    el.innerHTML = "";
    el.style.transform = "";
  }

  function hideMatrixBoard() {
    const el = $("matrix-board");
    el.classList.add("hidden");
    el.innerHTML = "";
  }

  function parkReel(on) {
    $("sw-world").classList.toggle("parked", !!on);
  }

  function clearInlineMotion() {
    const track = $("sw-track");
    const world = $("sw-world");
    const reel = $("reel");
    track.style.transition = "none";
    track.style.transform = "";
    track.style.opacity = "";
    world.style.transform = "";
    world.style.opacity = "";
    reel.style.transform = "";
    reel.style.opacity = "";
    reel.style.visibility = "";
    reel.classList.remove("out", "loop-fade", "loop-wipe");
    $("pages").style.opacity = "";
    $("ticker").style.transition = "none";
    $("ticker").style.transform = "";
    $("ticker").style.opacity = "";
    void track.offsetHeight;
    track.style.transition = "";
    $("ticker").style.transition = "";
  }

  function stripBodyMotion() {
    const drop = [];
    document.body.classList.forEach((c) => {
      if (c.indexOf("motion-") === 0 || c.indexOf("enter-") === 0) drop.push(c);
    });
    drop.forEach((c) => document.body.classList.remove(c));
  }

  function hardReset() {
    stopRaf();
    clearTimers();
    stopObserver();
    stopMatrix();
    hideCards();
    hideStinger();
    hidePages();
    hideTicker();
    hideMatrixBoard();
    parkReel(false);
    clearInlineMotion();
    stripBodyMotion();
    Object.assign(engine, {
      y: 0,
      x: 0,
      startY: 0,
      endY: 0,
      linear: 0,
      gapUntil: 0,
      started: false,
      phase: "idle",
      cardIndex: 0,
      cardUntil: 0,
      endUntil: 0,
      loopGap: false,
      pageIndex: 0,
      pages: [],
      fading: false,
      typeLines: [],
      typeLine: 0,
      typeCol: 0,
      typeHoldUntil: 0,
      typeState: "idle",
      typeAcc: 0,
    });
    lastMotion = "";
    lastMotionFp = "";
  }

  // ---------------------------------------------------------------- theme

  function applyQuery(t) {
    const out = Object.assign({}, t);
    qs.forEach((v, k) => {
      if (k === "demo" || k === "t" || k === "v") return;
      if (v === "true") out[k] = true;
      else if (v === "false") out[k] = false;
      else if (v !== "" && !Number.isNaN(Number(v)) && String(Number(v)) === v) out[k] = Number(v);
      else out[k] = v;
    });
    return out;
  }

  function shadowFrom(t) {
    if (t.text_shadow && t.shadow_strength == null) return t.text_shadow;
    const s = num(t.shadow_strength, 8);
    if (s <= 0) return "none";
    return "0 2px " + s + "px rgba(0,0,0,0.85)";
  }

  function isMovie() {
    return (roster.style || theme.style) === "movie" && !!roster.cast;
  }

  function movieLook() {
    const look = (roster.cast && roster.cast.look) || {};
    const movie = isMovie();
    return {
      letterbox: bool(theme.letterbox, false) || !!(movie && look.letterbox),
      grain: bool(theme.grain, false) || !!(movie && look.grain),
      vignette: bool(theme.vignette, false) || !!(movie && look.vignette),
    };
  }

  function isSolid() {
    const bg = theme.background || "transparent";
    return bg !== "transparent" && bg !== "";
  }

  function applyTheme(t) {
    theme = applyQuery(t || {});
    const r = document.documentElement.style;
    const set = (k, v) => r.setProperty(k, v);
    set("--title-color", theme.title_color || "#f3e2b0");
    set("--name-color", theme.name_color || "#f4f0e6");
    set("--muted", theme.muted_color || "#9a8f78");
    set("--mod", theme.mod_color || "#e8c36a");
    set("--vip", theme.vip_color || "#c9a0ff");
    set("--font", theme.font_family || "Georgia, serif");
    set("--title-size", num(theme.title_size_px, 54) + "px");
    set("--name-size", num(theme.name_size_px, 22) + "px");
    set("--subtitle-size", num(theme.subtitle_size_px, 26) + "px");
    set("--footer-size", num(theme.footer_size_px, 28) + "px");
    set("--title-weight", String(num(theme.title_weight, 600)));
    set("--name-weight", String(num(theme.name_weight, 500)));
    set("--shadow", shadowFrom(theme));
    set("--track", num(theme.letter_spacing_em, 0.04) + "em");
    set("--col-gap", num(theme.column_gap_px, 48) + "px");
    set("--row-gap", num(theme.row_gap_px, 10) + "px");
    set("--max-w", num(theme.max_width_px, 920) + "px");
    set("--mask", Math.max(0, num(theme.mask_fade_px, 72)) + "px");
    set("--sw-tilt", tiltDeg() + "deg");
    set("--sw-perspective", perspectivePx() + "px");
    set("--page-fade", pageFadeMs() + "ms");
    set("--title-case", bool(theme.uppercase_title, true) ? "uppercase" : "none");
    set("--name-case", bool(theme.uppercase_names, false) ? "uppercase" : "none");
    set("--align", theme.align === "left" ? "left" : "center");
    set("--stage-opacity", String(num(theme.opacity, 1)));
    set("--matrix", theme.title_color || "#00ff41");
    const glowOn = bool(theme.glow, false);
    set("--glow", glowOn
      ? "0 0 " + num(theme.glow_px, 16) + "px " + (theme.glow_color || "#e8c36a")
      : "0 0 0 transparent");

    const bg = theme.background || "transparent";
    const solid = isSolid();
    document.body.style.background = solid ? bg : "transparent";
    set("--bg", solid ? bg : "transparent");
    if (solid) set("--fade-from", bg);
    const body = document.body.classList;
    body.toggle("solid", solid);
    const mask = num(theme.mask_fade_px, 72);
    body.toggle("no-mask", mask <= 0);
    body.toggle("soft-mask", !solid && mask > 0);
    body.toggle("align-left", theme.align === "left");
    if (engine.phase !== "empty") {
      const look = movieLook();
      body.toggle("letterbox", look.letterbox);
      body.toggle("grain", look.grain);
      body.toggle("vignette", look.vignette);
      set("--letterbox", look.letterbox ? "7.5vh" : "0px");
    }

    if (theme.custom_font_url) {
      let link = $("custom-font");
      if (!link) {
        link = document.createElement("link");
        link.id = "custom-font";
        link.rel = "stylesheet";
        document.head.appendChild(link);
      }
      if (link.getAttribute("href") !== theme.custom_font_url) link.href = theme.custom_font_url;
    }
  }

  // ---------------------------------------------------------------- markup

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (ch) => {
      if (ch === "&") return "&amp;";
      if (ch === "<") return "&lt;";
      if (ch === ">") return "&gt;";
      if (ch === '"') return "&quot;";
      return "&#39;";
    });
  }

  function prettyName(c) {
    return String((c && (c.display_name || c.username)) || "").replace(/^@+/, "");
  }

  function personKey(c) {
    return prettyName(c).trim().toLowerCase();
  }

  // Plain text, or an empty span the typewriter fills in.
  function txt(text, opts) {
    return opts && opts.tw
      ? '<span class="tw-line" data-text="' + esc(text) + '"></span>'
      : esc(text);
  }

  function letterize(text) {
    return Array.from(String(text || ""))
      .map((ch, i) => {
        const safe = ch === " " ? "&nbsp;" : esc(ch);
        return '<span class="ch" style="animation-delay:' + i * 38 + 'ms">' + safe + "</span>";
      })
      .join("");
  }

  function cols() {
    return Math.max(1, Math.min(4, Math.round(num(theme.columns, 2))));
  }

  function nameCell(c, opts) {
    const showPlat = theme.show_platform !== false;
    const showCount = bool(theme.show_message_count, false);
    const hl = theme.highlight_mods !== false && c.is_mod;
    const vip = bool(theme.highlight_vips, false) && c.is_vip && !hl;
    const dot = showPlat ? '<span class="dot ' + esc(c.platform) + '"></span>' : "";
    const count = showCount ? '<span class="count">' + (c.messages || 1) + "</span>" : "";
    const noteText = c.alert_note || c.credit_note || c.title_note;
    const note = noteText ? '<span class="note">' + esc(noteText) + "</span>" : "";
    return '<div class="name' + (hl ? " mod" : "") + (vip ? " vip" : "") + '">' +
      dot + txt(prettyName(c), opts) + count + note + "</div>";
  }

  function grid(list, n, opts) {
    return '<div class="grid cols-' + n + '" style="--cols:' + n + '">' +
      list.map((c) => nameCell(c, opts)).join("") + "</div>";
  }

  function jobLayout() {
    const l = String(theme.job_layout || "dots");
    return l === "stacked" || l === "inline" ? l : "dots";
  }

  function jobRow(row, opts) {
    const hl = theme.highlight_mods !== false && row.is_mod;
    const vip = bool(theme.highlight_vips, false) && row.is_vip && !hl;
    const layout = jobLayout();
    return '<div class="job-row' + (layout !== "dots" ? " " + layout : "") + '">' +
      '<div class="job">' + txt(row.job || "", opts) + "</div>" +
      '<div class="dots"></div>' +
      '<div class="who' + (hl ? " mod" : "") + (vip ? " vip" : "") + '">' + txt(prettyName(row), opts) + "</div>" +
      "</div>";
  }

  function crewBlock(rows, opts) {
    const inner = rows.map((r) => jobRow(r, opts)).join("");
    if (rows.length >= 4 && cols() >= 2 && jobLayout() === "dots") {
      return '<div class="crew-cols">' + inner + "</div>";
    }
    return '<div class="job-list">' + inner + "</div>";
  }

  function heading(text, opts) {
    return '<div class="section">' + txt(text || "", opts) + "</div>";
  }

  function billing(row, opts) {
    return '<div class="billing"><div class="bill-role">' + txt(row.billing || "", opts) +
      '</div><div class="bill-name">' + txt(prettyName(row), opts) + "</div></div>";
  }

  function legalBlock(lines, opts) {
    return '<div class="legal">' + lines.map((ln) => "<div>" + txt(ln, opts) + "</div>").join("") + "</div>";
  }

  // Movie cast with each person shown once (first department / group wins).
  function cast() {
    if (castCache) return castCache;
    const src = roster.cast || {};
    const seen = new Set();
    const take = (list) => {
      const out = [];
      for (const c of list || []) {
        const k = personKey(c);
        if (!k || seen.has(k)) continue;
        seen.add(k);
        out.push(c);
      }
      return out;
    };
    const departments = (src.departments || [])
      .map((d) => ({ id: d.id, title: d.title, rows: take(d.rows) }))
      .filter((d) => d.rows.length);
    const groups = (src.groups || [])
      .map((g) => ({ id: g.id, title: g.title || g.id, chatters: take(g.chatters) }))
      .filter((g) => g.chatters.length);
    const extra = take((src.overflow && src.overflow.chatters) || []);
    castCache = {
      starring: src.starring || [],
      departments,
      groups,
      overflow: { title: (src.overflow && src.overflow.title) || "Additional Voices", chatters: extra },
      thanks: src.thanks || [],
      legal: src.legal || [],
    };
    return castCache;
  }

  function openingCards() {
    return (isMovie() && roster.cast && roster.cast.cards) || [];
  }

  function titleBlock(opts) {
    // Movie styles with opening cards use the cards as their title.
    if (openingCards().length) return "";
    const title = theme.title || "Thanks for watching";
    const subtitle = theme.subtitle || "";
    const tw = opts && opts.tw;
    const intro = tw ? "none" : String(theme.title_intro || "none");
    const inner = tw ? txt(title, opts) : intro === "letters" ? letterize(title) : esc(title);
    const introClass = intro !== "none" ? " intro-" + (intro === "letters" ? "letters" : intro) : "";
    let html = '<div class="title' + introClass + '">' + inner + "</div>";
    if (subtitle) html += '<div class="subtitle">' + txt(subtitle, opts) + "</div>";
    html += '<div class="rule ' + esc(theme.rule_style || "gradient") + '"></div>';
    return html;
  }

  // Tonight's chat rating (Stream Core chat games: !rate), shown above the footer.
  function ratingLine() {
    return String((roster && roster.rating_line) || "");
  }

  function footerBlock(opts) {
    const footer = theme.footer || "";
    const rating = ratingLine();
    return (rating ? '<div class="footer rating">' + txt(rating, opts) + "</div>" : "") +
      (footer ? '<div class="footer">' + txt(footer, opts) + "</div>" : "");
  }

  function renderMovieBody(opts) {
    const c = cast();
    const n = cols();
    let html = c.starring.map((row) => billing(row, opts)).join("");
    c.departments.forEach((d) => {
      html += heading(d.title, opts) + crewBlock(d.rows, opts);
    });
    c.groups.forEach((g) => {
      html += heading(g.title, opts) + grid(g.chatters, n, opts);
    });
    if (c.overflow.chatters.length) {
      html += heading(c.overflow.title, opts) + grid(c.overflow.chatters, n, opts);
    }
    if (c.thanks.length) html += heading("Special Thanks", opts) + crewBlock(c.thanks, opts);
    if (c.legal.length) html += legalBlock(c.legal, opts);
    return html;
  }

  function platformBuckets(chatters) {
    const buckets = {};
    chatters.forEach((ch) => {
      (buckets[ch.platform] || (buckets[ch.platform] = [])).push(ch);
    });
    const keys = PLATFORM_ORDER.filter((p) => buckets[p] && buckets[p].length)
      .concat(Object.keys(buckets).filter((p) => PLATFORM_ORDER.indexOf(p) < 0));
    return { buckets, keys };
  }

  function renderNamesBody(opts) {
    const chatters = roster.chatters || [];
    if (!chatters.length) return '<div class="empty">Waiting for chat</div>';
    if (isMovie()) return renderMovieBody(opts);
    const n = cols();
    if (theme.group_by_platform) {
      const { buckets, keys } = platformBuckets(chatters);
      return keys.map((p) =>
        '<div class="plat-block"><div class="plat-h ' + esc(p) + '">' +
        esc(PLATFORM_LABEL[p] || p) + "</div>" + grid(buckets[p], n, opts) + "</div>"
      ).join("");
    }
    return heading(theme.section_label || "Chatters", opts) + grid(chatters, n, opts);
  }

  function renderReel() {
    $("reel").innerHTML = titleBlock({}) + renderNamesBody({}) + footerBlock({});
  }

  // ---------------------------------------------------------------- pages

  function stageHeight() {
    return ($("stage") && $("stage").clientHeight) || window.innerHeight || 720;
  }

  function namesPerPage() {
    const n = cols();
    const namePx = num(theme.name_size_px, 22);
    const usable = stageHeight() * 0.58;
    const rowH = namePx * 1.7 + num(theme.row_gap_px, 10);
    const rows = Math.max(4, Math.min(12, Math.floor(usable / rowH)));
    return Math.max(n, rows * n);
  }

  function chunk(arr, n) {
    const out = [];
    for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n));
    return out;
  }

  function titleOwnPage() {
    return bool(theme.title_own_page, true);
  }

  function buildPages(tw) {
    const opts = { tw: !!tw };
    const chatters = roster.chatters || [];
    const per = namesPerPage();
    const n = cols();
    const title = titleBlock(opts);
    const inners = [];
    const push = (inner) => {
      if (inner) inners.push(inner);
    };

    if (!chatters.length) {
      push('<div class="empty">' + txt("Waiting for chat", opts) + "</div>");
    } else if (isMovie()) {
      const c = cast();
      c.starring.forEach((row) => push(billing(row, opts)));
      c.departments.forEach((d) => {
        chunk(d.rows, Math.max(6, Math.floor(per / Math.max(1, n)))).forEach((part) => {
          push(heading(d.title, opts) + crewBlock(part, opts));
        });
      });
      c.groups.forEach((g) => {
        chunk(g.chatters, per).forEach((part) => push(heading(g.title, opts) + grid(part, n, opts)));
      });
      if (c.overflow.chatters.length) {
        chunk(c.overflow.chatters, per).forEach((part) => {
          push(heading(c.overflow.title, opts) + grid(part, n, opts));
        });
      }
      if (c.thanks.length) push(heading("Special Thanks", opts) + crewBlock(c.thanks, opts));
      if (c.legal.length) push(legalBlock(c.legal, opts));
    } else if (theme.group_by_platform) {
      const { buckets, keys } = platformBuckets(chatters);
      keys.forEach((p) => {
        chunk(buckets[p], per).forEach((part) => {
          push('<div class="plat-h ' + esc(p) + '">' + txt(PLATFORM_LABEL[p] || p, opts) + "</div>" + grid(part, n, opts));
        });
      });
    } else {
      const label = theme.section_label || "Chatters";
      chunk(chatters, per).forEach((part) => push(heading(label, opts) + grid(part, n, opts)));
    }

    if (theme.footer || ratingLine()) push(footerBlock(opts));
    if (!inners.length) push('<div class="empty">' + txt("Waiting for chat", opts) + "</div>");
    if (title) {
      if (titleOwnPage()) inners.unshift(title);
      else inners[0] = title + inners[0];
    }
    return inners.map((inner) => '<div class="page">' + inner + "</div>");
  }

  function pageNodes() {
    return $("pages").querySelectorAll(".page");
  }

  function showPage(i, leaving) {
    pageNodes().forEach((el, idx) => {
      el.classList.remove("on", "leave");
      if (idx === leaving) el.classList.add("leave");
      if (idx === i) el.classList.add("on");
    });
  }

  function mountPages(tw) {
    const html = buildPages(tw);
    const el = $("pages");
    el.innerHTML = html.join("");
    el.classList.remove("hidden");
    parkReel(true);
    hideTicker();
    hideMatrixBoard();
    hideCards();
    hideStinger();
    engine.pages = html;
    engine.pageIndex = 0;
    showPage(0, -1);
  }

  function pageHoldFor(i) {
    return pageHoldMs() + (i === 0 ? titleHoldMs() : 0);
  }

  // ---------------------------------------------------------------- end of roll

  function wantsClear(mode) {
    return mode === "clear" || (mode === "once" && bool(theme.clear_when_done, false));
  }

  function clearStage() {
    hideCards();
    hideStinger();
    hidePages();
    hideTicker();
    hideMatrixBoard();
    stopMatrix();
    parkReel(true);
    document.body.classList.remove("letterbox", "grain", "vignette");
    engine.phase = "empty";
    engine.lastTs = 0;
    stopRaf();
  }

  function holdStill() {
    play.mode = "hold";
    stopRaf();
  }

  // Once / clear / loop decision shared by every motion. Returns true if the roll ended.
  function endOfRoll() {
    const mode = currentMode();
    if (wantsClear(mode)) {
      clearStage();
      return true;
    }
    if (mode === "once") {
      holdStill();
      return true;
    }
    return false;
  }

  // ---------------------------------------------------------------- movie cards

  function showCard(card) {
    parkReel(true);
    const wrap = $("cards");
    const kicker = $("card-kicker");
    const line = $("card-line");
    hideStinger();
    if (!card) {
      wrap.classList.add("hidden");
      return;
    }
    wrap.classList.remove("hidden");
    kicker.textContent = card.kicker || "";
    kicker.style.display = card.kicker ? "" : "none";
    if (card.type === "mpaa") {
      line.className = "mpaa-box";
    } else {
      const small = ["association", "location", "studio", "runtime"].indexOf(card.type) >= 0;
      line.className = "card-line" + (small ? " small" : "");
    }
    line.textContent = card.line || "";
  }

  function showStinger() {
    const st = isMovie() && roster.cast && roster.cast.stinger;
    if (!st) return false;
    parkReel(true);
    $("stinger-kicker").textContent = st.kicker || "";
    $("stinger-line").textContent = st.line || "";
    $("stinger").classList.remove("hidden");
    hideCards();
    return true;
  }

  function cardHoldTotal() {
    return openingCards().reduce((n, c) => n + num(c.hold_sec, 2.8), 0);
  }

  function endHoldSec() {
    return isMovie() ? num(roster.cast && roster.cast.end_hold_sec, 0) : 0;
  }

  // ---------------------------------------------------------------- crawl

  function measureReelHeight() {
    const world = $("sw-world");
    world.style.setProperty("transform", "none");
    const height = $("reel").scrollHeight || 0;
    world.style.removeProperty("transform");
    return height;
  }

  function metrics() {
    const stageH = stageHeight();
    const lb = movieLook().letterbox ? stageH * 0.075 : 0;
    const height = measureReelHeight();
    const motion = engine.motion;
    if (motion === "starwars") {
      // The plane is tilted away from the viewer, so the whole reel has to travel
      // well past the horizon before the last line is gone.
      const startY = stageH * 0.95;
      return { stageH, height, startY, endY: startY - (height + stageH) };
    }
    if (motion === "crawl-down") {
      return { stageH, height, startY: -height + lb, endY: stageH - lb };
    }
    return { stageH, height, startY: stageH - lb, endY: -height + lb };
  }

  function applyY(y) {
    $("sw-track").style.transform = "translate3d(0," + y + "px,0)";
  }

  function holdY() {
    const m = metrics();
    if (m.height <= m.stageH * 0.92) return Math.max(24, (m.stageH - m.height) / 2);
    return 48;
  }

  function bindEnters() {
    stopObserver();
    const enter = String(theme.name_enter || "none");
    if (!CRAWL_MOTIONS[engine.motion] || enter === "none") return;
    const nodes = $("reel").querySelectorAll(".name, .job-row, .billing");
    if (!nodes.length || typeof IntersectionObserver !== "function") {
      nodes.forEach((n) => n.classList.add("in"));
      return;
    }
    const stagger = Math.max(0, num(theme.name_stagger_ms, 40));
    nodes.forEach((node, i) => {
      node.style.transitionDelay = (i % 12) * stagger + "ms";
    });
    engine.observer = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (en.isIntersecting) en.target.classList.add("in");
      });
    }, { root: $("stage"), threshold: 0.12 });
    nodes.forEach((n) => engine.observer.observe(n));
  }

  function layoutCrawl() {
    const m = metrics();
    engine.startY = m.startY;
    engine.endY = m.endY;
    engine.linear = 0;
    engine.y = m.startY;
    applyY(engine.y);
  }

  function beginCrawl() {
    hideCards();
    hideStinger();
    hidePages();
    hideTicker();
    hideMatrixBoard();
    parkReel(false);
    engine.phase = "crawl";
    engine.fading = false;
    $("sw-track").style.opacity = "1";
    $("sw-track").style.transition = "none";
    layoutCrawl();
    bindEnters();
  }

  function startCards(ts) {
    const list = openingCards();
    engine.phase = "cards";
    engine.cardIndex = 0;
    engine.lastTs = 0;
    if (!list.length) {
      beginCrawl();
      return;
    }
    parkReel(true);
    showCard(list[0]);
    engine.cardUntil = ts + num(list[0].hold_sec, 2.8) * 1000;
  }

  function finishCrawl(ts) {
    const mode = currentMode();
    const endHold = endHoldSec();
    if (mode === "once" || mode === "clear" || endHold > 0) {
      if (engine.motion !== "starwars" && !wantsClear(mode)) {
        engine.y = holdY();
        applyY(engine.y);
      }
      parkReel(false);
      engine.phase = "end";
      engine.endUntil = ts + Math.max(0.4, endHold) * 1000;
      if ((mode === "once" || mode === "clear") && endHold <= 0 && !showStingerSoon()) {
        endOfRoll();
      }
      return;
    }
    loopCrawl(ts);
  }

  function showStingerSoon() {
    return !!(isMovie() && roster.cast && roster.cast.stinger);
  }

  function restartCrawlFromTop(ts) {
    engine.linear = 0;
    engine.y = engine.startY;
    engine.lastTs = 0;
    applyY(engine.y);
    const gap = loopGapMs();
    if (gap > 0) engine.gapUntil = ts + gap;
    if (openingCards().length) startCards(ts);
  }

  function loopCrawl(ts) {
    const track = $("sw-track");
    if (engine.motion === "starwars") {
      engine.fading = true;
      track.style.transition = "opacity 380ms linear";
      track.style.opacity = "0";
      later(() => {
        engine.linear = 0;
        engine.y = engine.startY;
        applyY(engine.y);
        track.style.opacity = "1";
        later(() => {
          track.style.transition = "";
          engine.fading = false;
          engine.lastTs = 0;
          if (openingCards().length) startCards(performance.now());
        }, 380);
      }, 380);
      return;
    }
    const trans = String(theme.loop_transition || "cut");
    if (trans === "fade" || trans === "wipe") {
      const reel = $("reel");
      engine.fading = true;
      reel.classList.add(trans === "wipe" ? "loop-wipe" : "loop-fade", "out");
      later(() => {
        restartCrawlFromTop(performance.now());
        reel.classList.remove("out");
        engine.fading = false;
        later(() => reel.classList.remove("loop-fade", "loop-wipe"), 600);
      }, trans === "wipe" ? 520 : 460);
      return;
    }
    restartCrawlFromTop(ts);
  }

  function crawlSpeed(travel) {
    const target = num(theme.duration_sec, 0);
    const budget = target > 0 ? Math.max(6, target - cardHoldTotal() - endHoldSec()) : 0;
    return budget > 0 ? Math.max(4, travel / budget) : Math.max(8, num(theme.speed_px_per_sec, 42));
  }

  function tickCrawl(ts) {
    if (engine.phase === "cards") {
      const list = openingCards();
      if (!list.length) beginCrawl();
      else if (ts >= engine.cardUntil) {
        engine.cardIndex += 1;
        if (engine.cardIndex >= list.length) beginCrawl();
        else {
          const card = list[engine.cardIndex];
          showCard(card);
          engine.cardUntil = ts + num(card.hold_sec, 2.8) * 1000;
        }
      }
      return;
    }
    if (engine.phase === "end") {
      if (ts >= engine.endUntil) {
        if (showStinger()) {
          engine.phase = "stinger";
          const hold = num(roster.cast && roster.cast.stinger && roster.cast.stinger.hold_sec, 4);
          engine.endUntil = ts + hold * 1000;
        } else {
          afterSequence(ts);
        }
      }
      return;
    }
    if (engine.phase === "stinger") {
      if (ts >= engine.endUntil) afterSequence(ts);
      return;
    }
    if (engine.fading) return;
    if (engine.gapUntil && ts < engine.gapUntil) return;
    engine.gapUntil = 0;
    if (!engine.lastTs) engine.lastTs = ts;
    const dt = Math.min(0.05, (ts - engine.lastTs) / 1000);
    engine.lastTs = ts;
    const travel = Math.max(1, Math.abs(engine.endY - engine.startY));
    engine.linear += (crawlSpeed(travel) * dt) / travel;
    if (engine.linear >= 1) {
      engine.linear = 1;
      engine.y = engine.endY;
      applyY(engine.y);
      finishCrawl(ts);
      return;
    }
    engine.y = engine.startY + (engine.endY - engine.startY) * ease(engine.linear, theme.easing || "linear");
    applyY(engine.y);
  }

  function afterSequence(ts) {
    if (endOfRoll()) return;
    hideStinger();
    if (CRAWL_MOTIONS[engine.motion]) {
      beginCrawl();
      restartCrawlFromTop(ts);
    } else {
      restartCurrent(ts);
    }
  }

  // ---------------------------------------------------------------- page motions

  function tickPages(ts) {
    if (engine.phase !== "pages") return;
    if (!engine.endUntil) engine.endUntil = ts + pageHoldFor(engine.pageIndex);
    if (ts < engine.endUntil) return;
    const n = engine.pages.length;
    if (engine.pageIndex + 1 < n) {
      const prev = engine.pageIndex;
      engine.pageIndex += 1;
      showPage(engine.pageIndex, prev);
      engine.endUntil = ts + pageHoldFor(engine.pageIndex);
      return;
    }
    if (endOfRoll()) return;
    const gap = loopGapMs();
    if (gap > 0 && !engine.loopGap) {
      engine.loopGap = true;
      engine.endUntil = ts + gap;
      return;
    }
    engine.loopGap = false;
    const prev = engine.pageIndex;
    engine.pageIndex = 0;
    showPage(0, prev);
    engine.endUntil = ts + pageHoldFor(0);
  }

  // ---------------------------------------------------------------- typewriter

  function typewriterCps() {
    return Math.max(4, num(theme.typewriter_cps, 28));
  }

  // line / card / page type each character; name reveals a whole line per type_ms.
  function typewriterUnit() {
    const u = String(theme.typewriter_unit || "line").toLowerCase();
    return u === "card" || u === "page" || u === "name" ? u : "line";
  }

  function collectTwLines(page) {
    return Array.prototype.slice.call(page ? page.querySelectorAll(".tw-line") : []);
  }

  function attachCaret(el) {
    $("pages").querySelectorAll(".caret").forEach((n) => n.parentNode && n.parentNode.removeChild(n));
    if (!el) return;
    const caret = document.createElement("span");
    caret.className = "caret";
    el.appendChild(caret);
  }

  function beginTypingPage(ts) {
    const page = pageNodes()[engine.pageIndex];
    engine.typeLines = collectTwLines(page);
    engine.typeLines.forEach((el) => {
      el.textContent = "";
    });
    engine.typeLine = 0;
    engine.typeCol = 0;
    engine.typeAcc = 0;
    engine.typeState = "typing";
    engine.lastTs = ts;
    attachCaret(engine.typeLines[0]);
  }

  function fillTypedPage() {
    collectTwLines(pageNodes()[engine.pageIndex]).forEach((el) => {
      el.textContent = el.getAttribute("data-text") || "";
    });
    attachCaret(null);
  }

  function startTypewriter(ts) {
    mountPages(true);
    engine.phase = "typewriter";
    beginTypingPage(ts);
  }

  function typewriterAdvance(chars) {
    const lines = engine.typeLines;
    if (!lines.length) return "done";
    let left = chars;
    const unit = typewriterUnit();
    while (left > 0 && engine.typeLine < lines.length) {
      const el = lines[engine.typeLine];
      const full = el.getAttribute("data-text") || "";
      if (engine.typeCol < full.length) {
        const take = Math.min(left, full.length - engine.typeCol);
        engine.typeCol += take;
        el.textContent = full.slice(0, engine.typeCol);
        attachCaret(el);
        left -= take;
        if (engine.typeCol >= full.length && unit === "line") {
          engine.typeLine += 1;
          engine.typeCol = 0;
          return engine.typeLine >= lines.length ? "done" : "line-break";
        }
      } else {
        engine.typeLine += 1;
        engine.typeCol = 0;
      }
    }
    return engine.typeLine >= lines.length ? "done" : "typing";
  }

  function revealNextLine() {
    const lines = engine.typeLines;
    if (engine.typeLine >= lines.length) return "done";
    const el = lines[engine.typeLine];
    el.textContent = el.getAttribute("data-text") || "";
    el.classList.add("typed");
    engine.typeLine += 1;
    attachCaret(lines[engine.typeLine] || el);
    return engine.typeLine >= lines.length ? "done" : "typing";
  }

  function tickTypewriter(ts) {
    if (engine.phase !== "typewriter") return;
    if (engine.typeState === "hold") {
      if (ts < engine.typeHoldUntil) return;
      if (engine.pageIndex + 1 < engine.pages.length) {
        engine.pageIndex += 1;
        showPage(engine.pageIndex, engine.pageIndex - 1);
        beginTypingPage(ts);
        return;
      }
      if (endOfRoll()) return;
      if (engine.typeState === "hold" && !engine.loopGap && loopGapMs() > 0) {
        engine.loopGap = true;
        engine.typeHoldUntil = ts + loopGapMs();
        return;
      }
      engine.loopGap = false;
      startTypewriter(ts);
      return;
    }
    if (engine.typeState === "line-pause") {
      if (ts < engine.typeHoldUntil) return;
      engine.typeState = "typing";
      engine.lastTs = ts;
      attachCaret(engine.typeLines[engine.typeLine]);
    }
    if (!engine.lastTs) engine.lastTs = ts;
    const dt = Math.min(0.08, (ts - engine.lastTs) / 1000);
    engine.lastTs = ts;
    const unit = typewriterUnit();
    let result = "typing";
    if (unit === "name") {
      engine.typeAcc += dt * 1000;
      const step = Math.max(10, num(theme.type_ms, 55));
      while (engine.typeAcc >= step && result !== "done") {
        engine.typeAcc -= step;
        result = revealNextLine();
      }
      if (!engine.typeLines.length) result = "done";
    } else {
      engine.typeAcc += typewriterCps() * dt;
      const chars = Math.floor(engine.typeAcc);
      if (chars < 1) return;
      engine.typeAcc -= chars;
      result = typewriterAdvance(chars);
    }
    if (result === "done") {
      engine.typeState = "hold";
      engine.typeHoldUntil = ts + pageHoldFor(engine.pageIndex);
      return;
    }
    if (result === "line-break") {
      engine.typeState = "line-pause";
      engine.typeHoldUntil = ts + 280;
    }
  }

  // ---------------------------------------------------------------- ticker

  function startTicker() {
    const el = $("ticker");
    const chatters = roster.chatters || [];
    const bits = ['<span class="tick-title">' + esc(theme.title || "Thanks for watching") + "</span>"];
    if (!chatters.length) bits.push('<span class="name">Waiting for chat</span>');
    else chatters.forEach((c) => bits.push(nameCell(c, {})));
    if (ratingLine()) bits.push('<span class="tick-title">' + esc(ratingLine()) + "</span>");
    if (theme.footer) bits.push('<span class="tick-title">' + esc(theme.footer) + "</span>");
    el.innerHTML = bits.join("") + bits.join("");
    el.classList.remove("hidden");
    parkReel(true);
    hidePages();
    hideMatrixBoard();
    hideCards();
    hideStinger();
    engine.phase = "ticker";
    engine.x = ($("stage") && $("stage").clientWidth) || window.innerWidth || 1280;
    el.style.transform = "translate3d(" + engine.x + "px,-50%,0)";
  }

  function tickTicker(ts) {
    if (engine.gapUntil && ts < engine.gapUntil) return;
    engine.gapUntil = 0;
    if (!engine.lastTs) engine.lastTs = ts;
    const dt = Math.min(0.05, (ts - engine.lastTs) / 1000);
    engine.lastTs = ts;
    const speed = Math.max(20, num(theme.speed_px_per_sec, 42) * 1.8);
    engine.x -= speed * dt;
    const el = $("ticker");
    const half = el.scrollWidth / 2;
    if (half > 0 && engine.x <= -half) {
      engine.x += half;
      if (endOfRoll()) return;
    }
    el.style.transform = "translate3d(" + engine.x + "px,-50%,0)";
  }

  // ---------------------------------------------------------------- matrix

  function decryptName(full, t, lockMs) {
    const n = full.length;
    const locked = Math.min(n, Math.floor((t / lockMs) * n));
    let out = full.slice(0, locked);
    for (let i = locked; i < n; i++) {
      out += MATRIX_GLYPHS.charAt((Math.floor(t / 40) + i * 7) % MATRIX_GLYPHS.length);
    }
    return out;
  }

  function matrixSections() {
    const sections = [];
    const chatters = roster.chatters || [];
    const per = Math.max(6, namesPerPage());
    if (isMovie() && chatters.length) {
      const c = cast();
      c.departments.forEach((d) => {
        chunk(d.rows.map(prettyName), per).forEach((names) => sections.push({ title: d.title, names }));
      });
      c.groups.forEach((g) => {
        chunk(g.chatters.map(prettyName), per).forEach((names) => sections.push({ title: g.title, names }));
      });
      if (c.overflow.chatters.length) {
        chunk(c.overflow.chatters.map(prettyName), per).forEach((names) => {
          sections.push({ title: c.overflow.title, names });
        });
      }
    } else if (chatters.length) {
      chunk(chatters, per).forEach((part) => {
        sections.push({ title: theme.section_label || "Chatters", names: part.map(prettyName) });
      });
    }
    if (!sections.length) sections.push({ title: theme.section_label || "Chatters", names: ["Waiting for chat"] });
    return sections;
  }

  function matrixDensity() {
    return Math.max(0.4, Math.min(2.2, num(theme.matrix_density, 1)));
  }

  function startMatrix() {
    const canvas = $("matrix");
    canvas.classList.remove("hidden");
    parkReel(true);
    hidePages();
    hideTicker();
    hideCards();
    hideStinger();
    $("matrix-board").classList.remove("hidden");
    engine.phase = "matrix";
    const now = performance.now();
    engine.matrix = {
      canvas,
      ctx: canvas.getContext("2d"),
      drops: [],
      font: 16,
      sections: matrixSections(),
      section: 0,
      sectionBorn: now,
      lastDraw: 0,
    };
    resizeMatrix();
    renderMatrixBoard(true);
  }

  function resizeMatrix() {
    const m = engine.matrix;
    if (!m) return;
    const canvas = m.canvas;
    const w = canvas.clientWidth || window.innerWidth;
    const h = canvas.clientHeight || window.innerHeight;
    canvas.width = w;
    canvas.height = h;
    if (m.ctx) {
      m.ctx.clearRect(0, 0, w, h);
      if (isSolid()) {
        m.ctx.fillStyle = theme.background;
        m.ctx.fillRect(0, 0, w, h);
      }
    }
    m.font = Math.max(12, Math.round(14 * matrixDensity()));
    const count = Math.max(12, Math.floor(w / m.font));
    m.drops = [];
    for (let i = 0; i < count; i++) m.drops.push(Math.random() * -40);
  }

  function renderMatrixBoard(resetText) {
    const m = engine.matrix;
    if (!m) return;
    const sec = m.sections[m.section] || m.sections[0];
    const board = $("matrix-board");
    const n = cols();
    board.innerHTML =
      '<div class="title">' + esc(theme.title || "Thanks for watching") + "</div>" +
      heading(sec.title, {}) +
      '<div class="grid cols-' + n + '" style="--cols:' + n + '">' +
      (sec.names || []).map((name, i) =>
        '<div class="name" data-full="' + esc(name) + '" data-i="' + i + '">' + esc(name) + "</div>"
      ).join("") +
      "</div>" + footerBlock({});
    if (resetText) board.querySelectorAll(".name").forEach((el) => { el.textContent = ""; });
  }

  function drawRain(m, ts) {
    // ~30 fps rain regardless of the display rate.
    if (m.lastDraw && ts - m.lastDraw < 33) return;
    m.lastDraw = ts;
    const ctx = m.ctx;
    const w = m.canvas.width;
    const h = m.canvas.height;
    if (isSolid()) {
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 0.32;
      ctx.fillStyle = theme.background;
      ctx.fillRect(0, 0, w, h);
      ctx.globalAlpha = 1;
    } else {
      // Transparent overlay: fade old glyphs out instead of painting black.
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = "rgba(0,0,0,0.32)";
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "source-over";
    }
    ctx.font = m.font + 'px "Share Tech Mono", monospace';
    for (let i = 0; i < m.drops.length; i++) {
      const ch = MATRIX_GLYPHS.charAt(Math.floor(Math.random() * MATRIX_GLYPHS.length));
      const y = m.drops[i] * m.font;
      ctx.fillStyle = "#a8ffb8";
      ctx.fillText(ch, i * m.font, y);
      ctx.fillStyle = theme.title_color || "#00ff41";
      ctx.fillText(ch, i * m.font, y - m.font);
      if (y > h && Math.random() > 0.975) m.drops[i] = 0;
      m.drops[i] += 0.95;
    }
  }

  function tickMatrix(ts) {
    const m = engine.matrix;
    if (!m || !m.ctx) return;
    drawRain(m, ts);
    const age = ts - m.sectionBorn;
    $("matrix-board").querySelectorAll(".name").forEach((el, i) => {
      el.textContent = decryptName(el.getAttribute("data-full") || "", Math.max(0, age - i * 90), 1100);
    });
    if (age < pageHoldFor(m.section)) return;
    if (m.section + 1 < m.sections.length) {
      m.section += 1;
      m.sectionBorn = ts;
      renderMatrixBoard(true);
      return;
    }
    if (endOfRoll()) return;
    m.section = 0;
    m.sectionBorn = ts + loopGapMs();
    renderMatrixBoard(true);
  }

  // ---------------------------------------------------------------- run loop

  function restartCurrent(ts) {
    const motion = engine.motion;
    if (CRAWL_MOTIONS[motion]) {
      if (openingCards().length) startCards(ts);
      else beginCrawl();
    } else if (motion === "typewriter") startTypewriter(ts);
    else if (PAGE_MOTIONS[motion]) {
      engine.pageIndex = 0;
      showPage(0, -1);
      engine.endUntil = ts + pageHoldFor(0);
      engine.phase = "pages";
    } else if (motion === "ticker") startTicker();
    else if (motion === "matrix") startMatrix();
  }

  function paused() {
    return play.playing === false || currentMode() === "hold";
  }

  function tick(ts) {
    if (!engine.running) return;
    engine.raf = requestAnimationFrame(tick);
    if (paused() || engine.phase === "empty") return;
    const motion = engine.motion;
    if (CRAWL_MOTIONS[motion]) tickCrawl(ts);
    else if (motion === "typewriter") tickTypewriter(ts);
    else if (PAGE_MOTIONS[motion]) tickPages(ts);
    else if (motion === "ticker") tickTicker(ts);
    else if (motion === "matrix") tickMatrix(ts);
  }

  function startRaf() {
    if (engine.running) return;
    engine.running = true;
    engine.lastTs = 0;
    engine.raf = requestAnimationFrame(tick);
  }

  function motionFingerprint(t) {
    t = t || theme;
    return [
      motionId(t),
      String(t.typewriter_unit || "line"),
      String(t.typewriter_cps || ""),
      String(t.matrix_density || ""),
      String(pick(t.page_duration_sec, t.page_hold_sec) || ""),
      String(t.name_enter || "none"),
      String(t.easing || "linear"),
      String(t.title_intro || "none"),
      String(t.title_own_page),
      String(t.clear_when_done),
    ].join("~");
  }

  function startMotion() {
    const motion = motionId();
    engine.motion = motion;
    lastMotion = motion;
    lastMotionFp = motionFingerprint(theme);
    document.body.classList.add("motion-" + motion);
    if (PAGE_MOTIONS[motion]) document.body.classList.add("motion-pages");
    const enter = String(theme.name_enter || "none");
    if (CRAWL_MOTIONS[motion] && enter !== "none") document.body.classList.add("enter-" + enter);
    const stopped = paused();
    engine.started = true;

    if (CRAWL_MOTIONS[motion]) {
      renderReel();
      if (stopped) {
        parkReel(false);
        engine.phase = "crawl";
        later(() => {
          engine.y = holdY();
          applyY(engine.y);
          $("reel").querySelectorAll(".name, .job-row, .billing").forEach((n) => n.classList.add("in"));
        }, 0);
        return;
      }
      later(() => {
        const now = performance.now();
        if (openingCards().length) startCards(now);
        else {
          beginCrawl();
          const hold = titleHoldMs();
          if (hold > 0) engine.gapUntil = now + hold;
        }
        startRaf();
      }, 16);
    } else if (motion === "typewriter") {
      startTypewriter(performance.now());
      if (stopped) {
        fillTypedPage();
        engine.typeState = "hold";
        engine.typeHoldUntil = Number.POSITIVE_INFINITY;
      } else startRaf();
    } else if (PAGE_MOTIONS[motion]) {
      mountPages(false);
      engine.phase = "pages";
      engine.endUntil = 0;
      if (!stopped) startRaf();
    } else if (motion === "ticker") {
      startTicker();
      if (!stopped) startRaf();
    } else if (motion === "matrix") {
      startMatrix();
      if (stopped) tickMatrix(performance.now());
      else startRaf();
    }
  }

  // Look / roster changed but the motion didn't: redraw where we are, no restart.
  function rerenderInPlace() {
    const motion = engine.motion;
    if (engine.phase === "empty") return;
    if (CRAWL_MOTIONS[motion]) {
      const y = engine.y;
      renderReel();
      if (engine.phase === "crawl") {
        const m = metrics();
        engine.startY = m.startY;
        engine.endY = m.endY;
        if (paused()) {
          engine.y = holdY();
        } else if ((theme.easing || "linear") === "linear") {
          const lo = Math.min(m.startY, m.endY);
          const hi = Math.max(m.startY, m.endY);
          engine.y = Math.min(hi, Math.max(lo, y));
          const span = m.endY - m.startY;
          engine.linear = span ? (engine.y - m.startY) / span : 0;
        } else {
          engine.y = m.startY + (m.endY - m.startY) * ease(engine.linear, theme.easing);
        }
        applyY(engine.y);
        bindEnters();
        if (paused()) $("reel").querySelectorAll(".name, .job-row, .billing").forEach((n) => n.classList.add("in"));
      }
    } else if (motion === "typewriter") {
      const idx = engine.pageIndex;
      mountPages(true);
      engine.pageIndex = Math.min(idx, engine.pages.length - 1);
      showPage(engine.pageIndex, -1);
      if (paused()) fillTypedPage();
      else beginTypingPage(performance.now());
    } else if (PAGE_MOTIONS[motion]) {
      const idx = engine.pageIndex;
      mountPages(false);
      engine.pageIndex = Math.min(idx, engine.pages.length - 1);
      showPage(engine.pageIndex, -1);
    } else if (motion === "ticker") {
      const x = engine.x;
      startTicker();
      engine.x = Math.min(x, engine.x);
      $("ticker").style.transform = "translate3d(" + engine.x + "px,-50%,0)";
    } else if (motion === "matrix" && engine.matrix) {
      const m = engine.matrix;
      m.sections = matrixSections();
      m.section = Math.min(m.section, m.sections.length - 1);
      renderMatrixBoard(false);
    }
  }

  function rosterKey(r) {
    const cards = ((r.cast && r.cast.cards) || []).map((c) => c.line).join(",");
    return (r.style || "") + "~" + cards + "~" + (r.chatters || []).map((c) =>
      [c.platform, c.username, c.display_name, c.job || "", c.is_mod ? 1 : 0, c.is_vip ? 1 : 0, c.messages].join(":")
    ).join("|");
  }

  function paint(opts) {
    opts = opts || {};
    castCache = null;
    const motion = motionId();
    const gen = Number(play.generation || 0);
    const fp = motionFingerprint(theme);
    const motionChanged = (motion !== lastMotion && lastMotion !== "") || (fp !== lastMotionFp && lastMotionFp !== "");
    const genChanged = gen !== engine.generation && engine.generation !== -1;
    const reset = !!opts.reset || motionChanged || genChanged || !engine.started;
    if (reset) {
      hardReset();
      engine.generation = gen;
      applyTheme(theme);
      lastRosterKey = rosterKey(roster);
      lastThemeKey = JSON.stringify(theme);
      lastMode = currentMode();
      startMotion();
      return;
    }
    applyTheme(theme);
    const rk = rosterKey(roster);
    const tk = JSON.stringify(theme);
    if (rk !== lastRosterKey || tk !== lastThemeKey) {
      lastRosterKey = rk;
      lastThemeKey = tk;
      rerenderInPlace();
    }
    engine.generation = gen;
    // Hold still shows the list where it can be read; Pause freezes in place.
    const mode = currentMode();
    if (mode === "hold" && lastMode !== "hold" && CRAWL_MOTIONS[engine.motion] && engine.phase === "crawl") {
      engine.y = holdY();
      applyY(engine.y);
      $("reel").querySelectorAll(".name, .job-row, .billing").forEach((n) => n.classList.add("in"));
    }
    lastMode = mode;
    if (!engine.running && !paused() && engine.phase !== "empty") {
      if (engine.phase === "idle" || (CRAWL_MOTIONS[engine.motion] && engine.phase === "crawl" && !engine.startY && !engine.endY)) {
        paint({ reset: true });
        return;
      }
      if (engine.motion === "typewriter" && engine.typeHoldUntil === Number.POSITIVE_INFINITY) {
        engine.typeHoldUntil = performance.now() + pageHoldFor(engine.pageIndex);
      }
      startRaf();
    }
  }

  function schedulePaint(opts) {
    clearTimeout(rebuildTimer);
    const reset = !!(opts && opts.reset) || !!(schedulePaint.pending && schedulePaint.pending.reset);
    schedulePaint.pending = { reset };
    rebuildTimer = setTimeout(() => {
      const o = schedulePaint.pending || {};
      schedulePaint.pending = null;
      paint(o);
    }, 40);
  }

  // ---------------------------------------------------------------- data

  async function fetchFirst(paths) {
    for (let i = 0; i < paths.length; i++) {
      try {
        const r = await fetch(paths[i], { cache: "no-store" });
        if (r.ok) return await r.json();
      } catch (e) {
        /* try the next mount path */
      }
    }
    return null;
  }

  async function boot() {
    try {
      const pack = await Promise.all([fetchFirst(API_THEME), fetchFirst(API_ROSTER), fetchFirst(API_PLAY)]);
      applyTheme(pack[0] || {});
      if (pack[1]) roster = pack[1];
      if (pack[2]) play = pack[2];
    } catch (e) {
      applyTheme({});
    }
    paint({ reset: true });
    connectWs();
  }

  function connectWs() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    let ws;
    try {
      ws = new WebSocket(proto + "://" + location.host + "/ws?credits=1");
    } catch (e) {
      setTimeout(connectWs, 2000);
      return;
    }
    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (e) {
        return;
      }
      const kind = msg.type || "";
      if (kind === "theme" || kind === "credits_theme") {
        const prev = motionFingerprint(theme);
        applyTheme(msg.data);
        schedulePaint({ reset: prev !== motionFingerprint(theme) });
      } else if (kind === "roster" || kind === "credits_roster") {
        roster = msg.data || { chatters: [] };
        schedulePaint();
      } else if (kind === "play" || kind === "credits_play") {
        play = msg.data || play;
        schedulePaint();
      }
    };
    ws.onclose = () => setTimeout(connectWs, 2000);
  }

  window.addEventListener("resize", () => {
    if (engine.motion === "matrix") resizeMatrix();
    if (!CRAWL_MOTIONS[engine.motion] || engine.phase !== "crawl") return;
    const m = metrics();
    engine.startY = m.startY;
    engine.endY = m.endY;
    if (paused()) {
      engine.y = holdY();
      applyY(engine.y);
    }
  });

  // Test hook (the admin preview and tests read it; harmless in OBS).
  window.__credits = { engine, state: () => ({ theme, roster, play }) };

  boot();
})();
