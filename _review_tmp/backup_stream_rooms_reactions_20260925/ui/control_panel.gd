extends CanvasLayer
## Control panel (Tab to hide/show). Thin UI: it shows AppState / EventBus data
## and forwards user input to AppState setters or EventBus requests. No logic.

@export var panel_width: float = 540.0

var _panel: PanelContainer
var _url: LineEdit
var _capture_label: Label
var _capture_url: String = ""
var _room_select: OptionButton
var _camera_box: HFlowContainer
var _react_btn: Button
var _mic_bar: ProgressBar
var _duck_label: Label
var _dialog: FileDialog
var _sliders: Dictionary = {}     # setting key -> HSlider
var _checks: Dictionary = {}      # setting key -> CheckBox
var _colors: Dictionary = {}      # setting key -> ColorPickerButton
var _room_box: VBoxContainer      # this room's own controls (rebuilt on every room change)
var _room_keys: Array[String] = []
var _chat_label: Label
var _options: Dictionary = {}          # setting key -> OptionButton (values in item metadata)
var _pres_count_label: Label
var _pres_details: Array[Control] = []
var _pres_feed_labels: Array[Label] = []
var _pres_camera_menus: Array[OptionButton] = []
var _pres_edit_buttons: Array[Button] = []
var _last_cams_json: String = "[]"
var _seat_label: Label
var _user_hidden: bool = false


func _ready() -> void:
	_build()
	EventBus.capture_status_changed.connect(_on_capture_status)
	EventBus.camera_presets_changed.connect(_on_camera_presets)
	EventBus.room_changed.connect(_on_room_changed)
	EventBus.room_controls_changed.connect(_on_room_controls)
	EventBus.react_pause_changed.connect(_on_react_pause_changed)
	EventBus.mic_level_changed.connect(_on_mic_level)
	EventBus.ducking_changed.connect(_on_ducking)
	EventBus.clean_feed_changed.connect(func(_c: bool) -> void: _refresh_visible())
	EventBus.setting_changed.connect(_on_setting_changed)
	EventBus.chat_status_changed.connect(_on_chat_status)
	EventBus.audience_count_changed.connect(_on_audience_count)
	EventBus.room_presenters_changed.connect(_on_room_presenters)
	_on_chat_status(ChatFeed.get_status())


func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key and key.pressed and not key.echo and key.keycode == KEY_TAB:
		_user_hidden = not _user_hidden
		_refresh_visible()
		get_viewport().set_input_as_handled()


# ── Build ────────────────────────────────────────────────────
func _build() -> void:
	_panel = PanelContainer.new()
	_panel.position = Vector2(16, 16)
	_panel.custom_minimum_size = Vector2(panel_width, 0)
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.05, 0.05, 0.07, 0.88)
	style.set_corner_radius_all(8)
	style.set_content_margin_all(10)
	_panel.add_theme_stylebox_override("panel", style)
	add_child(_panel)
	var outer := VBoxContainer.new()
	_panel.add_child(outer)
	var tabs := TabContainer.new()
	tabs.custom_minimum_size = Vector2(panel_width - 20, 0)
	outer.add_child(tabs)
	tabs.add_child(_build_source_tab())
	tabs.add_child(_build_room_tab())
	tabs.add_child(_build_react_tab())
	tabs.add_child(_build_audio_tab())
	tabs.add_child(_build_audience_tab())
	tabs.add_child(_build_presenters_tab())
	var hint := Label.new()
	hint.text = "Tab panel | Space react pause | F focus | 1-9, 0 cameras | PgUp/PgDn rooms | F10 clean feed | right-drag look"
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.custom_minimum_size = Vector2(panel_width - 20, 0)
	hint.add_theme_font_size_override("font_size", 12)
	hint.add_theme_color_override("font_color", Color(1, 1, 1, 0.5))
	outer.add_child(hint)

	_dialog = FileDialog.new()
	_dialog.file_mode = FileDialog.FILE_MODE_OPEN_FILE
	_dialog.access = FileDialog.ACCESS_FILESYSTEM
	_dialog.use_native_dialog = true
	_dialog.title = "Choose a video"
	_dialog.filters = PackedStringArray(["*.ogv, *.mp4, *.mkv, *.webm, *.mov, *.avi, *.m4v ; Videos", "* ; All files"])
	_dialog.file_selected.connect(func(p: String) -> void:
		_url.text = p
		EventBus.file_play_requested.emit(p))
	add_child(_dialog)


