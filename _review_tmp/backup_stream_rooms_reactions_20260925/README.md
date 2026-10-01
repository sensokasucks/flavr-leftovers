# Stream Rooms (Redot)

Swappable 3D rooms with a screen that shows a **shared browser tab** (live, e.g. YouTube in
Brave) or a **video file / URL**. The picture lights the room, and there are tools for
reaction streams.

Needs Redot 4.3+ (Forward+). Open `project.godot` in Redot, let it import, and press **F5**.

---

## Showing a browser tab (recommended)
1. Run the game.
2. In the panel's **Source** tab, click **Open sender page**. It opens `http://127.0.0.1:8765/`.
   Open it in Brave (or Chrome/Edge). Firefox can't share tab audio.
3. Click **Share a tab or window**, pick the YouTube tab, and leave **"Share tab audio"** on.
4. The tab appears on the screen within a second or two. Keep the sender page open. A small
   separate window works best, because browsers slow down hidden tabs.

**No double audio:** the sender asks the browser to silence the shared tab
(`suppressLocalAudioPlayback`) and sends its sound to the game instead. The sender page and the
game's Source tab both warn you if the browser couldn't silence it. If that happens, mute the tab.

**Lip-sync:** the picture travels a longer path than the sound, so audio is delayed by 150 ms by
default. Adjust **Audio delay** or **Video delay** in the *Audio & Screen* tab.

**Webcam:** click **Start webcam** on the sender page. It shows on the room's picture frame
(`WEBCAM_Frame`), or as a corner overlay if the room doesn't have one.

## Playing a file or URL (fallback)
Type a path or a YouTube URL in the *Source* tab, or click **Browse...**. Non-`.ogv` files and URLs
need `yt-dlp` and `ffmpeg`: right-click `tools/get_tools.ps1` > *Run with PowerShell*.

## Hotkeys
| Key | Action |
|---|---|
| **Space** | Pause to react. Pauses a file directly. For a browser tab it sends the Windows Play/Pause media key. Lights come up, the camera moves to the room's *Reaction* camera, and a badge shows. |
| **F** | Focus view: the video flat and full-frame, so viewers can read it. |
| **1-9, 0** | Camera presets (smooth moves). **0** is the 10th preset. |
| **PgUp / PgDn** | Previous / next room. |
| **F10** | Clean feed: hides all UI (the webcam overlay stays). |
| **Tab** | Show/hide the control panel. |
| **F11** | Fullscreen. |
| **C** | Chat screen on/off (rooms that have one). |
| Right-drag, WASD, Q/E, Shift | Free-look camera: hold the right mouse button and move to look; W/S forward/back, A/D left/right, **Q down / E up**, Shift = 3x speed. |

Hotkeys are ignored while you're typing in a text box (Esc leaves the box).

**Auto-duck:** in the *React* tab the video audio drops (14 dB by default) while your mic hears
you, then comes back up. Set **Talk threshold** by watching the mic meter. Windows may ask for
microphone permission the first time.

## Presenters (podium rooms)
**Lecture Hall (Panel)** is a copy of the lecture hall with four oak podiums, two each side of a
smaller screen that hangs higher. Each podium has a picture behind it for a presenter and a brass
reading lamp. It has no webcam monitor on the stage: your webcam uses the corner overlay.

Everything is in the **Presenters** tab:
- **On set:** which podiums are used (1-4, numbered left to right as the audience sees them).
  An unticked podium disappears with its picture and lamp.
- **Show:** what the presenter is.
  - *Silhouette:* a standing outline.
  - *Green screen:* a blank panel in the key colour.
  - *Camera:* a webcam.
  - *Tab / window:* a browser tab or app window, such as a vtuber.
  - *Web page (transparent):* a web page with a see-through background, such as a reactive
    PNGTuber / Discord avatar page (see below). Type its address in **Web page**.
- **Camera:** which webcam to use. The list comes from the sender page.
- **Self-lit (light panel):** the picture glows on its own, so the room's lights (and house-light
  dimming) don't change it. Off = the room and the podium lamp light it.
- **Podium light:** that podium's lamp brightness (0-300%).
- **Chroma key** for camera / tab pictures:
  - key colour
  - **Key similarity** (how close to the key colour counts as background)
  - **Key smoothness** (soft edge)
  - **Spill removal** (takes the green glow off hair and shoulders)
