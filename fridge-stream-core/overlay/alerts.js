(() => {
  const params = new URLSearchParams(location.search);
  const preview = params.get("preview") === "1" || params.get("preview") === "true";
  const skinParam = (params.get("skin") || "").trim();

  const wrap = document.getElementById("wrap");
  const box = document.getElementById("alert-box");
  const idle = document.getElementById("idle-hint");
  const kindEl = document.getElementById("alert-kind");
  const msgEl = document.getElementById("alert-message");
  const userMsgEl = document.getElementById("alert-user-message");
  const metaEl = document.getElementById("alert-meta");
  const imgEl = document.getElementById("alert-image");
  const videoEl = document.getElementById("alert-video");
  const customCss = document.getElementById("alerts-custom-css");

  let durationMs = 6000;
  let skin = "classic";
  let queue = [];
  let showing = false;
  let ws = null;

  if (preview) document.body.classList.add("preview");

  function applySkin(s) {
    skin = s || "classic";
    document.body.classList.remove("skin-classic", "skin-card", "skin-custom");
    document.body.classList.add("skin-" + (skin === "custom" ? "custom" : skin === "card" ? "card" : "classic"));
  }

  async function loadSettings() {
    try {
      const r = await fetch("alerts-settings.json?_=" + Date.now());
      if (r.ok) {
        const data = await r.json();
        if (data.duration_ms) durationMs = Math.max(1500, Math.min(30000, +data.duration_ms || 6000));
        if (data.skin) applySkin(data.skin);
      }
    } catch (e) {}
    if (skinParam) applySkin(skinParam);
    try {
      if (customCss) customCss.href = "alerts-custom.css?_=" + Date.now();
    } catch (e) {}
  }

  function mediaUrl(kind) {
    const base = "assets/alerts/" + kind;
    return [base + ".webm", base + ".gif", base + ".png", base + ".webp", base + ".jpg"];
  }

  function clearMedia() {
    imgEl.removeAttribute("src");
    imgEl.style.display = "none";
    videoEl.removeAttribute("src");
    videoEl.style.display = "none";
    try { videoEl.pause(); } catch (e) {}
  }

  function tryMedia(kind) {
    clearMedia();
    const urls = mediaUrl(kind);
    let i = 0;
    function next() {
      if (i >= urls.length) return;
      const url = urls[i++];
      if (url.endsWith(".webm")) {
        videoEl.onerror = () => next();
        videoEl.onloadeddata = () => { videoEl.style.display = "block"; videoEl.play().catch(() => {}); };
        videoEl.src = url;
      } else {
        const probe = new Image();
        probe.onload = () => { imgEl.src = url; imgEl.style.display = "block"; };
        probe.onerror = () => next();
        probe.src = url;
      }
    }
    next();
  }

  function kindClass(kind) {
    const map = {
      follow: "follower-alert",
      subscribe: "subscriber-alert",
      resub: "resub-alert",
      gift: "sub-gift-alert",
      raid: "raid-alert",
      host: "host-alert",
      bits: "cheer-alert",
      superchat: "superchat-alert",
      donation: "donation-alert",
    };
    return map[kind] || (kind + "-alert");
  }

  function formatMessage(payload) {
    const name = payload.name || "Viewer";
    let text = payload.text || payload.title || "";
    // wrap name / amount for CSS targeting
    if (name && text.includes(name)) {
      text = text.replace(name, '<span class="name">' + escapeHtml(name) + "</span>");
    }
    if (payload.amount != null && payload.amount !== "") {
      const a = String(payload.amount);
      if (text.includes(a)) text = text.replace(a, '<span class="amount">' + escapeHtml(a) + "</span>");
    }
    return text;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function show(payload) {
    return new Promise((resolve) => {
      showing = true;
      if (idle) idle.style.display = "none";
      box.className = "alert-box " + kindClass(payload.kind || "");
      if (payload.test) box.classList.add("test-alert");
      kindEl.textContent = payload.label || payload.kind || "";
      msgEl.innerHTML = formatMessage(payload);
      userMsgEl.textContent = payload.user_message || "";
      userMsgEl.style.display = payload.user_message ? "block" : "none";
      const bits = [];
      if (payload.test) bits.push("TEST");
      if (payload.platform) bits.push(String(payload.platform).toUpperCase());
      metaEl.textContent = bits.join(" · ");
      tryMedia(payload.kind || "");
      box.classList.remove("hidden");
      box.classList.add("show");
      const ms = durationMs;
      setTimeout(() => {
        box.classList.remove("show");
        box.classList.add("hidden");
        clearMedia();
        showing = false;
        resolve();
        pump();
      }, ms);
    });
  }

  function enqueue(payload) {
    if (!payload) return;
    queue.push(payload);
    pump();
  }

  function pump() {
    if (showing || !queue.length) return;
    const next = queue.shift();
    show(next);
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = proto + "://" + location.host + "/ws";
    ws = new WebSocket(url);
    ws.onopen = () => {
      try { ws.send(JSON.stringify({ type: "subscribe", channel: "alerts" })); } catch (e) {}
    };
    ws.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch (e) { return; }
      if (data.type === "alert" || data.type === "stream_alert") {
        enqueue(data.alert || data.payload || data);
      }
      if (data.type === "alert_settings" && data.settings) {
        if (data.settings.duration_ms) durationMs = +data.settings.duration_ms;
        if (data.settings.skin) applySkin(data.settings.skin);
      }
    };
    ws.onclose = () => setTimeout(connect, 2000);
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
  }

  loadSettings().then(() => {
    connect();
    if (preview && params.get("demo") === "1") {
      enqueue({
        kind: "follow",
        label: "Follow",
        name: "PreviewUser",
        text: "PreviewUser followed!",
        test: true,
      });
    }
  });

  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 25000);
})();
