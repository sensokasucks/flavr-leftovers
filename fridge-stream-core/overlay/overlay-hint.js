/*
 * A small line in the corner that says why an overlay is empty: Core not reachable, which
 * chat platforms are connected, the filter in the address, how many messages came in.
 *
 * Shown only when the page is opened in a normal browser tab (or the dashboard preview),
 * never inside OBS (window.obsstudio) unless the address has ?hint=1; ?hint=0 hides it, and so
 * does ?preview=1 (the dashboard's look previews).
 * Overlays call FridgeHint.set(key, text) and FridgeHint.count().
 */
(function () {
  const q = new URLSearchParams(location.search);
  const want = (q.get("hint") || "").toLowerCase();
  // not on the dashboard's own look previews (?preview=1), which show sample messages anyway
  const quiet = want === "0" || want === "false" || q.get("preview") === "1" || q.get("preview") === "true";
  const show = want === "1" || want === "true" || (!window.obsstudio && !quiet);
  const parts = { core: "Connecting to Core…", platforms: "", filter: "", count: "", note: "" };
  let messages = 0;
  let box = null;

  function render() {
    if (!show) return;
    if (!box) {
      box = document.createElement("div");
      box.className = "fridge-hint";
      box.setAttribute("role", "status");
      box.style.cssText =
        "position:fixed;left:8px;bottom:8px;z-index:99999;max-width:calc(100vw - 16px);" +
        "font:12px/1.4 system-ui,sans-serif;color:#e8ecf4;background:rgba(15,18,24,.85);" +
        "border:1px solid #2a3140;border-radius:6px;padding:4px 8px;pointer-events:none";
      (document.body || document.documentElement).appendChild(box);
    }
    box.textContent = Object.values(parts).filter(Boolean).join(" · ") +
      " (only shown outside OBS; add ?hint=0 to hide)";
  }

  async function platforms() {
    try {
      const h = await fetch("/api/health", { cache: "no-store" }).then((r) => r.json());
      const on = h.adapters || [];
      const up = h.connected || [];
      if (!on.length) parts.platforms = "no chat platform is switched on";
      else {
        parts.platforms = on.map((n) => n + (up.includes(n) ? " connected" : " not connected")).join(", ");
      }
    } catch (_) {
      parts.platforms = "";
    }
    render();
  }

  window.FridgeHint = {
    shown: show,
    set(key, text) {
      parts[key] = text || "";
      render();
    },
    count(label) {
      messages += 1;
      parts.count = messages + " " + (label || "messages") + " so far";
      render();
    },
  };

  if (show) {
    parts.count = "nothing received yet";
    const start = () => {
      render();
      platforms();
      setInterval(platforms, 10000);
    };
    if (document.body) start();
    else document.addEventListener("DOMContentLoaded", start);
  }
})();