- **Zoom** / **Move up/down:** frame the picture.

Camera and tab pictures come through the **sender page** (Source tab > Open sender page):
- **Cameras** start by themselves when you choose *Camera* in the game. The browser asks for
  camera permission the first time (**Allow cameras** button).
- **Tabs / windows:** click that presenter's **Pick a tab or window** button in the sender
  page. Browsers only allow picking a tab after a click.
- **Web pages (transparent):** screen sharing can't carry transparency, so the sender page
  puts the page on a solid background in the presenter's **Key colour** and the chroma key
  cuts that colour out again.
  1. In the sender page, click that presenter's **1. Open page**. A small window opens with the
     page over the key colour. Keep it open (it can sit behind the game; resize it to frame
     the avatar).
  2. Click **2. Share it** and pick the tab called *Presenter N web page*.
  - Pick a key colour the avatar doesn't use. Magenta (`#ff00ff`) is often safer than green
    for colourful avatars. Changing the colour or address in the game updates the window.
  - Some sites refuse to be shown inside another page (the window says the site *refused to
    connect*). Those can't be used this way; share their tab with *Tab / window* instead.
- Feeds are sent at 480p, up to 20 fps, in high quality so keyed edges stay clean.
- A tab only produces new frames when its picture changes (a quiet avatar sends nothing), so the
  sender page re-sends the last frame every second and the game trusts the sender's status.
  A quiet presenter stays on screen.
- Everything shares one connection to the game. When it gets busy, presenter pictures give way
  first and audio is never dropped, so the main video's sound stays smooth.
- They only run while you're in a room with podiums and that presenter is on set.
- Presenter tabs send video only (no audio).

Adding podiums to another room:
- `PRESENTER_<n>` empties (n = 1-4) at the bottom centre of each picture, with local -Y
  (Blender) facing the audience.
- Optional `PODIUM_<n>` meshes (shown and hidden with the presenter) and `PODIUM_LIGHT_<n>`
  empties for the lamp (+Y aims at the presenter).
- Picture size is `presenter_size` on the room's root node.

The panel copy is built by `../blender/lecture_hall_gen.py` with `PANEL = True` (see the top of
that file) into `../blender/lecture_hall_panel.blend`.

## Chat audience (Fridge Stream Core)
Rooms with audience seats (Home Theater, Lecture Hall, Old Classroom) can fill up with your chat:
- **Seats:** everyone who chats gets a seat with a head-and-shoulders silhouette in their own
  colour. It uses the platform's chat colour when it has one; otherwise a colour is picked from
  their name, so it's the same every time.
- **Speech bubbles:** their messages pop up in a speech bubble above their head, with their name
  on top. Each person gets one of four bubble shapes.
- **Emotes:** chat emotes show inline in the bubbles, and emote-only messages show them bigger.
  That covers Twitch emotes plus BetterTTV, FrankerFaceZ and 7TV emotes (Stream Core sends them
  with each message) and Kick emotes.
  - Images download once and are kept in `user://emote_cache/` (`autoload/emote_cache.gd`).
  - Animated GIF emotes (Kick, BetterTTV, ...) play in the bubbles and on the chat screen. The
    engine can't read GIFs, so `core/gif_decoder.gd` decodes them on a worker thread.
    Animated WebP can't be decoded yet: those show a still frame when the site provides one,
    otherwise their name as text (the Redot output then says "Emote image not supported").
  - Normal emoji use your system's colour emoji font (Segoe UI Emoji on Windows).
- **Chatter pictures:** Kick and YouTube chatters' profile pictures fill the silhouette's head,
  cropped round inside their colour ring.
  - YouTube pictures come with each message. For Kick, Stream Core looks each new chatter up
    once, so their picture appears a moment after their first message.
  - Twitch pictures aren't supported yet.
  - Turn pictures off with **Chatter pictures**, or hide one person's picture with
    **Hide pictures of** (Audience tab).
- **Leaving:** after **Idle timeout** minutes without chatting, they leave their seat. If every
  seat is taken, the person who has been quiet the longest makes room.
