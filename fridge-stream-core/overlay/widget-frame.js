/*
 * Runs first inside a chat widget's frame (/widget-frame/<name>), before the widget's own code.
 *
 * The frame is sandboxed into a blank origin, so everything comes from the page around it
 * (overlay/widget.js) by postMessage: settings, chat, alerts. This file turns those into the
 * events the widget listens for:
 *   StreamElements: window "onWidgetLoad" / "onEventReceived", plus a stand-in SE_API
 *   Streamlabs:     document "onLoad" / "onEventReceived", and the chat box itself (fills the
 *                   widget's #chatlist_item template into #log)
 */
(function () {
  "use strict";
  const me = document.currentScript;
  const platform = (me && me.dataset.platform) || "streamelements";
  const parentWin = window.parent;
  const send = (msg) => { try { parentWin.postMessage(Object.assign({ fridge: msg.fridge }, msg), "*"); } catch (_) {} };

  // A sandboxed frame has no storage of its own; widgets that save things get a memory copy
  try {
    void window.localStorage.length;
  } catch (_) {
    const mem = {};
    const storage = {
      getItem: (k) => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
      setItem: (k, v) => { mem[k] = String(v); },
      removeItem: (k) => { delete mem[k]; },
      clear: () => { Object.keys(mem).forEach((k) => delete mem[k]); },
      key: (i) => Object.keys(mem)[i] || null,
      get length() { return Object.keys(mem).length; },
    };
    try { Object.defineProperty(window, "localStorage", { value: storage, configurable: true }); } catch (_) {}
    try { Object.defineProperty(window, "sessionStorage", { value: storage, configurable: true }); } catch (_) {}
  }

  // ── StreamElements' SE_API: the store is kept by the page around the frame ──
  let nextId = 1;
  const waiting = {};
  function ask(kind, payload) {
    return new Promise((resolve) => {
      const id = nextId++;
      waiting[id] = resolve;
      send(Object.assign({ fridge: kind, id }, payload));
      setTimeout(() => { if (waiting[id]) { delete waiting[id]; resolve(null); } }, 3000);
    });
  }
  window.SE_API = {
    store: {
      get: (key) => ask("store-get", { key: String(key) }),
      set: (key, value) => {
        const copy = JSON.parse(JSON.stringify(value === undefined ? null : value));
        send({ fridge: "store-set", key: String(key), value: copy });
        // SE tells every custom widget about a store change
        setTimeout(() => fire(window, "onEventReceived", { listener: "kvstore:update", event: { data: { key: "customWidget." + key, value: copy } } }), 0);
      },
    },
    counters: { get: (counter) => Promise.resolve({ counter, value: 0 }) },
    sanitize: (obj) => Promise.resolve({ result: { message: (obj && obj.message) || "" }, skip: false }),
    cheerFilter: (message) => Promise.resolve(message),
    setField: () => {},
    getOverlayStatus: () => ({ isEditorMode: false, muted: false }),
    resumeQueue: () => {},
  };

  function fire(target, name, detail) {
    target.dispatchEvent(new CustomEvent(name, { detail }));
  }

  // ── Streamlabs chat box ──
  let slHide = 0;
  const SL_MAX = 100;
  function slLog() {
    return document.getElementById("log") || document.querySelector(".sl__chat__layout") || document.body;
  }
  function slTemplate() {
    const t = document.getElementById("chatlist_item");
    return t ? t.innerHTML : '<div data-from="{from}" data-id="{messageId}"><span class="meta" style="color: {color}"><span class="badges"></span><span class="name">{from}</span></span><span class="message">{message}</span></div>';
  }
  function slAdd(item, detail) {
    const tpl = slTemplate();
    const html = tpl.replace(/\{(from|message|color|messageId|badges|platform|userId|avatar)\}/g, (_, k) => item[k] || "");
    const box = document.createElement("div");
    box.innerHTML = html.trim();
    const log = slLog();
    Array.from(box.children).forEach((el) => {
      if (!el.dataset.id) el.dataset.id = item.messageId;
      if (!el.dataset.from) el.dataset.from = item.from;
      el.dataset.platform = item.platform;
      el.dataset.userId = item.userId;
      const slot = el.querySelector(".badges");
      if (slot && !tpl.includes("{badges}") && !slot.children.length) slot.innerHTML = item.badges;
      log.appendChild(el);
      if (slHide > 0) setTimeout(() => el.remove(), slHide * 1000);
    });
    while (log !== document.body && log.children.length > SL_MAX) log.firstElementChild.remove();
    fire(document, "onEventReceived", detail);
  }
  function slRemove(ids, userId) {
    const log = slLog();
    Array.from(log.querySelectorAll("[data-id]")).forEach((el) => {
      if (ids.includes(el.dataset.id) || (userId && el.dataset.userId === userId)) el.remove();
    });
    ids.forEach((id) => fire(document, "onEventReceived", { command: "CLEARMSG", messageId: id, body: "" }));
  }

  window.addEventListener("message", (ev) => {
    if (ev.source !== parentWin) return;
    const m = ev.data || {};
    switch (m.fridge) {
      case "load":
        if (platform === "streamlabs") {
          slHide = Number(m.hide) || 0;
          fire(document, "onLoad", m.detail);
        } else {
          fire(window, "onWidgetLoad", m.detail);
        }
        break;
      case "event":
        fire(platform === "streamlabs" ? document : window, "onEventReceived", m.detail);
        break;
      case "session":
        fire(window, "onSessionUpdate", m.detail);
        break;
      case "sl-chat":
        slAdd(m.item || {}, m.detail || {});
        break;
      case "sl-remove":
        slRemove(m.ids || [], m.userId || "");
        break;
      case "store-result":
        if (waiting[m.id]) { waiting[m.id](m.value === undefined ? null : m.value); delete waiting[m.id]; }
        break;
      default:
        break;
    }
  });

  window.FridgeWidget = {
    platform,
    ready: () => send({ fridge: "ready" }),
  };
})();
