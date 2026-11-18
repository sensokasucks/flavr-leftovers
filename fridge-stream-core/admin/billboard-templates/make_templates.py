"""Draws the Route 22 billboard picture templates the dashboard offers for download
(admin/rooms-setup.js MEDIA_TEMPLATES lists them; keep the sizes in step). Run from this folder:

    python make_templates.py

Needs Pillow. Each template is a plain PNG of the exact pixel size: a dark card with the size
written on it, a dashed "keep words inside" line 5% in from the edge. The
whole picture shows on a billboard (Stream Rooms builds each board to its picture's shape), so
the dashed line is only a comfortable margin, not a cut line.
"""
from PIL import Image, ImageDraw, ImageFont

# (file name, width, height, the one-line note under the size)
SIZES = [
    ("billboard-1920x1080.png", 1920, 1080, "Fits every billboard. The best all-round size."),
    ("billboard-wide-1920x660.png", 1920, 660, "Wide banner. Fills the parked trailer's side."),
    ("billboard-square-1080x1080.png", 1080, 1080, "Square. Shows on a narrower board."),
    ("billboard-tall-1080x1350.png", 1080, 1350, "Tall poster. Shows on a narrow, tall board."),
]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def dashed(draw, box, colour, width, dash=28, gap=18):
    """A dashed rectangle."""
    x0, y0, x1, y1 = box
    for y in (y0, y1):
        x = x0
        while x < x1:
            draw.line([x, y, min(x + dash, x1), y], fill=colour, width=width)
            x += dash + gap
    for x in (x0, x1):
        y = y0
        while y < y1:
            draw.line([x, y, x, min(y + dash, y1)], fill=colour, width=width)
            y += dash + gap


for name, w, h, note in SIZES:
    im = Image.new("RGB", (w, h), (24, 30, 42))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w - 1, h - 1], outline=(83, 252, 24), width=6)
    m = round(min(w, h) * 0.05)
    dashed(d, (m, m, w - m, h - m), (150, 160, 180), 3)
    big = ImageFont.truetype(FONT, round(min(w, h) * 0.11))
    small = ImageFont.truetype(FONT, round(min(w, h) * 0.034))
    lines = [(f"{w} x {h}", big, (235, 240, 250)), (note, small, (170, 180, 200)),
             ("Keep words inside the dashed line. Save as JPG or PNG under 3 MB.", small, (170, 180, 200))]
    y = h * 0.5 - min(w, h) * 0.2
    for text, font, colour in lines:
        # wrap the small lines on narrow templates
        words, row, rows = text.split(), "", []
        for word in words:
            if d.textlength((row + " " + word).strip(), font=font) > w - 4 * m:
                rows.append(row)
                row = word
            else:
                row = (row + " " + word).strip()
        rows.append(row)
        for r in rows:
            d.text(((w - d.textlength(r, font=font)) / 2, y), r, font=font, fill=colour)
            y += font.size * 1.35
        y += font.size * 0.3
    im.save(name, optimize=True)
    print(name)
