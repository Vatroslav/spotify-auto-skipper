"""Generate the Android Auto browse-list icons for Car Skipper.

Each icon is a single colour — brand green, red for the armed Remove — because
Android Auto renders the list on a light or a dark background depending on the
car's day/night mode, and a two-tone glyph loses half of itself in one of them.
Palette and the status glyph come from the existing brand mark
(tools/make_launcher_icon.py), so nothing here is a new design.

Drawn at 512 px and downsampled to 192 px for antialiasing. Run from the repo root:

    python android/tools/make_browse_icons.py
"""

import math
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_launcher_icon import GREEN, car  # noqa: E402

RED = (255, 68, 68, 255)  # PWA's remove/danger colour, --remove-hover
CLEAR = (0, 0, 0, 0)

DRAW = 512  # supersampled working canvas
OUT = 192  # exported size
C = DRAW / 2

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "main", "res", "drawable-nodpi")


def new_canvas():
    img = Image.new("RGBA", (DRAW, DRAW), CLEAR)
    return img, ImageDraw.Draw(img)


def skip_arrow(d, tip_x, edge_x, cy, half_height, color):
    """The brand mark's arrow: a triangle pointing at tip_x."""
    d.polygon([(tip_x, cy), (edge_x, cy - half_height), (edge_x, cy + half_height)], fill=color)


def heart(d, cx, cy, size, color):
    """The standard parametric heart, `size` wide and centred on (cx, cy).

    Circles-plus-triangle constructions read as a map pin at list-icon scale; the
    curve gets the cleft and the shoulders right on its own.
    """
    steps = 240
    raw = [
        (
            16 * math.sin(t) ** 3,
            13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t),
        )
        for t in (2 * math.pi * i / steps for i in range(steps))
    ]
    xs = [p[0] for p in raw]
    ys = [p[1] for p in raw]
    mid_x, mid_y = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    scale = size / (max(xs) - min(xs))
    # Curve y grows upward, screen y grows downward.
    d.polygon([(cx + (x - mid_x) * scale, cy - (y - mid_y) * scale) for x, y in raw], fill=color)


def icon_status(color):
    """The brand mark itself: skip arrows around a car, flattened to one colour.

    Scaled up from the launcher proportions — a list row gives the mark less room
    than an app icon does, so it has to earn its width.
    """
    img, d = new_canvas()
    k = 1.35

    def s(value):
        return C + (value - C) * k

    skip_arrow(d, s(90), s(175), C, 58 * k, color)
    skip_arrow(d, s(422), s(337), C, 58 * k, color)
    car(d, C, s(252), 138 * k, body=color, hollow=CLEAR)
    return img


def icon_check_now(color):
    """Clockwise refresh arc — check the current song again, now."""
    img, d = new_canvas()
    radius, stroke = 150, 46
    # Arc runs clockwise from 305° round to 235°, leaving the gap at the top.
    d.arc([C - radius, C - radius, C + radius, C + radius], start=305, end=235, fill=color, width=stroke)

    angle = math.radians(235)
    px, py = C + radius * math.cos(angle), C + radius * math.sin(angle)
    tangent = (-math.sin(angle), math.cos(angle))  # direction of travel
    radial = (math.cos(angle), math.sin(angle))
    head, half = 88, 62
    d.polygon(
        [
            (px + tangent[0] * head, py + tangent[1] * head),
            (px + radial[0] * half, py + radial[1] * half),
            (px - radial[0] * half, py - radial[1] * half),
        ],
        fill=color,
    )
    return img


def icon_pause(color):
    img, d = new_canvas()
    d.rounded_rectangle([168, 146, 232, 366], radius=18, fill=color)
    d.rounded_rectangle([280, 146, 344, 366], radius=18, fill=color)
    return img


def icon_resume(color):
    img, d = new_canvas()
    d.polygon([(186, 140), (186, 372), (388, 256)], fill=color)
    return img


def icon_dont_skip(color):
    """Skip arrows struck through: this one song is off limits."""
    img, d = new_canvas()
    skip_arrow(d, 262, 132, C, 104, color)
    skip_arrow(d, 398, 268, C, 104, color)
    # The bar runs against the arrows, not along them, or the whole thing reads as
    # shards. Clear a lane first, then lay the bar inside it, so the bar stays
    # legible as a separate mark without needing a second colour.
    d.line([(116, 116), (396, 396)], fill=CLEAR, width=54)
    d.line([(116, 116), (396, 396)], fill=color, width=24)
    return img


def icon_like_add(color):
    """Outline heart — not liked yet."""
    img, d = new_canvas()
    # Both hearts share a centre, so scaling one down leaves an even stroke.
    heart(d, C, C, 320, color)
    heart(d, C, C, 198, CLEAR)
    return img


def icon_like_remove(color):
    """Filled heart — already liked, tapping takes it back."""
    img, d = new_canvas()
    heart(d, C, C, 320, color)
    return img


def icon_trash(color):
    img, d = new_canvas()
    d.rounded_rectangle([214, 116, 298, 156], radius=14, fill=color)  # handle
    d.rounded_rectangle([146, 152, 366, 194], radius=20, fill=color)  # lid
    d.polygon([(176, 206), (336, 206), (318, 398), (194, 398)], fill=color)  # body
    for x in (222, 256, 290):
        d.rounded_rectangle([x - 9, 244, x + 9, 356], radius=9, fill=CLEAR)
    return img


ICONS = {
    "ic_status": (icon_status, GREEN),
    "ic_check_now": (icon_check_now, GREEN),
    "ic_pause_skipping": (icon_pause, GREEN),
    "ic_resume_skipping": (icon_resume, GREEN),
    "ic_dont_skip": (icon_dont_skip, GREEN),
    "ic_like_add": (icon_like_add, GREEN),
    "ic_like_remove": (icon_like_remove, GREEN),
    "ic_remove": (icon_trash, GREEN),
    "ic_remove_armed": (icon_trash, RED),
}


def main():
    res = os.path.abspath(OUT_DIR)
    os.makedirs(res, exist_ok=True)
    for name, (draw_icon, color) in ICONS.items():
        path = os.path.join(res, name + ".png")
        draw_icon(color).resize((OUT, OUT), Image.LANCZOS).save(path)
    print(f"wrote {len(ICONS)} browse icons to {res}")


if __name__ == "__main__":
    main()
