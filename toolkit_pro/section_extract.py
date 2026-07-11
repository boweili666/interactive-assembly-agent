"""Cut cross-sections through parts: exact mesh/plane intersection segments -> JSON.
Usage: bash bl.sh section_extract.py <parts_dir> <out.json> <part> <x|y|z> <value> [<part> <axis> <value> ...]"""
import bpy, os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tklib import argv, reset, import_part_mm

args = argv()
parts_dir, out_json = args[0], args[1]
triples = [(args[i], args[i + 1], float(args[i + 2])) for i in range(2, len(args), 3)]
AX = {"x": 0, "y": 1, "z": 2}

reset()
result = {}
cache = {}
for part, axis, value in triples:
    if part not in cache:
        obj, _ = import_part_mm(os.path.join(parts_dir, part + ".glb"))
        me = obj.data
        me.calc_loop_triangles()
        tris = [[me.vertices[i].co.copy() for i in t.vertices] for t in me.loop_triangles]
        cache[part] = tris
        bpy.data.objects.remove(obj, do_unlink=True)
    ai = AX[axis]
    segs = []
    for tri in cache[part]:
        d = [v[ai] - value for v in tri]
        pts = []
        for i in range(3):
            j = (i + 1) % 3
            if (d[i] > 0) != (d[j] > 0) and abs(d[i] - d[j]) > 1e-12:
                t = d[i] / (d[i] - d[j])
                p = tri[i].lerp(tri[j], t)
                pts.append([round(p.x, 3), round(p.y, 3), round(p.z, 3)])
        if len(pts) == 2:
            segs.append(pts)
    key = f"{part}@{axis}={value:g}"
    result[key] = {"axis": axis, "value": value, "segs": segs}
    print(key, len(segs), "segments")
with open(out_json, "w") as fh:
    json.dump(result, fh)
print("WROTE", out_json)