func _build_source_tab() -> Control:
	var v := _tab("Source")
	v.add_child(_heading("Browser tab (live)"))
	var row := HBoxContainer.new()
	v.add_child(row)
	row.add_child(_button("Open sender page", func() -> void:
		if _capture_url != "": OS.shell_open(_capture_url)))
	_capture_label = Label.new()
	_capture_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_capture_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_capture_label.text = "Not connected."
	row.add_child(_capture_label)
	var how := Label.new()
	how.text = "Open the sender page in Brave, click Share, pick the YouTube tab and keep \"Share tab audio\" on."
	how.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	how.add_theme_color_override("font_color", Color(1, 1, 1, 0.6))
	v.add_child(how)

	v.add_child(_heading("File or URL"))
	var r1 := HBoxContainer.new()
	v.add_child(r1)
	_url = LineEdit.new()
	_url.placeholder_text = "YouTube URL or path to a video file"
	_url.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_url.text_submitted.connect(func(t: String) -> void:
		_url.release_focus()
		EventBus.file_play_requested.emit(t))
	r1.add_child(_url)
	r1.add_child(_button("Play", func() -> void: EventBus.file_play_requested.emit(_url.text)))
	r1.add_child(_button("Browse...", func() -> void: _dialog.popup_centered_ratio(0.6)))
	var r2 := HBoxContainer.new()
	v.add_child(r2)
	r2.add_child(_button("Pause / resume", func() -> void: EventBus.file_pause_toggle_requested.emit()))
	r2.add_child(_button("Stop", func() -> void: EventBus.file_stop_requested.emit()))
	r2.add_child(_check("loop_files", "Loop"))
	var q := OptionButton.new()
	for h in [480, 720, 1080]:
		q.add_item("%dp" % h, h)
	q.select(q.get_item_index(int(AppState.get_setting("max_height"))))
	q.tooltip_text = "Resolution for downloads/conversion. Lower converts faster."
	q.item_selected.connect(func(i: int) -> void: AppState.set_setting("max_height", q.get_item_id(i)))
	r2.add_child(q)
	return v


func _build_room_tab() -> Control:
	var v := _tab("Room")
	v.add_child(_heading("Room"))
	_room_select = OptionButton.new()
	for id in RoomCatalog.get_ids():
		_room_select.add_item(RoomCatalog.get_info(id).display_name)
		_room_select.set_item_metadata(_room_select.item_count - 1, id)
	_room_select.item_selected.connect(func(i: int) -> void:
		AppState.request_room(String(_room_select.get_item_metadata(i))))
	v.add_child(_room_select)
	v.add_child(_slider("house_lights", "House lights", 0.0, 1.0, 0.01, "%d%%", 100.0))
	_room_box = VBoxContainer.new()
	_room_box.add_theme_constant_override("separation", 6)
	v.add_child(_room_box)
	v.add_child(_heading("Cameras (keys 1-9, 0 = 10th)"))
	_camera_box = HFlowContainer.new()
	v.add_child(_camera_box)
	return v


