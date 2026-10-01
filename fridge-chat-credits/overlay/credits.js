/* Fridge credits overlay engine.
   Crawl is rAF (OBS/CEF drops CSS keyframe crawls).
   Star Wars: perspective on #stage, rotateX on #sw-world, translateY on #sw-track.
   Motion changes and Restart always hard-reset so leftover transforms cannot black-screen. */
(function () {
  "use strict";

  const PLATFORM_ORDER = ["twitch", "kick", "youtube", "manual"];
  const PLATFORM_LABEL = { twitch: "Twitch", kick: "Kick", youtube: "YouTube", manual: "Chat" };
  const CRAWL_MOTIONS = { crawl: 1, "crawl-down": 1, starwars: 1 };
  const PAGE_MOTIONS = { cards: 1, fade: 1, slides: 1, typewriter: 1 };
  const MATRIX_GLYPHS = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789";

  const qs = new URLSearchParams(location.search);
  const API_THEME = ["/api/theme", "/api/credits/theme"];
  const API_ROSTER = ["/api/roster", "/api/credits/roster"];
  const API_PLAY = ["/api/play", "/api/credits/play"];
  let theme = {};
  let roster = { chatters: [], count: 0 };
  let play = { playing: true, mode: "loop", freeze: false, generation: 0 };
  let rebuildTimer = 0;
  let lastRosterKey = "";
  let lastThemeKey = "";
  let lastMotion = "";
  let lastEnter = "";
  let lastMotionFp = "";

  const engine = {
    raf: 0,
    timers: [],
    y: 0,
    x: 0,
    startY: 0,
    endY: 0,
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

  function $(id) {
    return document.getElementById(id);
  }

  function num(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  function motionId() {
    const m = String(theme.motion || "crawl").toLowerCase();
    return CRAWL_MOTIONS[m] || PAGE_MOTIONS[m] || m === "ticker" || m === "matrix" ? m : "crawl";
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
    const m = engine.matrix;
    if (m && m.raf) cancelAnimationFrame(m.raf);
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
    engine.y = 0;
    engine.x = 0;
    engine.startY = 0;
    engine.endY = 0;
    engine.gapUntil = 0;
    engine.started = false;
    engine.phase = "idle";
    engine.cardIndex = 0;
    engine.cardUntil = 0;
    engine.endUntil = 0;
    engine.pageIndex = 0;
    engine.pages = [];
    engine.fading = false;
    engine.typeLines = [];
    engine.typeLine = 0;
    engine.typeCol = 0;
    engine.typeHoldUntil = 0;
    engine.typeState = "idle";
    engine.typeAcc = 0;
    lastMotion = "";
    lastEnter = "";
    lastMotionFp = "";
  }

  function applyQuery(t) {
    const out = Object.assign({}, t);
    qs.forEach((v, k) => {
      if (k === "demo") return;
      if (v === "true") out[k] = true;
      else if (v === "false") out[k] = false;
      else if (v !== "" && !Number.isNaN(Number(v)) && String(Number(v)) === v) out[k] = Number(v);
      else out[k] = v;
    });
    return out;
  }

  function movieLook() {
    const look = (roster.cast && roster.cast.look) || {};
    const movie = (roster.style || theme.style) === "movie";
    return {
      letterbox: theme.letterbox != null ? !!theme.letterbox : !!(movie && look.letterbox),
      grain: theme.grain != null ? !!theme.grain : !!(movie && look.grain),
      vignette: theme.vignette != null ? !!theme.vignette : !!(movie && look.vignette),
    };
  }

  function applyTheme(t) {
    theme = applyQuery(t || {});
    const r = document.documentElement.style;
    r.setProperty("--title-color", theme.title_color || "#f3e2b0");
    r.setProperty("--name-color", theme.name_color || "#f4f0e6");
    r.setProperty("--muted", theme.muted_color || "#9a8f78");
    r.setProperty("--mod", theme.mod_color || "#e8c36a");
    r.setProperty("--font", theme.font_family || "Georgia, serif");
    r.setProperty("--title-size", (theme.title_size_px || 54) + "px");
    r.setProperty("--name-size", (theme.name_size_px || 22) + "px");
    r.setProperty("--shadow", theme.text_shadow || "0 2px 8px rgba(0,0,0,0.85)");
    r.setProperty("--track", (theme.letter_spacing_em || 0.04) + "em");
    r.setProperty("--col-gap", (theme.column_gap_px || 48) + "px");
    r.setProperty("--row-gap", (theme.row_gap_px || 10) + "px");
    r.setProperty("--max-w", (theme.max_width_px || 920) + "px");
    r.setProperty("--sw-tilt", num(theme.sw_tilt_deg, 52) + "deg");
    r.setProperty("--sw-perspective", num(theme.sw_perspective_px, 420) + "px");
    r.setProperty("--page-fade", Math.max(120, num(theme.page_fade_sec, 0.65) * 1000) + "ms");
    r.setProperty("--matrix", theme.title_color || "#00ff41");
    const bg = theme.background || "transparent";
    document.body.style.background = bg;
    document.body.classList.toggle("solid", bg !== "transparent" && bg !== "");
    const look = movieLook();
    document.body.classList.toggle("letterbox", look.letterbox);
    document.body.classList.toggle("grain", look.grain);
    document.body.classList.toggle("vignette", look.vignette);
    r.setProperty("--letterbox", look.letterbox ? "7.5vh" : "0px");
    if (theme.custom_font_url) {
      let link = document.getElementById("custom-font");
      if (!link) {
        link = document.createElement("link");
        link.id = "custom-font";
        link.rel = "stylesheet";
        document.head.appendChild(link);
      }
      if (link.href !== theme.custom_font_url) link.href = theme.custom_font_url;
    }
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (ch) {
      if (ch === "&") return "\u0026amp;";
      if (ch === "<") return "\u0026lt;";
      if (ch === ">") return "\u0026gt;";
      if (ch === '"') return "\u0026quot;";
      return "\u0026#39;";
    });
  }

  function prettyName(c) {
    return String((c && (c.display_name || c.username)) || "").replace(/^@+/, "");
  }

  function nameCell(c, opts) {
    opts = opts || {};
    const showPlat = theme.show_platform !== false;
    const showCount = !!theme.show_message_count;
    const hl = (theme.highlight_mods !== false && c.is_mod) || (theme.highlight_vips && c.is_vip);
    const dot = showPlat ? '<span class="dot ' + esc(c.platform) + '"></span>' : "";
    const count = showCount ? '<span class="count">' + (c.messages || 1) + "</span>" : "";
    const note = c.alert_note || c.credit_note
      ? '<span class="note">' + esc(c.alert_note || c.credit_note) + "</span>"
      : "";
    const label = prettyName(c);
    const text = opts.tw
      ? '<span class="tw-line" data-text="' + esc(label) + '"></span>'
      : esc(label);
    return '<div class="name' + (hl ? " mod" : "") + '">' + dot + text + count + note + "</div>";
  }

  function grid(list, cols, opts) {
    return '<div class="grid cols-' + cols + '" style="--cols:' + cols + '">' +
      list.map(function (c) { return nameCell(c, opts); }).join("") +
      "</div>";
  }

  function jobRow(row, opts) {
    opts = opts || {};
    const hl = theme.highlight_mods !== false && row.is_mod;
    const job = opts.tw
      ? '<span class="tw-line" data-text="' + esc(row.job || "") + '"></span>'
      : esc(row.job || "");
    const who = opts.tw
      ? '<span class="tw-line" data-text="' + esc(prettyName(row)) + '"></span>'
      : esc(prettyName(row));
    return '<div class="job-row">' +
      '<div class="job">' + job + "</div>" +
      '<div class="dots"></div>' +
      '<div class="who' + (hl ? " mod" : "") + '">' + who + "</div>" +
      "</div>";
  }

  function crewBlock(rows, opts) {
    if (rows.length >= 4) {
      return '<div class="crew-cols">' + rows.map(function (r) { return jobRow(r, opts); }).join("") + "</div>";
    }
    return '<div class="job-list">' + rows.map(function (r) { return jobRow(r, opts); }).join("") + "</div>";
  }

  function heading(text, opts) {
    const t = text || "";
    if (opts && opts.tw) {
      return '<div class="section"><span class="tw-line" data-text="' + esc(t) + '"></span></div>';
    }
    return '<div class="section">' + esc(t) + "</div>";
  }

  function titleBlock(opts) {
    const movie = (roster.style || theme.style) === "movie" && roster.cast;
    if (movie) return "";
    const title = theme.title || "Thanks for watching";
    const subtitle = theme.subtitle || "";
    const tw = opts && opts.tw;
    let html = tw
      ? '<div class="title"><span class="tw-line" data-text="' + esc(title) + '"></span></div>'
      : '<div class="title">' + esc(title) + "</div>";
    if (subtitle) {
      html += tw
        ? '<div class="subtitle"><span class="tw-line" data-text="' + esc(subtitle) + '"></span></div>'
        : '<div class="subtitle">' + esc(subtitle) + "</div>";
    }
    html += '<div class="rule"></div>';
    return html;
  }

  function footerBlock(opts) {
    const footer = theme.footer || "";
    if (!footer) return "";
    if (opts && opts.tw) {
      return '<div class="footer"><span class="tw-line" data-text="' + esc(footer) + '"></span></div>';
    }
    return '<div class="footer">' + esc(footer) + "</div>";
  }

  function rosterKey(r) {
    const jobs = (r.chatters || []).map(function (c) { return c.job || ""; }).join(",");
    const cards = ((r.cast && r.cast.cards) || []).map(function (c) { return c.line; }).join(",");
    return (r.style || "") + "~" + jobs + "~" + cards + "~" +
      (r.chatters || []).map(function (c) { return c.platform + ":" + c.username; }).join("|");
  }

  function themeKey(t) {
    return [
      t.title, t.subtitle, t.footer, t.section_label, t.columns, t.sort,
      t.group_by_platform, t.show_platform, t.show_message_count, t.highlight_mods,
      t.highlight_vips, t.name_size_px, t.title_size_px, t.font_family, t.style_id, t.style,
      t.letterbox, t.grain, t.vignette, t.duration_sec, t.clear_when_done,
      t.motion, t.name_enter, t.typewriter_unit, t.typewriter_cps, t.page_hold_sec,
      t.matrix_density, t.sw_tilt_deg, t.sw_perspective_px, t.max_width_px,
      t.column_gap_px, t.row_gap_px,
    ].join("~");
  }

  function motionFingerprint(t) {
    t = t || theme;
    return [
      String(t.motion || "crawl").toLowerCase(),
      String(t.typewriter_unit || "line"),
      String(t.typewriter_cps || ""),
      String(t.matrix_density || ""),
      String(t.page_hold_sec || ""),
      String(t.name_enter || "none"),
    ].join("~");
  }

  function isMovie() {
    return (roster.style || theme.style) === "movie" && roster.cast;
  }

  function cols() {
    return Math.max(1, Math.min(4, num(theme.columns, 2)));
  }

  function renderMovieBody(opts) {
    const cast = roster.cast;
    if (!cast) return "";
    const c = cols();
    let html = "";
    const starring = (cast.starring || []).slice(1);
    if (starring.length) {
      html += starring.map(function (row) {
        const role = opts && opts.tw
          ? '<span class="tw-line" data-text="' + esc(row.billing || "") + '"></span>'
          : esc(row.billing || "");
        const name = opts && opts.tw
          ? '<span class="tw-line" data-text="' + esc(prettyName(row)) + '"></span>'
          : esc(prettyName(row));
        return '<div class="billing"><div class="bill-role">' + role + '</div><div class="bill-name">' + name + "</div></div>";
      }).join("");
    }
    (cast.departments || []).forEach(function (d) {
      if (!(d.rows || []).length) return;
      html += heading(d.title, opts) + crewBlock(d.rows, opts);
    });
    (cast.groups || []).forEach(function (g) {
      if (!(g.chatters || []).length) return;
      html += heading(g.title || g.id, opts) + grid(g.chatters, c, opts);
    });
    const extra = (cast.overflow && cast.overflow.chatters) || [];
    if (extra.length) {
      html += heading((cast.overflow && cast.overflow.title) || "Additional Voices", opts) + grid(extra, c, opts);
    }
    if ((cast.thanks || []).length) {
      html += heading("Special Thanks", opts) + crewBlock(cast.thanks, opts);
    }
    if ((cast.legal || []).length) {
      html += '<div class="legal">' + cast.legal.map(function (ln) {
        if (opts && opts.tw) return "<div><span class=\"tw-line\" data-text=\"" + esc(ln) + "\"></span></div>";
        return "<div>" + esc(ln) + "</div>";
      }).join("") + "</div>";
    }
    return html;
  }

  function renderNamesBody(opts) {
    const chatters = roster.chatters || [];
    const label = theme.section_label || "Chatters";
    const group = !!theme.group_by_platform;
    const c = cols();
    if (!chatters.length) return '<div class="empty">Waiting for chat</div>';
    if (isMovie()) return renderMovieBody(opts);
    if (group) {
      const buckets = {};
      chatters.forEach(function (ch) {
        (buckets[ch.platform] || (buckets[ch.platform] = [])).push(ch);
      });
      const keys = PLATFORM_ORDER.filter(function (p) { return buckets[p] && buckets[p].length; })
        .concat(Object.keys(buckets).filter(function (p) { return PLATFORM_ORDER.indexOf(p) < 0; }));
      return keys.map(function (p) {
        return '<div class="plat-block"><div class="plat-h ' + esc(p) + '">' +
          esc(PLATFORM_LABEL[p] || p) + "</div>" + grid(buckets[p], c, opts) + "</div>";
      }).join("");
    }
    return heading(label, opts) + grid(chatters, c, opts);
  }

  function renderReel() {
    $("reel").innerHTML = titleBlock({}) + renderNamesBody({}) + footerBlock({});
  }

  function namesPerPage() {
    const c = cols();
    const namePx = num(theme.name_size_px, 22);
    const stageH = ($("stage") && $("stage").clientHeight) || window.innerHeight || 720;
    const usable = stageH * 0.58;
    const rowH = namePx * 1.7 + num(theme.row_gap_px, 10);
    const rows = Math.max(4, Math.min(12, Math.floor(usable / rowH)));
    return Math.max(c, rows * c);
  }

  function chunk(arr, n) {
    const out = [];
    for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n));
    return out;
  }

  function pageHtml(inner) {
    return '<div class="page">' + inner + "</div>";
  }

  function buildPages(tw) {
    const opts = { tw: !!tw };
    const movie = isMovie();
    const chatters = roster.chatters || [];
    const per = namesPerPage();
    const title = titleBlock(opts);
    const inners = [];

    function pushPage(inner) {
      if (inner) inners.push(inner);
    }

    if (!chatters.length) {
      pushPage((title || "") + '<div class="empty">Waiting for chat</div>');
      if (theme.footer) pushPage(footerBlock(opts));
      return inners.map(pageHtml);
    }

    if (movie) {
      const cast = roster.cast;
      const starring = (cast.starring || []).slice(1);
      starring.forEach(function (row) {
        const role = opts.tw
          ? '<span class="tw-line" data-text="' + esc(row.billing || "") + '"></span>'
          : esc(row.billing || "");
        const name = opts.tw
          ? '<span class="tw-line" data-text="' + esc(prettyName(row)) + '"></span>'
          : esc(prettyName(row));
        pushPage('<div class="billing"><div class="bill-role">' + role + '</div><div class="bill-name">' + name + "</div></div>");
      });
      (cast.departments || []).forEach(function (d) {
        const rows = d.rows || [];
        if (!rows.length) return;
        chunk(rows, Math.max(6, Math.floor(per / Math.max(1, cols())))).forEach(function (part) {
          pushPage(heading(d.title, opts) + crewBlock(part, opts));
        });
      });
      (cast.groups || []).forEach(function (g) {
        const list = g.chatters || [];
        if (!list.length) return;
        chunk(list, per).forEach(function (part) {
          pushPage(heading(g.title || g.id, opts) + grid(part, cols(), opts));
        });
      });
      const extra = (cast.overflow && cast.overflow.chatters) || [];
      if (extra.length) {
        chunk(extra, per).forEach(function (part) {
          pushPage(heading((cast.overflow && cast.overflow.title) || "Additional Voices", opts) + grid(part, cols(), opts));
        });
      }
      if ((cast.thanks || []).length) {
        pushPage(heading("Special Thanks", opts) + crewBlock(cast.thanks, opts));
      }
      if ((cast.legal || []).length) {
        pushPage('<div class="legal">' + cast.legal.map(function (ln) {
          return opts.tw
            ? "<div><span class=\"tw-line\" data-text=\"" + esc(ln) + "\"></span></div>"
            : "<div>" + esc(ln) + "</div>";
        }).join("") + "</div>");
      }
    } else if (theme.group_by_platform) {
      const buckets = {};
      chatters.forEach(function (ch) {
        (buckets[ch.platform] || (buckets[ch.platform] = [])).push(ch);
      });
      const keys = PLATFORM_ORDER.filter(function (p) { return buckets[p] && buckets[p].length; })
        .concat(Object.keys(buckets).filter(function (p) { return PLATFORM_ORDER.indexOf(p) < 0; }));
      keys.forEach(function (p) {
        chunk(buckets[p], per).forEach(function (part) {
          pushPage(
            '<div class="plat-h ' + esc(p) + '">' + esc(PLATFORM_LABEL[p] || p) + "</div>" +
            grid(part, cols(), opts)
          );
        });
      });
    } else {
      const label = theme.section_label || "Chatters";
      chunk(chatters, per).forEach(function (part) {
        pushPage(heading(label, opts) + grid(part, cols(), opts));
      });
    }

    if (theme.footer) pushPage(footerBlock(opts));
    if (!inners.length) pushPage('<div class="empty">Waiting for chat</div>');
    if (title && inners.length) inners[0] = title + inners[0];
    else if (title) pushPage(title);
    return inners.map(pageHtml);
  }

  function openingCards() {
    return (roster.cast && roster.cast.cards) || [];
  }

  function wantsClear(mode) {
    return mode === "clear" || (mode === "once" && !!theme.clear_when_done);
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

  function showCard(card) {
    parkReel(true);
    const wrap = $("cards");
    const kicker = $("card-kicker");
    const line = $("card-line");
    wrap.classList.remove("hidden");
    $("stinger").classList.add("hidden");
    if (!card) {
      wrap.classList.add("hidden");
      return;
    }
    kicker.textContent = card.kicker || "";
    kicker.style.display = card.kicker ? "" : "none";
    if (card.type === "mpaa") {
      line.className = "mpaa-box";
      line.textContent = card.line || "";
    } else {
      const small = card.type === "association" || card.type === "location" || card.type === "studio" || card.type === "runtime";
      line.className = "card-line" + (small ? " small" : "");
      line.textContent = card.line || "";
    }
  }

  function showStinger() {
    const st = roster.cast && roster.cast.stinger;
    if (!st) return false;
    parkReel(true);
    $("stinger-kicker").textContent = st.kicker || "";
    $("stinger-line").textContent = st.line || "";
    $("stinger").classList.remove("hidden");
    hideCards();
    return true;
  }

  function measureReelHeight() {
    const world = $("sw-world");
    const reel = $("reel");
    world.style.setProperty("transform", "none");
    const height = reel.scrollHeight || 0;
    world.style.removeProperty("transform");
    return height;
  }

  function metrics() {
    const stageH = ($("stage") && $("stage").clientHeight) || window.innerHeight || 720;
    const lb = movieLook().letterbox ? stageH * 0.075 : 0;
    const height = measureReelHeight();
    const motion = engine.motion;
    if (motion === "starwars") {
      const startY = stageH * 0.95;
      const travel = Math.max(height * 0.5, stageH * 0.9);
      return {
        stageH: stageH,
        height: height,
        startY: startY,
        endY: startY - travel,
      };
    }
    if (motion === "crawl-down") {
      return {
        stageH: stageH,
        height: height,
        startY: -height + lb,
        endY: stageH - lb,
      };
    }
    return {
      stageH: stageH,
      height: height,
      startY: stageH - lb,
      endY: -height + lb,
    };
  }

  function applyY(y) {
    $("sw-track").style.transform = "translate3d(0," + y + "px,0)";
  }

  function holdY() {
    const m = metrics();
    if (m.height <= m.stageH * 0.92) {
      return Math.max(24, (m.stageH - m.height) / 2);
    }
    return 48;
  }

  function bindEnters() {
    stopObserver();
    const enter = String(theme.name_enter || "none");
    if (!CRAWL_MOTIONS[engine.motion] || enter === "none") return;
    const nodes = $("reel").querySelectorAll(".name, .job-row, .billing");
    if (!nodes.length || typeof IntersectionObserver !== "function") {
      nodes.forEach(function (n) { n.classList.add("in"); });
      return;
    }
    engine.observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) en.target.classList.add("in");
      });
    }, { root: $("stage"), threshold: 0.15 });
    nodes.forEach(function (n) { engine.observer.observe(n); });
  }

  function layoutCrawl() {
    const m = metrics();
    engine.startY = m.startY;
    engine.endY = m.endY;
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
    applyY(engine.startY || 0);
    showCard(list[0]);
    engine.cardUntil = ts + num(list[0].hold_sec, 2.8) * 1000;
  }

  function cardHoldTotal() {
    return openingCards().reduce(function (n, c) { return n + num(c.hold_sec, 2.8); }, 0);
  }

  function finishCrawl(ts) {
    const mode = play.mode || theme.mode || "loop";
    const endHold = num(roster.cast && roster.cast.end_hold_sec, 0);
    if (mode === "once" || mode === "clear" || endHold > 0) {
      if (engine.motion !== "starwars") {
        engine.y = holdY();
        applyY(engine.y);
      }
      parkReel(false);
      engine.phase = "end";
      engine.endUntil = ts + Math.max(0.4, endHold) * 1000;
      if ((mode === "once" || mode === "clear") && endHold <= 0) {
        if (wantsClear(mode)) clearStage();
        else {
          play.mode = "hold";
          stopRaf();
        }
      }
      return;
    }
    loopCrawl(ts);
  }

  function loopCrawl(ts) {
    const gap = Math.max(0, num(theme.gap_after_loop_sec, 2.5));
    if (engine.motion === "starwars") {
      engine.fading = true;
      $("sw-track").style.transition = "opacity 380ms linear";
      $("sw-track").style.opacity = "0";
      later(function () {
        engine.y = engine.startY;
        applyY(engine.y);
        $("sw-track").style.opacity = "1";
        later(function () {
          $("sw-track").style.transition = "";
          engine.fading = false;
          engine.lastTs = 0;
          if (openingCards().length) startCards(performance.now());
        }, 380);
      }, 380);
      return;
    }
    engine.y = engine.startY;
    engine.lastTs = 0;
    applyY(engine.y);
    if (gap > 0) engine.gapUntil = ts + gap * 1000;
    if (openingCards().length) startCards(ts);
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
          const hold = num((roster.cast && roster.cast.stinger && roster.cast.stinger.hold_sec), 4);
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
    const mTravel = Math.max(1, Math.abs(engine.startY - engine.endY));
    const target = num(theme.duration_sec, 0);
    const extra = cardHoldTotal() + num(roster.cast && roster.cast.end_hold_sec, 0);
    const crawlBudget = target > 0 ? Math.max(6, target - extra) : 0;
    const speed = crawlBudget > 0
      ? Math.max(8, mTravel / crawlBudget)
      : Math.max(8, num(theme.speed_px_per_sec, 42));
    if (engine.motion === "crawl-down") engine.y += speed * dt;
    else engine.y -= speed * dt;
    const done = engine.motion === "crawl-down"
      ? engine.y >= engine.endY
      : engine.y <= engine.endY;
    if (done) {
      finishCrawl(ts);
      return;
    }
    applyY(engine.y);
  }

  function afterSequence(ts) {
    const mode = play.mode || theme.mode || "loop";
    if (wantsClear(mode)) clearStage();
    else if (mode === "once") {
      play.mode = "hold";
      stopRaf();
    } else {
      $("stinger").classList.add("hidden");
      if (CRAWL_MOTIONS[engine.motion] && openingCards().length) startCards(ts);
      else restartCurrent(ts);
    }
  }

  function pageHoldMs() {
    return Math.max(800, num(theme.page_hold_sec, 4.2) * 1000);
  }

  function showPage(i, leaving) {
    const nodes = $("pages").querySelectorAll(".page");
    nodes.forEach(function (el, idx) {
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

  function nextPageOrLoop(ts) {
    const mode = play.mode || theme.mode || "loop";
    const n = engine.pages.length;
    if (engine.pageIndex + 1 < n) {
      const prev = engine.pageIndex;
      engine.pageIndex += 1;
      showPage(engine.pageIndex, prev);
      engine.endUntil = ts + pageHoldMs();
      return;
    }
    if (wantsClear(mode)) {
      clearStage();
      return;
    }
    if (mode === "once") {
      play.mode = "hold";
      stopRaf();
      return;
    }
    const prev = engine.pageIndex;
    engine.pageIndex = 0;
    showPage(0, prev);
    engine.endUntil = ts + pageHoldMs();
  }

  function tickPages(ts) {
    if (engine.phase !== "pages") return;
    if (!engine.endUntil) engine.endUntil = ts + pageHoldMs();
    if (ts >= engine.endUntil) nextPageOrLoop(ts);
  }

  function collectTwLines(page) {
    return Array.prototype.slice.call(page.querySelectorAll(".tw-line"));
  }

  function typewriterCps() {
    return Math.max(8, num(theme.typewriter_cps, 32));
  }

  function typewriterUnit() {
    const u = String(theme.typewriter_unit || "line").toLowerCase();
    return u === "card" || u === "page" ? u : "line";
  }

  function startTypewriter(ts) {
    mountPages(true);
    engine.phase = "typewriter";
    engine.typeState = "typing";
    engine.typeLine = 0;
    engine.typeCol = 0;
    engine.typeAcc = 0;
    engine.lastTs = ts;
    const page = $("pages").querySelectorAll(".page")[engine.pageIndex];
    engine.typeLines = page ? collectTwLines(page) : [];
    engine.typeLines.forEach(function (el) { el.textContent = ""; });
    attachCaret(engine.typeLines[0]);
  }

  function attachCaret(el) {
    const old = $("pages").querySelectorAll(".caret");
    old.forEach(function (n) { n.parentNode && n.parentNode.removeChild(n); });
    if (!el) return;
    const caret = document.createElement("span");
    caret.className = "caret";
    el.appendChild(caret);
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
          return "line-break";
        }
      } else {
        engine.typeLine += 1;
        engine.typeCol = 0;
      }
    }
    if (engine.typeLine >= lines.length) return "done";
    return "typing";
  }

  function tickTypewriter(ts) {
    if (engine.phase !== "typewriter") return;
    if (engine.typeState === "hold") {
      if (ts >= engine.typeHoldUntil) {
        const mode = play.mode || theme.mode || "loop";
        if (engine.pageIndex + 1 < engine.pages.length) {
          engine.pageIndex += 1;
          showPage(engine.pageIndex, engine.pageIndex - 1);
          const page = $("pages").querySelectorAll(".page")[engine.pageIndex];
          engine.typeLines = page ? collectTwLines(page) : [];
          engine.typeLines.forEach(function (el) { el.textContent = ""; });
          engine.typeLine = 0;
          engine.typeCol = 0;
          engine.typeAcc = 0;
          engine.typeState = "typing";
          engine.lastTs = ts;
          attachCaret(engine.typeLines[0]);
        } else if (wantsClear(mode)) {
          clearStage();
        } else if (mode === "once") {
          play.mode = "hold";
          stopRaf();
        } else {
          startTypewriter(ts);
        }
      }
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
    engine.typeAcc += typewriterCps() * dt;
    const chars = Math.floor(engine.typeAcc);
    if (chars < 1) return;
    engine.typeAcc -= chars;
    const unit = typewriterUnit();
    const result = typewriterAdvance(chars);
    if (result === "done") {
      engine.typeState = "hold";
      engine.typeHoldUntil = ts + pageHoldMs();
      return;
    }
    if (result === "line-break" && unit === "line") {
      engine.typeState = "line-pause";
      engine.typeHoldUntil = ts + 280;
    }
  }

  function startTicker() {
    const el = $("ticker");
    const chatters = roster.chatters || [];
    const title = theme.title || "Thanks for watching";
    const bits = ['<span class="tick-title">' + esc(title) + "</span>"];
    if (!chatters.length) {
      bits.push('<span class="name">Waiting for chat</span>');
    } else {
      chatters.forEach(function (c) { bits.push(nameCell(c, {})); });
    }
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
    if (!engine.lastTs) engine.lastTs = ts;
    const dt = Math.min(0.05, (ts - engine.lastTs) / 1000);
    engine.lastTs = ts;
    const speed = Math.max(20, num(theme.speed_px_per_sec, 42) * 1.8);
    engine.x -= speed * dt;
    const el = $("ticker");
    const half = el.scrollWidth / 2;
    if (engine.x <= -half) engine.x += half;
    el.style.transform = "translate3d(" + engine.x + "px,-50%,0)";
  }

  function decryptName(full, t, lockMs) {
    const n = full.length;
    const locked = Math.min(n, Math.floor((t / lockMs) * n));
    let out = full.slice(0, locked);
    for (let i = locked; i < n; i++) {
      out += MATRIX_GLYPHS.charAt((Math.floor(t / 40) + i * 7) % MATRIX_GLYPHS.length);
    }
    return out;
  }

  function startMatrix() {
    const canvas = $("matrix");
    canvas.classList.remove("hidden");
    parkReel(true);
    hidePages();
    hideTicker();
    hideCards();
    hideStinger();
    const board = $("matrix-board");
    board.classList.remove("hidden");
    engine.phase = "matrix";
    const sections = [];
    const chatters = roster.chatters || [];
    if (isMovie()) {
      const cast = roster.cast;
      (cast.departments || []).forEach(function (d) {
        if ((d.rows || []).length) {
          sections.push({ title: d.title, names: d.rows.map(prettyName) });
        }
      });
      (cast.groups || []).forEach(function (g) {
        if ((g.chatters || []).length) {
          sections.push({ title: g.title || g.id, names: g.chatters.map(prettyName) });
        }
      });
      const extra = (cast.overflow && cast.overflow.chatters) || [];
      if (extra.length) sections.push({ title: (cast.overflow && cast.overflow.title) || "Additional Voices", names: extra.map(prettyName) });
    } else if (chatters.length) {
      const per = Math.max(6, namesPerPage());
      chunk(chatters, per).forEach(function (part, i) {
        sections.push({
          title: i === 0 ? (theme.section_label || "Chatters") : (theme.section_label || "Chatters"),
          names: part.map(prettyName),
        });
      });
    }
    if (!sections.length) {
      sections.push({ title: theme.title || "Thanks for watching", names: ["Waiting for chat"] });
    }
    const density = Math.max(0.4, Math.min(2.2, num(theme.matrix_density, 1)));
    engine.matrix = {
      raf: 0,
      canvas: canvas,
      ctx: canvas.getContext("2d"),
      cols: [],
      drops: [],
      font: 16,
      sections: sections,
      section: 0,
      born: performance.now(),
      sectionBorn: performance.now(),
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
      m.ctx.fillStyle = "#000000";
      m.ctx.fillRect(0, 0, w, h);
    }
    const density = Math.max(0.4, Math.min(2.2, num(theme.matrix_density, 1)));
    m.font = Math.max(12, Math.round(14 * density));
    const colCount = Math.max(12, Math.floor(w / m.font));
    m.drops = [];
    for (let i = 0; i < colCount; i++) m.drops.push(Math.random() * -40);
  }

  function renderMatrixBoard(resetText) {
    const m = engine.matrix;
    if (!m) return;
    const sec = m.sections[m.section];
    const board = $("matrix-board");
    const names = (sec.names || []).slice(0, namesPerPage());
    board.innerHTML =
      '<div class="title">' + esc(theme.title || "Thanks for watching") + "</div>" +
      heading(sec.title, {}) +
      '<div class="grid cols-' + cols() + '" style="--cols:' + cols() + '">' +
      names.map(function (n, i) {
        return '<div class="name" data-full="' + esc(n) + '" data-i="' + i + '">' + esc(n) + "</div>";
      }).join("") +
      "</div>";
    if (resetText) {
      board.querySelectorAll(".name").forEach(function (el) { el.textContent = ""; });
    }
  }

  function tickMatrix(ts) {
    const m = engine.matrix;
    if (!m || !m.ctx) return;
    const ctx = m.ctx;
    const w = m.canvas.width;
    const h = m.canvas.height;
    ctx.fillStyle = "rgba(0,0,0,0.32)";
    ctx.fillRect(0, 0, w, h);
    ctx.font = m.font + "px \"Share Tech Mono\", monospace";
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
    const sec = m.sections[m.section];
    const hold = pageHoldMs();
    const age = ts - m.sectionBorn;
    const board = $("matrix-board");
    board.querySelectorAll(".name").forEach(function (el, i) {
      const full = el.getAttribute("data-full") || "";
      el.textContent = decryptName(full, Math.max(0, age - i * 90), 1100);
    });
    if (age >= hold) {
      const mode = play.mode || theme.mode || "loop";
      if (m.section + 1 < m.sections.length) {
        m.section += 1;
        m.sectionBorn = ts;
        renderMatrixBoard(true);
      } else if (wantsClear(mode)) {
        clearStage();
      } else if (mode === "once") {
        play.mode = "hold";
        stopRaf();
      } else {
        m.section = 0;
        m.sectionBorn = ts;
        renderMatrixBoard(true);
      }
    }
  }

  function restartCurrent(ts) {
    const motion = engine.motion;
    if (CRAWL_MOTIONS[motion]) {
      if (openingCards().length) startCards(ts);
      else beginCrawl();
    } else if (motion === "typewriter") startTypewriter(ts);
    else if (PAGE_MOTIONS[motion]) {
      engine.pageIndex = 0;
      showPage(0, -1);
      engine.endUntil = ts + pageHoldMs();
      engine.phase = "pages";
    } else if (motion === "ticker") startTicker();
    else if (motion === "matrix") startMatrix();
  }

  function tick(ts) {
    if (!engine.running) return;
    engine.raf = requestAnimationFrame(tick);
    const mode = play.mode || theme.mode || "loop";
    if (play.playing === false || mode === "hold") return;
    if (engine.phase === "empty") return;
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

  function startMotion() {
    const motion = motionId();
    engine.motion = motion;
    lastMotion = motion;
    document.body.classList.add("motion-" + motion);
    const enter = String(theme.name_enter || "none");
    lastEnter = enter;
    if (CRAWL_MOTIONS[motion] && enter !== "none") {
      document.body.classList.add("enter-" + enter);
    }
    lastMotionFp = motionFingerprint(theme);
    const mode = play.mode || theme.mode || "loop";
    const paused = play.playing === false || mode === "hold";
    if (paused && CRAWL_MOTIONS[motion]) {
      renderReel();
      parkReel(false);
      later(function () {
        applyY(holdY());
      }, 0);
      engine.started = true;
      engine.phase = "crawl";
      return;
    }
    if (CRAWL_MOTIONS[motion]) {
      renderReel();
      later(function () {
        if (openingCards().length) startCards(performance.now());
        else beginCrawl();
        startRaf();
      }, 16);
    } else if (motion === "typewriter") {
      startTypewriter(performance.now());
      if (paused) {
        const page = $("pages").querySelectorAll(".page")[engine.pageIndex];
        (page ? collectTwLines(page) : []).forEach(function (el) {
          el.textContent = el.getAttribute("data-text") || "";
        });
        engine.typeState = "hold";
        engine.typeHoldUntil = Number.POSITIVE_INFINITY;
      } else {
        startRaf();
      }
    } else if (PAGE_MOTIONS[motion]) {
      mountPages(false);
      engine.phase = "pages";
      engine.endUntil = 0;
      if (!paused) startRaf();
    } else if (motion === "ticker") {
      startTicker();
      if (!paused) startRaf();
    } else if (motion === "matrix") {
      startMatrix();
      if (paused) {
        tickMatrix(performance.now());
      } else {
        startRaf();
      }
    }
    engine.started = true;
  }

  function paint(opts) {
    opts = opts || {};
    const motion = motionId();
    const gen = Number(play.generation || 0);
    const fp = motionFingerprint(theme);
    const motionChanged = (motion !== lastMotion && lastMotion !== "") ||
      (fp !== lastMotionFp && lastMotionFp !== "");
    const genChanged = gen !== engine.generation && engine.generation !== -1;
    const reset = !!(opts.reset) || motionChanged || genChanged || !engine.started;
    if (reset) {
      hardReset();
      engine.generation = gen;
      applyTheme(theme);
      renderReel();
      lastRosterKey = rosterKey(roster);
      lastThemeKey = themeKey(theme);
      startMotion();
      return;
    }
    applyTheme(theme);
    const rk = rosterKey(roster);
    const tk = themeKey(theme);
    if (rk !== lastRosterKey || tk !== lastThemeKey) {
      lastRosterKey = rk;
      lastThemeKey = tk;
      if (CRAWL_MOTIONS[engine.motion] && engine.phase === "crawl") {
        const y = engine.y;
        renderReel();
        const m = metrics();
        engine.startY = m.startY;
        engine.endY = m.endY;
        engine.y = Math.min(engine.startY, Math.max(engine.endY, y));
        applyY(engine.y);
        bindEnters();
      }
    }
    engine.generation = gen;
    if (!engine.running && play.playing !== false && (play.mode || theme.mode) !== "hold" && engine.phase !== "empty") {
      startRaf();
    }
  }

  function schedulePaint(opts) {
    clearTimeout(rebuildTimer);
    rebuildTimer = setTimeout(function () { paint(opts || {}); }, 40);
  }

  async function fetchFirst(paths) {
    for (let i = 0; i < paths.length; i++) {
      try {
        const r = await fetch(paths[i], { cache: "no-store" });
        if (r.ok) return await r.json();
      } catch (e) { /* try next mount path (standalone vs Stream Core) */ }
    }
    return null;
  }

  async function boot() {
    try {
      const pack = await Promise.all([
        fetchFirst(API_THEME),
        fetchFirst(API_ROSTER),
        fetchFirst(API_PLAY),
      ]);
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
    const ws = new WebSocket(proto + "://" + location.host + "/ws");
    ws.onmessage = function (ev) {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      const kind = msg.type || "";
      if (kind === "theme" || kind === "credits_theme") {
        const prev = motionFingerprint(theme);
        applyTheme(msg.data);
        schedulePaint({ reset: prev !== motionFingerprint(theme) });
      }
      if (kind === "roster" || kind === "credits_roster") {
        roster = msg.data;
        schedulePaint();
      }
      if (kind === "play" || kind === "credits_play") {
        play = msg.data;
        schedulePaint();
      }
    };
    ws.onclose = function () { setTimeout(connectWs, 2000); };
  }

  window.addEventListener("resize", function () {
    if (engine.motion === "matrix") resizeMatrix();
    if (!CRAWL_MOTIONS[engine.motion]) return;
    const m = metrics();
    engine.startY = m.startY;
    engine.endY = m.endY;
    if (play.mode === "hold" || play.playing === false) {
      engine.y = holdY();
      applyY(engine.y);
    }
  });

  boot();
})();
