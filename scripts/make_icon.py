"""Draw the integration's brand icon.

An original front-loading washer glyph; it uses no Sharp or Home Assistant
artwork. Writes icon.png (256 px) and icon@2x.png (512 px) into the
integration's brand folder.

    .venv/bin/python scripts/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BRAND_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "cocoro_wash" / "brand"

BODY = (43, 125, 233, 255)
WHITE = (255, 255, 255, 255)
GLASS = (201, 224, 255, 255)
WATER = (94, 162, 242, 255)

# Drawn on a 512-unit grid at 4x and scaled down for smooth edges.
GRID = 512
SCALE = 4


def draw() -> Image.Image:
    image = Image.new("RGBA", (GRID * SCALE, GRID * SCALE), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    def box(left: float, top: float, right: float, bottom: float) -> tuple[int, int, int, int]:
        return (
            round(left * SCALE),
            round(top * SCALE),
            round(right * SCALE),
            round(bottom * SCALE),
        )

    def circle(x: float, y: float, radius: float) -> tuple[int, int, int, int]:
        return box(x - radius, y - radius, x + radius, y + radius)

    # Cabinet.
    pen.rounded_rectangle(box(64, 36, 448, 476), radius=60 * SCALE, fill=BODY)
    # Control panel: two buttons and a display.
    pen.ellipse(circle(126, 98, 15), fill=WHITE)
    pen.ellipse(circle(176, 98, 15), fill=WHITE)
    pen.rounded_rectangle(box(292, 84, 390, 112), radius=14 * SCALE, fill=WHITE)
    # Door: white rim, glass, and water in the lower part of the drum.
    pen.ellipse(circle(256, 296, 136), fill=WHITE)
    pen.ellipse(circle(256, 296, 106), fill=GLASS)
    pen.chord(circle(256, 296, 106), start=10, end=170, fill=WATER)
    return image


def main() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    master = draw()
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        master.resize((size, size), Image.Resampling.LANCZOS).save(BRAND_DIR / name, optimize=True)
        print(f"wrote {BRAND_DIR / name} ({size}x{size})")


if __name__ == "__main__":
    main()
