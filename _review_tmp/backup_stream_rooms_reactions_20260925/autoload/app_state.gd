extends Node
## AppState: single source of truth for settings and runtime app state.
## Other systems read with get_setting() / the getters and change things only
## through the methods here, which emit EventBus signals.

const BASE_DEFAULTS: Dictionary = {
	"room_id": "theater",
	"volume": 0.8,               # 0..1, video/stream audio
	"ambience_volume": 0.5,      # 0..1, room background sound
	"room_acoustics": 1.0,       # 0 = dry, 1 = the room's own reverb, 2 = exaggerated
	"room_speaker": 1.0,         # 0 = clean, 1 = the room's own speaker character (e.g. old projector speaker)
	"audio_delay_ms": 150.0,     # delays stream audio to line up with video
	"video_delay_ms": 0.0,       # delays stream video (if audio is behind instead)
	"screen_light": 1.0,         # how strongly the screen lights the room
	"screen_glow": 1.6,          # screen emission brightness
	"duck_enabled": true,
	"duck_threshold_db": -38.0,  # mic level that counts as talking
	"duck_amount_db": -14.0,     # how far the video audio drops while talking
	"react_lights_up": true,     # raise house lights during a react pause
	"react_camera": true,        # jump to the "Reaction" camera during a react pause
	"auto_dim_house": true,
	"house_lights": 1.0,         # 0..1 dimmer for every room's house lights (chandeliers, lamps)
	# Room-specific looks (the Room tab shows them only in rooms that use them)
	"film_look": 1.0,            # old-film rooms: 0 = clean picture, 1 = the room's look, 2 = extra dirt
	"rain_amount": 1.0,          # rainy rooms: 0 = no rain, 1 = normal, 2 = downpour
	"holo_amount": 0.0,          # hologram screens: scan-line colour strength (0 = off)
	"holo_transparency": 0.0,    # hologram screens: 0 = solid, 1 = invisible
	"holo_glitch": 0.0,          # hologram screens: glitch strength
	"holo_lines": 100,           # hologram scan lines down the screen
	"holo_speed": 0.4,           # hologram scan-line scroll speed
	"holo_noise": 0.05,          # hologram static
	"holo_color1": Color(0.0, 0.0, 1.0),
	"holo_color2": Color(1.0, 0.0, 0.0),
	# Chat audience (Fridge Stream Core chat -> silhouettes with speech bubbles)
	"chat_enabled": true,        # connect to Stream Core's WebSocket
	"chat_core_url": "ws://127.0.0.1:3850/ws",
	"audience_enabled": true,    # show the audience in rooms that have seats
	"audience_idle_min": 10.0,   # minutes without chatting before someone leaves their seat
	"audience_bubble_s": 8.0,    # seconds a speech bubble stays up
	"audience_bubble_size": 1.0, # speech bubble size multiplier
	"audience_names": true,      # name tags over the silhouettes
	"audience_show_empty": true, # dim placeholders on empty seats
	"audience_hide_commands": true,   # !commands seat the chatter but show no bubble
	"audience_platform_colors": true, # use the chat platform's user colour when it has one
	"audience_avatars": true,    # chatters' profile pictures as the silhouette's head (Kick + YouTube)
	"audience_hide_avatars": "", # names whose picture is never shown (comma separated)
	"chat_screen": false,        # chat panel under the main screen (rooms with a CHAT_Screen marker)
	"chat_screen_text": 1.0,     # chat screen text size multiplier
	"chat_screen_columns": 2.0,  # messages flow top-to-bottom through this many columns
	"chat_screen_bg": 0.75,      # chat screen background opacity
	"chat_screen_pictures": true,  # chatter profile pictures next to names
	"audience_ignore": "nightbot, streamelements, streamlabs, moobot, fossabot, wizebot, botrix, kicklet, sery_bot",
	"webcam_in_room": true,      # false = show webcam as a corner overlay instead
	"capture_http_port": 8765,
	"capture_ws_port": 8766,
	"max_height": 720,           # file/URL conversion height
	"loop_files": true,
}

