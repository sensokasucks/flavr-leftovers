/**
 * Fridge Factorio Stats Bridge
 * - Connects to Factorio via RCON and polls /fridge-stats
 * - Optionally watches Wiretap stats.json for accurate power data
 * - Broadcasts merged JSON over WebSocket for the overlay
 * - Serves the overlay HTML statically
 *
 * Usage:
 *   1. Enable RCON in Factorio config.ini
 *   2. Install the fridge-factorio-stats mod (and optionally Wiretap)
 *   3. npm install && npm start
 *   4. In XSplit add Webpage source → http://localhost:3847/overlay.html
 */

const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const path = require('path');
const fs = require('fs');
const { Rcon } = require('rcon-client');
const chokidar = require('chokidar');

// ============== CONFIG ==============
const CONFIG = {
  // Factorio RCON (must match config.ini)
  rconHost: process.env.RCON_HOST || '127.0.0.1',
  rconPort: parseInt(process.env.RCON_PORT || '25575', 10),
  rconPassword: process.env.RCON_PASSWORD || 'factorio',

  // HTTP + WebSocket port
  port: parseInt(process.env.PORT || '3847', 10),

  // Poll interval for RCON (ms)
  pollIntervalMs: 2000,

  // Path to Wiretap JSON (optional – gives accurate power)
  // Windows default: %APPDATA%\Factorio\script-output\wiretap\stats.json
  wiretapPath: process.env.WIRETAP_PATH || path.join(
    process.env.APPDATA || process.env.HOME || '',
    'Factorio', 'script-output', 'wiretap', 'stats.json'
  ),

  // Path to our mod's JSON (fallback / extra)
  modStatsPath: process.env.MOD_STATS_PATH || path.join(
    process.env.APPDATA || process.env.HOME || '',
    'Factorio', 'script-output', 'fridge-stats', 'stats.json'
  )
};

// ============== STATE ==============
let latestStats = {
  tick: 0,
  deaths: 0,
  kills: { total: 0 },
  research: { current: null, progress: 0 },
  evolution: 0,
  alerts: [],
  power: { production_watts: 0, consumption_watts: 0, note: 'Waiting for data…' },
  players_online: 0,
  source: 'none',
  lastUpdate: null
};

let rcon = null;
let rconConnected = false;

// ============== RCON ==============
async function connectRcon() {
  try {
    rcon = await Rcon.connect({
      host: CONFIG.rconHost,
      port: CONFIG.rconPort,
      password: CONFIG.rconPassword,
      timeout: 3000
    });
    rconConnected = true;
    console.log(`[RCON] Connected to ${CONFIG.rconHost}:${CONFIG.rconPort}`);
    rcon.on('end', () => {
      rconConnected = false;
      console.log('[RCON] Disconnected – will retry…');
      setTimeout(connectRcon, 5000);
    });
  } catch (err) {
    rconConnected = false;
    console.warn(`[RCON] Connect failed: ${err.message}. Retrying in 5s…`);
    setTimeout(connectRcon, 5000);
  }
}

async function pollRcon() {
  if (!rconConnected || !rcon) return;
  try {
    let raw = await rcon.send('/fridge-stats');
    if (!raw || !raw.includes('{')) {
      raw = await rcon.send('/xsplit-stats');
    }
    // Factorio RCON often prefixes or has multiple lines; find the JSON object
    const match = raw.match(/\{[\s\S]*\}/);
    if (!match) {
      console.warn('[RCON] No JSON in response:', raw.slice(0, 120));
      return;
    }
    const data = JSON.parse(match[0]);
    mergeStats(data, 'rcon');
  } catch (err) {
    console.warn('[RCON] Poll error:', err.message);
    // reconnect on hard failure
    if (err.message.includes('closed') || err.message.includes('timeout')) {
      rconConnected = false;
      try { rcon.end(); } catch (_) {}
      setTimeout(connectRcon, 2000);
    }
  }
}

