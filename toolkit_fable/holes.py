"""Extract hole/slot wall clusters per part (Fable version: centroid + radius stats).
Usage: bash bl.sh holes.py <parts_dir> <out.json> [part_name ...]"""
import bpy, os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tklib import argv, reset, import_part_mm, part_files

args = argv()
parts_dir, out_json = args[0], args[1]
reset()
result = {}
for f in part_files(parts_dir, args[2:]):
    name = os.path.splitext(os.path.basename(f))[0]
    obj, _ = import_part_mm(f)
    me = obj.data
    verts = [v.co.copy() for v in me.vertices]
    wall = [p for p in me.polygons if abs(p.normal.z) < 0.4]
    parent = list(range(len(wall)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    edge_map = {}
    for i, p in enumerate(wall):
        for ek in p.edge_keys:
            if ek in edge_map:
                ra, rb = find(i), find(edge_map[ek])
                if ra != rb:
                    parent[ra] = rb
            else:
                edge_map[ek] = i
    clusters = {}
    for i, p in enumerate(wall):
        clusters.setdefault(find(i), []).append(p)
    info = []
    for faces in clusters.values():
        vids = set()
        for p in faces:
            vids.update(p.vertices)
        pts = [verts[i] for i in vids]
        cx = sum(p.x for p in pts) / len(pts)
        cy = sum(p.y for p in pts) / len(pts)
        rs = [math.hypot(p.x - cx, p.y - cy) for p in pts]
        zmin = min(p.z for p in pts); zmax = max(p.z for p in pts)
        ravg = sum(rs) / len(rs)
        circular = (max(rs) - min(rs)) < 0.25 * ravg
        info.append({
            "kind": "hole" if circular else "slot/outline",
            "center": [round(cx, 2), round(cy, 2)],
            "z": [round(zmin, 2), round(zmax, 2)],
            "r": round(ravg, 2), "r_min": round(min(rs), 2), "r_max": round(max(rs), 2),
            "nfaces": len(faces),
        })
    info.sort(key=lambda d: d["r"])
    result[name] = info
    bpy.data.objects.remove(obj, do_unlink=True)

with open(out_json, "w") as fh:
    json.dump(result, fh, indent=1)
for n, inf in result.items():
    print("==", n)
    for d in inf:
        if d["kind"] == "hole":
            print(f"   HOLE r={d['r']:5.2f} at ({d['center'][0]:7.2f},{d['center'][1]:7.2f}) z {d['z'][0]}..{d['z'][1]}")
    print(f"   (+{sum(1 for d in inf if d['kind'] != 'hole')} non-circular clusters — see json)")
print("WROTE", out_json)