func _build_react_tab() -> Control:
	var v := _tab("React")
	var row := HBoxContainer.new()
	v.add_child(row)
	_react_btn = _button("Pause to react (Space)", func() -> void: AppState.toggle_react_pause())
	row.add_child(_react_btn)
	row.add_child(_button("Focus view (F)", func() -> void: AppState.toggle_focus_view()))
	row.add_child(_button("Clean feed (F10)", func() -> void: AppState.toggle_clean_feed()))
	v.add_child(_check("react_lights_up", "Raise the lights while paused"))
	v.add_child(_check("react_camera", "Jump to the Reaction camera while paused"))
	v.add_child(_check("auto_dim_house", "Dim room lights while playing"))
	v.add_child(_check("webcam_in_room", "Show webcam in the room (off = corner overlay)"))

	v.add_child(_heading("Auto-duck when I talk"))
	v.add_child(_check("duck_enabled", "Lower the video while the mic hears me"))
	var meter := HBoxContainer.new()
	v.add_child(meter)
	var ml := Label.new()
	ml.text = "Mic"
	ml.custom_minimum_size = Vector2(120, 0)
	meter.add_child(ml)
	_mic_bar = ProgressBar.new()
	_mic_bar.min_value = -60.0
	_mic_bar.max_value = 0.0
	_mic_bar.show_percentage = false
	_mic_bar.custom_minimum_size = Vector2(0, 14)
	_mic_bar.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_mic_bar.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	meter.add_child(_mic_bar)
	_duck_label = Label.new()
	_duck_label.custom_minimum_size = Vector2(80, 0)
	meter.add_child(_duck_label)
	v.add_child(_slider("duck_threshold_db", "Talk threshold", -60.0, -10.0, 1.0, "%d dB"))
	v.add_child(_slider("duck_amount_db", "Duck by", -30.0, -3.0, 1.0, "%d dB"))
	return v


func _build_audio_tab() -> Control:
	var v := _tab("Audio & Screen")
	v.add_child(_slider("volume", "Video volume", 0.0, 1.0, 0.01, "%d%%", 100.0))
	v.add_child(_slider("ambience_volume", "Room ambience", 0.0, 1.0, 0.01, "%d%%", 100.0))
	v.add_child(_slider("room_acoustics", "Room acoustics", 0.0, 2.0, 0.01, "%d%%", 100.0))
	v.add_child(_slider("room_speaker", "Speaker FX", 0.0, 1.0, 0.01, "%d%%", 100.0))
	v.add_child(_slider("audio_delay_ms", "Audio delay", 0.0, 800.0, 10.0, "%d ms"))
	v.add_child(_slider("video_delay_ms", "Video delay", 0.0, 800.0, 10.0, "%d ms"))
	var tip := Label.new()
	tip.text = "Lip-sync: if the sound is early, raise Audio delay. If the picture is early, raise Video delay."
	tip.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	tip.add_theme_color_override("font_color", Color(1, 1, 1, 0.6))
	v.add_child(tip)
	v.add_child(_slider("screen_light", "Screen light", 0.0, 4.0, 0.05, "%.2f"))
	v.add_child(_slider("screen_glow", "Screen glow", 0.2, 4.0, 0.05, "%.2f"))
	return v


func _build_audience_tab() -> Control:
	var v := _tab("Audience")
	v.add_child(_heading("Chat (Fridge Stream Core)"))
	var row := HBoxContainer.new()
	v.add_child(row)
	row.add_child(_check("chat_enabled", "Connect"))
	_chat_label = Label.new()
	_chat_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_chat_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	row.add_child(_chat_label)
	row.add_child(_button("Retry now", func() -> void: ChatFeed.reconnect()))
	v.add_child(_text_setting("chat_core_url", "Core address", "ws://127.0.0.1:3850/ws"))

	v.add_child(_heading("Virtual audience"))
	var r2 := HBoxContainer.new()
	v.add_child(r2)
	r2.add_child(_check("audience_enabled", "Show audience"))
	_seat_label = Label.new()
	_seat_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_seat_label.text = "No seats in this room."
	r2.add_child(_seat_label)
	r2.add_child(_button("Test chat", func() -> void: ChatFeed.send_test_chat()))
	r2.add_child(_button("Clear", func() -> void: AudienceManager.clear()))
	v.add_child(_slider("audience_idle_min", "Idle timeout", 1.0, 60.0, 1.0, "%d min"))
	v.add_child(_slider("audience_bubble_s", "Bubble time", 2.0, 20.0, 0.5, "%.1f s"))
	v.add_child(_slider("audience_bubble_size", "Bubble size", 0.4, 2.5, 0.05, "%d%%", 100.0))
	var r3 := HFlowContainer.new()
	v.add_child(r3)
	r3.add_child(_check("audience_names", "Name tags"))
	r3.add_child(_check("audience_show_empty", "Show empty seats"))
	r3.add_child(_check("audience_hide_commands", "Hide !commands"))
	r3.add_child(_check("audience_platform_colors", "Use chat colours"))
	r3.add_child(_check("audience_avatars", "Chatter pictures"))
	v.add_child(_text_setting("audience_ignore", "Ignore names", "bots, comma separated"))
	v.add_child(_text_setting("audience_hide_avatars", "Hide pictures of", "names, comma separated"))
	return v


