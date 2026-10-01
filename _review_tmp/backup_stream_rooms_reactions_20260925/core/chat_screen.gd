class_name ChatScreen
extends Node3D
## A live chat panel under the main screen (rooms with a CHAT_Screen marker).
## RoomHost puts it on the marker: the marker is the panel's top centre, +Z faces the audience.
## Reads the same chat as the virtual audience (ChatFeed -> Stream Core), so it follows the
## audience's "Ignore names" and "Hide !commands" options and its name colours.
## Messages flow top-to-bottom through N columns (like a newspaper); the oldest drop off
## when the panel is full. Drawn in 2D into a SubViewport that only redraws when chat changes.

## Pixels per metre of the panel (capped at MAX_PX wide).
const PX_PER_M: float = 300.0
const MAX_PX: int = 3072
const KEEP: int = 80
const MAX_TEXT: int = 300
const BASE_TEXT: int = 32
const PAD: float = 16.0
const GAP: float = 22.0
const BAR_W: float = 5.0
const LINE_GAP: float = 8.0
const TEXT_COLOR: Color = Color(0.93, 0.93, 0.95)
const EMOJI_FONTS: PackedStringArray = ["Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", "Twemoji Mozilla"]

static var _font: Font
static var _bold: Font

var _size: Vector2 = Vector2(8.6, 1.5)
var _vp: SubViewport
var _bg: Panel
var _bg_style: StyleBoxFlat = StyleBoxFlat.new()
var _status: Label
var _quad: MeshInstance3D
var _mat: StandardMaterial3D = StandardMaterial3D.new()
## One per message: {name, hex, parts: Array, avatar, urls: PackedStringArray, node: Control, rtl: RichTextLabel, bar: ColorRect}
var _cards: Array[Dictionary] = []
var _dirty: bool = true
var _animating: bool = false


func setup(size_m: Vector2) -> void:
	_size = size_m


func _ready() -> void:
	var px := Vector2i(roundi(_size.x * PX_PER_M), roundi(_size.y * PX_PER_M))
	if px.x > MAX_PX:
		px = Vector2i(MAX_PX, roundi(float(MAX_PX) * _size.y / _size.x))
	_vp = SubViewport.new()
	_vp.size = px
	_vp.transparent_bg = true
	_vp.disable_3d = true
	_vp.gui_disable_input = true
	_vp.render_target_update_mode = SubViewport.UPDATE_ONCE
	add_child(_vp)
	_bg = Panel.new()
	_bg.size = Vector2(px)
	_bg_style.set_corner_radius_all(18)
	_bg.add_theme_stylebox_override("panel", _bg_style)
	_vp.add_child(_bg)
	_status = Label.new()
	_status.size = Vector2(px)
	_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_status.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_status.add_theme_font_size_override("font_size", 30)
	_status.add_theme_color_override("font_color", Color(1, 1, 1, 0.45))
	_vp.add_child(_status)

	_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	_mat.albedo_color = Color(0.9, 0.9, 0.9)
	_mat.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR
	_mat.albedo_texture = _vp.get_texture()
	_quad = MeshInstance3D.new()
	var q := QuadMesh.new()
	q.size = _size
	_quad.mesh = q
	_quad.position = Vector3(0, -_size.y * 0.5, 0)
	_quad.material_override = _mat
	_quad.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(_quad)

	EventBus.chat_message_received.connect(_on_chat)
	EventBus.chat_status_changed.connect(_on_status)
	EventBus.emote_ready.connect(_on_emote_ready)
	EventBus.setting_changed.connect(_on_setting_changed)
	_apply_style()
	_refresh_visibility()


func _exit_tree() -> void:
	EventBus.chat_message_received.disconnect(_on_chat)
	EventBus.chat_status_changed.disconnect(_on_status)
	EventBus.emote_ready.disconnect(_on_emote_ready)
	EventBus.setting_changed.disconnect(_on_setting_changed)


func _process(_delta: float) -> void:
	if _dirty and visible:
		_dirty = false
		_layout()
		# animated emotes on the panel: redraw every frame so they play; otherwise only on change
		_animating = false
		for c in _cards:
			_animating = _animating or (bool(c.get("animated", false)) and (c["node"] as Control).visible)
		_vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS if _animating else SubViewport.UPDATE_ONCE