- **Your view stays clear:** silhouettes right in front of the camera fade out. Bubbles and
  name tags grow with distance so you can read them from the balcony.
- **Settings:** all in the **Audience** tab.
  - bubble time and bubble size
  - name tags, dim placeholders on empty seats, hiding `!commands`
  - use chat colours
  - an ignore list for bots
  - **Test chat** fills seats with made-up chatters

Chat comes from **Fridge Stream Core** (FlaVR Leftovers workshop):
- Start it with *START Stream Core.bat*. The game connects to its overlay WebSocket at
  `ws://127.0.0.1:3850/ws`, the same feed its chat overlay uses. So every platform Core has
  enabled (Kick, Twitch, YouTube) shows up, and Core itself needs no changes.
- Chat that arrived in the last few minutes before connecting seats those chatters too.
- Core's own bot replies are skipped.
- The game reconnects on its own if Core is started later or restarted.

Adding seats to a room:
- Add an **AudienceRow** node (`core/audience/audience_row.gd`, a Marker3D) on the seat surface
  of the first seat, then set `count` + `spacing` (seats run along its local +X), or list
  `offsets` for uneven rows. `seat_scale` makes a row's silhouettes smaller or larger.
- Single seats can also be Blender empties named `AUDIENCE_<anything>`.
- Seats where a camera sits are skipped automatically.

### Chat screen
**Lecture Hall (Panel)** has a chat panel under the main screen, the same width as the screen.
Turn it on in the **Room** tab (*Show chat under the screen*) or press **C**.
- It shows the same Stream Core chat as the audience: names in their colours, emotes,
  Kick / YouTube profile pictures. It follows the Audience tab's **Ignore names** and
  **Hide !commands**.
- Messages flow down the columns like a newspaper, newest at the bottom right. The oldest drop
  off when it's full.
- Room tab settings: chatter pictures, text size, columns (1-4) and background opacity
  (0% = text floating on its own).
- Other rooms can have one: add a `CHAT_Screen` empty at the top centre of the panel (local -Y
  in Blender faces the audience) and set `chat_screen_size` (metres) on the room's root node.

## Adding a room
Create `rooms/<name>/` with:
- a scene whose root uses `rooms/room.gd`, containing:
  - `TVScreen`: the screen mesh (needs UVs). Screen lights place themselves from its size.
  - `CAM_<n>_<Name>`: empties/markers for camera presets, where -Z is the view direction. They
    sort by name, so use two digits (`CAM_01_...`) when a room has more than nine. A name
    containing `Reaction` becomes the react-pause camera.
  - `LIGHTS_House`: a node whose lights dim while a video plays.
    - `LAMP_<Name>` empties inside it become lights automatically. Set color, strength and
      range on the room's root node under "LAMP_ markers".
  - `WEBCAM_Frame` (optional): where the webcam picture goes. It faces the marker's +Z.
  - `BEAM_Projector` (optional): a projection-booth marker. A narrow beam shines from it at the
    screen, tinted by the picture, and shows up in volumetric fog.
  - `SCREEN_Mirror_<Name>` (optional): extra screen meshes (with UVs) that show the same picture,
    each with a soft light spill.
  - `AUDIENCE_<Name>` empties or `AudienceRow` nodes (optional): chat-audience seats (see above).
  - `CHAT_Screen` (optional): top centre of a chat panel under the screen (see *Chat screen*).
- `room_info.tres` (a **RoomInfo** resource): id, display name, scene path, and optional
  Environment, screen-light strength, reverb, ambience sound, and an **LED look** for big outdoor
  screens (`screen_led_amount` and `screen_led_count`). The LED dots fade out with distance so
  they don't shimmer.
  - Projector rooms can also use `screen_film_amount` (the old-film look), `screen_film_tint` and
    `screen_matte` (a white fabric screen instead of black glass). `speaker_lofi` gives the
    room a small old speaker. A room with a film look gets a **Film look** slider in the Room tab.
  - `screen_hologram` turns on the hologram screen controls in the Room tab (see Neon City).
- Optional: a room script can add its own controls to the Room tab by overriding
  `get_controls()` in `room.gd` (headings, sliders and colour pickers bound to AppState settings;
  see `rooms/neon_city/neon_city_room.gd` for the Rain slider).
