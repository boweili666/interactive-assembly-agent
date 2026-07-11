"""Extract feature edges (boundary + sharp >25deg) per part -> JSON segments.
Usage: bash bl.sh edges_extract.py <parts_dir> <out.json> [part_name ...]"""
import bpy, os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tklib import argv, reset, import_part_mm, part_files

args = argv()
parts_dir, out_json = args[0], args[1]
reset()
result = {}
COS_SHARP = math.cos(math.radians(25))
for f in part_files(parts_dir, args[2:]):
    name = os.path.splitext(os.path.basename(f))[0]
    obj, _ = import_part_mm(f)
    me = obj.data
    edge_faces = {}
    for p in me.polygons:
        for ek in p.edge_keys:
            edge_faces.setdefault(ek, []).append(p.index)
    segs = []
    for (a, b), fl in edge_faces.items():
        keep = len(fl) == 1
        if not keep and len(fl) >= 2:
            n0 = me.polygons[fl[0]].normal
            n1 = me.polygons[fl[1]].normal
            keep = n0.dot(n1) < COS_SHARP
        if keep:
            va, vb = me.vertices[a].co, me.vertices[b].co
            segs.append([[round(va.x, 2), round(va.y, 2), round(va.z, 2)],
                         [round(vb.x, 2), round(vb.y, 2), round(vb.z, 2)]])
    result[name] = segs
    print(name, len(segs), "feature edges")
    bpy.data.objects.remove(obj, do_unlink=True)
with open(out_json, "w") as fh:
    json.dump(result, fh)
print("WROTE", out_json)
