#!/usr/bin/env python3
"""Tile many PNGs into one labeled contact sheet (view 1 image instead of N).
Usage: python3 contact_sheet.py <out.png> <img1> <img2> ...  (globs ok via shell)"""
import sys, os, math
from PIL import Image, ImageDraw

out = sys.argv[1]
files = sys.argv[2:]
if not files:
    sys.exit("no input images")
CELL = 420
cols = math.ceil(math.sqrt(len(files)))
rows = math.ceil(len(files) / cols)
sheet = Image.new("RGB", (cols * CELL, rows * (CELL + 24)), (250, 250, 252))
dr = ImageDraw.Draw(sheet)
for i, f in enumerate(files):
    im = Image.open(f).convert("RGB")
    im.thumbnail((CELL - 8, CELL - 8))
    cx, cy = (i % cols) * CELL, (i // cols) * (CELL + 24)
    sheet.paste(im, (cx + (CELL - im.width) // 2, cy + (CELL - im.height) // 2))
    dr.text((cx + 6, cy + CELL + 4), os.path.basename(f)[:52], fill=(0, 0, 0))
sheet.save(out)
print(f"{out} {sheet.width}x{sheet.height} ({len(files)} images)")