- Optional: `glow_materials` on the room's root node lists imported materials (by name) whose
  glow dims with the house lights, such as chandelier bulbs.
- Optional: `material_overrides` on the room's root node swaps imported materials by name, for
  example a Blender material called `Win_Glass` for the interior-window shader. For that shader,
  the mesh's UVs must put one window bay by one floor into each 1x1 UV cell.

Blender empties exported to glTF keep their names, so you can put all the markers straight in the
.blend. For a camera empty, point its local **+Y** at what it should look at (Z up). For
`WEBCAM_Frame`, point its local **-Y** at the viewer. The room appears in the Room list
automatically.

Included rooms:
- **Home Theater**
- **Drive-In (1950s)**: night lot with a pickup with lawn chairs, a concession stand and a
  projector beam. The sky (`rooms/drive_in/night_sky.gdshader`) draws a textured, phase-lit
  moon, stars with a faint Milky Way, and a few moonlit drifting clouds. The moon sits wherever
  the room's `Moonlight` light comes from, so rotate that node to move the moon. Tune the moon
  size, phase, tint, edge softness (`moon_edge_softness`), atmospheric haze (`moon_haze`), cloud
  coverage and so on in `room_info.tres` > Environment > Sky > Shader Parameters. The moon surface (`moon_albedo.png`) is procedurally generated. Every marker lives in `../blender/drive_in.blend`, so move things
  there and re-export to `rooms/drive_in/drive_in.glb`. Export the `DriveIn` and
  `DriveIn_Markers` collections only, not `Preview_Only`.
