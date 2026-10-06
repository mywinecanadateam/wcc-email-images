#!/usr/bin/env python3
"""
prepare_cutouts.py: check every bottle cutout in a folder, and with --fix repair what can be repaired,
so the emails only ever receive finished bottle shots. No human step.

Usage:
    python3 prepare_cutouts.py <winery-slug>/bottle-shots            # report only
    python3 prepare_cutouts.py <winery-slug>/bottle-shots --fix      # repair in place, then re-check

What it checks, per PNG:
  alpha        real transparency exists and the four corners are transparent
  backdrop     no opaque studio or white backdrop left behind (flood-filled away on --fix)
  halo         the bottle's outer edge is not ringed with near-white pixels (softened on --fix)
  margin       the canvas hugs the bottle (cropped to the bottle plus 1 percent on --fix); a 1200x1500
               frame around a 400px bottle is what squeezed bottles in the emails
  proportions  height divided by width is a real bottle's (2.6 to 5.2); outside that the shot is stretched or cut
  resolution   the bottle is tall enough to look sharp at email size (700px or more)
  clipped      the bottle does not touch the canvas edge

Exit code 0 when every file passes after any repair, 1 otherwise (the failing files are listed with the reason).
A file that cannot be repaired (low resolution, stretched, clipped) goes back to wcc-email-source-winery to be re-sourced.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

MIN_H = 700
ASPECT = (2.6, 5.2)
PAD = 0.01


def alpha_bbox(a, thr=20):
    ys, xs = np.where(a > thr)
    if not len(xs):
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def analyze(im):
    rgba = np.array(im.convert("RGBA"))
    al = rgba[..., 3]
    h, w = al.shape
    out = {"size": im.size, "problems": []}
    corners = [al[0, 0], al[0, w - 1], al[h - 1, 0], al[h - 1, w - 1]]
    has_alpha = (al < 250).mean() > 0.02
    if not has_alpha:
        out["problems"].append("no transparency (opaque backdrop)")
    elif max(corners) > 10:
        out["problems"].append("opaque backdrop left at the corners")
    bb = alpha_bbox(al)
    if bb is None:
        out["problems"].append("empty image")
        return out
    x0, y0, x1, y1 = bb
    bw, bh = x1 - x0, y1 - y0
    out["bbox"] = bb
    out["bottle"] = (bw, bh)
    if bh / bw < ASPECT[0] or bh / bw > ASPECT[1]:
        out["problems"].append(f"proportions off (height/width {bh / bw:.2f}, a bottle is {ASPECT[0]} to {ASPECT[1]})")
    if bh < MIN_H:
        out["problems"].append(f"low resolution (bottle {bh}px tall, need {MIN_H}+)")
    # clipped = the bottle is cut flat by the canvas edge. A rounded base that merely reaches the frame
    # is fine, so measure how much of the bottle is cut at the edge row or column.
    solid_px = al > 128
    cut = []
    if y0 <= 1 and solid_px[0].sum() > 0.5 * bw:
        cut.append("top")
    if y1 >= h - 1 and solid_px[h - 1].sum() > 0.5 * bw:
        cut.append("bottom")
    if x0 <= 1 and solid_px[:, 0].sum() > 0.5 * bh:
        cut.append("left")
    if x1 >= w - 1 and solid_px[:, w - 1].sum() > 0.5 * bh:
        cut.append("right")
    if cut:
        out["problems"].append("bottle is cut off at the canvas " + "/".join(cut) + " (clipped)")
    pad_x, pad_y = (w - bw) / w, (h - bh) / h
    if pad_x > 0.10 or pad_y > 0.10:
        out["problems"].append(f"loose canvas ({pad_x:.0%} wide, {pad_y:.0%} tall of empty space)")
    # halo: near-white, low-saturation pixels in the 3px ring just inside the bottle edge
    solid = al > 128
    inner = np.array(Image.fromarray((solid * 255).astype("uint8")).filter(ImageFilter.MinFilter(7))) > 128
    ring = solid & ~inner
    if ring.any():
        px = rgba[..., :3][ring].astype(int)
        bright = (px.min(axis=1) > 225) & ((px.max(axis=1) - px.min(axis=1)) < 18)
        out["halo"] = float(bright.mean())
        if out["halo"] > 0.12:
            out["problems"].append(f"white halo on the edge ({out['halo']:.0%} of edge pixels)")
    return out


def remove_backdrop(im):
    """Flood-fill the backdrop colour away from the four corners."""
    rgb = im.convert("RGB")
    marker = (255, 0, 255)
    work = rgb.copy()
    w, h = work.size
    for xy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ImageDraw.floodfill(work, xy, marker, thresh=30)
    arr = np.array(work)
    bg = (arr[..., 0] == 255) & (arr[..., 1] == 0) & (arr[..., 2] == 255)
    rgba = np.array(im.convert("RGBA"))
    rgba[..., 3] = np.where(bg, 0, rgba[..., 3])
    return Image.fromarray(rgba)


def soften_halo(im):
    """Pull the alpha edge in one pixel and soften it, which drops the backdrop-coloured fringe."""
    rgba = im.convert("RGBA")
    a = rgba.getchannel("A")
    a = a.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    rgba.putalpha(a)
    return rgba


def trim(im):
    bb = alpha_bbox(np.array(im.convert("RGBA"))[..., 3], thr=8)
    if not bb:
        return im
    x0, y0, x1, y1 = bb
    pad = max(4, int(PAD * max(x1 - x0, y1 - y0)))
    return im.crop((max(0, x0 - pad), max(0, y0 - pad), min(im.width, x1 + pad), min(im.height, y1 + pad)))


def repair(path):
    im = Image.open(path)
    info = analyze(im)
    steps = []
    if any("backdrop" in p or "no transparency" in p for p in info["problems"]):
        im = remove_backdrop(im)
        steps.append("removed backdrop")
        info = analyze(im)
    if any("halo" in p for p in info["problems"]):
        passes = 0
        while passes < 6 and analyze(im).get("halo", 0) > 0.12:
            im = soften_halo(im)
            passes += 1
        steps.append(f"softened halo ({passes} pass{'es' if passes != 1 else ''})")
    trimmed = trim(im)
    if trimmed.size != im.size:
        steps.append(f"trimmed {im.size[0]}x{im.size[1]} to {trimmed.size[0]}x{trimmed.size[1]}")
    im = trimmed
    return im, steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()
    files = sorted(Path(a.folder).glob("*.png"))
    if not files:
        print("no PNG files found"); sys.exit(2)
    failed = []
    for f in files:
        steps = []
        if a.fix:
            im, steps = repair(f)
            if steps:
                im.save(f, optimize=True)
        info = analyze(Image.open(f))
        status = "PASS" if not info["problems"] else "FAIL"
        extra = f" (fixed: {'; '.join(steps)})" if steps else ""
        bottle = f" bottle {info['bottle'][0]}x{info['bottle'][1]}" if "bottle" in info else ""
        print(f"{status}  {f.name}  {info['size'][0]}x{info['size'][1]}{bottle}{extra}")
        for p in info["problems"]:
            print(f"      - {p}")
        if info["problems"]:
            failed.append(f.name)
    print(f"{len(files) - len(failed)} of {len(files)} cutouts pass")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
