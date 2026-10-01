extends Node
## AudienceManager: who sits where in the virtual audience. Single source of truth
## for the roster; rooms only draw it (core/audience_view.gd).
##   - Someone who chats gets a free seat (random) and keeps it while they're active.
##   - No chat for "audience_idle_min" minutes -> they leave their seat.
##   - All seats full -> the person idle the longest gives up their seat.
##   - Each person has a colour (platform colour or one picked from their name) and a
##     speech-bubble shape, so they look the same every time they come back.
## The roster survives room changes; each room reports how many seats it has.

const BUBBLE_STYLES: int = 4
const MAX_TEXT: int = 140
## An emote counts as this many characters toward MAX_TEXT.
const EMOTE_WEIGHT: int = 3
const KICK_EMOTE_URL: String = "https://files.kick.com/emotes/%s/fullsize"

## key "platform:user_id" -> {key, name, color: Color, style: int, slot: int, last: float}
var _members: Dictionary = {}
var _slots: Array[String] = []      # slot -> member key ("" = empty)
var _rng: RandomNumberGenerator = RandomNumberGenerator.new()
var _check_in: float = 1.0
var _ignore: PackedStringArray = []
var _hide_avatars: PackedStringArray = []


func _ready() -> void:
	_rng.randomize()
	_parse_ignore()
	_parse_hidden_avatars()
	EventBus.chat_message_received.connect(_on_chat)
	EventBus.chat_user_updated.connect(_on_user_updated)
	EventBus.setting_changed.connect(_on_setting_changed)


func _process(delta: float) -> void:
	_check_in -= delta
	if _check_in > 0.0:
		return
	_check_in = 1.0
	_expire_idle()


# ── Public API ───────────────────────────────────────────────
## Called by a room's audience view: how many seats this room has (0 = none).
func set_capacity(count: int) -> void:
	count = maxi(count, 0)
	if count == _slots.size():
		return
	# unseat anyone whose seat no longer exists (they stay in the roster)
	for i in range(count, _slots.size()):
		if _slots[i] != "":
			_members[_slots[i]]["slot"] = -1
	_slots.resize(count)
	for i in count:
		if _slots[i] != "" and not _members.has(_slots[i]):
			_slots[i] = ""
	# seat waiting members, most recently active first
	var waiting: Array = _members.values().filter(func(m: Dictionary) -> bool: return int(m["slot"]) < 0)
	waiting.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return float(a["last"]) > float(b["last"]))
	for m: Dictionary in waiting:
		var s := _free_slot()
		if s < 0:
			break
		_seat(m, s, false)
	_emit_count()


func get_capacity() -> int:
	return _slots.size()


## {name, color, style, avatar} for the person in a seat, or {} if it's empty.
## avatar is "" when pictures are off, hidden for this person, or unknown.
func get_seat_member(slot: int) -> Dictionary:
	if slot < 0 or slot >= _slots.size() or _slots[slot] == "":
		return {}
	var m: Dictionary = _members[_slots[slot]]
	var avatar := String(m.get("avatar", ""))
	if not bool(AppState.get_setting("audience_avatars")) or _hide_avatars.has(String(m["name"]).to_lower()):
		avatar = ""
	return {"name": m["name"], "color": m["color"], "style": m["style"], "avatar": avatar}


func get_seated_count() -> int:
	return _slots.filter(func(k: String) -> bool: return k != "").size()


## Everyone leaves their seat.
func clear() -> void:
	for i in _slots.size():
		if _slots[i] != "":
			_slots[i] = ""
			EventBus.audience_left.emit(i)
	_members.clear()
	_emit_count()