const PRESENTER_SOURCES: Array = [["silhouette", "Silhouette"], ["green", "Green screen"],
	["camera", "Camera"], ["tab", "Tab / window"], ["web", "Web page (transparent)"]]


func _build_presenters_tab() -> Control:
	var v := _tab("Presenters")
	_pres_count_label = Label.new()
	_pres_count_label.text = "This room has no podiums."
	_pres_count_label.add_theme_color_override("font_color", Color(1, 1, 1, 0.6))
	v.add_child(_pres_count_label)
	var on_row := HBoxContainer.new()
	v.add_child(on_row)
	var l := Label.new()
	l.text = "On set"
	l.custom_minimum_size = Vector2(120, 0)
	on_row.add_child(l)
	for n in range(1, AppState.PRESENTER_COUNT + 1):
		on_row.add_child(_check(AppState.presenter_key(n, "on"), str(n)))
	var edit_row := HBoxContainer.new()
	v.add_child(edit_row)
	var l2 := Label.new()
	l2.text = "Edit presenter"
	l2.custom_minimum_size = Vector2(120, 0)
	edit_row.add_child(l2)
	var group := ButtonGroup.new()
	for n in range(1, AppState.PRESENTER_COUNT + 1):
		var b := Button.new()
		b.text = " %d " % n
		b.toggle_mode = true
		b.button_group = group
		b.focus_mode = Control.FOCUS_NONE
		var idx := n - 1
		b.toggled.connect(func(on: bool) -> void:
			if on:
				for i in _pres_details.size():
					_pres_details[i].visible = i == idx)
		edit_row.add_child(b)
		_pres_edit_buttons.append(b)
	var hint := Label.new()
	hint.text = "Podiums are numbered left to right as the audience sees them."
	hint.add_theme_font_size_override("font_size", 12)
	hint.add_theme_color_override("font_color", Color(1, 1, 1, 0.5))
	edit_row.add_child(hint)
	for n in range(1, AppState.PRESENTER_COUNT + 1):
		var d := _build_presenter_detail(n)
		d.visible = n == 1
		v.add_child(d)
		_pres_details.append(d)
	_pres_edit_buttons[0].button_pressed = true
	return v


func _build_presenter_detail(n: int) -> VBoxContainer:
	var k := func(f: String) -> String: return AppState.presenter_key(n, f)
	var d := VBoxContainer.new()
	d.add_theme_constant_override("separation", 5)
	d.add_child(_heading("Presenter %d" % n))
	d.add_child(_option(k.call("source"), "Show", PRESENTER_SOURCES))
	var cam_row := HBoxContainer.new()
	var cl := Label.new()
	cl.text = "Camera"
	cl.custom_minimum_size = Vector2(120, 0)
	cam_row.add_child(cl)
	var cam := OptionButton.new()
	cam.focus_mode = Control.FOCUS_NONE
	cam.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	cam.fit_to_longest_item = false
	cam.item_selected.connect(func(i: int) -> void: AppState.set_setting(k.call("camera"), String(cam.get_item_metadata(i))))
	cam_row.add_child(cam)
	d.add_child(cam_row)
	_pres_camera_menus.append(cam)
	_fill_camera_menu(n, [])
	var url := _text_setting(k.call("url"), "Web page", "https://... (for \"Web page\")")
	url.tooltip_text = "For pages with a see-through background (e.g. a reactive PNGTuber page). The sender page shows it over the key colour, you share that, and the chroma key cuts the colour out again."
	d.add_child(url)
	var feed := Label.new()
	feed.add_theme_color_override("font_color", Color(1, 1, 1, 0.6))
	feed.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	d.add_child(feed)
	_pres_feed_labels.append(feed)
	var r := HFlowContainer.new()
	r.add_child(_check(k.call("self_lit"), "Self-lit (light panel)"))
	r.add_child(_check(k.call("key"), "Chroma key"))
	r.add_child(_color(k.call("key_color"), "Key colour"))
	d.add_child(r)
	d.add_child(_slider(k.call("light"), "Podium light", 0.0, 3.0, 0.01, "%d%%", 100.0))
	d.add_child(_slider(k.call("key_similarity"), "Key similarity", 0.0, 0.8, 0.005, "%.3f"))
	d.add_child(_slider(k.call("key_smoothness"), "Key smoothness", 0.0, 0.3, 0.005, "%.3f"))
	d.add_child(_slider(k.call("key_spill"), "Spill removal", 0.0, 1.0, 0.01, "%d%%", 100.0))
	d.add_child(_slider(k.call("zoom"), "Zoom", 0.3, 3.0, 0.01, "%.2fx"))
	d.add_child(_slider(k.call("offset_y"), "Move up/down", -0.5, 0.5, 0.01, "%.2f"))
	return d


