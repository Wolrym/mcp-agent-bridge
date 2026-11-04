"""Draw the app icon: an arch bridge on a graphite tile.

    python tools/make_icon.py            the default (orange deck)
    python tools/make_icon.py mono       ink only, no accent
    python tools/make_icon.py tile       ink bridge on an orange tile

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
INK = (236, 233, 226, 255)
ORANGE = (214, 79, 40, 255)  # bridge paint, kept muted

VARIANTS = {
    "deck": (INK, GRAPHITE, ORANGE),
    "mono": (INK, GRAPHITE, INK),
    "tile": (INK, ORANGE, INK),
}


def draw(fg, bg, deck) -> Image.Image:
    image = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * .22), fill=bg)
    deck_box = [int(S * .12), int(S * .30), int(S * .88), int(S * .41)]
    body_x0, body_x1, body_y1 = int(S * .19), int(S * .81), int(S * .74)
    d.rectangle([body_x0, deck_box[3] - 2, body_x1, body_y1], fill=fg)
    pier = int(S * .075)
    r = (body_x1 - body_x0 - 2 * pier) / 2
    cx = S / 2
    d.ellipse([cx - r, body_y1 - r, cx + r, body_y1 + r], fill=bg)
    d.rectangle(deck_box, fill=deck)
    return image


def main(argv: list) -> int:
    name = argv[0] if argv else "deck"
    if name not in VARIANTS:
        print("variants:", ", ".join(VARIANTS))
        return 2
    master = draw(*VARIANTS[name])
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    master.resize((256, 256), Image.LANCZOS).save(assets / "icon.png", optimize=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    master.resize((256, 256), Image.LANCZOS).save(
        assets / "icon.ico", sizes=[(s, s) for s in sizes]
    )
    print(f"icon '{name}' written to {assets}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
