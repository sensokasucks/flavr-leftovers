class_name AudienceView
extends Node3D
## Draws the chat audience in the current room: a silhouette per seat, a name tag and
## speech bubbles. Attached to the room by RoomHost and freed with it. The roster itself
## lives in AudienceManager; this node only shows it.

const SILHOUETTE: Texture2D = preload("res://core/audience/silhouette.png")
const EMPTY_COLOR: Color = Color(0.6, 0.6, 0.66, 0.22)
const SPEAKER_COLOR_BOOST: float = 1.25
## Where the head is in silhouette.png (pixels): centre and the radius inside the rim.
const HEAD_CENTER: Vector2 = Vector2(128, 94)
const HEAD_RADIUS: float = 56.0
const AVATAR_PX: int = 128

## Height of the silhouette (head-and-shoulders bust), metres.
@export var bust_height: float = 0.78
## How far the bust's bottom sits above the seat surface.
@export var bust_lift: float = 0.18
## Gap between the top of the head and the tail of a speech bubble.
@export var bubble_gap: float = 0.12
## Bubble size in metres per pixel at 100% bubble size.
@export var bubble_pixel_size: float = 0.0021
@export var fade_time: float = 0.35
## Silhouettes closer to the camera than this fade out, so heads in the front row
## don't block the view (they're fully visible again at near_fade_end).
@export var near_fade_start: float = 1.2
@export var near_fade_end: float = 2.6
## Bubbles and name tags grow with distance so they stay readable from far cameras:
## normal size up to this distance, then proportionally larger...
@export var readable_distance: float = 5.0
## ...up to this many times their normal size.
@export var max_distance_scale: float = 3.5

var _seats: Array[Dictionary] = []   # {root, sprite, label, bubble_sprite, viewport, bubble, queue, timer, scale}


## Called by RoomHost with the room's seat transforms (global).
func setup(seats: Array[Transform3D]) -> void:
	for t in seats:
		_seats.append(_build_seat(t))
	AudienceManager.set_capacity(_seats.size())
	for i in _seats.size():
		_refresh_seat(i, false)
	_apply_visibility()


func _ready() -> void:
	EventBus.audience_seated.connect(_on_seated)
	EventBus.audience_left.connect(_on_left)
	EventBus.audience_spoke.connect(_on_spoke)
	EventBus.emote_ready.connect(_on_emote_ready)
	EventBus.audience_updated.connect(_on_updated)
	EventBus.setting_changed.connect(_on_setting_changed)


func _exit_tree() -> void:
	EventBus.emote_ready.disconnect(_on_emote_ready)
	EventBus.audience_updated.disconnect(_on_updated)
	EventBus.audience_seated.disconnect(_on_seated)
	EventBus.audience_left.disconnect(_on_left)
	EventBus.audience_spoke.disconnect(_on_spoke)
	EventBus.setting_changed.disconnect(_on_setting_changed)


func _process(delta: float) -> void:
	var cam := get_viewport().get_camera_3d()
	var cam_pos := cam.global_position if cam else Vector3(0, 1e6, 0)
	var names_on := bool(AppState.get_setting("audience_names"))
	for i in _seats.size():
		var s: Dictionary = _seats[i]
		var root: Node3D = s["root"]
		var sc: float = s["scale"]
		var head := root.global_position + Vector3.UP * (bust_lift + bust_height) * sc
		var d := head.distance_to(cam_pos)
		var near := smoothstep(near_fade_start * sc, near_fade_end * sc, d)
		var c: Color = s["color"]
		var fade := lerpf(0.08, 1.0, near)
		(s["sprite"] as Sprite3D).modulate = Color(c.r, c.g, c.b, c.a * fade)
		(s["head"] as Sprite3D).modulate = Color(1, 1, 1, fade)
		var grow := clampf(d / readable_distance, 1.0, max_distance_scale)
		var label: Label3D = s["label"]
		label.visible = names_on and bool(s["seated"]) and s["bubble_sprite"] == null and near > 0.5
		label.scale = Vector3.ONE * grow
		(s["holder"] as Node3D).scale = Vector3.ONE * grow
		if s["bubble_sprite"] == null:
			continue
		s["timer"] = float(s["timer"]) - delta
		if float(s["timer"]) <= 0.0:
			_next_bubble(i)