## Camera menu for presenter n: "Default camera" + the cameras the sender page reports.
func _fill_camera_menu(n: int, cameras: Array) -> void:
	var menu: OptionButton = _pres_camera_menus[n - 1]
	var want := String(AppState.get_setting(AppState.presenter_key(n, "camera")))
	menu.clear()
	menu.add_item("Default camera")
	menu.set_item_metadata(0, "")
	var found := want == ""
	for c: Variant in cameras:
		if not c is Dictionary:
			continue
		menu.add_item(String(c.get("label", "Camera")))
		menu.set_item_metadata(menu.item_count - 1, String(c.get("id", "")))
		if String(c.get("id", "")) == want:
			menu.select(menu.item_count - 1)
			found = true
	if not found:
		menu.add_item("(saved camera, not connected)")
		menu.set_item_metadata(menu.item_count - 1, want)
		menu.select(menu.item_count - 1)
	elif want == "":
		menu.select(0)


## A dropdown bound to a String setting. items: [[value, text], ...]
func _option(key: String, label: String, items: Array) -> HBoxContainer:
	var h := HBoxContainer.new()
	var l := Label.new()
	l.text = label
	l.custom_minimum_size = Vector2(120, 0)
	h.add_child(l)
	var o := OptionButton.new()
	o.focus_mode = Control.FOCUS_NONE
	for it: Array in items:
		o.add_item(String(it[1]))
		o.set_item_metadata(o.item_count - 1, it[0])
		if it[0] == AppState.get_setting(key):
			o.select(o.item_count - 1)
	o.item_selected.connect(func(i: int) -> void: AppState.set_setting(key, o.get_item_metadata(i)))
	h.add_child(o)
	_options[key] = o
	return h


## A text box bound to a String setting. Applies on Enter or when it loses focus.
func _text_setting(key: String, label: String, placeholder: String) -> HBoxContainer:
	var h := HBoxContainer.new()
	var l := Label.new()
	l.text = label
	l.custom_minimum_size = Vector2(120, 0)
	h.add_child(l)
	var e := LineEdit.new()
	e.text = String(AppState.get_setting(key))
	e.placeholder_text = placeholder
	e.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var apply := func() -> void: AppState.set_setting(key, e.text.strip_edges())
	e.text_submitted.connect(func(_t: String) -> void:
		apply.call()
		e.release_focus())
	e.focus_exited.connect(apply)
	h.add_child(e)
	return h


# ── EventBus handlers ────────────────────────────────────────
func _on_chat_status(info: Dictionary) -> void:
	if _chat_label == null:
		return
	if info.get("connected", false):
		_chat_label.text = "Connected to Stream Core."
	elif not AppState.get_setting("chat_enabled"):
		_chat_label.text = "Off."
	else:
		var err := String(info.get("error", ""))
		_chat_label.text = "Waiting for Stream Core%s (retrying)." % ((": " + err) if err != "" else "")


