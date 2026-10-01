class_name SpeechBubble
extends Control
## A comic speech bubble drawn in 2D (rendered into a SubViewport by AudienceView).
## White fill, outline in the speaker's colour, their name on top, tail at the lower left.
## Shapes (style): 0 rounded box, 1 oval, 2 slanted box, 3 pinched box.
## The text is a RichTextLabel so chat emotes sit inline and wrap with the words;
## emoji use the system's colour emoji font.

const MAX_TEXT_WIDTH: float = 380.0
const PAD: float = 20.0
const OUTLINE: float = 5.0
const TAIL_H: float = 30.0
const NAME_SIZE: int = 24
const TEXT_SIZE: int = 30
## Emote height inline with text, and when the message is only emotes.
const EMOTE_SIZE: int = 38
const EMOTE_ONLY_SIZE: int = 72
const FILL: Color = Color(1, 1, 1, 0.97)
const TEXT_COLOR: Color = Color(0.08, 0.08, 0.1)
const EMOJI_FONTS: PackedStringArray = ["Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", "Twemoji Mozilla"]

static var _font: Font

var _color: Color = Color.WHITE
var _style: int = 0
var _body: Rect2 = Rect2()
var _tail_tip: Vector2 = Vector2.ZERO
var _rtl: RichTextLabel


func _init() -> void:
	_rtl = RichTextLabel.new()
	_rtl.bbcode_enabled = false
	_rtl.fit_content = true
	_rtl.scroll_active = false
	_rtl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_rtl.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_rtl.add_theme_font_override("normal_font", _shared_font())
	_rtl.add_theme_font_size_override("normal_font_size", TEXT_SIZE)
	_rtl.add_theme_color_override("default_color", TEXT_COLOR)
	add_child(_rtl)


## Sets the content and resizes itself. parts: Strings and {"url", "name"} emotes.
## textures: url -> Texture2D for the emotes that are loaded (others show their name).
## Returns the pixel size the viewport needs.
func set_content(speaker: String, parts: Array, color: Color, style: int, textures: Dictionary) -> Vector2i:
	_color = color
	_style = clampi(style, 0, 3)
	var emote_only := parts.size() <= 6 and parts.all(func(p: Variant) -> bool:
		return (p is Dictionary and textures.has(String(p["url"]))) or (p is String and String(p).strip_edges() == ""))
	var h := EMOTE_ONLY_SIZE if emote_only else EMOTE_SIZE
	_rtl.clear()
	_rtl.push_font_size(NAME_SIZE)
	_rtl.push_color(color.darkened(0.45))
	_rtl.add_text(speaker)
	_rtl.pop()
	_rtl.pop()
	_rtl.newline()
	for p: Variant in parts:
		if p is Dictionary:
			var tex: Texture2D = textures.get(String(p["url"]))
			if tex:
				var w := int(round(float(h) * tex.get_width() / maxf(tex.get_height(), 1.0)))
				_rtl.add_image(tex, w, h, Color.WHITE, INLINE_ALIGNMENT_CENTER, Rect2(), null, false, String(p["name"]))
			else:
				_rtl.add_text(String(p["name"]))
		else:
			_rtl.add_text(String(p))
	# measure: lay out at full width, then shrink to what the text actually uses
	_rtl.size = Vector2(MAX_TEXT_WIDTH, 0)
	_rtl.custom_minimum_size = Vector2(MAX_TEXT_WIDTH, 0)
	var used_w := clampf(float(_rtl.get_content_width()), 60.0, MAX_TEXT_WIDTH)
	_rtl.custom_minimum_size = Vector2(used_w + 2.0, 0)
	_rtl.size = Vector2(used_w + 2.0, 0)
	var used_h := float(_rtl.get_content_height())
	var inner := Vector2(used_w + 2.0, used_h)
	var grow := Vector2(1.36, 1.42) if _style == 1 else Vector2.ONE     # an oval needs room around the text
	var body_size := inner * grow + Vector2(PAD, PAD) * 2.0
	var margin := OUTLINE + 4.0
	_body = Rect2(Vector2(margin, margin), body_size)
	_rtl.position = _body.get_center() - inner * 0.5
	_rtl.size = inner
	_tail_tip = Vector2(_body.position.x + body_size.x * 0.2, _body.end.y + TAIL_H)
	var total := Vector2(_body.end.x + margin, _tail_tip.y + margin)
	size = total
	queue_redraw()
	return Vector2i(ceili(total.x), ceili(total.y))


