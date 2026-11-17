/*
 * Video requests queue overlay (video-queue.html). Core (core/video_requests.py player_state)
 * says what plays and what is next; this page only draws it:
 *   GET /api/video-requests/player -> {now: {title, by, length, thumb} | null,
 *        up_next: [{title, by, length, thumb}, ...] (approved, in play order, at most 5),
 *        gap: {left, total} | null (the pause between two videos; "left" = seconds to go)}
 *   asked every POLL_MS. Nothing is sent back: the page has no buttons.
 * The whole list hides while nothing plays and nothing is approved.
 */
(function () {
  "use strict";
  const POLL_MS = 1000;
  const params = new URLSearchParams(location.search);
  const count = Math.max(1, Math.min(5, parseInt(params.get("count") || "3", 10) || 3));
  const showNow = params.get("now") !== "0";
  const thumbs = params.get("thumbs") !== "0";
  if (params.get("align") === "right") document.body.classList.add("align-right");

  const box = document.getElementById("vq");
  const nowRow = document.getElementById("vq-now");
  const head = document.getElementById("vq-head");
  const list = document.getElementById("vq-list");
  let last = "";       // the last drawn state as text: redraw only when something changed

  function esc(t) {
    return String(t == null ? "" : t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }
  /** Seconds -> "3:07" / "1:02:15"; "" when the length isn't known. */
  function fmtLen(sec) {
    if (sec == null) return "";
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
  }
  function row(item, lead) {
    const pic = thumbs && item.thumb ? `<img src="${esc(item.thumb)}" alt="">` : "";
    const meta = [fmtLen(item.length), item.by ? "requested by " + esc(item.by) : ""].filter(Boolean).join(" · ");
    return `${lead}${pic}<div class="vq-text"><div class="vq-title">${esc(item.title)}</div><div class="vq-meta">${meta}</div></div>`;
  }

  function draw(st) {
    const next = (st.up_next || []).slice(0, count);
    const now = showNow ? st.now : null;
    const gapLeft = st.gap ? st.gap.left : -1;
    const key = JSON.stringify([now, next, gapLeft]);
    if (key === last) return;
    last = key;
    box.hidden = !now && !next.length;
    nowRow.hidden = !now;
    if (now) nowRow.innerHTML = row(now, "").replace('<div class="vq-title">', '<div class="vq-label">Now playing</div><div class="vq-title">');
    head.hidden = !next.length;
    head.textContent = gapLeft > 0 ? "Up next in " + gapLeft : "Up next";
    list.innerHTML = next.map((i, n) => `<div class="vq-row">${row(i, `<span class="vq-num">${n + 1}</span>`)}</div>`).join("");
  }

  async function poll() {
    try {
      const r = await fetch("/api/video-requests/player", { cache: "no-store" });
      if (r.ok) draw(await r.json());
    } catch (_) { /* Core restarting: try again next time */ }
  }
  poll();
  setInterval(poll, POLL_MS);
})();
