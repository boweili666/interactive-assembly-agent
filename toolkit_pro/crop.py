#!/usr/bin/env python3
"""Crop/zoom/enhance an image (for reading manual details).
Usage: python3 crop.py <in.png> <out.png> [--box x0 y0 x1 y1] [--scale 2]
       [--invert] [--autocontrast] [--brightness 1.5] [--contrast 1.5]"""
import argparse
from PIL import Image, ImageOps, ImageEnhance

ap = argparse.ArgumentParser()
ap.add_argument("inp"); ap.add_argument("out")
ap.add_argument("--box", nargs=4, type=int, help="x0 y0 x1 y1 (pixels)")
ap.add_argument("--scale", type=float, default=1.0)
ap.add_argument("--invert", action="store_true")
ap.add_argument("--autocontrast", action="store_true")
ap.add_argument("--brightness", type=float, default=1.0)
ap.add_argument("--contrast", type=float, default=1.0)
a = ap.parse_args()

im = Image.open(a.inp).convert("RGB")
if a.box:
    im = im.crop(tuple(a.box))
if a.scale != 1.0:
    im = im.resize((int(im.width * a.scale), int(im.height * a.scale)), Image.LANCZOS)
if a.invert:
    im = ImageOps.invert(im)
if a.autocontrast:
    im = ImageOps.autocontrast(im)
if a.brightness != 1.0:
    im = ImageEnhance.Brightness(im).enhance(a.brightness)
if a.contrast != 1.0:
    im = ImageEnhance.Contrast(im).enhance(a.contrast)
im.save(a.out)
print(f"{a.out} {im.width}x{im.height}")