# ── Chat handling ────────────────────────────────────────────
func _on_chat(msg: Dictionary) -> void:
	if bool(msg.get("system", false)):
		return
	var name := String(msg.get("name", ""))
	if name == "" or is_ignored(name):
		return
	var now := Time.get_unix_time_from_system()
	var ts := float(msg.get("timestamp", now))
	var history := bool(msg.get("history", false))
	if history and now - ts > _idle_seconds():
		return        # old backlog from before we connected
	var key := "%s:%s" % [String(msg.get("platform", "")), String(msg.get("user_id", name.to_lower()))]
	var m: Dictionary = _members.get(key, {})
	if m.is_empty():
		m = {"key": key, "name": name, "color": color_for(name, String(msg.get("color", ""))),
			"style": absi(hash(name.to_lower())) % BUBBLE_STYLES, "slot": -1, "last": ts}
		_members[key] = m
	m["last"] = maxf(float(m["last"]), minf(ts, now))
	m["name"] = name
	var avatar := String(msg.get("avatar", ""))
	if avatar != "" and avatar != String(m.get("avatar", "")):
		m["avatar"] = avatar
		if int(m["slot"]) >= 0:
			EventBus.audience_updated.emit(int(m["slot"]))
	if int(m["slot"]) < 0 and not _slots.is_empty():
		var s := _free_slot()
		if s < 0:
			s = _evict_most_idle()
		if s >= 0:
			_seat(m, s, true)
	if history or int(m["slot"]) < 0:
		return
	var raw := String(msg.get("text", "")).strip_edges()
	if raw == "" or (raw.begins_with("!") and bool(AppState.get_setting("audience_hide_commands"))):
		return
	var parts := message_parts(raw, msg.get("emotes", []) as Array)
	if parts.is_empty():
		return
	EventBus.audience_spoke.emit(int(m["slot"]), parts)


func _seat(m: Dictionary, slot: int, notify_count: bool) -> void:
	m["slot"] = slot
	_slots[slot] = String(m["key"])
	EventBus.audience_seated.emit(slot)
	if notify_count:
		_emit_count()


func _free_slot() -> int:
	var free: Array[int] = []
	for i in _slots.size():
		if _slots[i] == "":
			free.append(i)
	if free.is_empty():
		return -1
	return free[_rng.randi_range(0, free.size() - 1)]


func _evict_most_idle() -> int:
	var best := -1
	var oldest := INF
	for i in _slots.size():
		var k := _slots[i]
		if k != "" and float(_members[k]["last"]) < oldest:
			oldest = float(_members[k]["last"])
			best = i
	if best >= 0:
		_unseat(best, false)
	return best


func _unseat(slot: int, forget: bool) -> void:
	var k := _slots[slot]
	if k == "":
		return
	_slots[slot] = ""
	if forget:
		_members.erase(k)
	else:
		_members[k]["slot"] = -1
	EventBus.audience_left.emit(slot)


func _expire_idle() -> void:
	var cutoff := Time.get_unix_time_from_system() - _idle_seconds()
	var changed := false
	for k: String in _members.keys():
		var m: Dictionary = _members[k]
		if float(m["last"]) < cutoff:
			if int(m["slot"]) >= 0:
				_unseat(int(m["slot"]), true)
				changed = true
			else:
				_members.erase(k)
	if changed:
		_emit_count()


func _emit_count() -> void:
	EventBus.audience_count_changed.emit(get_seated_count(), _slots.size())


func _idle_seconds() -> float:
	return maxf(float(AppState.get_setting("audience_idle_min")), 0.05) * 60.0


