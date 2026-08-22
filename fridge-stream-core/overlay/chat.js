(() => {
  const MAX_MESSAGES = 30;
  const messagesEl = document.getElementById("messages");

  // URL filters: ?platform=kick | ?platforms=kick,twitch | omit = all
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

  // Kick embeds emotes as [emote:ID:NAME] in the message text
  const EMOTE_RE = /\[emote:(\d+):([^\]]+)\]/g;
  const EMOTE_URL = (id) => `https://files.kick.com/emotes/${id}/fullsize`;

  const PLATFORM_LABEL = {
    kick: "K",
    twitch: "T",
    youtube: "Y",
  };

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

  function renderMessageHtml(raw) {
    const parts = [];
    let last = 0;
    let m;
    const re = new RegExp(EMOTE_RE.source, "g");
    while ((m = re.exec(raw)) !== null) {
      if (m.index > last) {
        parts.push(escapeHtml(raw.slice(last, m.index)));
      }
      const id = m[1];
      const name = escapeHtml(m[2]);
      parts.push(
        `<img class="emote" src="${EMOTE_URL(id)}" alt="${name}" title="${name}" loading="lazy" />`
      );
      last = m.index + m[0].length;
    }
    if (last < raw.length) {
      parts.push(escapeHtml(raw.slice(last)));
    }
    return parts.join("") || "";
  }

  function badgeElements(user) {
    const badges = [];
    const seen = new Set();
    const list = (user.badges || []).map((b) => String(b).toLowerCase());

    const add = (key, label, cls) => {
      if (seen.has(key)) return;
      seen.add(key);
      badges.push(`<span class="badge ${cls}">${label}</span>`);
    };

    if (
      user.is_mod ||
      list.some(
        (b) =>
          b.includes("moderator") || b === "mod" || b.includes("broadcaster")
      )
    ) {
      if (list.some((b) => b.includes("broadcaster") || b.includes("owner"))) {
        add("bc", "Host", "broadcaster");
      } else {
        add("mod", "Mod", "mod");
      }
    }
    if (user.is_vip || list.some((b) => b.includes("vip"))) {
      add("vip", "VIP", "vip");
    }
    if (
      user.is_subscriber ||
      list.some(
        (b) =>
          b.includes("subscriber") ||
          b === "sub" ||
          b.includes("member") ||
          b.includes("sponsor")
      )
    ) {
      add("sub", "Sub", "sub");
    }
    if (list.some((b) => b.includes("og"))) {
      add("og", "OG", "og");
    }
    if (list.some((b) => b.includes("founder"))) {
      add("founder", "Founder", "founder");
    }

    if (!badges.length) return "";
    return `<span class="badges">${badges.join("")}</span>`;
  }

  function platformBadge(plat) {
    if (!showPlatformBadge) return "";
    const key = String(plat || "").toLowerCase();
    if (!key) return "";
    if (platformFilter.size === 1 && platformFilter.has(key)) return "";
    const label = PLATFORM_LABEL[key] || key.slice(0, 1).toUpperCase();
    return `<span class="plat plat-${escapeHtml(key)}" title="${escapeHtml(key)}">${label}</span>`;
  }

  function appendMessage(data) {
    if (!data || !data.message) return;
    if (!allowedPlatform(data.platform)) return;

    const user = data.user || {};
    const defaultColor =
      data.platform === "twitch"
        ? "#bf94ff"
        : data.platform === "youtube"
          ? "#ff4e45"
          : "#53fc18";
    const color = user.color || defaultColor;
    const name = escapeHtml(user.display_name || user.username || "unknown");
    const textHtml = renderMessageHtml(data.message);

    const row = document.createElement("div");
    row.className = "msg";
    if (data.platform) row.dataset.platform = data.platform;
    if (data.message_id) row.dataset.id = data.message_id;
    row.innerHTML =
      platformBadge(data.platform) +
      badgeElements(user) +
      `<span class="user" style="color:${escapeHtml(color)}">${name}</span>` +
      `<span class="text">${textHtml}</span>`;

    messagesEl.appendChild(row);

    while (messagesEl.children.length > MAX_MESSAGES) {
      messagesEl.removeChild(messagesEl.firstChild);
    }

    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function loadHistory(list) {
    if (!Array.isArray(list)) return;
    messagesEl.innerHTML = "";
    for (const item of list) {
      appendMessage(item);
    }
  }

  let ws;
  let retryMs = 1000;

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws`;
    ws = new WebSocket(url);

    ws.onopen = () => {
      retryMs = 1000;
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "chat" && msg.data) {
          appendMessage(msg.data);
        } else if (msg.type === "chat_history" && msg.data) {
          loadHistory(msg.data);
        }
      } catch (_) {}
    };

    ws.onclose = () => {
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 1.5, 10000);
    };

    ws.onerror = () => {
      try {
        ws.close();
      } catch (_) {}
    };
  }

  connect();

  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send("ping");
    }
  }, 25000);
})();
