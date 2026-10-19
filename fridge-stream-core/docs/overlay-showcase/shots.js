// Showcase screenshots of the overlays fed by showcase_server.py (port 3899), with headless Chrome
// over the DevTools protocol. Crisp 2x captures on a dark backdrop, so the transparent overlay reads.
//   node docs\overlay-showcase\shots.js <out dir>
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const outDir = process.argv[2] || path.join(__dirname, "images");
// Windows install path of Chrome; change it on other systems.
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
// DevTools port of the headless Chrome this script starts.
const PORT = 9445;
// The overlay pages as served by showcase_server.py (start it first).
const BASE = "http://127.0.0.1:3899/overlay";
const SHOTS = [
  // [url, file, width, height, wait ms]
  ["chat.html", "chat-all-platforms.png", 760, 640, 3500],
  ["chat.html?platform=twitch", "chat-twitch-only.png", 760, 440, 3500],
  ["chat.html?platform=kick", "chat-kick-only.png", 760, 340, 3500],
  ["chat.html?platform=youtube", "chat-youtube-only.png", 760, 340, 3500],
  ["chat.html?badges=0", "chat-no-platform-letters.png", 760, 640, 3500],
  ["replies.html", "replies-and-poll-board.png", 1100, 430, 3500],
  ["alerts.html", "alert-subscribe.png", 900, 320, 3500],
];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  // A separate throwaway profile, so your normal Chrome profile is not touched.
  const profile = path.join(process.env.TEMP || ".", "sc_showcase_profile");
  const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, "--window-size=900,800", "--hide-scrollbars",
    `--user-data-dir=${profile}`, "--no-first-run", "--autoplay-policy=no-user-gesture-required", "about:blank"], { stdio: "ignore" });
  let targets = [];
  // Wait up to about 10 s for Chrome's DevTools endpoint to list a page.
  for (let i = 0; i < 40 && !targets.length; i++) {
    await sleep(250);
    try { targets = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).filter((t) => t.type === "page"); } catch (_) {}
  }
  if (!targets.length) { console.log("Chrome didn't start"); chrome.kill(); return; }
  const ws = new WebSocket(targets[0].webSocketDebuggerUrl);
  await new Promise((ok, fail) => { ws.onopen = ok; ws.onerror = fail; });
  // Tiny DevTools client: send() resolves with the reply that carries the same id.
  let id = 0; const waiting = new Map();
  ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); } };
  const send = (method, params = {}) => new Promise((ok) => { const n = ++id; waiting.set(n, ok); ws.send(JSON.stringify({ id: n, method, params })); });
  await send("Page.enable");
  // Dark backdrop (rgb 22, 24, 30) behind the transparent overlay pages.
  await send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 22, g: 24, b: 30, a: 255 } });
  for (const [url, file, w, h, wait] of SHOTS) {
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 2, mobile: false });
    await send("Page.navigate", { url: `${BASE}/${url}` });
    // Give the page time to connect to /ws and animate in before the capture.
    await sleep(wait);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    if (shot.result && shot.result.data) { fs.writeFileSync(path.join(outDir, file), Buffer.from(shot.result.data, "base64")); console.log("saved", file); }
    else console.log("failed", file, JSON.stringify(shot).slice(0, 200));
  }
  ws.close();
  chrome.kill();
})().catch((e) => { console.log("error", String(e)); process.exit(1); });