## Where the tail points, in pixels from the top-left.
func get_tail_tip() -> Vector2:
	return _tail_tip


func _draw() -> void:
	if _body.size == Vector2.ZERO:
		return
	var body := _shape_points()
	var tail := PackedVector2Array([
		Vector2(_body.position.x + _body.size.x * 0.24, _body.end.y - OUTLINE - 10.0),
		Vector2(_body.position.x + _body.size.x * 0.42, _body.end.y - OUTLINE - 10.0),
		_tail_tip])
	# outlines first, fills on top, so the tail joins the body without a seam
	var closed := body.duplicate()
	closed.append(body[0])
	draw_polyline(closed, _color, OUTLINE * 2.0, true)
	var tail_outline := PackedVector2Array([tail[0] + Vector2(-2, 6), tail[2], tail[1] + Vector2(2, 6)])
	draw_polyline(tail_outline, _color, OUTLINE * 2.0, true)
	var fill := FILL.lerp(_color, 0.07)
	draw_colored_polygon(body, fill)
	draw_colored_polygon(tail, fill)


static func _shared_font() -> Font:
	if _font == null:
		var emoji := SystemFont.new()
		emoji.font_names = EMOJI_FONTS
		var f := FontVariation.new()
		f.base_font = ThemeDB.fallback_font
		f.fallbacks = [emoji]
		_font = f
	return _font


func _shape_points() -> PackedVector2Array:
	var r := _body
	var pts := PackedVector2Array()
	match _style:
		1:   # oval
			for i in 48:
				var a := TAU * i / 48.0
				pts.append(r.get_center() + Vector2(cos(a) * r.size.x * 0.5, sin(a) * r.size.y * 0.5))
		2:   # slanted box: the top edge tilts
			var tilt := minf(r.size.y * 0.12, 14.0)
			pts = PackedVector2Array([r.position + Vector2(0, tilt), Vector2(r.end.x, r.position.y),
				r.end, Vector2(r.position.x, r.end.y)])
		3:   # pinched box: sides bow inward a little
			var n := 10
			var bow := minf(r.size.y, r.size.x) * 0.06
			for i in n + 1:
				var t := float(i) / n
				pts.append(Vector2(lerpf(r.position.x, r.end.x, t), r.position.y + sin(t * PI) * bow))
			for i in range(1, n + 1):
				var t := float(i) / n
				pts.append(Vector2(r.end.x - sin(t * PI) * bow * 0.6, lerpf(r.position.y, r.end.y, t)))
			for i in range(1, n + 1):
				var t := float(i) / n
				pts.append(Vector2(lerpf(r.end.x, r.position.x, t), r.end.y - sin(t * PI) * bow))
			for i in range(1, n):
				var t := float(i) / n
				pts.append(Vector2(r.position.x + sin(t * PI) * bow * 0.6, lerpf(r.end.y, r.position.y, t)))
		_:   # rounded box
			var rad := minf(26.0, minf(r.size.x, r.size.y) * 0.45)
			var corners := [[r.position + Vector2(rad, rad), PI], [Vector2(r.end.x - rad, r.position.y + rad), PI * 1.5],
				[r.end - Vector2(rad, rad), 0.0], [Vector2(r.position.x + rad, r.end.y - rad), PI * 0.5]]
			for c: Array in corners:
				for k in 7:
					var a: float = float(c[1]) + PI * 0.5 * k / 6.0
					pts.append((c[0] as Vector2) + Vector2(cos(a), sin(a)) * rad)
	return pts
