class_name CameraRig
extends Camera3D
## Camera presets from the room's CAM_* markers, with smooth moves between them,
## plus free-look (hold right mouse, WASD / Q-E, Shift = faster).
## During a react pause it can jump to the room's "Reaction" preset and return after.

@export var move_time: float = 0.9
@export var look_sensitivity: float = 0.0025
@export var move_speed: float = 2.5

var _presets: Array[Transform3D] = []
var _labels: PackedStringArray = []
var _reaction_index: int = -1
var _pre_react_transform: Transform3D
var _pre_react_valid: bool = false
var _tween: Tween
var _yaw: float = 0.0
var _pitch: float = 0.0
var _looking: bool = false


func _ready() -> void:
	EventBus.camera_preset_requested.connect(go_to_preset)
	EventBus.react_pause_changed.connect(_on_react_pause_changed)


# ── Public API ───────────────────────────────────────────────
## Called by main when a room is ready (parent wiring).
func set_presets(markers: Array[Node3D], labels: PackedStringArray) -> void:
	_presets.clear()
	_labels = labels
	_reaction_index = -1
	for i in markers.size():
		_presets.append(markers[i].global_transform.orthonormalized())
		if labels[i].to_lower().contains("reaction"):
			_reaction_index = i
	_pre_react_valid = false
	if not _presets.is_empty():
		go_to_preset(0, false)


func go_to_preset(index: int, smooth: bool = true) -> void:
	if index < 0 or index >= _presets.size():
		return
	_move_to(_presets[index], smooth)


# ── Input: free-look ─────────────────────────────────────────
func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_RIGHT:
		_looking = event.pressed
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if _looking else Input.MOUSE_MODE_VISIBLE
		if _looking:
			_kill_tween()
			_sync_angles()
			get_viewport().gui_release_focus()
	elif event is InputEventMouseMotion and _looking:
		_yaw -= event.relative.x * look_sensitivity
		_pitch = clampf(_pitch - event.relative.y * look_sensitivity, deg_to_rad(-85.0), deg_to_rad(85.0))
		rotation = Vector3(_pitch, _yaw, 0.0)


func _process(delta: float) -> void:
	if get_viewport().gui_get_focus_owner() is LineEdit:
		return
	var input := Vector3.ZERO
	if Input.is_key_pressed(KEY_W): input.z -= 1.0
	if Input.is_key_pressed(KEY_S): input.z += 1.0
	if Input.is_key_pressed(KEY_A): input.x -= 1.0
	if Input.is_key_pressed(KEY_D): input.x += 1.0
	if Input.is_key_pressed(KEY_Q): input.y -= 1.0
	if Input.is_key_pressed(KEY_E): input.y += 1.0
	if input == Vector3.ZERO:
		return
	_kill_tween()
	_sync_angles()
	var speed := move_speed * (3.0 if Input.is_key_pressed(KEY_SHIFT) else 1.0)
	var flat := Basis(Vector3.UP, _yaw) * Vector3(input.x, 0.0, input.z)
	if flat.length() > 0.0:
		global_position += flat.normalized() * speed * delta
	global_position.y += input.y * speed * delta


# ── Private ──────────────────────────────────────────────────
func _on_react_pause_changed(paused: bool) -> void:
	if not AppState.get_setting("react_camera") or _reaction_index < 0:
		return
	if paused:
		_pre_react_transform = global_transform
		_pre_react_valid = true
		go_to_preset(_reaction_index)
	elif _pre_react_valid:
		_pre_react_valid = false
		_move_to(_pre_react_transform, true)


func _move_to(target: Transform3D, smooth: bool) -> void:
	_kill_tween()
	if not smooth:
		global_transform = target
		_sync_angles()
		return
	var from := global_transform
	_tween = create_tween().set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN_OUT)
	_tween.tween_method(func(t: float) -> void:
		global_transform = from.interpolate_with(target, t), 0.0, 1.0, move_time)
	_tween.tween_callback(_sync_angles)


func _kill_tween() -> void:
	if _tween and _tween.is_valid():
		_tween.kill()
	_tween = null


func _sync_angles() -> void:
	var fwd := -global_transform.basis.z
	_yaw = atan2(-fwd.x, -fwd.z)
	_pitch = asin(clampf(fwd.y, -1.0, 1.0))
