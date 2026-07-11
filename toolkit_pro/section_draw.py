#!/usr/bin/env python3
"""Draw cross-sections (from section_extract.py) with a labeled mm grid.
Usage: python3 section_draw.py <sections.json> <out_dir>"""
import json, os, sys, math
from PIL import Image, ImageDraw

data = json.load(open(sys.argv[1]))
out_dir = sys.argv[2]
os.makedirs(out_dir, exist_ok=True)
SIZE, MARGIN = 1000, 70
AX = {"x": 0, "y": 1, "z": 2}
LBL = {"x": ("y", "z"), "y": ("x", "z"), "z": ("x", "y")}

for key, sec in data.items():
    ai = AX[sec["axis"]]
    rest = [i for i in range(3) if i != ai]
    segs = sec["segs"]
    if not segs:
        continue
    xs = [p[rest[0]] for s in segs for p in s]
    ys = [p[rest[1]] for s in segs for p in s]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = max(x1 - x0, 1e-3), max(y1 - y0, 1e-3)
    sc = (SIZE - 2 * MARGIN) / max(w, h)

    def P(x, y):
        return (MARGIN + (x - x0) * sc, SIZE - MARGIN - (y - y0) * sc)

    im = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    step = 10 if max(w, h) > 30 else (5 if max(w, h) > 12 else 1)
    g = math.floor(x0 / step) * step
    while g <= x1:
        dr.line([P(g, y0), P(g, y1)], fill=(225, 225, 235))
        dr.text((P(g, y0)[0] - 8, SIZE - MARGIN + 10), f"{g:g}", fill=(120, 120, 140))
        g += step
    g = math.floor(y0 / step) * step
    while g <= y1:
        dr.line([P(x0, g), P(x1, g)], fill=(225, 225, 235))
        dr.text((10, P(x0, g)[1] - 6), f"{g:g}", fill=(120, 120, 140))
        g += step
    for s in segs:
        dr.line([P(s[0][rest[0]], s[0][rest[1]]), P(s[1][rest[0]], s[1][rest[1]])],
                fill=(180, 30, 30), width=3)
    hx, hy = LBL[sec["axis"]]
    dr.text((MARGIN, 14), f"SECTION {key}   ({hx}->right, {hy}->up)   grid {step}mm", fill=(0, 0, 0))
    fname = key.replace("@", "_").replace("=", "") + ".png"
    im.save(os.path.join(out_dir, fname))
    print(os.path.join(out_dir, fname))
