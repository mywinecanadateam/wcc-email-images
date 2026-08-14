#!/usr/bin/env python3
"""
composite_hero.py — build a WITY hero image by placing real bottle shots
onto a real background photo (vineyard / tasting room). No AI generation:
every pixel comes from a real photo the winery supplied or published.

Usage:
    python3 composite_hero.py \
        --background "Winery Pictures/patio 2026.jpg" \
        --bottles "Winery Pictures/Chard_Mottiar_NV.png" "Winery Pictures/Gamay_Courtney_NV.png" \
        --output "malivoire-2026-09/hero-composites/2-bottle-mixed.jpg"

Same background can be reused across every pack size for a winery feature —
just change --bottles and --output per pack. Layout scales automatically
with bottle count (1 row up to ~7 bottles, 2 rows beyond that, up to 12).

Bottle images without real transparency are auto-matted (background-colour
removal from the four corners). If a bottle's background can't be matted
cleanly (busy/non-uniform background), it's skipped and reported — never
force a bad cutout into the composite.
"""

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps

CANVAS_W = 1200
CANVAS_H = 675  # 16:9, per wcc-email-design-system.md Module 09 hero spec

MATTE_LOW = 18   # colour distance below this -> fully background/transparent
MATTE_HIGH = 45  # colour distance above this -> fully foreground/opaque
MATTE_MIN_BG_FRAC = 0.15  # if less of the image reads as background than this, the shot probably isn't a clean studio backdrop
MATTE_MAX_BG_FRAC = 0.92  # if more than this reads as background, something's wrong (bottle too close to bg colour, or empty frame)


def has_real_alpha(img: Image.Image) -> bool:
    if img.mode != "RGBA":
        return False
    lo, _hi = img.split()[-1].getextrema()
    return lo < 250


def estimate_background_color(rgb: Image.Image, sample: int = 14) -> tuple[int, int, int]:
    w, h = rgb.size
    sample = min(sample, w // 4, h // 4) or 1
    corners = [(0, 0), (w - sample, 0), (0, h - sample), (w - sample, h - sample)]
    r = g = b = 0
    for x, y in corners:
        px = rgb.crop((x, y, x + sample, y + sample)).resize((1, 1), Image.LANCZOS).getpixel((0, 0))
        r += px[0]; g += px[1]; b += px[2]
    n = len(corners)
    return (r // n, g // n, b // n)


def auto_matte(img: Image.Image):
    """Returns (matted_rgba, bg_color, background_fraction)."""
    rgb = img.convert("RGB")
    bg_color = estimate_background_color(rgb)
    bg_layer = Image.new("RGB", rgb.size, bg_color)
    diff = ImageChops.difference(rgb, bg_layer)
    dr, dg, db = diff.split()
    dist = ImageChops.lighter(ImageChops.lighter(dr, dg), db)  # per-pixel max channel distance

    def ramp(v, lo=MATTE_LOW, hi=MATTE_HIGH):
        if v <= lo:
            return 0
        if v >= hi:
            return 255
        return int((v - lo) / (hi - lo) * 255)

    alpha = dist.point(ramp).filter(ImageFilter.GaussianBlur(1))
    bg_pixels = alpha.histogram()[0:64]  # low end of the 0-255 histogram = background pixels
    bg_frac = sum(bg_pixels) / (rgb.size[0] * rgb.size[1])

    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out, bg_color, bg_frac


def load_bottle(path: Path):
    """Returns (rgba_image, note) or (None, reason) if it had to be skipped."""
    img = Image.open(path)
    if has_real_alpha(img):
        return img.convert("RGBA"), "used as-is (real transparency)"
    matted, bg_color, bg_frac = auto_matte(img)
    if bg_frac < MATTE_MIN_BG_FRAC or bg_frac > MATTE_MAX_BG_FRAC:
        return None, (
            f"could not auto-matte cleanly (background estimated as {bg_color}, "
            f"{bg_frac:.0%} of frame) — likely not a uniform studio backdrop; "
            f"needs a real cutout or a different source photo"
        )
    return matted, f"auto-matted (background ~{bg_color}, {bg_frac:.0%} of frame)"


def layout_params(n: int):
    """Bottle target height (px) and row count, scaling down as the pack gets bigger."""
    if n <= 2:
        return int(CANVAS_H * 0.62), 1
    if n <= 4:
        return int(CANVAS_H * 0.52), 1
    if n <= 7:
        return int(CANVAS_H * 0.40), 1
    return int(CANVAS_H * 0.30), 2  # 8-12 bottles: two rows


def add_shadow(canvas: Image.Image, bottle: Image.Image, pos: tuple[int, int]):
    alpha = bottle.split()[-1].point(lambda a: int(a * 0.32))
    shadow = Image.new("RGBA", bottle.size, (10, 5, 5, 255))
    shadow.putalpha(alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(7))
    canvas.alpha_composite(shadow, (pos[0] + 5, pos[1] + 10))


def build_hero(background_path: Path, bottle_paths: list[Path], output_path: Path):
    bg = Image.open(background_path).convert("RGB")
    bg = ImageOps.fit(bg, (CANVAS_W, CANVAS_H), method=Image.LANCZOS)
    canvas = bg.convert("RGBA")

    used, skipped = [], []
    bottles = []
    for p in bottle_paths:
        img, note = load_bottle(p)
        if img is None:
            skipped.append((p.name, note))
            continue
        bottles.append(img)
        used.append((p.name, note))

    if not bottles:
        raise RuntimeError("No bottles could be placed — every source image was skipped. See notes above.")

    bottle_h, rows = layout_params(len(bottles))
    resized = []
    for img in bottles:
        w, h = img.size
        new_w = max(1, int(bottle_h * w / h))
        resized.append(img.resize((new_w, bottle_h), Image.LANCZOS))

    per_row = math.ceil(len(resized) / rows)
    row_groups = [resized[i * per_row:(i + 1) * per_row] for i in range(rows)]

    margin = int(CANVAS_W * 0.035)
    gap = int(CANVAS_W * 0.014)
    y_cursor = CANVAS_H - margin

    for row_items in reversed(row_groups):
        row_width = sum(im.size[0] for im in row_items) + gap * (len(row_items) - 1)
        x_cursor = CANVAS_W - margin - row_width
        y_top = y_cursor - bottle_h
        for im in row_items:
            add_shadow(canvas, im, (x_cursor, y_top))
            canvas.alpha_composite(im, (x_cursor, y_top))
            x_cursor += im.size[0] + gap
        y_cursor = y_top - gap

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, "JPEG", quality=88)
    return used, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--background", required=True, type=Path)
    ap.add_argument("--bottles", required=True, type=Path, nargs="+")
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    if not args.background.exists():
        sys.exit(f"Background not found: {args.background}")
    missing = [str(p) for p in args.bottles if not p.exists()]
    if missing:
        sys.exit(f"Bottle image(s) not found: {', '.join(missing)}")

    used, skipped = build_hero(args.background, args.bottles, args.output)

    print(f"\nWrote {args.output} ({CANVAS_W}x{CANVAS_H})")
    print(f"Background: {args.background}")
    print(f"\nBottles used ({len(used)}):")
    for name, note in used:
        print(f"  - {name}: {note}")
    if skipped:
        print(f"\nSkipped ({len(skipped)}) — needs attention:")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")


if __name__ == "__main__":
    main()