## Presenter podiums (rooms with PRESENTER_<n> markers). Keys are "presenter_<n>_<field>", n = 1..4.
const PRESENTER_COUNT: int = 4
const PRESENTER_FIELDS: Dictionary = {
	"on": false,                 # on set (podium, picture and lamp shown)
	"source": "silhouette",      # "silhouette" | "green" | "camera" | "tab" | "web"
	"camera": "",                # camera device id for "camera" ("" = default camera)
	"url": "",                   # web page for "web" (shown over the key colour, e.g. a transparent avatar page)
	"self_lit": false,           # glows like a light panel instead of taking the room's light
	"light": 1.0,                # podium lamp brightness (0..3)
	"key": true,                 # chroma key on camera / tab pictures
	"key_color": Color(0.0, 1.0, 0.0),
	"key_similarity": 0.28,      # how close to the key colour counts as background
	"key_smoothness": 0.08,      # soft edge width
	"key_spill": 0.6,            # remove the key colour's glow from the edges
	"zoom": 1.0,                 # picture size inside the frame
	"offset_y": 0.0,             # move the picture up (+) / down (-)
}

## Every setting and its default (base settings + one set per presenter).
var DEFAULTS: Dictionary = _build_defaults()
var _settings: Dictionary = DEFAULTS.duplicate(true)
var _source_mode: String = "none"
var _playback_active: bool = false
var _react_paused: bool = false
var _focus_view: bool = false
var _clean_feed: bool = false
var _room_has_webcam_frame: bool = false


# ── Settings ─────────────────────────────────────────────────
static func _build_defaults() -> Dictionary:
	var d := BASE_DEFAULTS.duplicate(true)
	for n in range(1, PRESENTER_COUNT + 1):
		for f: String in PRESENTER_FIELDS.keys():
			d["presenter_%d_%s" % [n, f]] = PRESENTER_FIELDS[f]
	d["presenter_2_on"] = true     # two presenters (the inner podiums) on set by default
	d["presenter_3_on"] = true
	return d


## Shortcut for presenter settings: presenter(2, "source") -> "presenter_2_source".
static func presenter_key(n: int, field: String) -> String:
	return "presenter_%d_%s" % [n, field]


func get_setting(key: String) -> Variant:
	return _settings.get(key, DEFAULTS.get(key))


func set_setting(key: String, value: Variant) -> void:
	if not DEFAULTS.has(key):
		push_warning("Unknown setting: %s" % key)
		return
	if _settings.get(key) == value:
		return
	_settings[key] = value
	EventBus.setting_changed.emit(key, value)


func get_all_settings() -> Dictionary:
	return _settings.duplicate(true)


## Used by SaveManager. Unknown keys are ignored, missing keys keep defaults.
func apply_saved_settings(saved: Dictionary) -> void:
	for key in saved.keys():
		if DEFAULTS.has(key) and typeof(saved[key]) == typeof(DEFAULTS[key]):
			_settings[key] = saved[key]


# ── Source / playback ────────────────────────────────────────
func get_source_mode() -> String:
	return _source_mode


func set_source_mode(mode: String) -> void:
	if mode == _source_mode:
		return
	_source_mode = mode
	EventBus.source_changed.emit(mode)


func is_playback_active() -> bool:
	return _playback_active


func set_playback_active(active: bool) -> void:
	if active == _playback_active:
		return
	_playback_active = active
	EventBus.playback_active_changed.emit(active)


# ── Reaction features ────────────────────────────────────────
func is_react_paused() -> bool:
	return _react_paused


func toggle_react_pause() -> void:
	set_react_paused(not _react_paused)


func set_react_paused(paused: bool) -> void:
	if paused == _react_paused:
		return
	if paused and _source_mode == "none":
		EventBus.status_message.emit("Nothing is playing to pause.", false)
		return
	_react_paused = paused
	EventBus.react_pause_changed.emit(paused)


func is_focus_view() -> bool:
	return _focus_view


func toggle_focus_view() -> void:
	_focus_view = not _focus_view
	EventBus.focus_view_changed.emit(_focus_view)


func is_clean_feed() -> bool:
	return _clean_feed


func toggle_clean_feed() -> void:
	_clean_feed = not _clean_feed
	EventBus.clean_feed_changed.emit(_clean_feed)


# ── Rooms ────────────────────────────────────────────────────
## Whether the loaded room has a WEBCAM_Frame marker (otherwise the webcam
## is shown as a corner overlay).
func room_has_webcam_frame() -> bool:
	return _room_has_webcam_frame


func set_room_has_webcam_frame(on: bool) -> void:
	_room_has_webcam_frame = on


func request_room(room_id: String) -> void:
	if RoomCatalog.get_info(room_id) == null:
		EventBus.status_message.emit("Unknown room: %s" % room_id, true)
		return
	set_setting("room_id", room_id)
	EventBus.room_requested.emit(room_id)


func cycle_room(step: int) -> void:
	var ids := RoomCatalog.get_ids()
	if ids.is_empty():
		return
	var i := ids.find(get_setting("room_id"))
	request_room(ids[posmod(i + step, ids.size())])
