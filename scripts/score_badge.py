"""
Pre-rendered quality-score circle badges for WITB emails (and anywhere else a
"92 PTS" medallion is needed) — one PNG per score value, transparent
background, Burgundy fill, white WorkSans-Bold numerals.

Why this exists: the WITB HTML previously drew the circle with a table cell
(width:34px;height:34px;border-radius:50%). Table cells don't reliably honour
a fixed height across email clients, so a two-line "92<br>PTS" label stretches
the cell taller than it is wide and the "circle" renders as an oval/pill. Same
class of fix as the award medallions in WineClub Brand/ (ACWC, NWAC, OWA...) —
render the shape once as an image so every client shows the same pixels,
instead of re-deriving it from CSS on every send.

Usage:
    python3 scripts/score_badge.py --min 85 --max 96 \
        --output-dir "WineClub Brand"

Output: "WineClub Brand/Score <N>.png" for every N in [min, max], 240x240px
(renders at 34x34 in the WITB HTML — 240px gives room for retina displays
without the file getting heavy). Re-run is idempotent — same input always
produces the same bytes, safe to regenerate if the design changes.
"""
import argparse
import os
from PIL import Image, ImageDraw, ImageFont

BURGUNDY = (123, 45, 66, 255)  # #7B2D42
WHITE = (255, 255, 255, 255)
CANVAS = 240
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_PATH = os.path.join(FONT_DIR, "WorkSans-Bold.ttf")


def draw_badge(score: int) -> Image.Image:
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = 4
    draw.ellipse([pad, pad, CANVAS - pad, CANVAS - pad], fill=BURGUNDY)

    number_font = ImageFont.truetype(FONT_PATH, 96)
    label_font = ImageFont.truetype(FONT_PATH, 26)
    number = str(score)
    label = "PTS"

    # Letter-spaced "PTS" to match the tracked-caps treatment used elsewhere
    # in the WITB design system (badges, eyebrows).
    spaced_label = " ".join(label)

    num_bbox = draw.textbbox((0, 0), number, font=number_font)
    num_w, num_h = num_bbox[2] - num_bbox[0], num_bbox[3] - num_bbox[1]
    label_bbox = draw.textbbox((0, 0), spaced_label, font=label_font)
    label_w, label_h = label_bbox[2] - label_bbox[0], label_bbox[3] - label_bbox[1]

    gap = 6
    block_h = num_h + gap + label_h
    top = (CANVAS - block_h) / 2

    num_x = (CANVAS - num_w) / 2 - num_bbox[0]
    num_y = top - num_bbox[1]
    draw.text((num_x, num_y), number, font=number_font, fill=WHITE)

    label_x = (CANVAS - label_w) / 2 - label_bbox[0]
    label_y = top + num_h + gap - label_bbox[1]
    draw.text((label_x, label_y), spaced_label, font=label_font, fill=WHITE)

    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=85)
    ap.add_argument("--max", type=int, default=96)
    ap.add_argument("--output-dir", default="WineClub Brand")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    for score in range(args.min, args.max + 1):
        img = draw_badge(score)
        path = os.path.join(args.output_dir, f"Score {score}.png")
        img.save(path)
        print(path)


if __name__ == "__main__":
    main()
