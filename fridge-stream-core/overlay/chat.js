(() => {
  const logEl = document.getElementById("log");
  const customLink = document.getElementById("chat-custom-css");

  // URL options: ?platform=kick | ?platforms=kick,twitch | omit = all
  //   ?badges=0 hides the K / T / Y platform letters, ?skin=classic|plain|custom,
  //   ?hide=12 (seconds, 0 = keep), ?avatars=1, ?sound=0, ?top=1 (newest on top), ?preview=1
  const params = new URLSearchParams(location.search);
  const platformFilter = new Set();
  const single = (params.get("platform") || "").trim().toLowerCase();
  if (single) platformFilter.add(single);
  const multi = (params.get("platforms") || "").trim().toLowerCase();
  if (multi) {
    multi.split(/[,+\s]+/).forEach((p) => {
      if (p) platformFilter.add(p);
    });
  }
  const showPlatformBadge = params.get("badges") !== "0";
  const skinParam = (params.get("skin") || "").trim().toLowerCase();
  const preview = params.get("preview") === "1" || params.get("preview") === "true";
  const SKINS = ["classic", "plain", "custom"];

  // Dashboard settings (Admin → Chat overlay). URL parameters win over these.
  const options = {
    hide_after_sec: 0,
    max_messages: 30,
    newest_on_top: false,
    show_avatars: false,
    sound_volume: 0.6,
    sound_min_gap_sec: 2,
  };
  const urlNum = (key) => (params.has(key) ? Number(params.get(key)) : null);
  const urlBool = (key) => (params.has(key) ? params.get(key) !== "0" && params.get(key) !== "false" : null);
  function effective() {
    const hide = urlNum("hide");
    return {
      hide: hide != null && Number.isFinite(hide) ? hide : options.hide_after_sec,
      max: Math.max(1, Number(options.max_messages) || 30),
      top: urlBool("top") ?? !!options.newest_on_top,
      avatars: urlBool("avatars") ?? !!options.show_avatars,
      sound: urlBool("sound") ?? true,
    };
  }

  let mediaMap = {};   // slot -> url (background, badge-mod, ...)
  let soundMap = {};   // slot -> url (message, paid)
  let lastCssVer = null;
  let historyLoading = false;
  let lastSoundAt = 0;
  const sounds = {};

  // Kick embeds emotes as [emote:ID:NAME] in the message text
  const EMOTE_RE = /\[emote:(\d+):([^\]]+)\]/g;
  const EMOTE_URL = (id) => `https://files.kick.com/emotes/${id}/fullsize`;

  const PLATFORM_LABEL = { kick: "K", twitch: "T", youtube: "Y" };
  const BADGE_LABEL = { broadcaster: "Host", mod: "Mod", vip: "VIP", sub: "Sub", og: "OG", founder: "Founder" };

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function allowedPlatform(plat) {
    if (!platformFilter.size) return true;
    return platformFilter.has(String(plat || "").toLowerCase());
  }

  function applySkin(skin) {
    const s = SKINS.includes(skin) ? skin : "classic";
    SKINS.forEach((k) => document.body.classList.remove("skin-" + k));
    document.body.classList.add("skin-" + s);
  }
  if (skinParam) applySkin(skinParam);

  // Twitch (native + BetterTTV / FrankerFaceZ / 7TV): Core sends emote ranges.
  // start/end are inclusive code-point indices, so split with Array.from.
  function renderRangesHtml(raw, emotes) {
    const chars = Array.from(raw);
    const list = emotes
      .filter((e) => Number.isInteger(e.start) && Number.isInteger(e.end) && e.url)
      .sort((a, b) => a.start - b.start);
    const parts = [];
    let pos = 0;
    for (const e of list) {
      if (e.start < pos || e.end >= chars.length) continue;
      if (e.start > pos) parts.push(escapeHtml(chars.slice(pos, e.start).join("")));
      const name = escapeHtml(e.name || chars.slice(e.start, e.end + 1).join(""));
      parts.push(`<img class="emote" src="${escapeHtml(e.url)}" alt="${name}" title="${name}" loading="lazy" />`);
      pos = e.end + 1;
    }
    if (pos < chars.length) parts.push(escapeHtml(chars.slice(pos).join("")));
    return parts.join("");
  }

  function renderMessageHtml(raw, emotes) {
    if (Array.isArray(emotes) && emotes.length) return renderRangesHtml(raw, emotes);
    const parts = [];
    let last = 0;
    let m;
    const re = new RegExp(EMOTE_RE.source, "g");
    while ((m = re.exec(raw)) !== null) {
      if (m.index > last) parts.push(escapeHtml(raw.slice(last, m.index)));
      const id = m[1];
      const name = escapeHtml(m[2]);
      parts.push(`<img class="emote" src="${EMOTE_URL(id)}" alt="${name}" title="${name}" loading="lazy" />`);
      last = m.index + m[0].length;
    }
    if (last < raw.length) parts.push(escapeHtml(raw.slice(last)));
    return parts.join("") || "";
  }

  // Which badges a chatter gets (keys match the picture slots badge-<key>)
  function badgeKeys(user) {
    const keys = [];
    const list = (user.badges || []).map((b) => String(b).toLowerCase());
    const hostLike = list.some((b) => b.includes("broadcaster") || b.includes("owner"));
    if (hostLike) keys.push("broadcaster");
    else if (user.is_mod || list.some((b) => b.includes("moderator") || b === "mod")) keys.push("mod");
    if (user.is_vip || list.some((b) => b.includes("vip"))) keys.push("vip");
    if (user.is_subscriber || list.some((b) => b.includes("subscriber") || b === "sub" || b.includes("member") || b.includes("sponsor"))) keys.push("sub");
    if (list.some((b) => b.includes("og"))) keys.push("og");
    if (list.some((b) => b.includes("founder"))) keys.push("founder");
    return keys;
  }

  function badgesHtml(user) {
    const keys = badgeKeys(user);
    if (!keys.length) return "";
    const items = keys.map((k) => {
      const pic = mediaMap["badge-" + k];
      const label = BADGE_LABEL[k] || k;
      if (pic) return `<img class="badge ${k}" src="${escapeHtml(pic)}" alt="${label}" title="${label}" />`;
      return `<span class="badge ${k}">${label}</span>`;
    });
    return `<span class="badges">${items.join("")}</span>`;
  }

  function platformBadge(plat) {
    if (!showPlatformBadge) return "";
    const key = String(plat || "").toLowerCase();
    if (!key) return "";
    if (platformFilter.size === 1 && platformFilter.has(key)) return "";
    const label = PLATFORM_LABEL[key] || key.slice(0, 1).toUpperCase();
    return `<span class="plat plat-${escapeHtml(key)}" title="${escapeHtml(key)}">${label}</span>`;
  }

  function avatarHtml(user) {
    if (!effective().avatars) return "";
    // Core's own copy first (/avatars/...), the platform's link until Core has it
    const url = user.avatar_local || user.profile_image_url;
    const attrs = url ? ` src="${escapeHtml(url)}"` : ` hidden`;
    return `<img class="avatar"${attrs} alt="" loading="lazy" />`;
  }

  function playSound(slot) {
    const eff = effective();
    if (!eff.sound || historyLoading) return;
    const url = soundMap[slot] || (slot !== "message" ? soundMap.message : null);
    if (!url) return;
    const now = Date.now();
    if (now - lastSoundAt < Number(options.sound_min_gap_sec || 0) * 1000) return;
    lastSoundAt = now;
    try {
      let a = sounds[url];
      if (!a) {
        a = new Audio(url);
        sounds[url] = a;
      }
      a.volume = Math.max(0, Math.min(1, Number(options.sound_volume) || 0));
      a.currentTime = 0;
      a.play().catch(() => {});       // browsers outside OBS need a click first
    } catch (_) {}
  }

  function scheduleHide(row) {
    const sec = Number(effective().hide) || 0;
    if (sec <= 0) return;
    setTimeout(() => {
      row.classList.add("hide");
      setTimeout(() => row.remove(), 450);
    }, sec * 1000);
  }

  function appendMessage(data) {
    if (!data || !data.message) return;
    if (!allowedPlatform(data.platform)) return;

    const user = data.user || {};
    const defaultColor = data.platform === "twitch" ? "#bf94ff" : data.platform === "youtube" ? "#ff4e45" : "#53fc18";
    const color = user.color || defaultColor;
    const name = escapeHtml(user.display_name || user.username || "unknown");
    const login = escapeHtml(user.username || user.display_name || "");
    const textHtml = renderMessageHtml(data.message, data.emotes);

    const row = document.createElement("div");
    row.className = "msg message-row";
    if (data.platform) row.dataset.platform = data.platform;
    if (data.message_id) row.dataset.id = data.message_id;
    row.dataset.from = login;
    row.dataset.sender = login;
    if (user.id != null) row.dataset.userId = String(user.id);
    if (data.is_paid) row.classList.add("paid");
    if (data.is_system) row.classList.add("system");
    // a reply made with the platform's reply button: "Replying to Name: what they said"
    let replyHtml = "";
    const r = data.reply_to;
    if (r && typeof r === "object" && r.user) {
      const quote = String(r.message || "").slice(0, 80);
      replyHtml = `<div class="reply">↩ Replying to <b>${escapeHtml(String(r.user))}</b>` +
        (quote ? `: ${escapeHtml(quote)}${String(r.message || "").length > 80 ? "…" : ""}` : "") + `</div>`;
    }
    row.innerHTML =
      replyHtml +
      avatarHtml(user) +
      `<span class="meta" style="color:${escapeHtml(color)}">` +
        platformBadge(data.platform) +
        badgesHtml(user) +
        `<span class="name user">${name}</span>` +
        `<span class="colon">:</span>` +
      `</span>` +
      `<span class="message text">${textHtml}</span>`;

    const eff = effective();
    if (eff.top) logEl.prepend(row);
    else logEl.appendChild(row);
    while (logEl.children.length > eff.max) {
      logEl.removeChild(eff.top ? logEl.lastChild : logEl.firstChild);
    }
    if (!eff.top) logEl.scrollTop = logEl.scrollHeight;
    scheduleHide(row);
    playSound(data.is_paid ? "paid" : "message");
  }

  function loadHistory(list) {
    if (!Array.isArray(list)) return;
    historyLoading = true;
    logEl.innerHTML = "";
    for (const item of list) appendMessage(item);
    historyLoading = false;
    if (preview && !logEl.children.length) showSample();
  }

  // a later user_update fills the avatar in: the platform's link (Kick / Twitch lookups),
  // then Core's saved copy; "hidden" (the chatter went on the hide list) takes it away
  function userUpdate(data) {
    if (!data || !data.id) return;
    const url = data.avatar_local || data.profile_image_url;
    if (!url && !data.hidden) return;
    const sel = `[data-platform="${CSS.escape(String(data.platform || ""))}"][data-user-id="${CSS.escape(String(data.id))}"] .avatar`;
    logEl.querySelectorAll(sel).forEach((img) => {
      if (data.hidden || !url) {
        img.removeAttribute("src");
        img.hidden = true;
        return;
      }
      img.src = url;
      img.hidden = false;
    });
  }

  // Made-up chatters for the dashboard preview when there is no chat yet
  function showSample() {
    const rows = [
      { platform: "kick", user: { username: "lunabyte", display_name: "LunaByte", color: "#53fc18", is_subscriber: true }, message: "hi everyone! first time seeing the 3D room" },
      { platform: "twitch", user: { username: "pixelpirate", display_name: "PixelPirate", color: "#bf94ff", is_mod: true }, message: "the curtain reveal was clean" },
      { platform: "youtube", user: { username: "marblemoth", display_name: "MarbleMoth", color: "#ff4e45" }, message: "love the podium lights" },
      { platform: "twitch", user: { username: "velvet_vole", display_name: "velvet_vole", color: "#e0a040", is_vip: true }, message: "this is what the chat overlay looks like", reply_to: { user: "MarbleMoth", message: "love the podium lights" } },
    ];
    historyLoading = true;
    rows.forEach(appendMessage);
    historyLoading = false;
  }

  async function loadSettings() {
    try {
      const res = await fetch("/api/overlay/chat-settings?t=" + Date.now());
      if (!res.ok) return;
      const s = await res.json();
      if (!skinParam && s.skin) applySkin(s.skin);
      if (s.options && typeof s.options === "object") Object.assign(options, s.options);
      if (s.media && typeof s.media === "object") mediaMap = s.media;
      if (s.sounds && typeof s.sounds === "object") soundMap = s.sounds;
      document.body.classList.toggle("newest-top", !!effective().top);
      document.documentElement.style.setProperty("--chat-bg-image", mediaMap.background ? `url("${mediaMap.background}")` : "none");
      const ver = s.css_version || 0;
      if (customLink && ver !== lastCssVer) {
        lastCssVer = ver;
        customLink.href = "chat-custom.css?v=" + ver;
      }
    } catch (_) {}
  }

  let ws;
  let retryMs = 1000;

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      retryMs = 1000;
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "chat" && msg.data) appendMessage(msg.data);
        else if (msg.type === "chat_history" && msg.data) loadHistory(msg.data);
        else if (msg.type === "user_update" && msg.data) userUpdate(msg.data);
      } catch (_) {}
    };
    ws.onclose = () => {
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 1.5, 10000);
    };
    ws.onerror = () => {
      try { ws.close(); } catch (_) {}
    };
  }

  // settings first (badge pictures, skin), then chat; settings keep refreshing so saves apply live
  loadSettings().finally(connect);
  setInterval(loadSettings, 4000);

  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 25000);
})();