func _update_presenter_feeds(info: Dictionary) -> void:
	var connected := bool(info.get("connected", false))
	var cams: Array = info.get("cameras", []) if info.get("cameras") is Array else []
	var feeds: Array = info.get("presenters", []) if info.get("presenters") is Array else []
	var cams_json := JSON.stringify(cams)
	var cams_changed := cams_json != _last_cams_json
	_last_cams_json = cams_json
	for n in range(1, AppState.PRESENTER_COUNT + 1):
		var menu: OptionButton = _pres_camera_menus[n - 1]
		if cams_changed and not menu.get_popup().visible:
			_fill_camera_menu(n, cams)
		var src := String(AppState.get_setting(AppState.presenter_key(n, "source")))
		menu.disabled = src != "camera"
		var text := ""
		if src == "camera" or src == "tab" or src == "web":
			var f: Dictionary = feeds[n - 1] if n - 1 < feeds.size() and feeds[n - 1] is Dictionary else {}
			if not connected:
				text = "Open the sender page (Source tab) - the feed comes from there."
			elif String(f.get("error", "")) != "":
				text = "Sender page: " + String(f["error"])
			elif bool(f.get("active", false)):
				text = "Live: " + String(f.get("label", ""))
			elif src == "tab":
				text = "Waiting - click Presenter %d's button in the sender page and pick a tab or window." % n
			elif src == "web" and String(AppState.get_setting(AppState.presenter_key(n, "url"))) == "":
				text = "Type the web page's address above."
			elif src == "web":
				text = "Waiting - in the sender page click Presenter %d's \"Open page\", then \"Share it\"." % n
			else:
				text = "Starting the camera..."
		_pres_feed_labels[n - 1].text = text


func _on_room_presenters(count: int) -> void:
	_pres_count_label.text = "This room has no podiums." if count == 0 else \
		"%d podiums in this room. Tick who's on set, then pick what each one shows." % count


func _on_audience_count(seated: int, capacity: int) -> void:
	if capacity <= 0:
		_seat_label.text = "No seats in this room."
	else:
		_seat_label.text = "%d / %d seats taken" % [seated, capacity]


func _on_capture_status(info: Dictionary) -> void:
	_capture_url = String(info.get("url", _capture_url))
	_update_presenter_feeds(info)
	if not info.get("connected", false):
		_capture_label.text = "Sender page not connected."
		return
	if not info.get("capturing", false):
		_capture_label.text = "Sender connected - not sharing yet."
		return
	var text := "Live: %s (%d fps)" % [String(info.get("label", "tab")), int(info.get("fps", 0))]
	if not info.get("has_audio", false):
		text += "\nNo audio - turn on \"Share tab audio\" in the picker."
	elif not info.get("suppress_local_audio", false):
		text += "\nBrowser couldn't silence the tab - mute it to avoid double audio."
	_capture_label.text = text


func _on_camera_presets(names: PackedStringArray) -> void:
	for c in _camera_box.get_children():
		c.queue_free()
	for i in names.size():
		var idx := i
		_camera_box.add_child(_button("%d  %s" % [i + 1, names[i]], func() -> void:
			EventBus.camera_preset_requested.emit(idx)))


func _on_room_changed(room_id: String) -> void:
	for i in _room_select.item_count:
		if String(_room_select.get_item_metadata(i)) == room_id:
			_room_select.select(i)


func _on_room_controls(controls: Array) -> void:
	for key in _room_keys:
		_sliders.erase(key)
		_colors.erase(key)
		_checks.erase(key)
	_room_keys.clear()
	for c in _room_box.get_children():
		c.queue_free()
	for spec: Dictionary in controls:
		if spec.has("heading"):
			_room_box.add_child(_heading(String(spec["heading"])))
			continue
		var key := String(spec.get("key", ""))
		if key == "" or AppState.get_setting(key) == null:
			push_warning("Room control for unknown setting: %s" % key)
			continue
		var w: Control
		if String(spec.get("type", "slider")) == "color":
			w = _color(key, String(spec.get("label", key)))
		elif String(spec.get("type", "slider")) == "check":
			w = _check(key, String(spec.get("label", key)))
		else:
			w = _slider(key, String(spec.get("label", key)), float(spec.get("min", 0.0)), float(spec.get("max", 1.0)),
				float(spec.get("step", 0.01)), String(spec.get("format", "%.2f")), float(spec.get("scale", 1.0)))
		w.tooltip_text = String(spec.get("tooltip", ""))
		_room_box.add_child(w)
		_room_keys.append(key)


