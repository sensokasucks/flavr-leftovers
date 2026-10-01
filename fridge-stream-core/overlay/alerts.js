(() => {
  const params = new URLSearchParams(location.search);
  const preview = params.get("preview") === "1" || params.get("preview") === "true";
  const skinParam = (params.get("skin") || "").trim().toLowerCase();
  if (preview) document.body.classList.add("preview");

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
  };

  const queue = [];
  let busy = false;
  let lastCssVer = null;
  let mediaMap = {};

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }


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

  function wrapHeadline(data) {
    let html = escapeHtml(data.headline || "");
    const name = escapeHtml(data.display_name || data.username || "");
    if (name && html.indexOf(name) !== -1) {
      html = html.replace(name, '<span class="name alertbox-message-name">' + name + "</span>");
    }
    const amt = data.amount_fmt ? escapeHtml(String(data.amount_fmt)) : "";
    if (amt && html.indexOf(amt) !== -1) {
      html = html.replace(amt, '<span class="amount">' + amt + "</span>");
    }
    if (data.months != null) {
      const m = String(data.months);
      html = html.replace(m + " months", '<span class="months">' + m + "</span> months");
    }
    if (data.viewers != null) {
      const v = String(data.viewers);
      html = html.replace(v + " viewers", '<span class="viewers">' + v + "</span> viewers");
    }
    if (data.qty != null) {
      const q = String(data.qty);
      html = html.replace(q + " sub", '<span class="amount">' + q + "</span> sub");
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

  function setMedia(kind) {
    clearMedia();
    const src = mediaMap[kind];
    if (!src || !imgWrap) return;
    if (/\.webm$/i.test(src) && videoEl) {
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

  function show(data) {
    if (!data) return;
    queue.push(data);
    pump();
  }

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

    setMedia(kind);
    box.className = "alert-box " + extra + " show";

    const ms = Math.max(1500, Number(data.duration_ms) || 6000);
    setTimeout(() => {
      box.classList.remove("show");
      box.classList.add("hide");
      setTimeout(() => {
        box.className = "alert-box hidden";
        clearMedia();
        busy = false;
        if (!queue.length) setIdle(true);
        pump();
      }, 340);
    }, ms);
  }

  async function loadSettings() {
    try {
      const res = await fetch("/api/overlay/alerts-settings?t=" + Date.now());
      if (!res.ok) return;
      const s = await res.json();
      if (!skinParam && s.skin) applySkin(s.skin);
      if (s.media && typeof s.media === "object") mediaMap = s.media;
      const ver = s.css_version || 0;
      if (customLink && ver !== lastCssVer) {
        lastCssVer = ver;
        customLink.href = "alerts-custom.css?v=" + ver;
      }
    } catch (_) {}
  }

  loadSettings();
  setInterval(loadSettings, 4000);

  let ws;
  let retryMs = 1000;

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(proto + "://" + location.host + "/ws");
    ws.onopen = () => {
      retryMs = 1000;
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "alert" && msg.data) show(msg.data);
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

  connect();
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 25000);
})();
