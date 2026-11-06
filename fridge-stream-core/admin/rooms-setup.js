/*
 * Setup > Stream Rooms settings (#rooms, <section id="tab-rooms"> in index.html): every setting
 * Stream Rooms' in-game panel has a control for, drawn here from the list the game sends
 * (work list items 16 and 18).
 *
 * Where the list comes from: Stream Rooms' ui/control_panel.gd settings_schema() describes each
 * control (key, label, help text, panel tab, heading, Advanced or not, type and range / choices);
 * core/rooms_remote.gd sends it to Core as "rooms_settings" and changes as "rooms_values";
 * core/reactions.py keeps it. A new control in the game shows up here with no change in this file.
 *
 * Routes (api/admin_routes.py, admin token like admin.js):
 *   GET  /api/admin/rooms/settings   {connected, schema, values, defaults}
 *   POST /api/admin/rooms/set        {key, value}  (checked again in core/reactions.py check_rooms_value)
 *   GET  /api/admin/rooms            the Live card state (for the Start here checklist)
 *   GET / PUT /api/admin/dashboard-prefs   pins (the pin buttons here; the Live "Pinned" card is
 *                                          in admin/live-extras.js and uses makeControl below)
 *
 * The page's tabs: PAGES maps each of Core's sub-pages to the game panel's tabs. Keep it in step
 * with PAGE_SETS.roomset in admin.js and the .acc[data-sub] blocks in index.html.
 *
 * Cards and wording: the game's list follows its in-game panel (tabs, headings, "the Co-stream
 * tab"...). CARDS below regroups the settings into cards for this browser page and WORDS rewrites the
 * labels and help texts that only make sense inside the game; anything they don't name keeps the
 * game's own heading and words, so a new game setting still shows up.
 *
 * On each page: Basics / More (More shows the game's Advanced ▸ settings too), a filter box, a dot
 * and Reset on every setting that differs from its default ("changed" marks), a warning mark on a
 * few risky values (WARN), "Add to Live" (pins it to the Live page's Pinned card), and on the first
 * page a Start here checklist.
 * Layout: each page is split into headed sections (SECTIONS), and layout() spreads each section's
 * cards over columns in reading order (see "Card layout").
 * What the big screen shows is picked on the Live page's Stream Rooms card (admin.js
 * renderRoomsSources); the Big screen page only links there.
 * admin.js calls window.RoomsSetup.open(sub) from activateTab.
 */
