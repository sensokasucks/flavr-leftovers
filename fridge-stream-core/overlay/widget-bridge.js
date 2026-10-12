/*
 * Chat widgets: Core's /ws packets -> the events StreamElements and Streamlabs widgets listen for.
 *
 * Pure functions (no DOM), used by overlay/widget.js and by tests (node).
 * StreamElements: onWidgetLoad {channel, currency, fieldData, ...} and onEventReceived
 *   {listener: "message" | "delete-message" | "delete-messages" | "follower-latest" | ...,
 *    event: {...}} in the shapes SE's own overlay sends.
 * Streamlabs: the chat box fills its #chatlist_item template ({from}, {message}, {color},
 *   {messageId}, {badges}) and fires onEventReceived with the message; alerts arrive in the
 *   Streamlabs socket shape {type, for, message: [{name, amount, ...}]}.
 * Kick and YouTube are dressed as the nearest Twitch thing (badges, tiers, cheers).
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.FridgeWidgetBridge = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const TWITCH_BADGE = (id) => `https://static-cdn.jtvnw.net/badges/v1/${id}/3`;
  // Twitch's global badge pictures (version 1)
  const BADGES = {
    broadcaster: { id: "5527c58c-fb7d-422d-b71b-f309dcb85cc1", text: "Broadcaster" },
    moderator: { id: "3267646d-33f0-4b17-b3df-f923a41db1d0", text: "Moderator" },
    vip: { id: "b817aba4-fad8-49e2-b88a-7cc744dfa6ec", text: "VIP" },
    subscriber: { id: "5d9f2208-5dd8-11e7-8513-2ff4adfae661", text: "Subscriber" },
    founder: { id: "511b78a9-ab37-472f-9569-457753bbe7d3", text: "Founder" },
    premium: { id: "bbbe0db0-a598-423e-86d0-f9fb98ca1933", text: "Prime Gaming" },
    partner: { id: "d12a2e27-16f6-41d0-ab77-b780518f00a3", text: "Verified" },
    turbo: { id: "bd444ec6-8f34-4bf9-91f4-af1e3428d80f", text: "Turbo" },
  };
  // Kick / YouTube / Core names -> Twitch's
  const BADGE_ALIAS = {
    owner: "broadcaster", host: "broadcaster", mod: "moderator", member: "subscriber", sponsor: "subscriber",
    sub: "subscriber", verified: "partner", prime: "premium",
  };
  // Core's chat picture slots (Chat overlay -> Pictures) for these, when uploaded
  const SLOT_FOR = { broadcaster: "badge-broadcaster", moderator: "badge-mod", vip: "badge-vip", subscriber: "badge-sub", founder: "badge-founder" };
  const KICK_EMOTE_RE = /\[emote:(\d+):([^\]]+)\]/g;
  const KICK_EMOTE_URL = (id) => `https://files.kick.com/emotes/${id}/fullsize`;
  const CURRENCY_SYMBOL = { USD: "$", CAD: "$", AUD: "$", NZD: "$", EUR: "€", GBP: "£", JPY: "¥", BRL: "R$", INR: "₹", KRW: "₩", PLN: "zł", SEK: "kr", NOK: "kr", DKK: "kr", CHF: "CHF", MXN: "$", RUB: "₽", TRY: "₺" };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function badgeKeys(user) {
    const out = [];
    const add = (k) => { if (k && !out.includes(k)) out.push(k); };
    (user.badges || []).forEach((b) => {
      const raw = String(b || "").toLowerCase().split("/")[0].trim();
      const k = BADGE_ALIAS[raw] || raw;
      if (BADGES[k]) add(k);
    });
    if (user.is_mod && !out.includes("broadcaster")) add("moderator");
    if (user.is_vip) add("vip");
    if (user.is_subscriber) add("subscriber");
    // Twitch shows the broadcaster first, then mod / vip, then sub
    const order = ["broadcaster", "moderator", "vip", "founder", "subscriber", "partner", "premium", "turbo"];
    return out.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  }

  function badgeList(user, media) {
    return badgeKeys(user).map((k) => ({
      type: k,
      version: "1",
      url: (media && media[SLOT_FOR[k]]) || TWITCH_BADGE(BADGES[k].id),
      description: BADGES[k].text,
    }));
  }

  // emote picture sizes 1x / 2x / 4x where the address says which
  function emoteUrls(url) {
    const u = String(url || "");
    let m = u.match(/^(.*\/emoticons\/v2\/[^/]+\/[^/]+\/[^/]+\/)(\d\.0)$/);
    if (m) return { 1: m[1] + "1.0", 2: m[1] + "2.0", 4: m[1] + "3.0" };
    m = u.match(/^(.*\/)([1-4])x(\.\w+)?$/); // BetterTTV / 7TV: .../2x(.webp)
    if (m) return { 1: m[1] + "1x" + (m[3] || ""), 2: m[1] + "2x" + (m[3] || ""), 4: m[1] + (m[3] ? "4x" : "3x") + (m[3] || "") };
    return { 1: u, 2: u, 4: u };
  }

  /* Core chat (text + emote ranges, or Kick's [emote:id:name] tokens) ->
   * {text with emote names, emotes: [{name, start, end, url, provider}]} */
  function plainText(data) {
    const raw = String(data.message || "");
    const list = Array.isArray(data.emotes) ? data.emotes.filter((e) => Number.isInteger(e.start) && Number.isInteger(e.end) && e.url) : [];
    if (list.length) {
      const chars = Array.from(raw);
      const emotes = list.map((e) => ({
        name: e.name || chars.slice(e.start, e.end + 1).join(""),
        id: String(e.id || ""),
        provider: e.provider || (String(e.url).includes("jtvnw") ? "twitch" : "other"),
        url: e.url, start: e.start, end: e.end, sticker: !!e.sticker, gift: !!e.gift,
        animated: !!e.animated,
      }));
      return { text: raw, emotes };
    }
    const emotes = [];
    let text = "";
    let last = 0;
    let m;
    const re = new RegExp(KICK_EMOTE_RE.source, "g");
    while ((m = re.exec(raw)) !== null) {
      text += raw.slice(last, m.index);
      const start = Array.from(text).length;
      const name = m[2];
      emotes.push({ name, id: m[1], provider: "kick", url: KICK_EMOTE_URL(m[1]), start, end: start + Array.from(name).length - 1 });
      text += name;
      last = m.index + m[0].length;
    }
    text += raw.slice(last);
    return { text, emotes };
  }

  /* Most StreamElements chat widgets find emotes by splitting the text on spaces and matching
   * whole words, as Twitch chat always has spaces around them. YouTube and Kick don't
   * (":_heart::_heart:", "hi[emote:1:wave]!"), so give every emote a space on each side. */
  function spaceEmotes(text, emotes) {
    const chars = Array.from(text);
    const out = [];
    const moved = [];
    let pos = 0;
    const blank = (c) => c === undefined || /\s/.test(c);
    [...emotes].sort((a, b) => a.start - b.start).forEach((e) => {
      if (e.start < pos || e.end >= chars.length || e.end < e.start) return;
      out.push(...chars.slice(pos, e.start));
      if (!blank(out[out.length - 1])) out.push(" ");
      const start = out.length;
      out.push(...chars.slice(e.start, e.end + 1));
      moved.push(Object.assign({}, e, { start, end: out.length - 1 }));
      pos = e.end + 1;
      if (!blank(chars[pos])) out.push(" ");
    });
    out.push(...chars.slice(pos));
    return { text: out.join(""), emotes: moved };
  }

  // text with emotes as <img> (escaped), what SE calls renderedText
  function renderedText(text, emotes, size) {
    const chars = Array.from(text);
    const parts = [];
    let pos = 0;
    [...emotes].sort((a, b) => a.start - b.start).forEach((e) => {
      if (e.start < pos || e.end >= chars.length) return;
      if (e.start > pos) parts.push(esc(chars.slice(pos, e.start).join("")));
      const url = emoteUrls(e.url)[size || 1];
      parts.push(`<img src="${esc(url)}" alt="${esc(e.name)}" title="${esc(e.name)}" class="emote" />`);
      pos = e.end + 1;
    });
    if (pos < chars.length) parts.push(esc(chars.slice(pos).join("")));
    return parts.join("");
  }

  function currencyInfo(code) {
    const c = String(code || "USD").toUpperCase();
    return { code: c, name: c, symbol: CURRENCY_SYMBOL[c] || c + " " };
  }

  // ── StreamElements ────────────────────────────────────────────────────
  // session data keeps "<kind>-latest" and "<kind>-recent" (newest first, 25 kept)
  function seRemember(session, ev) {
    const latest = ev.listener;
    session[latest] = ev.event;
    const recent = latest.replace(/-latest$/, "-recent");
    session[recent] = [ev.event].concat(session[recent] || []).slice(0, 25);
    return session;
  }

  function seLoadDetail(info, session) {
    const channel = String(info.channel || "");
    return {
      channel: { username: channel.toLowerCase(), apiToken: "", id: "", providerId: "", avatar: "" },
      currency: currencyInfo(info.currency),
      fieldData: Object.assign({}, info.values || {}),
      recents: [],
      session: { data: session || {}, settings: {} },
      overlay: { isEditorMode: false, muted: false },
      emotes: [],
    };
  }

  function seMessage(data, media) {
    const user = data.user || {};
    const plain = plainText(data);
    const { text, emotes } = spaceEmotes(plain.text, plain.emotes);
    const badges = badgeList(user, media);
    const keys = badges.map((b) => b.type);
    const isAction = /^\u0001ACTION /.test(text);
    const clean = isAction ? text.replace(/^\u0001ACTION /, "").replace(/\u0001$/, "") : text;
    const name = user.display_name || user.username || "";
    const userId = String(user.id || user.username || "");
    const msgId = String(data.message_id || "");
    const mod = keys.includes("moderator") || keys.includes("broadcaster");
    return {
      listener: "message",
      event: {
        service: data.platform || "twitch",
        data: {
          time: Math.round((Number(data.timestamp) || Date.now() / 1000) * 1000),
          tags: {
            "badge-info": "",
            badges: badges.map((b) => b.type + "/1").join(","),
            color: user.color || "",
            "display-name": name,
            emotes: "",
            flags: "",
            id: msgId,
            mod: mod ? "1" : "0",
            "room-id": "",
            subscriber: keys.includes("subscriber") || keys.includes("founder") ? "1" : "0",
            "tmi-sent-ts": String(Math.round((Number(data.timestamp) || Date.now() / 1000) * 1000)),
            turbo: keys.includes("turbo") ? "1" : "0",
            "user-id": userId,
            "user-type": mod && !keys.includes("broadcaster") ? "mod" : "",
            vip: keys.includes("vip") ? "1" : "0",
            "first-msg": "0",
          },
          nick: String(user.username || name).toLowerCase(),
          userId,
          displayName: name,
          displayColor: user.color || "",
          badges,
          channel: "",
          text: clean,
          isAction,
          emotes: emotes.map((e) => ({
            type: e.provider === "twitch" ? "twitch" : e.provider,
            name: e.name, id: e.id, gif: e.animated || /\.gif|animated/i.test(e.url), animated: e.animated,
            urls: emoteUrls(e.url), start: e.start, end: e.end,
          })),
          msgId,
        },
        renderedText: renderedText(clean, emotes, 1),
      },
    };
  }

  const TIER = { 1: "1000", 2: "2000", 3: "3000" };

  /* Core alert -> SE "*-latest" event, or null for kinds SE has nothing for */
  function seAlert(a) {
    const name = a.display_name || a.username || "Someone";
    const base = { name, displayName: name, providerId: "", isTest: !!a.is_test, message: a.message || "" };
    const amount = Number(a.amount) || 0;
    const tier = TIER[a.tier] || "1000";
    switch (a.kind) {
      case "follow":
        return { listener: "follower-latest", event: base };
      case "subscribe":
      case "member":
        return { listener: "subscriber-latest", event: { ...base, amount: 1, tier, gifted: false, bulkGifted: false, isCommunityGift: false } };
      case "resub":
      case "member_milestone":
        return { listener: "subscriber-latest", event: { ...base, amount: Number(a.months) || 1, tier, gifted: false, bulkGifted: false, isCommunityGift: false } };
      case "gift":
      case "member_gift": {
        const qty = Number(a.qty) || 1;
        // Core doesn't know who got single gifts; both read as "<gifter> gifted N subs"
        return { listener: "subscriber-latest", event: { ...base, sender: name, amount: qty, tier, gifted: true, bulkGifted: true, isCommunityGift: false } };
      }
      case "raid":
        return { listener: "raid-latest", event: { ...base, amount: Number(a.viewers) || 0 } };
      case "host":
        return { listener: "host-latest", event: { ...base, amount: Number(a.viewers) || 0 } };
      case "bits":
      case "powerup":
      case "kicks":
        return { listener: "cheer-latest", event: { ...base, amount: Math.round(amount) } };
      case "superchat":
      case "supersticker":
      case "donation":
      case "jewels":
      case "charity":
        return { listener: "tip-latest", event: { ...base, amount, currency: a.currency || "" } };
      default:
        return null;
    }
  }

  // ── Streamlabs ────────────────────────────────────────────────────────
  function slMessage(data, media) {
    const user = data.user || {};
    const { text, emotes } = plainText(data);
    const badges = badgeList(user, media);
    const name = user.display_name || user.username || "";
    const keys = badges.map((b) => b.type);
    return {
      // what the chat box fills its #chatlist_item template with
      item: {
        from: esc(name),
        message: renderedText(text, emotes, 2),
        color: esc(user.color || ""),
        messageId: esc(String(data.message_id || "")),
        badges: badges.map((b) => `<img src="${esc(b.url)}" class="badge ${esc(b.type)}-icon" alt="${esc(b.description)}" />`).join(""),
        platform: esc(data.platform || ""),
        userId: esc(String(user.id || "")),
        avatar: esc(user.avatar_local || user.profile_image_url || ""),
      },
      // and the detail of the onEventReceived it fires afterwards
      detail: {
        command: "PRIVMSG",
        platform: data.platform || "twitch",
        messageId: String(data.message_id || ""),
        from: name,
        owner: keys.includes("broadcaster"),
        body: text,
        tags: {
          badges: badges.map((b) => b.type + "/1").join(","),
          color: user.color || "",
          "display-name": name,
          id: String(data.message_id || ""),
          mod: keys.includes("moderator") ? "1" : "0",
          subscriber: keys.includes("subscriber") ? "1" : "0",
          vip: keys.includes("vip") ? "1" : "0",
          "user-id": String(user.id || ""),
        },
        emotes: emotes.map((e) => ({ name: e.name, start: e.start, end: e.end, url: e.url })),
      },
    };
  }

  const SL_TYPE = {
    follow: "follow", subscribe: "subscription", member: "subscription", resub: "resub", member_milestone: "resub",
    gift: "subscription", member_gift: "subscription", raid: "raid", host: "host", bits: "bits", powerup: "bits",
    kicks: "bits", superchat: "superchat", supersticker: "superchat", donation: "donation", jewels: "donation",
    charity: "donation",
  };
  const SL_FOR = { twitch: "twitch_account", youtube: "youtube_account", kick: "twitch_account" };

  function slAlert(a) {
    const type = SL_TYPE[a.kind];
    if (!type) return null;
    const name = a.display_name || a.username || "Someone";
    const amount = a.kind === "raid" || a.kind === "host" ? Number(a.viewers) || 0
      : a.kind === "resub" || a.kind === "member_milestone" ? Number(a.months) || 1
        : a.kind === "gift" || a.kind === "member_gift" ? Number(a.qty) || 1
          : Number(a.amount) || 0;
    return {
      type,
      for: SL_FOR[a.platform] || "streamlabs",
      message: [{
        name, from: name, amount, months: Number(a.months) || 1, message: a.message || "",
        formatted_amount: a.amount_fmt || String(amount), currency: a.currency || "",
        sub_plan: "1000", gifter: a.kind === "gift" || a.kind === "member_gift" ? name : undefined,
        isTest: !!a.is_test, _id: a.id || "",
      }],
    };
  }

  return {
    esc, badgeKeys, badgeList, emoteUrls, plainText, spaceEmotes, renderedText, currencyInfo,
    seLoadDetail, seRemember, seMessage, seAlert, slMessage, slAlert, BADGES,
  };
});