# ── Building ─────────────────────────────────────────────────
func _build_seat(t: Transform3D) -> Dictionary:
	var sc := t.basis.get_scale().x
	var root := Node3D.new()
	root.name = "Seat%d" % _seats.size()
	add_child(root)
	root.global_position = t.origin
	var spr := Sprite3D.new()
	spr.texture = SILHOUETTE
	spr.pixel_size = bust_height * sc / float(SILHOUETTE.get_height())
	spr.billboard = BaseMaterial3D.BILLBOARD_FIXED_Y
	spr.shaded = false
	spr.alpha_cut = SpriteBase3D.ALPHA_CUT_DISABLED
	spr.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	spr.position.y = (bust_lift + bust_height * 0.5) * sc
	spr.modulate = EMPTY_COLOR
	root.add_child(spr)
	# the chatter's profile picture, laid over the silhouette's head (inside its coloured rim)
	var head := Sprite3D.new()
	head.billboard = BaseMaterial3D.BILLBOARD_FIXED_Y
	head.shaded = false
	head.alpha_cut = SpriteBase3D.ALPHA_CUT_DISABLED
	head.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	head.render_priority = 1
	head.pixel_size = spr.pixel_size * (HEAD_RADIUS * 2.0) / float(AVATAR_PX)
	var sil_center := Vector2(SILHOUETTE.get_width(), SILHOUETTE.get_height()) * 0.5
	head.position.y = spr.position.y + (sil_center.y - HEAD_CENTER.y) * spr.pixel_size
	head.position.x = (HEAD_CENTER.x - sil_center.x) * spr.pixel_size
	head.visible = false
	root.add_child(head)
	var label := Label3D.new()
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	label.font_size = 40
	label.pixel_size = 0.0022 * sc
	label.outline_size = 12
	label.outline_modulate = Color(0, 0, 0, 0.85)
	label.position.y = (bust_lift + bust_height + 0.07) * sc
	label.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	label.visible = false
	root.add_child(label)
	var holder := Node3D.new()      # bubble anchor (tail tip); scaled with camera distance
	holder.position.y = (bust_lift + bust_height + bubble_gap) * sc
	root.add_child(holder)
	return {"root": root, "sprite": spr, "head": head, "avatar": "", "label": label, "holder": holder, "bubble_sprite": null, "viewport": null,
		"bubble": null, "queue": [], "timer": 0.0, "scale": sc, "seated": false, "color": EMPTY_COLOR,
		"parts": [], "waiting": []}


func _refresh_seat(i: int, animate: bool) -> void:
	var s: Dictionary = _seats[i]
	var m := AudienceManager.get_seat_member(i)
	var spr: Sprite3D = s["sprite"]
	var label: Label3D = s["label"]
	s["seated"] = not m.is_empty()
	var target := EMPTY_COLOR
	if s["seated"]:
		target = (m["color"] as Color)
		label.text = String(m["name"])
		label.modulate = m["color"]
	else:
		_clear_bubbles(i)
	_refresh_head(i, m)
	var show_seat := bool(s["seated"]) or bool(AppState.get_setting("audience_show_empty"))
	if animate:
		var tw := create_tween().set_parallel(true)
		tw.tween_method(func(c: Color) -> void: s["color"] = c, s["color"], target, fade_time)
		if s["seated"]:
			spr.scale = Vector3.ONE * 0.85
			tw.tween_property(spr, "scale", Vector3.ONE, fade_time).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
		spr.visible = true
		if not show_seat:
			tw.chain().tween_callback(func() -> void: spr.visible = _seat_visible(i))
	else:
		s["color"] = target
		spr.visible = show_seat


func _seat_visible(i: int) -> bool:
	return bool(_seats[i]["seated"]) or bool(AppState.get_setting("audience_show_empty"))


func _apply_visibility() -> void:
	visible = bool(AppState.get_setting("audience_enabled"))
	for i in _seats.size():
		var s: Dictionary = _seats[i]
		(s["sprite"] as Sprite3D).visible = _seat_visible(i)


# ── Speech bubbles ───────────────────────────────────────────
func _on_spoke(slot: int, parts: Array) -> void:
	if slot < 0 or slot >= _seats.size():
		return
	var s: Dictionary = _seats[slot]
	for p: Variant in parts:          # start downloading emotes right away
		if p is Dictionary:
			EmoteCache.get_texture(String(p["url"]))
	var q: Array = s["queue"]
	q.append(parts)
	while q.size() > 3:
		q.pop_front()
	if s["bubble_sprite"] == null:
		_next_bubble(slot)
	elif float(s["timer"]) > 1.2 and q.size() > 0:
		s["timer"] = 1.2        # someone is typing fast: move the current bubble along


func _next_bubble(i: int) -> void:
	var s: Dictionary = _seats[i]
	var q: Array = s["queue"]
	if q.is_empty():
		_hide_bubble(i)
		return
	var parts: Array = q.pop_front()
	var m := AudienceManager.get_seat_member(i)
	if m.is_empty():
		_clear_bubbles(i)
		return
	if s["bubble_sprite"] == null:
		_make_bubble(i)
	s["parts"] = parts
	_render_bubble(i)
	var spr: Sprite3D = s["bubble_sprite"]
	spr.position.y = 0.1 * float(s["scale"]) if i % 2 == 1 else 0.0     # stagger neighbours a little
	var seconds := float(AppState.get_setting("audience_bubble_s"))
	if not q.is_empty():
		seconds *= 0.6
	s["timer"] = seconds
	spr.modulate = Color(1, 1, 1, 0)
	spr.scale = Vector3.ONE * 0.8
	var tw := create_tween().set_parallel(true)
	tw.tween_property(spr, "modulate:a", 1.0, 0.15)
	tw.tween_property(spr, "scale", Vector3.ONE, 0.2).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	# the speaker's silhouette brightens while they talk
	var boosted := (m["color"] as Color) * SPEAKER_COLOR_BOOST
	s["color"] = Color(boosted.r, boosted.g, boosted.b, 1.0)