- **Neon City (night)**: a rain-soaked megacity avenue.
  - The main screen is a giant LED video billboard on a tower whose base is a lit traffic portal.
    A street gantry screen mirrors the same video.
  - Cameras: a rooftop balcony (the default), a pedestrian overpass, a billboard close-up, a
    high skyline view, and a Reaction camera aimed at the webcam display on the balcony wall.
  - Every building window is a little 3D room (`core/interiors/interior_windows.gdshader`,
    adapted from an MIT-licensed interior-mapping shader). Lights are on or off per window,
    warm, cool or neon, with blinds, curtains and the odd flickering TV. The seven facade
    styles are the `Win_*` materials in `rooms/neon_city/materials/`, which the room swaps in
    by name (see `material_overrides` on the room's root node).
  - Buildings come from `../blender/city_gen.py` (run inside Blender: see the top of that
    file). Windows follow a floor grid, so they line up with corners and roofs. Every roof has
    a cornice, parapet and equipment or a crown (notched, slanted, spire, neon fins, helipad,
    halo). Building types include setback towers, a teal megablock with an exposed frame and
    braces, a ring tower with LED ticker bands, a gate building with sky bridges, a capsule
    tower and overhanging "hammerhead" tops.
  - `rooms/neon_city/neon_city_room.gd` adds rain that follows the camera, flying traffic
    (some craft carry lights that sweep across the buildings), street traffic, flickering flare
    stacks marked `FLARE_*`, and a generated rain ambience. All are tunable on the room's root
    node.
  - The sky (`smog_sky.gdshader`) is a smoggy cloud deck lit from below by the city.
  - Source file: `../blender/neon_city.blend`. Export the `City` and `City_Markers`
    collections, or run `export_glb()` from `city_gen.py`.
  - **Room tab controls:**
    - **Rain**: 0% (dry) to 200% (downpour). The rain sound follows it.
    - **Hologram**: how strongly the scan-line colours take over the picture (0% = normal
      screen). **Transparency** makes the screen see-through, and the dark box behind the
      screen fades with it so the picture floats in front of the tower. **Glitch** adds torn
      bands, RGB split, jumps and dropouts in bursts. **Scan lines**, **Scroll speed**,
      **Noise** and the two **Line colours** are the original shader's settings.
      The hologram look is ported from "Hologram Simple CanvasItem Shader" by Vaquers
      (godotshaders.com, CC0), in `core/screen_inc.gdshaderinc`.
    - The screens use the see-through shader (`core/screen_holo.gdshader`) only while
      Transparency is above 0%. See-through screens don't show in the wet-road reflections.
  - All brands, signs and designs are original.
- **Old Classroom (film day)**: a 1950s-style classroom with the blinds drawn.
  - The video plays on a roll-down projection screen in front of the chalkboard, thrown by a
    16 mm projector on an AV cart in the middle aisle. The reels turn while the film runs and
    run down when you pause to react. Dust drifts through the beam.
  - The picture has an old-film look: faded warm colour, grain, dust specks, hairs, a drifting
    scratch, gate weave, flicker and a projector hot-spot. The light on the room flickers with it.
  - The sound goes through a tinny old speaker: no bass or treble, mono, a little distortion
    and film flutter. Use **Speaker FX** in the *Audio & Screen* tab to set how much (0% = clean).
  - **Film look** in the Room tab sets how much of the old-film look the picture gets:
    0% = clean, 100% = the room's look, up to 200% for extra dust, hairs, scratches and flicker.
  - The projector beam lights exactly the picture area. The mask is traced from the projector's
    real position, so it doesn't spill onto the screen fabric or the wall.
  - The projector whirrs and clatters on the ambience track, and the wall clock shows the real
    time and ticks.
  - Cameras: a student's desk (the default), the back corner, the screen, the projector, and a
    Reaction camera aimed at the webcam picture pinned to the corkboard.
  - Source: `../blender/classroom.blend`, built by `../blender/classroom_gen.py`
    (run it inside Blender: see the top of that file).
- **Lecture Hall**: a Victorian Gothic university theatre in dark oak.
  - The plan follows a real 1870s hall: a U of straight side walls and a half-octagon back, a
    flat pit of straight pews with a centre aisle, raked pews on every facet, a narrow
    wrap-around balcony on slender posts, an arcaded top gallery, a hammer-beam ceiling and a
    curved wooden sounding canopy over the stage. The inscription, shields and statues are
    original stand-ins.
  - The screen is 14.4 m x 8.1 m and stands right on the stage floor, with a matte white face.
  - The ring chandelier dims with the house lights. Use **House lights** in the *Room* tab to set
    the level by hand (it scales the automatic dimming too).
  - 12 cameras: pit, front row, centre rows, rear diagonal, side seat under the balcony,
    three balcony seats, the gallery rail, a Reaction camera by the webcam monitor, the lectern
    (looking out at the hall), and a view past the chandelier. Press **0** for the 10th.
  - A big-room reverb and a faint room tone.
  - Source: `../blender/lecture_hall.blend`, built by `../blender/lecture_hall_gen.py`.
- **Studio**: a simple test room without a webcam frame, which shows the corner-overlay fallback.

## Exporting a standalone build (Windows)
1. *Editor > Manage Export Templates > Download and Install* (once per Redot version).
2. *Project > Export...*, pick the **Windows Desktop** preset, then **Export Project** and untick
   *Export With Debug* for a release build. The preset already includes `web/*` (the sender page),
   leaves out `_tests/`, and writes to `../export/StreamRooms.exe` (+ `StreamRooms.pck`).
3. Copy the `tools/` folder (yt-dlp.exe, ffmpeg.exe) next to the .exe if you want *File or URL*
   downloads. Browser-tab capture, chat and presenters don't need it.
4. Ship the whole export folder. Settings and the emote cache live in the user data folder
   (*Project > Open User Data Folder* in the editor), shared with editor runs.

## Project layout
- `autoload/`: EventBus (signals only), AppState (settings and state), SaveManager
  (`user://settings.cfg`), RoomCatalog, AudioManager (buses, reverb, ducking), SystemMedia
  (media key)
- `core/`: main scene and wiring, RoomHost (threaded load and fade), ScreenFeed (file and capture
  sources, A/V delay), CaptureServer (local HTTP + WebSocket), ScreenLights, WebcamDisplay,
  CameraRig, Hotkeys, VideoLoader
- `core/interiors/`: the interior-window facade shader and its room atlas (8 room types)
- `ui/`: control panel, focus view, overlays (toasts, badge, webcam corner)
- `web/sender.html`: the browser sender page. **When exporting the game**, add `web/*` to
  *Export > Resources > Filters to export non-resource files*.
- `rooms/`: one folder per room

The link only listens on `127.0.0.1` (this PC). Ports 8765 and 8766 are in AppState's defaults.
