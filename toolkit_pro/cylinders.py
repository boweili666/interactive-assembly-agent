"""Axis-agnostic cylindrical feature detector: finds holes/bosses along ANY axis
(not just Z). Smooth-patch clustering + normal-covariance axis + circle fit.
Usage: bash bl.sh cylinders.py <parts_dir> [part_name ...]"""
import bpy, os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tklib import argv, reset, import_part_mm, part_files
import numpy as np

args = argv()
parts_dir = args[0]
COS_SMOOTH = math.cos(math.radians(40))

reset()
for f in part_files(parts_dir, args[1:]):
    name = os.path.splitext(os.path.basename(f))[0]
    obj, _ = import_part_mm(f)
    me = obj.data
    polys = me.polygons
    parent = list(range(len(polys)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    edge_map = {}
    for p in polys:
        for ek in p.edge_keys:
            if ek in edge_map:
                q = edge_map[ek]
                if polys[p.index].normal.dot(polys[q].normal) > COS_SMOOTH:
                    ra, rb = find(p.index), find(q)
                    if ra != rb:
                        parent[ra] = rb
            else:
                edge_map[ek] = p.index
    patches = {}
    for p in polys:
        patches.setdefault(find(p.index), []).append(p)

    found = []
    for faces in patches.values():
        if len(faces) < 6:
            continue
        N = np.array([list(p.normal) for p in faces])
        # curved patch? normals must spread
        if np.ptp(N @ N.mean(axis=0)) < 0.05 and np.linalg.norm(N.std(axis=0)) < 0.05:
            continue
        M = N.T @ N / len(faces)
        w, V = np.linalg.eigh(M)
        axis = V[:, 0]                     # min-eigenvalue dir = cylinder axis
        if w[0] > 0.05:                    # normals not coplanar enough -> not a cylinder
            continue
        if w[1] < 0.15:                    # normals barely spread -> flat plane
            continue
        u = V[:, 1]; v = V[:, 2]
        vids = set()
        for p in faces:
            vids.update(p.vertices)
        P = np.array([list(me.vertices[i].co) for i in vids])
        pu = P @ u; pv = P @ v; pw = P @ axis
        A = np.c_[pu, pv, np.ones(len(pu))]
        B = -(pu ** 2 + pv ** 2)
        try:
            (a, b, c), *_ = np.linalg.lstsq(A, B, rcond=None)
        except Exception:
            continue
        cu, cv = -a / 2, -b / 2
        r = math.sqrt(max(0.0, (a * a + b * b) / 4 - c))
        if r < 0.4 or r > 25:
            continue
        res = np.abs(np.hypot(pu - cu, pv - cv) - r)
        if res.mean() > max(0.12 * r, 0.08):
            continue
        wmid = (pw.min() + pw.max()) / 2
        center = cu * u + cv * v + wmid * axis
        # hole (normals point toward axis) vs boss (away)
        fc = np.array([list(sum((me.vertices[i].co for i in p.vertices),
                       me.vertices[p.vertices[0]].co * 0) / len(p.vertices)) for p in faces])
        rad = fc - (fc @ axis)[:, None] * axis[None, :] \
                 - (cu * u + cv * v)[None, :]
        rad = rad / (np.linalg.norm(rad, axis=1, keepdims=True) + 1e-9)
        ndot = float((N * rad).sum(axis=1).mean())
        kind = "hole" if ndot < -0.2 else "boss"
        ax_lbl = max(zip((abs(axis[0]), abs(axis[1]), abs(axis[2])), "xyz"))[1]
        found.append((r, kind, ax_lbl, axis, center, pw.max() - pw.min(), res.mean()))

    print("==", name)
    found.sort(key=lambda t: t[0])
    for r, kind, ax_lbl, axis, center, ln, err in found:
        print(f"   {kind.upper():4s} r={r:5.2f} axis~{ax_lbl} ({axis[0]:+.2f},{axis[1]:+.2f},{axis[2]:+.2f}) "
              f"center=({center[0]:7.2f},{center[1]:7.2f},{center[2]:6.2f}) len={ln:.1f} err={err:.3f}")
    if not found:
        print("   (no cylindrical features)")
    bpy.data.objects.remove(obj, do_unlink=True)