// ============== FILE WATCHERS ==============
function mergeWiretap(filePath) {
  try {
    if (!fs.existsSync(filePath)) return;
    const raw = fs.readFileSync(filePath, 'utf8');
    const wt = JSON.parse(raw);

    // Extract power from first surface that has data (usually nauvis)
    let power = { production_watts: 0, consumption_watts: 0, accumulator_charge_j: 0, accumulator_capacity_j: 0 };
    if (wt.surfaces) {
      for (const [name, surf] of Object.entries(wt.surfaces)) {
        if (surf.power && surf.power.totals) {
          const t = surf.power.totals;
          power = {
            production_watts: t.production_watts || 0,
            consumption_watts: t.consumption_watts || 0,
            accumulator_charge_j: t.accumulator_charge_joules || 0,
            accumulator_capacity_j: t.accumulator_capacity_joules || 0,
            network_count: t.network_count || 0,
            surface: name
          };
          break; // take first meaningful surface
        }
      }
    }

    // Research from forces.player
    let research = null;
    if (wt.forces && wt.forces.player && wt.forces.player.research) {
      const r = wt.forces.player.research;
      research = {
        current: r.current || null,
        progress: r.progress || 0,
        queue: r.queue || [],
        researched_count: r.technologies_researched || 0,
        total_technologies: r.technologies_total || 0
      };
    }

    // Evolution
    let evolution = 0;
    if (wt.forces && wt.forces.enemy && wt.forces.enemy.evolution) {
      const evo = wt.forces.enemy.evolution;
      evolution = evo.nauvis || Object.values(evo)[0] || 0;
    }

    mergeStats({
      power,
      research: research || undefined,
      evolution,
      meta: wt.meta
    }, 'wiretap');
  } catch (err) {
    console.warn('[Wiretap] Parse error:', err.message);
  }
}

function mergeModFile(filePath) {
  try {
    if (!fs.existsSync(filePath)) return;
    const raw = fs.readFileSync(filePath, 'utf8');
    const data = JSON.parse(raw);
    mergeStats(data, 'mod-file');
  } catch (err) {
    console.warn('[ModFile] Parse error:', err.message);
  }
}

function mergeStats(incoming, source) {
  // Prefer Wiretap for power & research when available
  if (incoming.power && (source === 'wiretap' || !latestStats.power.production_watts)) {
    latestStats.power = { ...latestStats.power, ...incoming.power };
  }
  if (incoming.research) {
    latestStats.research = { ...latestStats.research, ...incoming.research };
  }
  if (incoming.deaths !== undefined) latestStats.deaths = incoming.deaths;
  if (incoming.kills) latestStats.kills = incoming.kills;
  if (incoming.alerts) latestStats.alerts = incoming.alerts;
  if (incoming.evolution !== undefined) latestStats.evolution = incoming.evolution;
  if (incoming.players_online !== undefined) latestStats.players_online = incoming.players_online;
  if (incoming.tick) latestStats.tick = incoming.tick;
  if (incoming.game_time_seconds) latestStats.game_time_seconds = incoming.game_time_seconds;

  latestStats.source = source;
  latestStats.lastUpdate = new Date().toISOString();

  // Broadcast to all WS clients
  const payload = JSON.stringify(latestStats);
  wss.clients.forEach(client => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(payload);
    }
  });
}

// ============== HTTP + WS ==============
const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

// Serve overlay static files
const overlayDir = path.join(__dirname, '..', 'overlay');
app.use(express.static(overlayDir));

// Health / latest stats endpoint (for debugging)
app.get('/stats', (req, res) => {
  res.json(latestStats);
});

app.get('/', (req, res) => {
  res.redirect('/overlay.html');
});

wss.on('connection', (ws) => {
  console.log('[WS] Client connected');
  // Send current state immediately
  ws.send(JSON.stringify(latestStats));
  ws.on('close', () => console.log('[WS] Client disconnected'));
});

// ============== START ==============
async function start() {
  console.log('=== Fridge Factorio Stats Bridge ===');
  console.log(`HTTP/WS listening on http://localhost:${CONFIG.port}`);
  console.log(`Overlay URL for XSplit: http://localhost:${CONFIG.port}/overlay.html`);
  console.log(`RCON target: ${CONFIG.rconHost}:${CONFIG.rconPort}`);
  console.log(`Wiretap path: ${CONFIG.wiretapPath}`);
  console.log('');

  // Start RCON
  await connectRcon();
  setInterval(pollRcon, CONFIG.pollIntervalMs);

  // Watch Wiretap file (accurate power)
  if (fs.existsSync(path.dirname(CONFIG.wiretapPath))) {
    chokidar.watch(CONFIG.wiretapPath, { ignoreInitial: false, awaitWriteFinish: { stabilityThreshold: 200 } })
      .on('add', mergeWiretap)
      .on('change', mergeWiretap);
    console.log('[Watch] Monitoring Wiretap stats.json');
  } else {
    console.log('[Watch] Wiretap folder not found – power will be approximate or missing until you install hmph-wiretap');
  }

  // Watch our mod file as fallback
  const modDir = path.dirname(CONFIG.modStatsPath);
  if (!fs.existsSync(modDir)) {
    try { fs.mkdirSync(modDir, { recursive: true }); } catch (_) {}
  }
  chokidar.watch(CONFIG.modStatsPath, { ignoreInitial: false, awaitWriteFinish: { stabilityThreshold: 200 } })
    .on('add', mergeModFile)
    .on('change', mergeModFile);

  server.listen(CONFIG.port, () => {
    console.log(`[HTTP] Ready. Add the Webpage source in XSplit pointing to the overlay URL above.`);
  });
}

start().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
