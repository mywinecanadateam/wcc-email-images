#!/usr/bin/env python3
"""
pack_group.py — build a tight, transparent-background bottle-group image
for a pack, styled like a product shot: bottles standing close together,
soft drop shadows, transparent square canvas.

Two uses for the same output file:
  1. Directly as a Shopify product image (transparent PNG, square).
  2. As a single pre-arranged "sprite" fed into composite_hero.py's
     --bottles argument, so the email hero places one grouped cluster
     instead of loose bottles scattered across the frame — this is what
     fixes the 12-Bottle hero looking crowded.

Usage:
    python3 pack_group.py \
        --bottles "Winery Pictures/Chard_Mottiar_NV.png" "Winery Pictures/Gamay_Courtney_NV.png" "Winery Pictures/Rose Moira NV HR.png" \
        --output "malivoire-2026-09/pack-groups/3-bottle-mixed.png"
"""
import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))
from composite_hero import load_bottle  # reuse the same loading/matting logic

CANVAS = 1600  # reference scale, Shopify product-image friendly
BOTTLE_H_FRAC = 0.74  # per row, before row-count shrinks it further
OVERLAP_FRAC = 0.10  # tight spacing, not heavy overlap — keep every label readable
MAX_PER_ROW = 6  # beyond this many bottles, wrap to a second row rather than one very wide strip


def _row_count(n: int) -> int:
    return math.ceil(n / MAX_PER_ROW)


def build_group(bottle_paths, output_path, bottle_h_frac=BOTTLE_H_FRAC, overlap_frac=OVERLAP_FRAC):
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
        raise RuntimeError("No bottles could be placed — every source image was skipped.")

    rows = _row_count(len(bottles))
    per_row = math.ceil(len(bottles) / rows)
    row_groups = [bottles[i * per_row:(i + 1) * per_row] for i in range(rows)]

    bottle_h = int(CANVAS * bottle_h_frac / rows ** 0.4)  # shrink per row so 2 rows doesn't just double the canvas height
    row_gap = int(bottle_h * 0.12)

    def resize_row(row):
        out = []
        for img in row:
            w, h = img.size
            new_w = max(1, int(bottle_h * w / h))
            out.append(img.resize((new_w, bottle_h), Image.LANCZOS))
        return out

    resized_rows = [resize_row(r) for r in row_groups]

    def row_width(row):
        x = 0
        positions = []
        for im in row:
            positions.append(x)
            x += int(im.size[0] * (1 - overlap_frac))
        total = positions[-1] + row[-1].size[0] if row else 0
        return positions, total

    row_layout = [row_width(r) for r in resized_rows]
    canvas_content_w = max(total for _, total in row_layout)

    pad_x = int(CANVAS * 0.03)
    pad_top = int(CANVAS * 0.03)
    pad_bottom = int(CANVAS * 0.08)
    canvas_w = canvas_content_w + pad_x * 2
    canvas_h = bottle_h * rows + row_gap * (rows - 1) + pad_top + pad_bottom
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    y = pad_top
    for row_idx, row in enumerate(resized_rows):
        positions, total = row_layout[row_idx]
        x_offset = pad_x + (canvas_content_w - total) // 2  # centre shorter rows under longer ones
        for i, im in enumerate(row):
            x_pos = positions[i] + x_offset
            shadow_alpha = im.split()[-1].point(lambda a: int(a * 0.28))
            shadow = Image.new("RGBA", im.size, (10, 5, 5, 255))
            shadow.putalpha(shadow_alpha)
            shadow = shadow.filter(ImageFilter.GaussianBlur(9))
            canvas.alpha_composite(shadow, (x_pos + 4, y + 12))
            canvas.alpha_composite(im, (x_pos, y))
        y += bottle_h + row_gap

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    return used, skipped, canvas.size


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bottles", required=True, type=Path, nargs="+")
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    missing = [str(p) for p in args.bottles if not p.exists()]
    if missing:
        sys.exit(f"Bottle image(s) not found: {', '.join(missing)}")

    used, skipped, size = build_group(args.bottles, args.output)

    print(f"\nWrote {args.output} ({size[0]}x{size[1]}, transparent)")
    print(f"\nBottles used ({len(used)}):")
    for name, note in used:
        print(f"  - {name}: {note}")
    if skipped:
        print(f"\nSkipped ({len(skipped)}) — needs attention:")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")


if __name__ == "__main__":
    main()
