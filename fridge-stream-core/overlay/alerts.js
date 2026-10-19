/*
 * Stream alerts overlay: /overlay/alerts.html (OBS / XSplit Webpage source).
 *
 * Plays Core's "alert" packets from /ws one at a time (follows, subs, gifts, raids, bits,
 * Super Chats, KICKs, EventSub extras ...). Alert data is built by core/alerts.py: kind,
 * platform, headline, title, message, amount / amount_fmt / currency, months, qty, viewers,
 * level, item, image, falls_back, css_classes, duration_ms, is_test.
 * Skin, pictures, sounds, volume, tiers and the custom CSS version come from
 * /api/overlay/alerts-settings, polled every 4 s so dashboard saves apply live.
 *
 * Markup uses Streamlabs Alert Box ids and StreamElements class names so existing alert CSS
 * packs work; every URL switch and selector is documented in overlay/ALERTS.md (keep it, the
 * address builder in core/overlay_catalog.py and tests/test_overlay_compat.py in step).
 */
(() => {
  const params = new URLSearchParams(location.search);
  const preview = params.get("preview") === "1" || params.get("preview") === "true";
  const skinParam = (params.get("skin") || "").trim().toLowerCase();
  if (preview) document.body.classList.add("preview");

  // ── URL filters and per-source options (ALERTS.md "URL options") ──
  function list(key) {
    return (params.get(key) || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  }
  function numParam(key) {
    const raw = params.get(key);
    if (raw == null || raw.trim() === "") return null;
    const n = Number(raw);
    return isFinite(n) ? n : null;
  }
  function offParam(key) {
    const v = (params.get(key) || "").trim().toLowerCase();
    return v === "0" || v === "false" || v === "off" || v === "no";
  }

  // names streamers already use in Streamlabs / StreamElements URLs and widget settings
  const KIND_ALIASES = {
    follower: "follow", followers: "follow", sub: "subscribe", subs: "subscribe", subscriber: "subscribe",
    subscription: "subscribe", membership: "member", members: "member", milestone: "member_milestone",
    giftmembership: "member_gift", resubscribe: "resub", powerups: "powerup", "power-up": "powerup",
    celebrations: "celebration", charity_donation: "charity", hype: "hypetrain", hype_train: "hypetrain",
    hypetrains: "hypetrain",
    gifted: "gift", giftsub: "gift", subgift: "gift", cheer: "bits", bit: "bits", tip: "donation",
    tips: "donation", donate: "donation", sticker: "supersticker", jewel: "jewels", kick: "kicks",
  };
  // ?group=money|subs|community. `money` is also the set ?min= applies to.
  const GROUPS = {
    money: ["superchat", "supersticker", "jewels", "bits", "kicks", "donation", "powerup", "celebration", "charity"],
    subs: ["subscribe", "resub", "gift", "member", "member_milestone", "member_gift"],
    community: ["follow", "raid", "host", "hypetrain"],
  };
  const kindOf = (k) => KIND_ALIASES[k] || k;
  // YouTube memberships used to arrive as subscribe / resub / gift: a URL that names those
  // still gets the matching membership alerts (?platforms=twitch,kick keeps them out)
  const FAMILY = { member: "subscribe", member_milestone: "resub", member_gift: "gift" };
  const listed = (kinds, kind) => kinds.includes(kind) || (FAMILY[kind] && kinds.includes(FAMILY[kind]));
  const onlyPlatforms = list("platforms").concat(list("platform"));
  const onlyKinds = list("kinds").map(kindOf);
  list("group").forEach((g) => (GROUPS[g] || []).forEach((k) => onlyKinds.push(k)));
  const hideKinds = list("hide").map(kindOf);
  const minMoney = numParam("min");
  const minBits = numParam("min_bits");
  const minKicks = numParam("min_kicks");
  const showTests = !offParam("tests");
  const durationSec = numParam("duration");
  const muted = offParam("sound");
  const volumeParam = numParam("volume");
  // ?queue=: most alerts waiting in line (1..200, default 50).
  const queueMax = Math.max(1, Math.min(200, numParam("queue") || 50));
  const layout = ["above", "side", "banner"].includes((params.get("layout") || "").toLowerCase())
    ? params.get("layout").toLowerCase() : "above";
  const align = (params.get("align") || "").toLowerCase().replace("centre", "center");
  const cssSlot = (params.get("css") || "").trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").slice(0, 40);
  const tiersParam = params.get("tiers");
  // animate.css names (fadeIn, bounceIn, slideInLeft ...); packs can bring their own keyframes
  const animIn = (params.get("in") || "").replace(/[^A-Za-z]/g, "");
  const animOut = (params.get("out") || "").replace(/[^A-Za-z]/g, "");

  const wrapEl = document.getElementById("wrap");
  if (wrapEl) wrapEl.dataset.layout = layout;      // Streamlabs: [data-layout=above|side|banner]
  if (offParam("image")) document.body.classList.add("no-image");
  if (offParam("message")) document.body.classList.add("no-message");
  if (["left", "center", "right"].includes(align)) document.body.classList.add("align-" + align);
  if (animIn || animOut) document.body.classList.add("anim-named");
  if (animIn) document.documentElement.style.setProperty("--alert-in", animIn);
  if (animOut) document.documentElement.style.setProperty("--alert-out", animOut);

  function lower(v) { return String(v == null ? "" : v).toLowerCase(); }
  function isTokens(cur) { return ["bits", "bit", "kicks", "kick"].includes(lower(cur)); }

  // "is this alert for this source?" — every filter on the URL has to agree
  function wanted(data) {
    const kind = lower(data.kind);
    if (data.is_test && !showTests) return false;
    if (onlyPlatforms.length && !onlyPlatforms.includes(lower(data.platform))) return false;
    if (onlyKinds.length && !listed(onlyKinds, kind)) return false;
    if (listed(hideKinds, kind)) return false;
    const amt = data.amount == null ? null : Number(data.amount);
    if (amt != null && isFinite(amt)) {
      const cur = lower(data.currency);
      if (cur.startsWith("bit")) { if (minBits != null && amt < minBits) return false; }
      else if (cur.startsWith("kick")) { if (minKicks != null && amt < minKicks) return false; }
      else if (minMoney != null && GROUPS.money.includes(kind) && amt < minMoney) return false;
    }
    return true;
  }

  // tier-1 .. tier-4 like Streamlabs alert variations; bits and KICKs count 100 to the dollar
  let tierCuts = [5, 20, 100];
  // raw: "5,20,100" (from ?tiers= or the Alerts tab's tiers option): up to 3 amounts where
  // tier-2, tier-3 and tier-4 start. tierOf() returns 0 for alerts with no amount.
  function setTiers(raw) {
    const cuts = String(raw || "").split(",").map(Number).filter((n) => isFinite(n) && n > 0).sort((a, b) => a - b);
    if (cuts.length) tierCuts = cuts.slice(0, 3);
  }
  if (tiersParam) setTiers(tiersParam);
  function tierOf(data) {
    if (data.amount == null || !isFinite(Number(data.amount))) return 0;
    const value = isTokens(data.currency) ? Number(data.amount) / 100 : Number(data.amount);
    let tier = 1;
    tierCuts.forEach((cut) => { if (value >= cut) tier += 1; });
    return Math.min(4, tier);
  }

  const box = document.getElementById("alert-box");
  const kindEl = document.getElementById("alert-kind");
  const messageEl = document.getElementById("alert-message");
  const userMsgEl = document.getElementById("alert-user-message");
  const metaEl = document.getElementById("alert-meta");
  const idle = document.getElementById("idle-hint");
  const imgWrap = document.getElementById("alert-image-wrap");
  const imgEl = document.getElementById("alert-image");
  const videoEl = document.getElementById("alert-video");
  const customLink = document.getElementById("alerts-custom-css");

  // Fallback only: Core sends each alert's classes as css_classes (core/alerts.py KIND_CLASSES).
  // Keep the two lists and the table in ALERTS.md the same.
  const KIND_CLASSES = {
    follow: "follower-alert kind-follow",
    subscribe: "subscriber-alert kind-subscribe",
    resub: "subscriber-alert resub-alert kind-resub",
    gift: "sub-gift-alert gift-alert kind-gift",
    raid: "raid-alert kind-raid",
    host: "host-alert kind-host",
    bits: "cheer-alert bits-alert kind-bits",
    superchat: "superchat-alert donation-alert kind-superchat",
    donation: "donation-alert kind-donation",
    supersticker: "sticker-alert superchat-alert donation-alert kind-supersticker",
    jewels: "jewels-alert gift-alert donation-alert kind-jewels",
    kicks: "kicks-alert donation-alert kind-kicks",
    powerup: "powerup-alert cheer-alert bits-alert kind-powerup",
    celebration: "celebration-alert powerup-alert cheer-alert bits-alert kind-celebration",
    charity: "charity-alert donation-alert kind-charity",
    hypetrain: "hypetrain-alert hype-train-alert kind-hypetrain",
    member: "member-alert subscriber-alert kind-member",
    member_milestone: "member-alert subscriber-alert resub-alert kind-member_milestone",
    member_gift: "member-alert sub-gift-alert gift-alert kind-member_gift",
  };

  // queue: alerts waiting; busy: one is on screen. mediaMap / soundMap: kind -> file address
  // from the settings (Stored files). soundVolume: 0..1, ?volume= (0..100) wins over it.
  const queue = [];
  let busy = false;
  let lastCssVer = null;
  let mediaMap = {};
  let soundMap = {};
  let soundVolume = 0.8;
  const sounds = {};

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }


  // The "waiting for an alert" tile, only ever shown on the dashboard preview (?preview=1).
  function setIdle(on) {
    if (!idle) return;
    if (preview && on) idle.classList.remove("gone");
    else idle.classList.add("gone");
  }

  if (!preview) setIdle(false);

  function applySkin(skin) {
    const s = ["classic", "card", "custom"].includes(skin) ? skin : "classic";
    document.body.classList.remove("skin-classic", "skin-card", "skin-custom");
    document.body.classList.add("skin-" + s);
  }

  if (skinParam) applySkin(skinParam);

  // ?letters=wiggle: every letter of the name / amount gets "animated-letter animated wiggle"
  const letterAnim = (params.get("letters") || "").replace(/[^A-Za-z]/g, "");
  if (letterAnim) document.documentElement.style.setProperty("--letter-anim", letterAnim);
  // Takes already-escaped text, returns one span per character (escaped again on the way out).
  function letters(escaped) {
    const tmp = document.createElement("span");
    tmp.innerHTML = escaped;
    const cls = "animated-letter" + (letterAnim ? " animated " + letterAnim : "");
    return Array.from(tmp.textContent).map((ch) =>
      '<span class="' + cls + '">' + (ch === " " ? "&nbsp;" : escapeHtml(ch)) + "</span>").join("");
  }

  // the headline with its values wrapped like Streamlabs does: <span data-token="name">
  // plus Core's older .name / .amount / .months / .viewers classes, so either kind of pack CSS lands
  function wrapHeadline(data) {
    let html = escapeHtml(data.headline || "");
    // Streamlabs nests span[data-token] > span > one span per letter, which packs animate
    // (#alert-message > span > span { display: inline-block }, .animated-letter.wiggle)
    const wrap = (value, cls, token) =>
      '<span class="' + cls + '" data-token="' + token + '"><span>' + letters(value) + "</span></span>";
    const name = escapeHtml(data.display_name || data.username || "");
    if (name && html.indexOf(name) !== -1) {
      html = html.replace(name, wrap(name, "name alertbox-message-name", "name"));
    }
    const amt = data.amount_fmt ? escapeHtml(String(data.amount_fmt)) : "";
    if (amt && html.indexOf(amt) !== -1) {
      html = html.replace(amt, wrap(amt, "amount", "amount"));
    }
    const item = data.item ? escapeHtml(String(data.item)) : "";
    if (item && html.indexOf(item) !== -1 && item !== name) {
      html = html.replace(item, wrap(item, "item", "item"));
    }
    if (data.months != null) {
      const m = String(data.months);
      html = html.replace(m + " months", wrap(m, "months", "months") + " months");
    }
    if (data.level != null) {
      const l = String(data.level);
      html = html.replace("level " + l, "level " + wrap(l, "level", "level"));
    }
    if (data.viewers != null) {
      const v = String(data.viewers);
      html = html.replace(v + " viewers", wrap(v, "viewers", "count") + " viewers");
    }
    if (data.qty != null) {
      const q = String(data.qty);
      html = html.replace(q + " sub", wrap(q, "amount", "count") + " sub");
    }
    return html;
  }

  function clearMedia() {
    if (imgWrap) imgWrap.classList.remove("has-image", "has-video");
    if (imgEl) {
      imgEl.removeAttribute("src");
      imgEl.hidden = true;
    }
    if (videoEl) {
      try { videoEl.pause(); } catch (_) {}
      videoEl.removeAttribute("src");
      videoEl.load();
      videoEl.hidden = true;
    }
  }

  // a newer kind (Super Sticker, YouTube gift, KICKs) uses its older cousin's picture / sound
  // until it has its own; a sticker or gift's own picture comes before both
  function setMedia(kind, data) {
    clearMedia();
    const src = mediaMap[kind] || (data && data.image) || mediaMap[(data && data.falls_back) || ""];
    if (!src || !imgWrap) return;
    if (/\.(webm|mp4)(\?|$)/i.test(src) && videoEl) {
      videoEl.src = src;
      videoEl.hidden = false;
      imgWrap.classList.add("has-video");
      videoEl.play().catch(() => {});
      return;
    }
    if (imgEl) {
      imgEl.src = src;
      imgEl.hidden = false;
      imgWrap.classList.add("has-image");
    }
  }

  // one uploaded sound per kind (Admin → Alerts → Pictures and sounds); OBS plays without a click
  function playSound(kind, data) {
    const url = soundMap[kind] || soundMap[(data && data.falls_back) || ""];
    if (!url || muted) return;
    try {
      let a = sounds[url];
      if (!a) {
        a = new Audio(url);
        sounds[url] = a;
      }
      const vol = volumeParam != null ? volumeParam / 100 : Number(soundVolume);
      a.volume = Math.max(0, Math.min(1, vol || 0));
      a.currentTime = 0;
      a.play().catch(() => {});
    } catch (_) {}
  }

  // Entry point for each /ws alert: filter it for this source, queue it, start the queue.
  function show(data) {
    if (!data || !wanted(data)) return;
    if (queue.length >= queueMax) return;     // a flood past ?queue= is dropped, not stacked up
    queue.push(data);
    pump();
  }

  // classes and data-* attributes a stylesheet can pick one alert out by
  function boxClasses(data, kind, extra) {
    const plat = lower(data.platform);
    const out = ["alert-box", extra, "layout-" + layout];
    if (plat) out.push("platform-" + plat);
    if (plat === "youtube" && GROUPS.subs.includes(kind)) out.push("membership-alert");
    const tier = tierOf(data);
    if (tier) out.push("tier-" + tier);
    if (data.is_test) out.push("test-alert");
    return { names: out, tier };
  }

  function setData(data, kind, tier) {
    box.dataset.kind = kind;
    box.dataset.platform = lower(data.platform);
    box.dataset.amount = data.amount == null ? "" : String(data.amount);
    box.dataset.currency = data.currency || "";
    box.dataset.tier = tier ? String(tier) : "";
  }

  // Show the next queued alert: fill text, picture, sound, classes; after the duration play the
  // exit animation, then clear and move on to the next one.
  function pump() {
    if (busy || !queue.length) return;
    busy = true;
    setIdle(false);
    const data = queue.shift();
    const kind = String(data.kind || "follow");
    const extra = (data.css_classes && data.css_classes.length)
      ? data.css_classes.join(" ")
      : (KIND_CLASSES[kind] || "kind-follow");

    kindEl.textContent = data.title || kind;
    messageEl.innerHTML = wrapHeadline(data);
    userMsgEl.textContent = data.message || "";

    const bits = [];
    if (data.platform) bits.push(data.platform);
    if (data.is_test) bits.push("TEST");
    metaEl.innerHTML = bits
      .map((b) =>
        b === "TEST"
          ? '<span class="test-flag">TEST</span>'
          : escapeHtml(b)
      )
      .join(" · ");

    setMedia(kind, data);
    playSound(kind, data);
    const cls = boxClasses(data, kind, extra);
    setData(data, kind, cls.tier);
    // "animated fadeIn" / "animated fadeOut" are the animate.css names packs override
    box.className = cls.names.concat(["show", "animated", animIn || "fadeIn"]).join(" ");

    // on-screen time in ms: ?duration= (seconds) or Core's duration_ms, never under 1.5 s
    const ms = durationSec != null && durationSec > 0
      ? Math.max(1500, Math.min(60000, durationSec * 1000))
      : Math.max(1500, Number(data.duration_ms) || 6000);
    // how long the exit animation gets before the box is cleared: named animate.css exits
    // (?in= / ?out= or the custom skin) take longer than the built-in fade
    const named = document.body.classList.contains("anim-named") || document.body.classList.contains("skin-custom");
    setTimeout(() => {
      box.className = cls.names.concat(["hide", "animated", animOut || "fadeOut"]).join(" ");
      setTimeout(() => {
        box.className = "alert-box hidden";
        delete box.dataset.kind;
        clearMedia();
        busy = false;
        if (!queue.length) setIdle(true);
        pump();
      }, named ? 650 : 340);
    }, ms);
  }

  // Dashboard settings (core/alerts.py read_alert_settings). URL switches still win.
  async function loadSettings() {
    try {
      const res = await fetch("/api/overlay/alerts-settings?t=" + Date.now());
      if (!res.ok) return;
      const s = await res.json();
      if (!skinParam && s.skin) applySkin(s.skin);
      if (s.media && typeof s.media === "object") mediaMap = s.media;
      if (s.sounds && typeof s.sounds === "object") soundMap = s.sounds;
      if (s.options && s.options.sound_volume != null) soundVolume = Number(s.options.sound_volume);
      if (s.options && s.options.tiers && !tiersParam) setTiers(s.options.tiers);
      // ?css=money loads the saved slot "money" instead of the default custom CSS
      const slots = s.css_slots || {};
      const useSlot = cssSlot && cssSlot !== "default" && slots[cssSlot] != null;
      const ver = useSlot ? slots[cssSlot] : (s.css_version || 0);
      const href = (useSlot ? "alerts-css/" + cssSlot + ".css" : "alerts-custom.css") + "?v=" + ver;
      if (customLink && href !== lastCssVer) {
        lastCssVer = href;
        customLink.href = href;
      }
    } catch (_) {}
  }

  loadSettings();
  setInterval(loadSettings, 4000);

  const hint = window.FridgeHint || { set() {}, count() {} };
  let ws;
  let retryMs = 1000;

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(proto + "://" + location.host + "/ws");
    ws.onopen = () => {
      retryMs = 1000;
      hint.set("core", "Connected to Core, waiting for an alert (Alerts page → Fire test)");
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "alert" && msg.data) {
          hint.count("alerts");
          show(msg.data);
        }
      } catch (_) {}
    };
    ws.onclose = () => {
      hint.set("core", "Can't reach Core at " + location.host + " (is it running?), retrying");
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 1.5, 10000);
    };
    ws.onerror = () => {
      try { ws.close(); } catch (_) {}
    };
  }

  connect();
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 25000);
})();