## How many messages it holds (for tests).
func get_message_count() -> int:
	return _cards.size()


## How many are on the panel right now (for tests).
func get_visible_count() -> int:
	var n := 0
	for c in _cards:
		if (c["node"] as Control).visible:
			n += 1
	return n


func clear() -> void:
	for c in _cards:
		(c["node"] as Control).queue_free()
	_cards.clear()
	_dirty = true


# ── Chat ─────────────────────────────────────────────────────
func _on_chat(msg: Dictionary) -> void:
	if bool(msg.get("system", false)):
		return
	var name := String(msg.get("name", ""))
	if name == "" or AudienceManager.is_ignored(name):
		return
	var raw := String(msg.get("text", "")).strip_edges()
	if raw == "" or (raw.begins_with("!") and bool(AppState.get_setting("audience_hide_commands"))):
		return
	var parts := AudienceManager.message_parts(raw, msg.get("emotes", []) as Array, MAX_TEXT)
	if parts.is_empty():
		return
	var urls := PackedStringArray()
	for p: Variant in parts:
		if p is Dictionary:
			urls.append(String(p["url"]))
	var avatar := String(msg.get("avatar", ""))
	if avatar != "":
		urls.append(avatar)
	var card := {"name": name, "hex": String(msg.get("color", "")), "parts": parts, "avatar": avatar, "urls": urls}
	var node := Control.new()
	var bar := ColorRect.new()
	node.add_child(bar)
	var rtl := RichTextLabel.new()
	rtl.bbcode_enabled = false
	rtl.fit_content = true
	rtl.scroll_active = false
	rtl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	rtl.mouse_filter = Control.MOUSE_FILTER_IGNORE
	rtl.add_theme_font_override("normal_font", _shared_font())
	rtl.add_theme_font_override("bold_font", _bold_font())
	rtl.add_theme_color_override("default_color", TEXT_COLOR)
	rtl.position = Vector2(BAR_W + 10.0, 0)
	node.add_child(rtl)
	node.visible = false
	_bg.add_child(node)
	card["node"] = node
	card["rtl"] = rtl
	card["bar"] = bar
	_cards.append(card)
	_fill(card)
	while _cards.size() > KEEP:
		(_cards.pop_front()["node"] as Control).queue_free()
	_dirty = true


func _fill(card: Dictionary) -> void:
	var rtl: RichTextLabel = card["rtl"]
	var size := _text_size()
	var color := AudienceManager.color_for(String(card["name"]), String(card["hex"]))
	(card["bar"] as ColorRect).color = color
	rtl.clear()
	rtl.add_theme_font_size_override("normal_font_size", size)
	rtl.add_theme_font_size_override("bold_font_size", size)
	var pic := String(card["avatar"])
	if pic != "" and bool(AppState.get_setting("chat_screen_pictures")) and bool(AppState.get_setting("audience_avatars")):
		var tex := EmoteCache.get_circle_texture(pic)
		if tex:
			var s := roundi(size * 1.25)
			rtl.add_image(tex, s, s, Color.WHITE, INLINE_ALIGNMENT_CENTER)
			rtl.add_text(" ")
	rtl.push_bold()
	rtl.push_color(color)
	rtl.add_text(String(card["name"]))
	rtl.pop()
	rtl.pop()
	rtl.add_text("  ")
	var h := roundi(size * 1.35)
	card["animated"] = false
	for p: Variant in card["parts"]:
		if p is Dictionary:
			var tex: Texture2D = EmoteCache.get_texture(String(p["url"]))
			if tex:
				card["animated"] = bool(card["animated"]) or EmoteCache.is_animated(tex)
				var w := roundi(float(h) * tex.get_width() / maxf(tex.get_height(), 1.0))
				rtl.add_image(tex, w, h, Color.WHITE, INLINE_ALIGNMENT_CENTER, Rect2(), null, false, String(p["name"]))
			else:
				rtl.add_text(String(p["name"]))
		else:
			rtl.add_text(String(p))


