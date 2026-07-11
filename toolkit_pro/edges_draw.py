#!/usr/bin/env python3
"""Draw CAD-style line views (top/front/side) from edges JSON, with a mm grid
so coordinates can be read straight off the image.
Usage: python3 edges_draw.py <edges.json> <out_dir> [part ...]"""
import json, os, sys
from PIL import Image, ImageDraw

edges_json, out_dir = sys.argv[1], sys.argv[2]
only = set(sys.argv[3:])
os.makedirs(out_dir, exist_ok=True)
data = json.load(open(edges_json))

VIEWS = {"top": (0, 1), "front": (0, 2), "side": (1, 2)}  # axis index pairs
SIZE = 1000
MARGIN = 60

for name, segs in data.items():
    if only and name not in only:
        continue
    for vname, (ax, ay) in VIEWS.items():
        xs = [p[ax] for s in segs for p in s]
        ys = [p[ay] for s in segs for p in s]
        if not xs:
            continue
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w, h = max(x1 - x0, 1e-3), max(y1 - y0, 1e-3)
        sc = (SIZE - 2 * MARGIN) / max(w, h)

        def P(x, y):
            return (MARGIN + (x - x0) * sc, SIZE - MARGIN - (y - y0) * sc)

        im = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
        dr = ImageDraw.Draw(im)
        import math
        step = 10 if max(w, h) > 30 else 5
        gx = math.floor(x0 / step) * step
        while gx <= x1:
            dr.line([P(gx, y0), P(gx, y1)], fill=(225, 225, 235), width=1)
            dr.text((P(gx, y0)[0] - 8, SIZE - MARGIN + 8), f"{gx:g}", fill=(120, 120, 140))
            gx += step
        gy = math.floor(y0 / step) * step
        while gy <= y1:
            dr.line([P(x0, gy), P(x1, gy)], fill=(225, 225, 235), width=1)
            dr.text((8, P(x0, gy)[1] - 6), f"{gy:g}", fill=(120, 120, 140))
            gy += step
        # axes through 0 if visible
        if x0 <= 0 <= x1:
            dr.line([P(0, y0), P(0, y1)], fill=(180, 180, 210), width=2)
        if y0 <= 0 <= y1:
            dr.line([P(x0, 0), P(x1, 0)], fill=(180, 180, 210), width=2)
        for s in segs:
            dr.line([P(s[0][ax], s[0][ay]), P(s[1][ax], s[1][ay])], fill=(20, 20, 30), width=2)
        lbl = {"top": "top (x→,y↑)", "front": "front (x→,z↑)", "side": "side (y→,z↑)"}[vname]
        dr.text((MARGIN, 16), f"{name} — {lbl}  grid {step}mm", fill=(0, 0, 0))
        out = os.path.join(out_dir, f"{name}_{vname}_edges.png")
        im.save(out)
        print(out)
