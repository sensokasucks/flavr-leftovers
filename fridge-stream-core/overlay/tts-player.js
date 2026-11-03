/*
 * Text-to-speech player for the alerts overlay (/overlay/alerts.html loads this before alerts.js).
 *
 * Core (core/tts.py) sends three packets on /ws:
 *   {"type": "tts", "data": {id, url, alert_id, platform, volume, trigger}}  a line is ready:
 *       url is /tts/<file> (audio Core got from the streamer's TTS server), volume 0..100
 *   {"type": "tts_skip", "data": {alert_id}}   that alert's voice won't come (filtered, server down)
 *   {"type": "tts_control", "data": {action: "skip" | "clear"}}   the dashboard's Skip / Clear
 *
 * Lines play one at a time, oldest first. A line tied to an alert (alert_id) waits until that
 * alert is on screen and its own sound has finished; alerts.js asks forAlert() when it shows an
 * alert whose payload has "tts": {"wait_ms"} and keeps the alert up until the promise settles.
 * Lines for alerts this source never showed (filtered out by ?platforms= / ?kinds= ...) are
 * ignored, so each voice plays once even with several alert sources.
 *
 * URL options (overlay/ALERTS.md): ?tts=0 never plays voices on this source; ?tts_volume=60
 * sets this source's voice volume (%) instead of the dashboard's. Lines not tied to an alert
 * (chat, !tts, highlights, plugins) also follow ?platforms=.
 */
(() => {
  const params = new URLSearchParams(location.search);
  const off = ["0", "false", "off", "no"].includes((params.get("tts") || "").trim().toLowerCase());
  const volParam = params.get("tts_volume");
  const volumeOverride = volParam != null && volParam.trim() !== "" && isFinite(Number(volParam)) ? Number(volParam) : null;
  const onlyPlatforms = ((params.get("platforms") || "") + "," + (params.get("platform") || ""))
    .split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  // A line longer than this (ms) is cut off, so a broken file can't block the queue for ever.
  const MAX_LINE_MS = 120000;
  // How many alert ids to remember (shown alerts and early-arriving voices).
  const REMEMBER = 200;

  const queue = [];          // [{item, done}] waiting to play
  let playing = null;        // {audio, done, timer}
  const shown = new Set();   // alert ids this source accepted (alerts.js calls accept())
  const finished = new Set(); // alert ids whose wait is over (played, skipped or gave up)
  const early = new Map();   // alert_id -> item: voice arrived before its alert was on screen
  const waiting = new Map(); // alert_id -> {resolve, timer, ready}: alert on screen, voice not here yet

  function remember(set, id) {
    set.add(id);
    if (set.size > REMEMBER) set.delete(set.values().next().value);
  }

  function volumeOf(item) {
    const v = volumeOverride != null ? volumeOverride : Number(item.volume);
    return Math.max(0, Math.min(1, (isFinite(v) ? v : 80) / 100));
  }

  // Play the next line when nothing is playing.
  function pump() {
    if (playing || !queue.length) return;
    const { item, done } = queue.shift();
    let audio;
    try {
      audio = new Audio(item.url);
    } catch (_) {
      if (done) done();
      pump();
      return;
    }
    audio.volume = volumeOf(item);
    const finish = () => {
      if (!playing || playing.audio !== audio) return;
      clearTimeout(playing.timer);
      playing = null;
      if (done) done();
      pump();
    };
    playing = { audio, done, timer: setTimeout(finish, MAX_LINE_MS), finish };
    audio.onended = finish;
    audio.onerror = finish;
    audio.play().catch(finish);
  }

  function enqueue(item, done) {
    queue.push({ item, done });
    pump();
  }

  // The voice for a shown alert is here: play it once the alert's own sound has ended.
  function startForAlert(id, item) {
    const w = waiting.get(id);
    if (!w) return;
    waiting.delete(id);
    clearTimeout(w.timer);
    w.ready.then(() => enqueue(item, () => { remember(finished, id); w.resolve(); }));
  }

  // A {"type": "tts"} packet.
  function onLine(item) {
    if (off || !item || !item.url) return;
    const id = item.alert_id ? String(item.alert_id) : "";
    if (id) {
      if (!shown.has(id)) {
        // not seen yet: either it is still in this source's queue, or this source filters it out.
        // Kept until the alert shows (accept() marks it seen first, so a filtered one never plays).
        early.set(id, item);
        if (early.size > REMEMBER) early.delete(early.keys().next().value);
        return;
      }
      if (waiting.has(id)) return startForAlert(id, item);
      // the alert already gave up waiting and went: a late paid voice still plays
      if (finished.has(id)) return enqueue(item, null);
      early.set(id, item);
      return;
    }
    const plat = String(item.platform || "").toLowerCase();
    if (onlyPlatforms.length && plat && !onlyPlatforms.includes(plat)) return;
    enqueue(item, null);
  }

  function onSkip(data) {
    const id = data && data.alert_id ? String(data.alert_id) : "";
    if (!id) return;
    early.delete(id);
    const w = waiting.get(id);
    if (w) {
      waiting.delete(id);
      clearTimeout(w.timer);
      remember(finished, id);
      w.resolve();
    }
  }

  function onControl(data) {
    const action = data && data.action;
    if (action === "clear") {
      const dropped = queue.splice(0);
      dropped.forEach((q) => { if (q.done) q.done(); });
      waiting.forEach((w, id) => { clearTimeout(w.timer); remember(finished, id); w.resolve(); });
      waiting.clear();
      early.clear();
    }
    if ((action === "skip" || action === "clear") && playing) {
      try { playing.audio.pause(); } catch (_) {}
      playing.finish();
    }
  }

  // alerts.js: this source will show alert ``id`` (it passed the URL filters).
  function accept(id) {
    if (id) remember(shown, String(id));
  }

  /**
   * alerts.js: alert ``id`` is on screen now. ``soundDone`` settles when the alert's own sound has
   * finished (or at once when it has none); ``waitMs`` is how long to wait for the voice (the
   * payload's tts.wait_ms). The promise settles when the voice has played, or when it won't come.
   */
  function forAlert(id, soundDone, waitMs) {
    id = String(id || "");
    if (off || !id) return Promise.resolve();
    return new Promise((resolve) => {
      const ready = Promise.resolve(soundDone).catch(() => {});
      const timer = setTimeout(() => {
        if (waiting.get(id) && waiting.get(id).timer === timer) {
          waiting.delete(id);
          remember(finished, id);
          resolve();
        }
      }, Math.max(1000, Number(waitMs) || 19000));
      waiting.set(id, { resolve, timer, ready });
      if (early.has(id)) {
        const item = early.get(id);
        early.delete(id);
        startForAlert(id, item);
      }
    });
  }

  window.FridgeVoice = { onLine, onSkip, onControl, accept, forAlert, enabled: !off };
})();
