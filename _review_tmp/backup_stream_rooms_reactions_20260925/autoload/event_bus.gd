extends Node
## EventBus: cross-system signals only. No state, no logic.

# ── Screen / video ───────────────────────────────────────────
## The texture currently shown on the screen changed (new source, or first frame).
signal screen_texture_changed(texture: Texture2D)
## Average colour of the left / centre / right thirds of the current frame.
signal screen_colors_changed(left: Color, center: Color, right: Color)
## Webcam texture from the browser sender (null when the webcam stops).
signal webcam_texture_changed(texture: Texture2D)
## Which source feeds the screen: "none", "file" or "capture".
signal source_changed(mode: String)
## True while the screen is actively playing (not stopped / paused).
signal playback_active_changed(active: bool)

# ── Requests (UI / hotkeys -> systems) ───────────────────────
signal file_play_requested(input: String)
signal file_stop_requested
signal file_pause_toggle_requested
signal camera_preset_requested(index: int)

# ── Reaction features ────────────────────────────────────────
signal react_pause_changed(paused: bool)
signal focus_view_changed(on: bool)
signal clean_feed_changed(on: bool)
signal mic_level_changed(db: float)
signal ducking_changed(ducking: bool)

# ── Rooms ────────────────────────────────────────────────────
signal room_requested(room_id: String)
signal room_changed(room_id: String)
signal camera_presets_changed(names: PackedStringArray)
## Room-specific controls for the Room tab: an Array of Dictionaries (see Room.get_controls()).
signal room_controls_changed(controls: Array)

# ── Capture link ─────────────────────────────────────────────
## Keys: connected (bool), fps (float), has_audio (bool),
## suppress_local_audio (bool), webcam (bool), url (String)
signal capture_status_changed(info: Dictionary)
## A presenter feed's picture (camera / tab from the sender page); null when it stops.
signal presenter_texture_changed(presenter: int, texture: Texture2D)   # presenter = 1..4
## How many presenter podiums the current room has (0 = none).
signal room_presenters_changed(count: int)

# ── Settings / messages ──────────────────────────────────────
signal setting_changed(key: String, value: Variant)
signal status_message(text: String, is_error: bool)
## Chat source (ChatFeed): {"connected": bool, "url": String, "error": String}
signal chat_status_changed(info: Dictionary)
## One normalized chat message (see ChatFeed._normalize for the keys).
signal chat_message_received(msg: Dictionary)
## Late info about a chatter from Stream Core: {"platform", "user_id", "avatar"}
signal chat_user_updated(info: Dictionary)
## Audience roster (AudienceManager). Views look members up with AudienceManager.get_seat_member().
signal audience_seated(slot: int)
signal audience_left(slot: int)
## parts: Strings and emote Dictionaries {"url": String, "name": String}, in order.
signal audience_spoke(slot: int, parts: Array)
## EmoteCache finished downloading an emote image.
signal emote_ready(url: String)
signal audience_count_changed(seated: int, capacity: int)
## Something about the person in a seat changed (e.g. their picture arrived).
signal audience_updated(slot: int)
