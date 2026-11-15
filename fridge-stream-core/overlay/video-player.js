/*
 * Video requests player (video-player.html). Core (core/video_requests.py player_state) says
 * what should play; this page only follows it:
 *   GET  /api/video-requests/player  -> {seq, paused, volume, show_title, title_seconds, show_next, next_seconds,
 *        gap: {left, total} | null, up_next: [{title, by, thumb, ...}], current: {id, video_id, title, by} | null}
 *        asked every POLL_MS. "seq" goes up whenever the video must (re)start (new video, skip, Play now).
 *        "gap" is the pause between two videos (auto-play): the "Up next" card counts it down.
 *   POST /api/video-requests/player/ended {id}       when YouTube's player says the video ended
 *   POST /api/video-requests/player/error {id, code} when it refuses the video (removed, not embeddable)
 * Core then moves the queue on (auto-play) and the next poll loads the next video.
 * The player is YouTube's IFrame API (https://www.youtube.com/iframe_api), so nothing is downloaded.
 */
(function () {
  "use strict";
  const POLL_MS = 1000;
  const params = new URLSearchParams(location.search);
  if (params.get("bg") === "black") document.body.classList.add("bg-black");
  const titleAllowed = params.get("title") !== "0";
  const nextAllowed = params.get("next") !== "0";

  const frame = document.getElementById("vp-frame");
  const titleBox = document.getElementById("vp-title");
  const startBtn = document.getElementById("vp-start");
  const nextBox = document.getElementById("vp-next");
  let player = null;          // YT.Player once the API is ready
  let ready = false;
  let shownSeq = -1;          // the seq the page last acted on
  let currentId = null;       // request id loaded now (ended / error reports name it)
  let reported = null;        // id already reported as ended / failed (report once)
  let titleTimer = 0;
  let wantPaused = false;

  // YouTube's script calls this global once it has loaded.
  window.onYouTubeIframeAPIReady = function () {
    player = new YT.Player("vp-player", {
      width: "100%", height: "100%",
      playerVars: { autoplay: 1, controls: 0, rel: 0, modestbranding: 1, playsinline: 1, iv_load_policy: 3, fs: 0, disablekb: 1 },
      events: {
        onReady: () => { ready = true; poll(); },
        onStateChange: onState,
        onError: (e) => report("error", { code: e.data }),
      },
    });
  };

  function onState(e) {
    if (e.data === YT.PlayerState.ENDED) report("ended", {});
    if (e.data === YT.PlayerState.PLAYING) startBtn.hidden = true;
  }

  /** Tell Core once per video that it ended / failed. */
  function report(kind, extra) {
    if (currentId == null || reported === currentId) return;
    reported = currentId;
    frame.classList.remove("on");
    fetch("/api/video-requests/player/" + kind, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ id: currentId }, extra)),
    }).catch(() => {});
  }

  function showTitle(cur, st) {
    clearTimeout(titleTimer);
    if (!titleAllowed || !st.show_title || !cur || !st.title_seconds) { titleBox.hidden = true; return; }
    document.getElementById("vp-title-text").textContent = cur.title || "";
    document.getElementById("vp-title-by").textContent = cur.by ? "requested by " + cur.by : "";
    titleBox.hidden = false;
    titleTimer = setTimeout(() => { titleBox.hidden = true; }, st.title_seconds * 1000);
  }

  /**
   * The "Up next" card. Shown (settings show_next) while the pause between two videos runs,
   * with the seconds left, and in the corner for the last next_seconds of the video playing.
   * Hidden when nothing is approved, and while the title card of a fresh video shows.
   */
  function showNext(st) {
    const nxt = (st.up_next || [])[0];
    let mode = "";
    if (nextAllowed && st.show_next && nxt) {
      if (st.gap) mode = "gap";
      else if (st.current && st.next_seconds > 0 && currentId === st.current.id && titleBox.hidden) {
        const left = (player.getDuration() || 0) - (player.getCurrentTime() || 0);
        if (player.getDuration() > 0 && left <= st.next_seconds && player.getPlayerState() === YT.PlayerState.PLAYING) mode = "corner";
      }
    }
    nextBox.hidden = !mode;
    if (!mode) return;
    nextBox.classList.toggle("gap", mode === "gap");
    document.getElementById("vp-next-head").textContent = mode === "gap" && st.gap.left > 0 ? "Up next in " + st.gap.left : "Up next";
    document.getElementById("vp-next-title").textContent = nxt.title || "";
    document.getElementById("vp-next-by").textContent = nxt.by ? "requested by " + nxt.by : "";
    const img = document.getElementById("vp-next-thumb");
    if (nxt.thumb && img.getAttribute("src") !== nxt.thumb) img.src = nxt.thumb;
    img.hidden = !nxt.thumb;
  }

  function apply(st) {
    if (!ready) return;
    player.setVolume(Math.max(0, Math.min(100, st.volume)));
    const cur = st.current;
    if (st.seq !== shownSeq) {
      shownSeq = st.seq;
      if (cur && cur.id !== currentId) {
        currentId = cur.id;
        reported = null;
        frame.classList.add("on");
        player.loadVideoById(cur.video_id);
        showTitle(cur, st);
        // a browser tab may block autoplay with sound: offer the one click it needs
        setTimeout(() => {
          const s = player.getPlayerState();
          if (currentId === cur.id && s !== YT.PlayerState.PLAYING && s !== YT.PlayerState.BUFFERING && !wantPaused) startBtn.hidden = false;
        }, 2500);
      } else if (!cur) {
        currentId = null;
        frame.classList.remove("on");
        titleBox.hidden = true;
        player.stopVideo();
      }
    }
    if (cur && st.paused !== wantPaused) {
      wantPaused = st.paused;
      if (wantPaused) player.pauseVideo(); else player.playVideo();
    }
    showNext(st);
  }

  async function poll() {
    try {
      const r = await fetch("/api/video-requests/player", { cache: "no-store" });
      if (r.ok) apply(await r.json());
    } catch (_) { /* Core restarting: try again next time */ }
  }

  startBtn.addEventListener("click", () => {
    startBtn.hidden = true;
    if (player && ready) { player.unMute(); player.playVideo(); }
  });
  setInterval(poll, POLL_MS);
})();
