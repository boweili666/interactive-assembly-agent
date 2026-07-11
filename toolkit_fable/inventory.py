"""Inventory all parts: dims (mm), triangle count, unit normalization applied.
Usage: bash bl.sh inventory.py <parts_dir> <out.json>"""
import bpy, os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tklib import argv, reset, import_part_mm, bbox, part_files

args = argv()
parts_dir, out_json = args[0], args[1]
reset()
report = {}
for f in part_files(parts_dir, args[2:]):
    name = os.path.splitext(os.path.basename(f))[0]
    obj, scale = import_part_mm(f)
    mins, maxs = bbox([obj])
    report[name] = {
        "dims_mm": [round(v, 2) for v in (maxs - mins)],
        "bbox_min": [round(v, 2) for v in mins],
        "bbox_max": [round(v, 2) for v in maxs],
        "tris": len(obj.data.polygons),
        "scale_applied": scale,
    }
    bpy.data.objects.remove(obj, do_unlink=True)

with open(out_json, "w") as fh:
    json.dump(report, fh, indent=1)
for n, d in report.items():
    print(f"{n:20s} dims_mm={d['dims_mm']}  bbox={d['bbox_min']}..{d['bbox_max']}  tris={d['tris']}  x{d['scale_applied']:g}")
print("WROTE", out_json)
