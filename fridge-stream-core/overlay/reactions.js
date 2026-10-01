/*
 * Fallback chat reactions overlay. Core sends {type:"reaction", data:{...}}
 * over /ws. We only draw route === "overlay" (or everything with ?any=1).
 * Text from chat is only ever set with textContent.
 */
(() => {
  const qs = new URLSearchParams(location.search);
  const ANY = qs.get("any") === "1";
  const DEBUG = qs.get("debug") === "1";
  const SCALE = Math.max(0.3, Math.min(4, Number(qs.get("scale")) || 1));
  const stage = document.getElementById("stage");
  const dbg = document.getElementById("debug");
  document.documentElement.style.setProperty("--rx-scale", String(SCALE));
  const MAX_LIVE = 250;

  function log(msg) {
    if (!DEBUG) return;
    dbg.hidden = false;
    const li = document.createElement("li");
    li.textContent = new Date().toLocaleTimeString() + " " + msg;
    dbg.prepend(li);
    while (dbg.children.length > 8) dbg.lastChild.remove();
  }

  const W = () => window.innerWidth;
  const H = () => window.innerHeight;
  const rand = (a, b) => a + Math.random() * (b - a);

  // stable 0..1 from a string: same chatter / target → same spot
  function hash01(s) {
    let h = 2166136261;
    for (const c of String(s || "")) {
      h ^= c.codePointAt(0);
      h = Math.imul(h, 16777619);
    }
    return ((h >>> 0) % 10000) / 10000;
  }

  function seatOf(user) {
    return { x: W() * (0.08 + 0.84 * hash01("seat:" + user)), y: H() + 40 };
  }

  function targetPoint(target, from) {
    if (!target) return { x: W() / 2, y: H() * 0.42 };
    if (target.type === "user") {
      const s = seatOf(target.name);
      return { x: s.x, y: H() * 0.86 };
    }
    if (target.name) {
      const t = hash01("target:" + target.name);
      return { x: W() * (0.25 + 0.5 * t), y: H() * (0.3 + 0.25 * hash01("y:" + target.name)) };
    }
    return { x: W() * rand(0.35, 0.65), y: H() * rand(0.32, 0.5) };
  }

  // An emoji / emote name, or the reaction's uploaded picture ("img:boot" → params.object_image).
  function obj(text, p) {
    const el = document.createElement("div");
    el.className = "rx-obj";
    const pic = p && p.object_image && p.object_image.url;
    // Core's own pictures, or an emote's picture from its platform CDN (https only)
    if (pic && (String(pic).startsWith("/reactions/images/") || /^https:\/\/[^\s"'<>]+$/.test(String(pic)))) {
      const img = document.createElement("img");
      img.className = "rx-img";
      img.alt = "";
      img.src = pic;
      el.appendChild(img);
    } else {
      el.textContent = String(text || "❓").slice(0, 16);
    }
    stage.appendChild(el);
    return el;
  }

  function tooMany() {
    return stage.childElementCount > MAX_LIVE;
  }

  function nameTag(text, x, y, ms) {
    const n = document.createElement("div");
    n.className = "rx-name";
    n.textContent = text;
    n.style.left = x + "px";
    n.style.top = y + "px";
    stage.appendChild(n);
    n.animate([{ opacity: 0 }, { opacity: 1, offset: 0.1 }, { opacity: 1, offset: 0.8 }, { opacity: 0 }], { duration: ms })
      .onfinish = () => n.remove();
  }

  function throwOne(d, delay) {
    const p = d.params || {};
    const from = seatOf(d.from.username);
    const to = targetPoint(d.target, from);
    to.x += rand(-30, 30);
    to.y += rand(-20, 20);
    const el = obj(p.object || "🍅", p);
    const arc = Math.max(0.2, Number(p.arc_height) || 1) * H() * 0.35;
    const mid = { x: (from.x + to.x) / 2, y: Math.min(from.y, to.y) - arc };
    const dur = 900;
    const frames = [];
    for (let i = 0; i <= 12; i++) {
      const t = i / 12;
      const x = (1 - t) * (1 - t) * from.x + 2 * (1 - t) * t * mid.x + t * t * to.x;
      const y = (1 - t) * (1 - t) * from.y + 2 * (1 - t) * t * mid.y + t * t * to.y;
      frames.push({ transform: `translate(${x}px, ${y}px) translate(-50%,-50%) rotate(${t * 540}deg)` });
    }
    const a = el.animate(frames, { duration: dur, delay, easing: "linear", fill: "both" });
    a.onfinish = () => {
      el.remove();
      impact(p.impact || "splat", to, p, d);
    };
  }

  function impact(kind, at, p, d) {
    const stickMs = Math.max(0, Number(p.stick_sec) || 0) * 1000;
    if (kind === "bounce") {
      const el = obj(p.object || "🍅", p);
      el.animate(
        [
          { transform: `translate(${at.x}px, ${at.y}px) translate(-50%,-50%)` },
          { transform: `translate(${at.x + rand(-120, 120)}px, ${at.y - 120}px) translate(-50%,-50%) rotate(200deg)` },
          { transform: `translate(${at.x + rand(-200, 200)}px, ${H() + 80}px) translate(-50%,-50%) rotate(400deg)` },
        ],
        { duration: 1100, easing: "ease-in" }
      ).onfinish = () => el.remove();
      return;
    }
    if (kind === "stick") {
      const el = obj(p.object || "🍅", p);
      el.style.transform = `translate(${at.x}px, ${at.y}px) translate(-50%,-50%) rotate(${rand(-30, 30)}deg)`;
      el.animate([{ opacity: 1 }, { opacity: 1, offset: 0.85 }, { opacity: 0 }], { duration: Math.max(800, stickMs) })
        .onfinish = () => el.remove();
      return;
    }
    // splat / shatter
    const s = document.createElement("div");
    s.className = "rx-splat";
    s.style.left = at.x + "px";
    s.style.top = at.y + "px";
    if (kind === "shatter") s.style.background = "radial-gradient(circle, #fff 0 8%, #9ad 30%, rgba(150,180,220,0) 70%)";
    stage.appendChild(s);
    s.animate(
      [
        { transform: "translate(-50%,-50%) scale(.2)", opacity: 1 },
        { transform: "translate(-50%,-50%) scale(1.1)", opacity: 0.95, offset: 0.08 },
        { transform: "translate(-50%,-40%) scale(1)", opacity: 0.9, offset: 0.8 },
        { transform: "translate(-50%,-30%) scale(1)", opacity: 0 },
      ],
      { duration: Math.max(900, stickMs) }
    ).onfinish = () => s.remove();
    if (d.target && d.target.type === "user") nameTag(d.target.name, at.x, at.y + 50, 1800);
  }

  function floatUp(d) {
    const p = d.params || {};
    const from = seatOf(d.from.username);
    const n = Math.min(40, Math.max(1, Number(p.count) || 5));
    const dur = Math.max(500, (Number(p.duration_sec) || 3) * 1000);
    for (let i = 0; i < n; i++) {
      const el = obj(p.object || "❤️", p);
      const x = from.x + rand(-40, 40);
      el.animate(
        [
          { transform: `translate(${x}px, ${H()}px) scale(.6)`, opacity: 0 },
          { opacity: 1, offset: 0.1 },
          { transform: `translate(${x + rand(-80, 80)}px, ${H() * rand(0.2, 0.5)}px) scale(1)`, opacity: 0 },
        ],
        { duration: dur, delay: i * 120, easing: "ease-out", fill: "both" }
      ).onfinish = () => el.remove();
    }
    nameTag(d.from.display_name || d.from.username, from.x, H() - 40, dur);
  }

  function fallDown(d, wide) {
    const p = d.params || {};
    const n = Math.min(wide ? 300 : 80, Math.max(1, Number(p.count) || (wide ? 40 : 12)));
    const dur = Math.max(1000, (Number(p.duration_sec) || (wide ? 6 : 4)) * 1000);
    const c = wide ? { x: W() / 2 } : targetPoint(d.target);
    const spread = wide ? W() / 2 : 160;
    for (let i = 0; i < n; i++) {
      const el = obj(p.object || "🌹", p);
      const x = c.x + rand(-spread, spread);
      const drift = rand(-60, 60);
      el.animate(
        [
          { transform: `translate(${x}px, -80px) rotate(0deg)` },
          { transform: `translate(${x + drift}px, ${H() + 80}px) rotate(${rand(-360, 360)}deg)` },
        ],
        { duration: dur * rand(0.7, 1.1), delay: rand(0, dur * 0.5), easing: "ease-in", fill: "both" }
      ).onfinish = () => el.remove();
    }
  }

  const RAINBOW = ["#ff3b6b", "#ffb400", "#53fc18", "#28c8ff", "#a55bff", "#ffffff"];
  function confetti(d) {
    const p = d.params || {};
    const colors = String(p.colors || "").split(",").map((s) => s.trim()).filter(Boolean);
    const pal = colors.length ? colors : RAINBOW;
    const at = d._at || targetPoint(d.target);
    const n = Math.min(400, Math.max(5, Number(p.count) || 80));
    for (let i = 0; i < n; i++) {
      const c = document.createElement("div");
      c.className = "rx-conf";
      c.style.background = pal[i % pal.length];
      stage.appendChild(c);
      const ang = rand(0, Math.PI * 2);
      const dist = rand(80, 380) * SCALE;
      const x2 = at.x + Math.cos(ang) * dist;
      const y2 = at.y + Math.sin(ang) * dist;
      c.animate(
        [
          { transform: `translate(${at.x}px, ${at.y}px) rotate(0deg)`, opacity: 1 },
          { transform: `translate(${x2}px, ${y2}px) rotate(${rand(180, 720)}deg)`, opacity: 1, offset: 0.35 },
          { transform: `translate(${x2 + rand(-40, 40)}px, ${y2 + 300}px) rotate(${rand(720, 1080)}deg)`, opacity: 0 },
        ],
        { duration: rand(1600, 2600), easing: "cubic-bezier(.2,.7,.3,1)" }
      ).onfinish = () => c.remove();
    }
  }

  // Fireworks: a few confetti bursts at random heights, one after another.
  function fireworks(d) {
    const p = d.params || {};
    const n = Math.min(30, Math.max(1, Number(p.count) || 6));
    const span = Math.max(1000, (Number(p.duration_sec) || 4) * 1000);
    for (let i = 0; i < n; i++) {
      setTimeout(() => {
        const x = W() * rand(0.15, 0.85);
        const y = H() * rand(0.15, 0.45);
        confetti({ params: { count: 60 }, target: null, _at: { x, y } });
      }, (i / n) * span);
    }
  }

  function bigShout(d) {
    const p = d.params || {};
    const who = d.from.display_name || d.from.username;
    let text = String(p.text || "{message}")
      .replace("{message}", d.message || "")
      .replace("{user}", who)
      .trim();
    if (!text) text = who;
    const el = document.createElement("div");
    el.className = "rx-shout";
    el.style.setProperty("--rx-color", /^#[0-9a-f]{3,8}$/i.test(p.color || "") ? p.color : "#ffd400");
    const small = document.createElement("small");
    small.textContent = who;
    el.appendChild(small);
    el.appendChild(document.createTextNode(text.slice(0, 200)));
    stage.appendChild(el);
    const dur = Math.max(1000, (Number(p.duration_sec) || 5) * 1000);
    el.animate(
      [
        { transform: "translateX(-50%) scale(.3)", opacity: 0 },
        { transform: "translateX(-50%) scale(1.08)", opacity: 1, offset: 0.08 },
        { transform: "translateX(-50%) scale(1)", opacity: 1, offset: 0.9 },
        { transform: "translateX(-50%) scale(.9)", opacity: 0 },
      ],
      { duration: dur }
    ).onfinish = () => el.remove();
  }

  function shake(d) {
    const p = d.params || {};
    const s = Math.max(0.05, Math.min(2, Number(p.strength) || 0.5)) * 18;
    const dur = Math.max(100, (Number(p.duration_sec) || 0.6) * 1000);
    const frames = [];
    for (let i = 0; i < 10; i++) frames.push({ transform: `translate(${rand(-s, s)}px, ${rand(-s, s)}px)` });
    frames.push({ transform: "translate(0,0)" });
    document.body.animate(frames, { duration: dur });
  }

  function play(d) {
    if (!d || !d.from) return;
    if (!ANY && d.route !== "overlay") return;
    if (tooMany()) {
      log("skipped (busy): " + d.reaction);
      return;
    }
    log(`${d.reaction} ${d.effect} from ${d.from.username}` + (d.target ? ` → ${d.target.type}:${d.target.name || ""}` : ""));
    const count = Math.max(1, Math.min(50, Number(d.count) || 1));
    switch (d.effect) {
      case "throw":
        for (let i = 0; i < count; i++) throwOne(d, i * 180);
        break;
      case "float_up":
        floatUp(d);
        break;
      case "fall_down":
        fallDown(d, false);
        break;
      case "rain":
        fallDown(d, true);
        break;
      case "confetti":
        confetti(d);
        break;
      case "big_shout":
        bigShout(d);
        break;
      case "camera_shake":
        shake(d);
        break;
      case "fireworks":
        fireworks(d);
        break;
      default:
        log("no overlay version of " + d.effect);
    }
  }

  let ws = null;
  let backoff = 1000;
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      backoff = 1000;
      log("connected");
    };
    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg && msg.type === "reaction") play(msg.data);
    };
    ws.onclose = () => {
      log("disconnected, retrying");
      setTimeout(connect, backoff);
      backoff = Math.min(15000, backoff * 1.6);
    };
    ws.onerror = () => {
      try { ws.close(); } catch {}
    };
  }
  connect();
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 25000);
})();
