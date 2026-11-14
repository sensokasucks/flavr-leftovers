/*
 * Video requests player (video-player.html). Core (core/video_requests.py player_state) says
 * what should play; this page only follows it:
 *   GET  /api/video-requests/player  -> {seq, paused, volume, show_title, title_seconds, current: {id, video_id, title, by} | null}
 *        asked every POLL_MS. "seq" goes up whenever the video must (re)start (new video, skip, Play now).
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

  const frame = document.getElementById("vp-frame");
  const titleBox = document.getElementById("vp-title");
  const startBtn = document.getElementById("vp-start");
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
