#!/usr/bin/env python3
"""Compose a side-by-side comparison image: manual figure | render(s).
Usage: python3 compare.py <out.png> <manual_img> <render1> [render2 ...]"""
import sys
from PIL import Image, ImageDraw, ImageOps

out, manual = sys.argv[1], sys.argv[2]
renders = sys.argv[3:]
H = 720
imgs = []
for i, f in enumerate([manual] + renders):
    im = Image.open(f).convert("RGB")
    im = ImageOps.autocontrast(im) if i == 0 else im
    im = im.resize((int(im.width * H / im.height), H), Image.LANCZOS)
    imgs.append((f, im))
W = sum(im.width for _, im in imgs) + 10 * (len(imgs) - 1)
sheet = Image.new("RGB", (W, H + 30), (245, 245, 248))
dr = ImageDraw.Draw(sheet)
x = 0
labels = ["MANUAL"] + [f"RENDER {i+1}" for i in range(len(renders))]
for (f, im), lbl in zip(imgs, labels):
    sheet.paste(im, (x, 30))
    dr.text((x + 6, 8), lbl, fill=(0, 0, 0))
    x += im.width + 10
sheet.save(out)
print(f"{out} {sheet.width}x{sheet.height}")
