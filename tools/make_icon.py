"""Draw the app icon: a suspension bridge on a rounded tile.

    python tools/make_icon.py            the default (white bridge, orange tile)
    python tools/make_icon.py deck       ink bridge, orange deck, graphite tile
    python tools/make_icon.py mono       ink on graphite, no accent

Writes assets/icon.png (256 px) and assets/icon.ico (16-256 px). Needs
Pillow. The shape is flat on purpose - no glow, no gradient - so it stays
readable at 16 px on both dark and light taskbars.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
S = 1024  # drawn large, scaled down for every size

GRAPHITE = (40, 42, 46, 255)
INK = (246, 243, 236, 255)
ORANGE = (214, 79, 40, 255)  # bridge paint, kept muted

# name: (bridge, tile, deck)
VARIANTS = {
    "tile": (INK, ORANGE, INK),
    "deck": (INK, GRAPHITE, ORANGE),
    "mono": (INK, GRAPHITE, INK),
}

DECK_Y = .64
TOWERS = (.33, .67)
TOP_Y = .24


def px(v: float) -> int:
    return int(S * v)


def quad(p0, p1, p2, n=120):
    """Points of a quadratic Bezier curve (a hanging cable)."""
    out = []
    for i in range(n + 1):
        t = i / n
        out.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                    (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]))
    return out


def cable(d: ImageDraw.ImageDraw, pts, width: float) -> None:
    line = [(px(x), px(y)) for x, y in pts]
    d.line(line, fill=255, width=px(width), joint="curve")
    r = px(width) / 2
    for x, y in (line[0], line[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=255)


def bridge_mask() -> tuple:
    """Two masks: the whole bridge, and the deck alone."""
    body = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(body)
    left, right = TOWERS
    main = quad((left, TOP_Y), (.5, .66), (right, TOP_Y))
    cable(d, main, .048)
    cable(d, quad((left, TOP_Y), (.22, .52), (.10, .60)), .048)
    cable(d, quad((right, TOP_Y), (.78, .52), (.90, .60)), .048)
    for x in (.415, .5, .585):
        y = min(main, key=lambda p: abs(p[0] - x))[1]
        d.rectangle([px(x - .013), px(y), px(x + .013), px(DECK_Y)], fill=255)
    for x in TOWERS:
        d.rounded_rectangle([px(x - .037), px(TOP_Y - .045), px(x + .037), px(.82)],
                            radius=px(.016), fill=255)
    deck = Image.new("L", (S, S), 0)
    ImageDraw.Draw(deck).rounded_rectangle(
        [px(.10), px(DECK_Y - .042), px(.90), px(DECK_Y + .042)], radius=px(.02), fill=255)
    return body, deck


def draw(fg, bg, deck_colour) -> Image.Image:
    image = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle([0, 0, S - 1, S - 1], radius=px(.22), fill=bg)
    body, deck = bridge_mask()
    image.paste(Image.new("RGBA", (S, S), fg), (0, 0), body)
    image.paste(Image.new("RGBA", (S, S), deck_colour), (0, 0), deck)
    return image


def main(argv: list) -> int:
    name = argv[0] if argv else "tile"
    if name not in VARIANTS:
        print("variants:", ", ".join(VARIANTS))
        return 2
    master = draw(*VARIANTS[name])
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    icon = master.resize((256, 256), Image.LANCZOS)
    icon.save(assets / "icon.png", optimize=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    icon.save(assets / "icon.ico", sizes=[(s, s) for s in sizes])
    print(f"icon '{name}' written to {assets}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