func _on_emote_ready(url: String) -> void:
	for c in _cards:
		if (c["urls"] as PackedStringArray).has(url):
			_fill(c)
			_dirty = true


func _on_status(_info: Dictionary) -> void:
	_dirty = true


# ── Layout ───────────────────────────────────────────────────
## Newspaper flow: fill column 1 top to bottom, then column 2 ... Shows as many of the
## newest messages as fit; the rest stay hidden (and are dropped after KEEP).
func _layout() -> void:
	var area := Vector2(_vp.size) - Vector2(PAD, PAD) * 2.0
	var cols := clampi(int(AppState.get_setting("chat_screen_columns")), 1, 4)
	var col_w := (area.x - GAP * (cols - 1)) / cols
	var heights: Array[float] = []
	for c in _cards:
		var rtl: RichTextLabel = c["rtl"]
		var w := col_w - BAR_W - 10.0
		rtl.custom_minimum_size = Vector2(w, 0)
		rtl.size = Vector2(w, 0)
		heights.append(float(rtl.get_content_height()))
	# the oldest message that still lets everything after it fit
	var start := _cards.size()
	while start > 0 and _fits(heights, start - 1, cols, area.y):
		start -= 1
	start = mini(start, maxi(_cards.size() - 1, 0))     # always show the newest, even if it's tall
	var col := 0
	var y := 0.0
	for i in _cards.size():
		var node: Control = _cards[i]["node"]
		if i < start:
			node.visible = false
			continue
		var h := heights[i]
		if y > 0.0 and y + h > area.y:
			col += 1
			y = 0.0
		node.visible = col < cols
		node.position = Vector2(PAD + col * (col_w + GAP), PAD + y)
		node.size = Vector2(col_w, h)
		var bar: ColorRect = _cards[i]["bar"]
		bar.position = Vector2(0, 2)
		bar.size = Vector2(BAR_W, maxf(h - 4.0, 4.0))
		y += h + LINE_GAP
	_status.visible = _cards.is_empty()
	if _status.visible:
		if not bool(AppState.get_setting("chat_enabled")):
			_status.text = "Chat is off (Audience tab > Connect)"
		elif not ChatFeed.is_connected_to_core():
			_status.text = "Waiting for Stream Core…"
		else:
			_status.text = "Waiting for chat…"


func _fits(heights: Array[float], start: int, cols: int, col_h: float) -> bool:
	var col := 0
	var y := 0.0
	for i in range(start, heights.size()):
		var h := heights[i]
		if y > 0.0 and y + h > col_h:
			col += 1
			y = 0.0
			if col >= cols:
				return false
		if h > col_h:
			return false
		y += h + LINE_GAP
	return true


# ── Settings ─────────────────────────────────────────────────
func _on_setting_changed(key: String, _value: Variant) -> void:
	match key:
		"chat_screen":
			_refresh_visibility()
		"chat_screen_bg":
			_apply_style()
		"chat_screen_text", "chat_screen_pictures", "audience_avatars", "audience_platform_colors":
			for c in _cards:
				_fill(c)
			_dirty = true
		"chat_screen_columns", "chat_enabled":
			_dirty = true


func _apply_style() -> void:
	_bg_style.bg_color = Color(0.03, 0.035, 0.05, clampf(float(AppState.get_setting("chat_screen_bg")), 0.0, 1.0))
	_dirty = true


func _refresh_visibility() -> void:
	visible = bool(AppState.get_setting("chat_screen"))
	_dirty = true


func _text_size() -> int:
	return roundi(BASE_TEXT * clampf(float(AppState.get_setting("chat_screen_text")), 0.5, 3.0))


static func _shared_font() -> Font:
	if _font == null:
		var emoji := SystemFont.new()
		emoji.font_names = EMOJI_FONTS
		var f := FontVariation.new()
		f.base_font = ThemeDB.fallback_font
		f.fallbacks = [emoji]
		_font = f
	return _font


static func _bold_font() -> Font:
	if _bold == null:
		var f := FontVariation.new()
		f.base_font = _shared_font()
		f.variation_embolden = 0.8
		_bold = f
	return _bold