func _on_react_pause_changed(paused: bool) -> void:
	_react_btn.text = "Resume (Space)" if paused else "Pause to react (Space)"


func _on_mic_level(db: float) -> void:
	_mic_bar.value = db


func _on_ducking(ducking: bool) -> void:
	_duck_label.text = "ducking" if ducking else ""


func _on_setting_changed(key: String, value: Variant) -> void:
	if _sliders.has(key):
		var s: HSlider = _sliders[key]
		s.set_value_no_signal(float(value) * float(s.get_meta("scale", 1.0)))
		s.value_changed.emit(s.value)  # refresh the number label only
	if _checks.has(key):
		(_checks[key] as CheckBox).set_pressed_no_signal(bool(value))
	if _colors.has(key):
		(_colors[key] as ColorPickerButton).color = value
	if _options.has(key):
		var o: OptionButton = _options[key]
		for i in o.item_count:
			if o.get_item_metadata(i) == value:
				o.select(i)
	if key.begins_with("presenter_") and key.ends_with("_source"):
		var n := int(key.get_slice("_", 1))
		if n >= 1 and n <= _pres_camera_menus.size():
			_pres_camera_menus[n - 1].disabled = value != "camera"


func _refresh_visible() -> void:
	_panel.visible = not _user_hidden and not AppState.is_clean_feed()
	if not _panel.visible:
		get_viewport().gui_release_focus()


# ── Widget helpers ───────────────────────────────────────────
func _tab(title: String) -> VBoxContainer:
	var v := VBoxContainer.new()
	v.name = title
	v.add_theme_constant_override("separation", 6)
	return v


func _heading(text: String) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", 15)
	l.add_theme_color_override("font_color", Color(1.0, 0.72, 0.4))
	return l


func _button(text: String, cb: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.focus_mode = Control.FOCUS_NONE   # so Space never "clicks" a button
	b.pressed.connect(cb)
	return b


func _check(key: String, text: String) -> CheckBox:
	var c := CheckBox.new()
	c.text = text
	c.focus_mode = Control.FOCUS_NONE
	c.button_pressed = bool(AppState.get_setting(key))
	c.toggled.connect(func(on: bool) -> void: AppState.set_setting(key, on))
	_checks[key] = c
	return c


func _color(key: String, text: String) -> HBoxContainer:
	var h := HBoxContainer.new()
	var l := Label.new()
	l.text = text
	l.custom_minimum_size = Vector2(120, 0)
	h.add_child(l)
	var b := ColorPickerButton.new()
	b.color = AppState.get_setting(key)
	b.edit_alpha = false
	b.focus_mode = Control.FOCUS_NONE
	b.custom_minimum_size = Vector2(90, 24)
	b.color_changed.connect(func(c: Color) -> void: AppState.set_setting(key, c))
	h.add_child(b)
	_colors[key] = b
	return h


## scale: display multiplier (e.g. 100 to show 0..1 as 0..100%).
func _slider(key: String, label: String, lo: float, hi: float, step: float, fmt: String, scale: float = 1.0) -> HBoxContainer:
	var h := HBoxContainer.new()
	var l := Label.new()
	l.text = label
	l.custom_minimum_size = Vector2(120, 0)
	h.add_child(l)
	var s := HSlider.new()
	s.min_value = lo * scale
	s.max_value = hi * scale
	s.step = step * scale
	s.set_meta("scale", scale)
	s.value = float(AppState.get_setting(key)) * scale
	s.focus_mode = Control.FOCUS_NONE
	s.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	s.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	h.add_child(s)
	var num := Label.new()
	num.custom_minimum_size = Vector2(70, 0)
	num.text = fmt % s.value
	h.add_child(num)
	var is_int := typeof(AppState.get_setting(key)) == TYPE_INT
	s.value_changed.connect(func(x: float) -> void:
		num.text = fmt % x
		var raw := x / scale
		AppState.set_setting(key, int(raw) if is_int else raw))
	_sliders[key] = s
	return h