## Draws the seat's current message into its bubble (again when an emote finishes loading).
func _render_bubble(i: int) -> void:
	var s: Dictionary = _seats[i]
	var m := AudienceManager.get_seat_member(i)
	if m.is_empty() or s["bubble"] == null:
		return
	var textures: Dictionary = {}
	var waiting: Array = []
	for p: Variant in s["parts"]:
		if p is Dictionary:
			var url := String(p["url"])
			var tex := EmoteCache.get_texture(url)
			if tex:
				textures[url] = tex
			elif not EmoteCache.is_failed(url):
				waiting.append(url)
	s["waiting"] = waiting
	var vp: SubViewport = s["viewport"]
	var bubble: SpeechBubble = s["bubble"]
	var px := bubble.set_content(String(m["name"]), s["parts"], m["color"], int(m["style"]), textures)
	vp.size = px
	var animated := false
	for t: Texture2D in textures.values():
		animated = animated or EmoteCache.is_animated(t)
	# animated emotes need the bubble redrawn every frame; still ones just once
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS if animated else SubViewport.UPDATE_ONCE
	var spr: Sprite3D = s["bubble_sprite"]
	var sc: float = float(s["scale"]) * float(AppState.get_setting("audience_bubble_size"))
	spr.pixel_size = bubble_pixel_size * sc
	var tip := bubble.get_tail_tip()
	spr.offset = Vector2(px.x * 0.5 - tip.x, tip.y - px.y * 0.5)   # tail tip on the anchor


## Shows the chatter's picture on the head once it has downloaded (hidden otherwise).
func _refresh_head(i: int, m: Dictionary) -> void:
	var s: Dictionary = _seats[i]
	var head: Sprite3D = s["head"]
	var url := String(m.get("avatar", "")) if not m.is_empty() else ""
	s["avatar"] = url
	var tex: Texture2D = EmoteCache.get_circle_texture(url, AVATAR_PX) if url != "" else null
	head.texture = tex
	head.visible = tex != null


func _on_updated(slot: int) -> void:
	if slot >= 0 and slot < _seats.size():
		_refresh_head(slot, AudienceManager.get_seat_member(slot))


func _on_emote_ready(url: String) -> void:
	for i in _seats.size():
		var s: Dictionary = _seats[i]
		if String(s["avatar"]) == url:
			_refresh_head(i, AudienceManager.get_seat_member(i))
		if s["bubble"] != null and (s["waiting"] as Array).has(url):
			_render_bubble(i)


func _make_bubble(i: int) -> void:
	var s: Dictionary = _seats[i]
	var vp := SubViewport.new()
	vp.transparent_bg = true
	vp.disable_3d = true
	vp.msaa_2d = Viewport.MSAA_4X
	vp.render_target_update_mode = SubViewport.UPDATE_ONCE
	var bubble := SpeechBubble.new()
	vp.add_child(bubble)
	s["root"].add_child(vp)
	var spr := Sprite3D.new()
	spr.texture = vp.get_texture()
	spr.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	spr.no_depth_test = true
	spr.shaded = false
	spr.render_priority = 10
	spr.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	spr.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR
	s["holder"].add_child(spr)
	s["viewport"] = vp
	s["bubble"] = bubble
	s["bubble_sprite"] = spr


func _hide_bubble(i: int) -> void:
	var s: Dictionary = _seats[i]
	var spr: Sprite3D = s["bubble_sprite"]
	if spr == null:
		return
	var vp: SubViewport = s["viewport"]
	s["bubble_sprite"] = null
	s["viewport"] = null
	s["bubble"] = null
	var tw := create_tween()
	tw.tween_property(spr, "modulate:a", 0.0, 0.3)
	tw.tween_callback(func() -> void:
		spr.queue_free()
		vp.queue_free())
	var m := AudienceManager.get_seat_member(i)
	if not m.is_empty():
		s["color"] = m["color"]


func _clear_bubbles(i: int) -> void:
	(_seats[i]["queue"] as Array).clear()
	_hide_bubble(i)


# ── EventBus handlers ────────────────────────────────────────
func _on_seated(slot: int) -> void:
	if slot >= 0 and slot < _seats.size():
		_refresh_seat(slot, true)


func _on_left(slot: int) -> void:
	if slot >= 0 and slot < _seats.size():
		_refresh_seat(slot, true)


func _on_setting_changed(key: String, _value: Variant) -> void:
	if key in ["audience_enabled", "audience_names", "audience_show_empty"]:
		_apply_visibility()
