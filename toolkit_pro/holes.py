"""Extract hole/slot wall clusters per part — pro version.
Per cluster: least-squares circle fit (center, r, residual), z-range,
and classification: HOLE (walls face inward), BOSS/OUTLINE (walls face outward),
SLOT (elongated non-circular).
Usage: bash bl.sh holes.py <parts_dir> <out.json> [part_name ...]"""
import bpy, os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tklib import argv, reset, import_part_mm, part_files
import numpy as np

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
    for i in range(len(wall)):
        clusters.setdefault(find(i), []).append(wall[i])

    info = []
    for faces in clusters.values():
        vids = set()
        for p in faces:
            vids.update(p.vertices)
        pts = [verts[i] for i in vids]
        cx0 = sum(p.x for p in pts) / len(pts)
        cy0 = sum(p.y for p in pts) / len(pts)
        zmin = min(p.z for p in pts); zmax = max(p.z for p in pts)
        xs = [p.x for p in pts]; ys = [p.y for p in pts]

        # least-squares (Kasa) circle fit in XY
        A = np.array([[p.x, p.y, 1.0] for p in pts])
        B = np.array([-(p.x * p.x + p.y * p.y) for p in pts])
        try:
            (a, b, c), *_ = np.linalg.lstsq(A, B, rcond=None)
            cx, cy = -a / 2, -b / 2
            r = math.sqrt(max(0.0, (a * a + b * b) / 4 - c))
            res = [abs(math.hypot(p.x - cx, p.y - cy) - r) for p in pts]
            err = sum(res) / len(res)
        except Exception:
            cx, cy = cx0, cy0
            rs = [math.hypot(p.x - cx0, p.y - cy0) for p in pts]
            r = sum(rs) / len(rs)
            err = (max(rs) - min(rs)) / 2

        circular = err < max(0.08 * r, 0.06)

        # walls facing inward (toward axis) = hole; outward = boss / outer outline
        dots = []
        for p in faces:
            fc = sum((verts[i] for i in p.vertices), verts[p.vertices[0]] * 0) / len(p.vertices)
            rv = fc.xy - type(fc.xy)((cx, cy))
            nv = p.normal.xy
            if rv.length > 1e-6 and nv.length > 1e-6:
                dots.append(nv.normalized().dot(rv.normalized()))
        ndot = sum(dots) / len(dots) if dots else 0.0
        if circular:
            kind = "hole" if ndot < -0.2 else "boss/outline"
        else:
            kind = "slot/outline"

        info.append({
            "kind": kind,
            "center": [round(cx, 2), round(cy, 2)],
            "r": round(r, 2), "fit_err": round(err, 3),
            "z": [round(zmin, 2), round(zmax, 2)],
            "extent": [round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)],
            "nfaces": len(faces),
        })
    info.sort(key=lambda d: (d["kind"] != "hole", d["r"]))
    result[name] = info
    bpy.data.objects.remove(obj, do_unlink=True)

with open(out_json, "w") as fh:
    json.dump(result, fh, indent=1)
for n, inf in result.items():
    print("==", n)
    for d in inf:
        if d["kind"] == "hole":
            print(f"   HOLE r={d['r']:5.2f} at ({d['center'][0]:7.2f},{d['center'][1]:7.2f}) z {d['z'][0]}..{d['z'][1]}  err={d['fit_err']}")
    nb = sum(1 for d in inf if d["kind"] == "boss/outline")
    ns = sum(1 for d in inf if d["kind"] == "slot/outline")
    print(f"   (+{nb} boss/outline, {ns} slot/outline clusters — see json)")
print("WROTE", out_json)