## The message as a list of text pieces and emotes ({"url", "name"}), in order.
##   - Twitch: Stream Core sends emote ranges (native + BTTV/FFZ/7TV), inclusive code points.
##   - Kick: emotes are inline tokens "[emote:123:name]".
## Spaces are tidied and the whole thing is capped at max_text (an emote counts EMOTE_WEIGHT).
## Also used by the chat screen (core/chat_screen.gd).
func message_parts(text: String, ranges: Array, max_text: int = MAX_TEXT) -> Array:
	var raw: Array = []
	var pos := 0
	var sorted := ranges.duplicate()
	sorted.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return int(a.get("start", 0)) < int(b.get("start", 0)))
	for e: Dictionary in sorted:
		var s := int(e.get("start", -1))
		var t := int(e.get("end", -1))
		if s < pos or t < s or t >= text.length():
			continue
		var url := String(e.get("static_url", ""))
		if url == "":
			url = String(e.get("url", ""))
		if url == "":
			continue
		if s > pos:
			raw.append(text.substr(pos, s - pos))
		raw.append({"url": url, "name": text.substr(s, t - s + 1)})
		pos = t + 1
	if pos < text.length():
		raw.append(text.substr(pos))
	# Kick tokens inside the text pieces
	var kick := RegEx.create_from_string("\\[emote:(\\d+):([^\\]]+)\\]")
	var parts: Array = []
	for piece: Variant in raw:
		if piece is Dictionary:
			parts.append(piece)
			continue
		var s2 := String(piece)
		var at := 0
		for m in kick.search_all(s2):
			if m.get_start() > at:
				parts.append(s2.substr(at, m.get_start() - at))
			parts.append({"url": KICK_EMOTE_URL % m.get_string(1), "name": m.get_string(2)})
			at = m.get_end()
		if at < s2.length():
			parts.append(s2.substr(at))
	# tidy whitespace and cap the length
	var spaces := RegEx.create_from_string("\\s+")
	var out: Array = []
	var budget := max_text
	for p: Variant in parts:
		if budget <= 0:
			out.append("…")
			break
		if p is Dictionary:
			out.append(p)
			budget -= EMOTE_WEIGHT
			continue
		var s3 := spaces.sub(String(p), " ", true)
		if s3.length() > budget:
			s3 = s3.substr(0, budget - 1).strip_edges(false, true) + "…"
		budget -= s3.length()
		out.append(s3)
	if not out.is_empty() and out[0] is String:
		out[0] = String(out[0]).strip_edges(true, false)
	if not out.is_empty() and out[-1] is String:
		out[-1] = String(out[-1]).strip_edges(false, true)
	return out.filter(func(p: Variant) -> bool: return p is Dictionary or String(p) != "")


## Platform colour when it's usable, otherwise a colour picked from the name.
## Either way it's kept bright enough to read on a white bubble outline and in a dark room.
func color_for(name: String, platform_hex: String) -> Color:
	var c: Color
	if bool(AppState.get_setting("audience_platform_colors")) and Color.html_is_valid(platform_hex):
		c = Color.html(platform_hex)
	else:
		var h := float(absi(hash(name.to_lower())) % 1000) / 1000.0
		c = Color.from_hsv(fposmod(h * 0.618034 * 7.0, 1.0), 0.7, 0.95)
	var s := c.s
	if s < 0.15:
		# grey/white/black names: give them a soft colour so they still stand apart
		return Color.from_hsv(c.h if s > 0.02 else float(absi(hash(name)) % 360) / 360.0, 0.35, 0.95)
	return Color.from_hsv(c.h, clampf(s, 0.45, 0.85), clampf(c.v, 0.75, 1.0))


## True for names on the "Ignore names" list (bots).
func is_ignored(name: String) -> bool:
	return _ignore.has(name.to_lower())


func _on_user_updated(info: Dictionary) -> void:
	var key := "%s:%s" % [String(info.get("platform", "")), String(info.get("user_id", ""))]
	if not _members.has(key):
		return
	var m: Dictionary = _members[key]
	m["avatar"] = String(info.get("avatar", ""))
	if int(m["slot"]) >= 0:
		EventBus.audience_updated.emit(int(m["slot"]))


func _refresh_all_seats() -> void:
	for i in _slots.size():
		if _slots[i] != "":
			EventBus.audience_updated.emit(i)


func _parse_hidden_avatars() -> void:
	_hide_avatars.clear()
	for part in String(AppState.get_setting("audience_hide_avatars")).split(",", false):
		var p := part.strip_edges().to_lower()
		if p != "":
			_hide_avatars.append(p)


func _parse_ignore() -> void:
	_ignore.clear()
	for part in String(AppState.get_setting("audience_ignore")).split(",", false):
		var p := part.strip_edges().to_lower()
		if p != "":
			_ignore.append(p)


func _on_setting_changed(key: String, _value: Variant) -> void:
	if key == "audience_ignore":
		_parse_ignore()
	elif key == "audience_hide_avatars":
		_parse_hidden_avatars()
		_refresh_all_seats()
	elif key == "audience_avatars":
		_refresh_all_seats()
