/*
 * Helper for plugin dashboard pages (plugin.json "pages", served at /plugin-pages/<id>/...).
 * The dashboard shows the page in a frame; include this file and admin.css:
 *
 *   <link rel="stylesheet" href="/admin/admin.css" />
 *   <script src="/admin/plugin-page.js"></script>
 *
 * StreamCore.api(path, opts)  fetch with the dashboard's admin token; JSON back, errors thrown
 * StreamCore.token()          the admin token the dashboard keeps in this browser
 * StreamCore.escapeHtml(s)    for building HTML from data
 * StreamCore.go(tab, sub)     open another dashboard page (e.g. "config", "games")
 * StreamCore.resize()         tell the dashboard the page height changed (also done on its own)
 */
(function () {
  // Same localStorage keys as admin.js: keep the two files in step.
  const tokenKey = "stream_core_admin_token";
  const hcKey = "stream_core_high_contrast";

  function token() {
    try { return localStorage.getItem(tokenKey) || ""; } catch (_) { return ""; }
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // Errors come back as Error(detail) from FastAPI's {"detail": ...}, else "HTTP <status>".
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      ...opts,
      headers: { "Content-Type": "application/json", "X-Admin-Token": token(), ...(opts.headers || {}) },
    });
    const ct = res.headers.get("content-type") || "";
    const body = ct.includes("application/json") ? await res.json() : await res.text();
    if (!res.ok) {
      const detail = body && typeof body === "object" ? body.detail : body;
      throw new Error(typeof detail === "string" && detail ? detail : "HTTP " + res.status);
    }
    return body;
  }

  const inFrame = window.parent && window.parent !== window;

  // The dashboard sets the frame height from this message (the "message" listener in admin.js).
  function resize() {
    if (!inFrame) return;
    const h = Math.ceil(document.documentElement.scrollHeight);
    window.parent.postMessage({ type: "plugin-page-height", height: h }, location.origin);
  }

  // In a frame the dashboard switches page; opened on its own, it loads the dashboard address.
  function go(tab, sub) {
    if (inFrame) window.parent.postMessage({ type: "plugin-page-go", tab, sub: sub || "" }, location.origin);
    else location.href = "/admin/#" + tab + (sub ? "/" + sub : "");
  }

  // Same look as the dashboard, high contrast included
  try {
    const pref = localStorage.getItem(hcKey);
    const on = pref === null ? window.matchMedia("(prefers-contrast: more)").matches : pref === "1";
    document.documentElement.classList.toggle("hc", on);
  } catch (_) { /* storage blocked: default look */ }
  document.documentElement.classList.add("plugin-page");

  if (inFrame) {
    new ResizeObserver(resize).observe(document.documentElement);
    window.addEventListener("load", resize);
  }

  window.StreamCore = { api, token, escapeHtml, go, resize };
})();