(() => {
  const $ = (id) => document.getElementById(id);
  const tokenKey = "stream_core_admin_token";   // same key as admin.js
  const moreKey = "stream_core_rooms_more";      // Basics / More, remembered in this browser
  const POLL_MS = 3000;

  // [sub-page id, title, the game panel tabs it shows]
  const PAGES = [
    ["room", "Room & sound", ["Room", "Sound", "Panel"]],
    ["screen", "Big screen", ["Source"]],
    ["chat", "Chat windows", ["Chat"]],
    ["audience", "Audience", ["Audience", "Seating"]],
    ["reactions", "Reactions & games", ["React", "Games"]],
    ["people", "Presenters & Co-stream", ["Presenters", "Co-stream"]],
  ];

  // Warning marks: setting key -> (value, all values) => text when it's worth a second look, else "".
  // Keys that the game doesn't have are skipped, so an entry here can't break anything.
  const WARN = {
    photosensitive_safe: (v) => (v === false ? "Flashes and strobes are on. Viewers sensitive to flashing light may need this ticked." : ""),
    flash_strength: (v, all) => (Number(v) > 0.8 && all.photosensitive_safe === false ? "Very strong flashes." : ""),
    graphics_quality: (v) => (v === "high" || v === "custom" ? "Heavy on a low-end PC: use Medium on the second PC." : ""),
    together_hide_address: (v) => (v === false ? "Guests can see your home address (IP) while this is off." : ""),
    messages_on_picture: (v) => (v === true ? "Status messages show on stream." : ""),
    volume: (v) => (Number(v) === 0 ? "The big screen is muted." : ""),
  };

  // ── How this page groups and words the game's settings ─────────────────
  // The game describes its settings the way its in-game panel shows them (that panel's tabs and
  // headings, "the Co-stream tab", key letters...). This page is a browser page, so CARDS regroups
  // them into cards that make sense here and WORDS rewrites the labels and help texts that only make
  // sense inside the game. Both go by setting key, so:
  //  - a key the game doesn't have is skipped (an older Stream Rooms still works),
  //  - a new setting the game adds and this list doesn't know still shows, in a card named after
  //    the game's own heading (the old behaviour), with the game's own wording.
  // A card is [title, keys or a RegExp over keys, optional one-line note under the title]. A key
  // goes in the first card on its page that lists it. Keep a card to roughly 12 rows: the More
  // view shows them all.
  const CARDS = {
    room: [
      ["Room", ["house_lights", "sun_rays", "camera_see_through"]],
      ["Stage curtain", /^curtain_/, "The curtain buttons are on the Live page's Stream Rooms card."],
      ["Camera moves", ["camera_glide", "camera_fov"], "Camera views are picked on the Live page; new ones are saved in the game."],
      ["Big screen light", ["screen_light", "screen_glow"]],
      ["Sound", ["volume", "ambience_volume", "room_acoustics", "room_speaker", "audio_delay_ms", "video_delay_ms"]],
      ["Graphics and speed", ["graphics_quality", "gfx_gi", "gfx_ssao", "gfx_ssr", "gfx_fog", "gfx_shadows", "gfx_msaa", "gfx_render_scale", "fps_cap", "vsync"],
        "For the PC Stream Rooms runs on. Lower these on a slower PC."],
      ["Game window", ["panel_small", "panel_scale", "messages_on_picture", "debug_log"]],
    ],
    screen: [
      ["Video files and links", ["loop_files"]],
      ["NDI (from OBS or NDI Tools)", ["ndi_auto", "ndi_audio_buffer_ms"]],
      ["Spout (programs on the same PC)", ["spout_auto"]],
      ["Co-stream avatar on the big screen", ["screen_peer"]],
    ],
    chat: [
      ["Chat from Stream Core", ["chat_enabled"]],
      ["All chat windows", ["chat_screen_pictures", "chat_screen_hide_commands", "reply_screen_hold_s"]],
      ["Left of the screen", /^chat_left/],
      ["Right of the screen", /^chat_right/],
      ["Under the screen", /^chat_screen/],
      ["Above the screen (replies)", /^reply_screen/],
      ["Chat box on the picture", /^chat_hud/, "A chat box in a corner of the picture, in every room and from every camera."],
    ],
    audience: [
      ["Audience", ["audience_enabled", "audience_seating", "audience_bubble_size", "audience_bubble_s", "audience_bubble_tints"]],
      ["Speech bubbles show", ["audience_bubble_text", "audience_bubble_emotes", "audience_bubble_paid", "audience_bubble_highlighted",
        "audience_bubble_replies", "audience_bubble_animated", "audience_hide_commands"]],
      ["Names and glows", ["audience_names", "audience_titles", "audience_highlight_glow", "audience_tts_glow"]],
      ["Chatter pictures", ["audience_avatars", "audience_hide_avatars"]],
      ["Seats", ["audience_idle_min", "audience_seat_gap", "audience_show_empty", "audience_ignore", "audience_reserved_hold"]],
      ["Seating by platform", ["seating_by_platform", "seating_strict"], "The seating plan itself is drawn in the game (its Seating tab)."],
      ["Colours", ["audience_color_by", /^platform_color_/]],
      ["Crowd (Lecture Hall tiers, balcony, gallery)", /^audience_(crowd|fill_main)/],
    ],
    reactions: [
      ["Chat reactions", ["reactions_enabled", "reaction_size", "reaction_camera_shake"]],
      ["Flashing lights", ["flash_strength", "photosensitive_safe"], "For viewers sensitive to flashing light."],
      ["Pause to react", ["react_lights_up", "react_camera", "auto_dim_house", "webcam_in_room"]],
      ["Lower the video when I talk", /^duck_/],
      ["Chat games boards", ["board_hud", "board_hud_scale"]],
    ],
    people: [
      ["Who's on set", /^presenter_\d_on$/],
      ["Presenter 1", /^presenter_1_/],
      ["Presenter 2", /^presenter_2_/],
      ["Presenter 3", /^presenter_3_/],
      ["Presenter 4", /^presenter_4_/],
      ["You in a co-stream", ["together_name", "together_avatar_source", "together_avatar_url"]],
      ["Hosting", ["together_hide_address", "together_bind", "together_live_relay", "together_live_feed"],
        "Starting, joining and leaving a co-stream happen in the game (Esc menu > Co-stream)."],
      ["Shared with guests", /^together_(share|shared|audience_areas|streamer_looks|show_cameras)/],
      ["Co-stream video quality", /^together_(screen|avatar)_(height|fps|kbps)$/],
    ],
  };

  // Each page is split into a few headed sections, so it reads as "what this part of the page is
  // for" instead of one wall of cards (Sen, 2026-11-06: the cards were fine but not well ordered).
  // A section is [heading, [card titles from CARDS above], optional one-line note]. Order: the
  // switches and the things you'd change most first, then looks, then set-once / this-PC things.
  // A card no section names (a new game heading CARDS doesn't know) goes in a last "More from
  // Stream Rooms" section, so nothing is ever dropped. Keep the titles in step with CARDS.
  const SECTIONS = {
    room: [
      ["In the room", ["Room", "Stage curtain", "Big screen light", "Camera moves"]],
      ["Sound", ["Sound"]],
      ["This PC and the game window", ["Graphics and speed", "Game window"], "Only for the PC Stream Rooms runs on."],
    ],
    screen: [
      ["Sources", ["Video files and links", "NDI (from OBS or NDI Tools)", "Spout (programs on the same PC)"]],
      ["Co-stream", ["Co-stream avatar on the big screen"]],
    ],
    chat: [
      ["Chat in the room", ["Chat from Stream Core", "All chat windows", "Chat box on the picture"]],
      ["Windows around the big screen", ["Left of the screen", "Right of the screen", "Under the screen", "Above the screen (replies)"],
        "Each window only shows in rooms that have a place for it."],
    ],
    audience: [
      ["Who sits where", ["Audience", "Seats", "Seating by platform", "Crowd (Lecture Hall tiers, balcony, gallery)"]],
      ["How the audience looks", ["Speech bubbles show", "Names and glows", "Chatter pictures", "Colours"],
        "Shapes and colours per group (mods, subs...) are on Audience looks."],
    ],
    reactions: [
      ["Reactions", ["Chat reactions", "Pause to react", "Lower the video when I talk", "Flashing lights"]],
      ["Chat games", ["Chat games boards"]],
    ],
    people: [
      ["Presenters (the podiums)", ["Who's on set", "Presenter 1", "Presenter 2", "Presenter 3", "Presenter 4"]],
      ["Co-stream", ["You in a co-stream", "Hosting", "Shared with guests", "Co-stream video quality"]],
    ],
  };
  const OTHER_SECTION = "More from Stream Rooms";

  // Labels and help texts for this page, by key (presenter keys once, as presenter_N_...).
  // Only what the game's own wording gets wrong here: in-game tabs and buttons, key letters,
  // "this panel", or a label that only made sense under an in-game heading.
  const WORDS = {
    ndi_auto: { tip: "When the NDI source shown last comes back (OBS restarted, for example), show it again by itself." },
    spout_auto: { tip: "When the last Spout sender starts again (and nothing else is on the big screen), show it again by itself." },
    screen_peer: { label: "Show the avatar of", tip: "In a co-stream: put someone's avatar (what they set up as their avatar for co-streams) on the big screen. Pick (nobody) to go back to the shared tab. The host's choice goes to every PC in the session." },
    curtain_sign: { label: "Sign on the curtain" },
    curtain_show_lights: { tip: "Reveal dims the room lights while the curtain opens, like a show starting." },
    gfx_render_scale: { tip: "Draws the 3D room at a lower resolution and scales it up with AMD FSR. Text and chat windows stay sharp. 75% is a big saving on a laptop." },
    graphics_quality: { tip: "One switch for the expensive effects. Applies right away and is kept for every room." },
    panel_small: { label: "Small in-game panel", tip: "While Stream Core is connected, the game's own control panel keeps only what has to be done in the game (picking a video, the seating chart, saving a camera view, co-stream). Everything else is set here. Off: the in-game panel shows every setting too." },
    panel_scale: { label: "In-game panel size", tip: "How big the game's own control panel is (text, buttons, sliders)." },
    messages_on_picture: { label: "Show messages on stream", tip: "Also show each status message for a few seconds at the bottom of the room picture (the window OBS captures), so they would show on your stream. Off by default." },
    chat_enabled: { label: "Get chat from Stream Core", tip: "Stream Rooms takes chat, reactions and these settings from Stream Core. Off: no audience, chat windows or reactions in the room." },
    chat_screen_pictures: { tip: "Chatters' profile pictures next to their names in the chat windows. Turning off Chatter pictures (Audience page) hides them here too." },
    chat_screen_hide_commands: { label: "Hide !commands", tip: "Chat commands (!points, !throw ...) don't show in the chat windows." },
    chat_left: { label: "Show this window" },
    chat_right: { label: "Show this window" },
    chat_screen: { label: "Show this window", tip: "The chat window under the big screen, in rooms that have one (Lecture Hall (Panel)). Key C in the game turns it on and off too." },
    reply_screen: { label: "Show this window", tip: "The reply window above the big screen, in rooms that have one (Lecture Hall (Panel)). Key R in the game turns it on and off too." },
    chat_hud: { label: "Show the chat box" },
    audience_seating: { tip: "Where someone who starts chatting sits down. Seating by platform (below) can keep platforms apart on top of this." },
    audience_avatars: { label: "Chatter pictures", tip: "Chatters' profile pictures (Kick, Twitch, YouTube) as their heads and in the chat windows. Off: no pictures anywhere. Stream Core finds and saves them; Twitch pictures need Twitch connected under Connect platforms." },
    audience_hide_avatars: { tip: "Never show a picture for these people. A name matches the display name or the login; write kick:name, twitch:name or youtube:name for one platform only. The names are also added to Stream Core's own list (Chat box > Chatter profile pictures), so the chat overlay hides them too." },
    audience_bubble_text: { tip: "Ordinary messages with words in them (emotes inside are fine). Off: only the kinds ticked below get a bubble." },
    seating_by_platform: { tip: "Seat chatters by the seating plan: each section only seats the platforms ticked for it. The plan is drawn on the seating chart in the game." },
    together_name: { tip: "The name the others in a co-stream see next to your camera and in the people list." },
    together_hide_address: { tip: "On (recommended, especially for VTubers): guests join through a one-off Cloudflare address and the video goes through VDO.Ninja's relay, so nobody in the session learns where you are. It overrides Listen on and Relay the live feed (except This PC only, for testing). Needs cloudflared.exe in Stream Rooms' tools folder." },
    together_avatar_source: { label: "My avatar comes from" },
    together_screen_height: { tip: "The size of the shared tab as the guests get it. Your own stream keeps the sender page's quality." },
    presenter_N_on: { label: "On set" },
    presenter_N_source: { label: "Shows", tip: "What this podium shows. Someone's avatar: what a person in your co-stream set up as their avatar, yours included." },
    presenter_N_peer: { tip: "Whose avatar this podium shows: a person in the co-stream session." },
  };

  /** The label and help text this page uses for a schema entry (WORDS over the game's own). */
  function wording(e) {
    const w = WORDS[e.key] || WORDS[String(e.key).replace(/^presenter_\d_/, "presenter_N_")] || {};
    let label = w.label || e.label || e.key;
    // the four "on set" ticks are labelled 1-4 in the game; here they need the podium's name
    const n = /^presenter_(\d)_on$/.exec(e.key);
    if (n) label = "Presenter " + n[1];
    // every chat window has a "Header" text and a "Show" tick for it; in one card they need telling apart
    if (/_header_on$/.test(e.key) && !w.label) label = "Show the header";
    else if (/_header$/.test(e.key) && !w.label) label = "Header text";
    return { label, tip: w.tip != null ? w.tip : e.tip || "" };
  }

  /** "Card title: label", for places that show a setting out of its card (the Live page's Pinned card). */
  function fullLabel(key) {
    const e = byKey[key];
    if (!e) return key;
    const { label } = wording(e);
    const card = cardOf(e);
    return card && !label.toLowerCase().includes(card.toLowerCase()) && /^(show|show this window|on set|shows|header|text size|width|height|background|columns)/i.test(label)
      ? card + ": " + label : label;
  }

  /** Whether a CARDS entry's keys (an array of keys / RegExps, or one RegExp) take this key. */
  function takes(spec, key) {
    const list = Array.isArray(spec) ? spec : [spec];
    return list.some((k) => (k instanceof RegExp ? k.test(key) : k === key));
  }

  /** The title of the card a schema entry goes in on its page (CARDS, else the game's heading). */
  function cardOf(e) {
    const page = PAGES.find(([, , tabs]) => tabs.includes(e.tab));
    const card = page && (CARDS[page[0]] || []).find(([, spec]) => takes(spec, e.key));
    return card ? card[0] : e.group || e.tab;
  }

  let data = { connected: false, schema: [], values: {}, defaults: {} };
  let byKey = {};
  let pins = [];
  let state = null;          // GET /api/admin/rooms .state (Start here)
  let current = "room";
  let timer = 0;
  let built = "";            // signature of the schema the page was drawn from

  // ── Helpers ─────────────────────────────────────────────────────────────
  function token() {
    return localStorage.getItem(tokenKey) || ($("token") ? $("token").value.trim() : "");
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  async function call(path, opts = {}) {
    const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Admin-Token": token() } });
    if (!res.ok) {
      let msg = res.statusText || "HTTP " + res.status;
      try {
        const j = await res.json();
        if (j && typeof j.detail === "string") msg = j.detail;
      } catch (_) { /* not JSON */ }
      throw new Error(msg);
    }
    return res.json();
  }
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const changed = (key) => key in data.defaults && !same(data.values[key], data.defaults[key]);
  function showMore() {
    try { return localStorage.getItem(moreKey) === "1"; } catch (_) { return false; }
  }

  /** A slider value as the game shows it ("75%"): fmt is Godot's (%d, %.1f, %s), times scale. */
  function shown(e, v) {
    const x = Number(v) * (e.scale || 1);
    if (e.zero && Math.abs(x) < 1e-9) return e.zero;
    const fmt = String(e.fmt || "%s");
    return fmt.replace(/%(\.(\d+))?([dfs])/, (_m, _p, dec, t) => (t === "d" ? String(Math.round(x)) : t === "f" ? x.toFixed(Number(dec || 2)) : String(x)))
      .replace(/%%/g, "%");
  }

  // ── One setting's control (also used by the Live "Pinned" card) ────────
  /**
   * The input for one schema entry, with its value, sending changes to the game. onSent(ok, msg)
   * runs after each send. Returns the element (a checkbox, a slider row, a select, a text or a
   * colour box).
   */
  function makeControl(e, onSent) {
    const v = data.values[e.key];
    const send = async (value) => {
      try {
        await call("/api/admin/rooms/set", { method: "POST", body: JSON.stringify({ key: e.key, value }) });
        data.values[e.key] = value;
        if (onSent) onSent(true, "");
      } catch (err) {
        if (onSent) onSent(false, String(err.message || err));
      }
    };
    let el;
    if (e.type === "bool") {
      el = document.createElement("input");
      el.type = "checkbox";
      el.checked = !!v;
      el.addEventListener("change", () => send(el.checked));
    } else if (e.type === "range") {
      el = document.createElement("span");
      el.className = "rs-range";
      const r = document.createElement("input");
      r.type = "range";
      r.min = e.min;
      r.max = e.max;
      r.step = e.step || "any";
      r.value = v;
      const out = document.createElement("output");
      out.textContent = shown(e, v);
      r.addEventListener("input", () => { out.textContent = shown(e, r.value); });
      r.addEventListener("change", () => send(e.int ? Math.round(Number(r.value)) : Number(r.value)));
      el.append(r, out);
    } else if (e.type === "choice") {
      el = document.createElement("select");
      (e.options || []).forEach(([val, label]) => {
        const o = document.createElement("option");
        o.value = JSON.stringify(val);   // keeps a number a number
        o.textContent = label;
        el.appendChild(o);
      });
      el.value = JSON.stringify(v);
      el.addEventListener("change", () => send(JSON.parse(el.value)));
    } else if (e.type === "color") {
      el = document.createElement("input");
      el.type = "color";
      el.value = typeof v === "string" ? v : "#ffffff";
      el.addEventListener("change", () => send(el.value));
    } else {
      el = document.createElement("input");
      el.type = "text";
      el.value = v == null ? "" : String(v);
      el.addEventListener("change", () => send(el.value.trim()));
    }
    el.dataset.rsKey = e.key;
    return el;
  }

  /** Put a value into a control made by makeControl (unless the person is using it right now). */
  function setControl(el, e, v) {
    if (!el || el.contains(document.activeElement)) return;
    if (e.type === "bool") el.checked = !!v;
    else if (e.type === "range") {
      el.querySelector("input").value = v;
      el.querySelector("output").textContent = shown(e, v);
    } else if (e.type === "choice") el.value = JSON.stringify(v);
    else el.value = v == null ? "" : String(v);
  }

  // ── The page ────────────────────────────────────────────────────────────
  function pageBox(sub) {
    return $("rooms-page-" + sub);
  }

  /** Draw every page from the schema (once per schema; values are refreshed by refreshValues). */
  function build() {
    const sig = JSON.stringify(data.schema.map((e) => e.key));
    if (sig === built) return;
    built = sig;
    PAGES.forEach(([sub, title, tabs]) => {
      const box = pageBox(sub);
      if (!box) return;
      const entries = data.schema.filter((e) => tabs.includes(e.tab));
      // cards in CARDS order (each keeps the game's order inside); settings CARDS doesn't know
      // go after them, in cards named after the game's heading
      const known = (CARDS[sub] || []).map(([name, , note]) => ({ name, note: note || "", items: [] }));
      const groups = known.slice();
      entries.forEach((e) => {
        const name = cardOf(e);
        let g = groups.find((x) => x.name === name);
        if (!g) groups.push((g = { name, note: "", items: [] }));
        g.items.push(e);
      });
      const cardsNow = groups.filter((g) => g.items.length);
      // put the cards in their SECTIONS (section order, then the order listed there); cards no
      // section names go in a last OTHER_SECTION in CARDS / game order
      const secs = (SECTIONS[sub] || []).map(([title, names, note]) => ({
        title, note: note || "", cards: names.map((n) => cardsNow.find((g) => g.name === n)).filter(Boolean),
      }));
      const placed = new Set(secs.flatMap((x) => x.cards));
      const rest = cardsNow.filter((g) => !placed.has(g));
      if (rest.length) secs.push({ title: OTHER_SECTION, note: "", cards: rest });
      // one card per group: title, an optional note, then one row per setting:
      //   [dot] name ............ control
      //   help text
      //   ⚠ warning (WARN)                Reset · Add to Live
      const card = (g, i) => `<fieldset class="cfg-card rs-card" data-rs-group data-order="${i}"><legend>${esc(g.name)}</legend>` +
        (g.note ? `<p class="rs-note muted">${esc(g.note)}</p>` : "") +
        g.items.map((e) => {
          const w = wording(e);
          return `<div class="rs-row${e.adv ? " rs-adv" : ""}" data-key="${esc(e.key)}">
            <label class="rs-label"><span class="rs-dot" title="Changed from the default" aria-label="changed"></span><span class="rs-name">${esc(w.label)}</span><span class="rs-slot"></span></label>
            ${w.tip ? `<p class="field-help">${esc(w.tip)}</p>` : ""}
            <div class="rs-actions">
              <span class="rs-warn" hidden title=""></span>
              <button type="button" class="rs-reset link-btn" title="Put the default back">Reset</button>
              <button type="button" class="rs-pin link-btn" aria-pressed="false" title="Show this setting on the Live page's Pinned card">Add to Live</button>
            </div>
          </div>`;
        }).join("") + "</fieldset>";
      box.innerHTML =
        (sub === "room" ? '<div class="rs-start" id="rooms-start" hidden></div>' : "") +
        `<div class="rs-bar">
          <div class="rs-mode" role="group" aria-label="How many settings to show">
            <button type="button" data-rs-more="0" title="The settings you'd change most">Basics</button>
            <button type="button" data-rs-more="1" title="Every setting, including the set-once ones">More</button>
          </div>
          <label class="rs-filter">Find <input type="search" data-rs-filter placeholder="setting name or help text" /></label>
          <label class="check rs-only"><input type="checkbox" data-rs-changed /> Changed only</label>
          <span class="muted rs-count" data-rs-count></span>
        </div>` +
        (sub === "screen" ? '<p class="rs-note muted rs-page-note">To pick what the big screen shows (a browser tab, NDI, Spout or a video link), use ' +
          '<a href="#live">the Live page</a> (Stream Rooms card, Big screen). This page holds the set-once settings.</p>' : "") +
        // one block per section: a heading, its note, and its own grid; each grid's cards start in
        // one column and layout() spreads them over columns in reading order
        secs.map((x) => `<section class="rs-section" data-rs-section>
          <h3 class="rs-section-title">${esc(x.title)}</h3>` +
          (x.note ? `<p class="rs-note muted rs-section-note">${esc(x.note)}</p>` : "") +
          `<div class="rs-grid"><div class="rs-col">${x.cards.map(card).join("")}</div></div></section>`).join("") +
        (entries.length ? "" : '<p class="muted">Nothing here from Stream Rooms yet.</p>');
      box.querySelectorAll(".rs-row").forEach((row) => {
        const e = byKey[row.dataset.key];
        const ctl = makeControl(e, (ok, msg) => {
          if (!ok) {
            say(msg, true);
            setControl(ctl, e, data.values[e.key]);
          }
          markRow(row);
        });
        row.querySelector(".rs-slot").appendChild(ctl);
      });
      if (resizeWatch) box.querySelectorAll(".rs-grid").forEach((grid) => resizeWatch.observe(grid));   // see "Card layout"
    });
    applyView();
  }

  function say(text, bad) {
    const el = $("rooms-setup-msg");
    if (!el) return;
    el.textContent = text || "";
    el.style.color = bad ? "var(--bad, #ff6b6b)" : "";
  }

  /** The changed dot, Reset, warning mark and pin state of one row. */
  function markRow(row) {
    const key = row.dataset.key;
    const e = byKey[key];
    if (!e) return;
    const ch = changed(key);
    row.classList.toggle("rs-changed", ch);
    row.querySelector(".rs-reset").hidden = !ch;
    const w = WARN[key] ? WARN[key](data.values[key], data.values) : "";
    const mark = row.querySelector(".rs-warn");
    mark.hidden = !w;
    mark.title = w;
    mark.textContent = w ? "⚠ " + w : "";
    const pin = row.querySelector(".rs-pin");
    const on = pins.some((p) => p.key === key);
    pin.setAttribute("aria-pressed", on ? "true" : "false");
    pin.textContent = on ? "On Live ✓" : "Add to Live";
    pin.title = on ? "On the Live page's Pinned card: press to take it off" : "Show this setting on the Live page's Pinned card";
  }

  /** Basics / More, the filter box and Changed only, on every page. */
  function applyView() {
    const more = showMore();
    document.querySelectorAll("#tab-rooms [data-rs-more]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.rsMore === (more ? "1" : "0"))));
    PAGES.forEach(([sub]) => {
      const box = pageBox(sub);
      if (!box) return;
      const q = (box.querySelector("[data-rs-filter]") || {}).value || "";
      const words = q.toLowerCase().split(/\s+/).filter(Boolean);
      const only = !!(box.querySelector("[data-rs-changed]") || {}).checked;
      let shownCount = 0;
      let changedCount = 0;
      box.querySelectorAll(".rs-row").forEach((row) => {
        markRow(row);
        const e = byKey[row.dataset.key];
        const w = wording(e);
        const hay = (w.label + " " + w.tip + " " + cardOf(e) + " " + (e.label || "") + " " + e.key).toLowerCase();
        const ch = changed(e.key);
        if (ch) changedCount++;
        // a search or "Changed only" also finds Advanced settings, so nothing is out of reach
        const on = (more || !e.adv || words.length > 0 || only) && words.every((w) => hay.includes(w)) && (!only || ch);
        row.hidden = !on;
        if (on) shownCount++;
      });
      box.querySelectorAll("[data-rs-group]").forEach((fs) => {
        fs.hidden = !fs.querySelector(".rs-row:not([hidden])");
      });
      // a section with no card left (Basics, a search, Changed only) hides with its heading
      box.querySelectorAll("[data-rs-section]").forEach((sec) => {
        sec.hidden = !sec.querySelector(".rs-card:not([hidden])");
      });
      layout(box);
      const count = box.querySelector("[data-rs-count]");
      if (count) count.textContent = `${shownCount} shown · ${changedCount} changed from default`;
    });
  }

  // ── Card layout ─────────────────────────────────────────────────────────
  // Each section (SECTIONS) has its own grid, laid out on its own. Inside it the cards read in the
  // order SECTIONS lists them, left to right: the first ones go across the top row, and each next
  // card goes under the column that is shortest so far (ties: the leftmost). So the page reads like
  // text and still has no big empty gaps beside one tall card. CSS columns (the old way) read top to
  // bottom instead, which scattered related cards. Cards are only moved when the plan changes, so a
  // control being used isn't pulled out from under the mouse on the 3-second refresh.
  const CARD_MIN_W = 340;   // narrowest column in px (keep in step with .rs-col's look in admin.css)
  const CARD_GAP = 12;      // px between cards (admin.css .rs-grid / .rs-col gap)

  /** Lay out every section grid on one page (applyView, and the ResizeObserver below). */
  function layout(box) {
    box.querySelectorAll(".rs-grid").forEach(layoutGrid);
  }

  /** Spread one section's cards over as many columns as fit (skipped while the page or section is hidden). */
  function layoutGrid(grid) {
    if (!grid || !grid.clientWidth) return;
    const n = Math.max(1, Math.floor((grid.clientWidth + CARD_GAP) / (CARD_MIN_W + CARD_GAP)));
    let cols = [...grid.querySelectorAll(":scope > .rs-col")];
    while (cols.length < n) {
      const c = document.createElement("div");
      c.className = "rs-col";
      grid.appendChild(c);
      cols.push(c);
    }
    const cards = [...grid.querySelectorAll(".rs-card")].sort((a, b) => a.dataset.order - b.dataset.order);
    const heights = new Array(n).fill(0);
    const plan = Array.from({ length: n }, () => []);
    cards.forEach((card) => {
      if (card.hidden) {
        plan[0].push(card);   // takes no room; parked in the first column
        return;
      }
      const c = heights.indexOf(Math.min(...heights));
      plan[c].push(card);
      heights[c] += card.offsetHeight + CARD_GAP;
    });
    plan.forEach((want, i) => {
      const have = [...cols[i].children];
      if (have.length !== want.length || have.some((el, k) => el !== want[k])) want.forEach((el) => cols[i].appendChild(el));
    });
    // columns past n are empty now: drop them so the rest share the width
    cols.slice(n).forEach((c) => c.remove());
  }

  // Lay a page out again when its width changes: the page tab opening (0 -> full width) or the
  // window being resized. Only width counts; cards growing (More, a filter) go through applyView.
  const gridWidth = new WeakMap();
  const resizeWatch = typeof ResizeObserver === "function" ? new ResizeObserver((entries) => {
    entries.forEach((en) => {
      const w = Math.round(en.contentRect.width);
      if (gridWidth.get(en.target) === w) return;
      gridWidth.set(en.target, w);
      layoutGrid(en.target);
    });
  }) : null;

  /** New values from the game (it may have changed them itself): controls and marks follow. */
  function refreshValues() {
    document.querySelectorAll("#tab-rooms .rs-row").forEach((row) => {
      const e = byKey[row.dataset.key];
      setControl(row.querySelector("[data-rs-key]"), e, data.values[e.key]);
    });
    applyView();
  }

  /** Start here: the few things that make Stream Rooms work, ticked from the game's state. */
  function renderStart() {
    const box = $("rooms-start");
    if (!box) return;
    const st = state || {};
    const scr = st.screen || {};
    const snd = st.sender || {};
    const v = data.values;
    const items = [
      [data.connected, "Stream Rooms is running and connected to Core", ""],
      // (the big screen is picked on the Live page's Stream Rooms card, so those two link there)
      [!!scr.ok, "Something on the big screen (" + (scr.text || "nothing yet") + ")", "#live"],
      [scr.mode !== "capture" || (!!snd.connected && !!snd.sharing), "The sender page shares a tab or window", "#live"],
      [v.audience_enabled !== false, "Chat sits in the room as the audience", "#rooms/audience"],
    ];
    const todo = items.filter((i) => !i[0]).length;
    box.hidden = todo === 0;
    box.innerHTML = `<h3>Start here <small class="muted">${items.length - todo} of ${items.length} done</small></h3><ul>` +
      items.map(([ok, text, href]) => `<li class="${ok ? "rs-ok" : "rs-todo"}">${ok ? "✓" : "○"} ${esc(text)}` +
        (!ok && href ? ` <a href="${href}">Go there</a>` : "") + "</li>").join("") + "</ul>";
  }

  async function load() {
    try {
      const [s, r, p] = await Promise.all([
        call("/api/admin/rooms/settings"),
        call("/api/admin/rooms").catch(() => ({})),
        call("/api/admin/dashboard-prefs").catch(() => ({ pins: [] })),
      ]);
      data = s;
      byKey = Object.fromEntries((s.schema || []).map((e) => [e.key, e]));
      state = r.state || null;
      pins = p.pins || [];
      const off = $("rooms-setup-off");
      if (off) off.hidden = !!(s.connected && s.schema.length);
      build();
      refreshValues();
      renderStart();
    } catch (e) {
      say(String(e.message || e), true);
    }
    return data;
  }

  async function togglePin(key) {
    const e = byKey[key];
    if (!e) return;
    const on = pins.some((p) => p.key === key);
    const next = on ? pins.filter((p) => p.key !== key) : [...pins, { key, label: fullLabel(key) }];
    try {
      const saved = await call("/api/admin/dashboard-prefs", { method: "PUT", body: JSON.stringify({ pins: next }) });
      pins = saved.pins || [];
      say(on ? "Took " + fullLabel(key) + " off the Live page" : "Added " + fullLabel(key) + " to the Live page's Pinned card", false);
      applyView();
    } catch (err) {
      say(String(err.message || err), true);
    }
  }

  // ── Events (one listener for all pages) ────────────────────────────────
  document.addEventListener("click", (ev) => {
    const t = ev.target;
    if (!t.closest || !t.closest("#tab-rooms")) return;
    const more = t.closest("[data-rs-more]");
    if (more) {
      try { localStorage.setItem(moreKey, more.dataset.rsMore); } catch (_) { /* private window */ }
      applyView();
      return;
    }
    const row = t.closest(".rs-row");
    if (!row) return;
    const key = row.dataset.key;
    if (t.closest(".rs-reset")) {
      const e = byKey[key];
      call("/api/admin/rooms/set", { method: "POST", body: JSON.stringify({ key, value: data.defaults[key] }) })
        .then(() => {
          data.values[key] = data.defaults[key];
          setControl(row.querySelector("[data-rs-key]"), e, data.defaults[key]);
          applyView();
          say("Reset " + fullLabel(key), false);
        })
        .catch((err) => say(String(err.message || err), true));
    } else if (t.closest(".rs-pin")) togglePin(key);
  });
  document.addEventListener("input", (ev) => {
    if (ev.target.closest && ev.target.closest("#tab-rooms") && ev.target.matches("[data-rs-filter]")) applyView();
  });
  document.addEventListener("change", (ev) => {
    if (ev.target.closest && ev.target.closest("#tab-rooms") && ev.target.matches("[data-rs-changed]")) applyView();
  });

  /** admin.js activateTab: the page opened (sub = the tab across the top). Refreshes while it shows. */
  function open(sub) {
    if (sub) current = sub;
    load();
    if (!timer) {
      timer = setInterval(() => {
        const panel = $("tab-rooms");
        if (panel && panel.classList.contains("active")) load();
      }, POLL_MS);
    }
  }

  window.RoomsSetup = {
    open,
    load,
    makeControl,
    setControl,
    entry: (key) => byKey[key],
    fullLabel,
    data: () => data,
    pins: () => pins,
    setPins: (p) => { pins = p || []; applyView(); },
    PAGES,
  };
})();
