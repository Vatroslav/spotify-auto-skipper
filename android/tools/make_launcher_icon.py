"""Generate the Car Skipper launcher icon.

The mark is the existing Auto-Skipper brand (two green skip arrows, colours sampled
from cloud/app/static/icons/maskable-512.png) with a car between them, so the car
app is not mistaken for the installed PWA on the same phone.

Writes the adaptive-icon foreground (transparent, content inside the central 66%
safe zone) plus a legacy square icon. Run from the repo root:

    python android/tools/make_launcher_icon.py
"""

import os
from PIL import Image, ImageDraw

BG = (41, 46, 50, 255)  # brand dark, #292E32
GREEN = (6, 212, 101, 255)  # brand green, #06D465
WHITE = (255, 255, 255, 255)

SIZE = 512
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "res")


def car(draw, cx, cy, width, body=WHITE, hollow=BG):
    """Side-view car facing right, centred on (cx, cy). Design grid is 100 units wide."""
    u = width / 100.0

    def pt(x, y):
        return (cx + x * u, cy + y * u)

    def circle(x, y, radius, fill):
        draw.ellipse([pt(x - radius, y - radius), pt(x + radius, y + radius)], fill=fill)

    # Cabin first, then the body over its base so the two read as one silhouette.
    draw.polygon([pt(-32, -6), pt(-21, -33), pt(13, -33), pt(26, -6)], fill=body)
    draw.rounded_rectangle([pt(-50, -8), pt(50, 19)], radius=9 * u, fill=body)
    for wheel_x in (-30, 30):
        circle(wheel_x, 19, 13, body)
        circle(wheel_x, 19, 5.5, hollow)


def arrow(draw, tip_x, edge_x, cy, half_height):
    draw.polygon([(tip_x, cy), (edge_x, cy - half_height), (edge_x, cy + half_height)], fill=GREEN)


def mark(scale=1.0):
    """Skip arrows flanking the car, centred on a transparent canvas."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = SIZE / 2

    def s(value):
        """Scale a distance from the canvas centre."""
        return c + (value - c) * scale

    # Arrows keep the brand mark's width-to-height ratio; the gaps to the car are deliberate.
    arrow(d, s(90), s(175), c, 58 * scale)
    arrow(d, s(422), s(337), c, 58 * scale)
    car(d, c, s(252), 138 * scale)
    return img


def main():
    res = os.path.abspath(OUT_DIR)

    # Adaptive foreground: the system crops to the central 66%, so the content stays inside it
    # with a small margin — at 1.0 the arrow tips graze the circular mask.
    foreground = mark(0.95)
    foreground.save(os.path.join(res, "drawable-nodpi", "ic_launcher_foreground.png"))

    # Legacy square icon (unused on API 26+, kept as a fallback): same mark, larger, on brand dark.
    legacy = Image.new("RGBA", (SIZE, SIZE), BG)
    legacy.alpha_composite(mark(1.3))
    legacy.save(os.path.join(res, "mipmap-xxxhdpi", "ic_launcher.png"))

    print("wrote foreground + legacy icon to", res)


if __name__ == "__main__":
    main()
