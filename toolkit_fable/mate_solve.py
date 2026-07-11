#!/usr/bin/env python3
"""Pose solver: find the rigid 2D transform (rotation + optional mirror + translation)
that best aligns part A's hole pattern onto part B's (or onto the assembled world).
Enumerates candidate poses from hole-pair correspondences (RANSAC-style), scores by
inlier count + RMS. Use this instead of guessing orientations of symmetric parts.

Usage:
  python3 mate_solve.py <holes.json> <partA> <partB>            [options]
  python3 mate_solve.py <holes.json> <partA> <world_holes.json> [options]
Options:
  --rmax 4.0     ignore features with r > rmax (default 4; raise to include bosses)
  --kinds hole,boss/outline   feature kinds to use
  --tol-d 0.6    pair-distance tolerance (mm)
  --tol-r 0.6    radius-match tolerance (mm)
  --inlier 0.8   inlier distance (mm)
  --top 5        print top N poses
Output per pose: mirror_x, rot_z (deg), translation (mm), inliers, rms, matches.
Apply in assemble.py as: {"mirror_x":..., "rot_z":..., "loc":[tx,ty,<your z>]}.
"""
import json, math, sys, os, itertools

args = sys.argv[1:]
opts = {"rmax": 4.0, "tol_d": 0.6, "tol_r": 0.6, "inlier": 0.8, "top": 5,
        "kinds": "hole,boss/outline"}
pos = []
i = 0
while i < len(args):
    if args[i].startswith("--"):
        k = args[i][2:].replace("-", "_")
        opts[k] = args[i + 1]
        i += 2
    else:
        pos.append(args[i]); i += 1
holes_json, partA, targetB = pos[0], pos[1], pos[2]
RMAX = float(opts["rmax"]); TOL_D = float(opts["tol_d"]); TOL_R = float(opts["tol_r"])
INL = float(opts["inlier"]); TOP = int(opts["top"])
KINDS = set(k.strip() for k in str(opts["kinds"]).split(","))

db = json.load(open(holes_json))

def feats_from_part(part):
    out = []
    for h in db.get(part, []):
        if h.get("kind", "hole") in KINDS and h.get("r", 99) <= RMAX:
            out.append((h["center"][0], h["center"][1], h["r"], part))
    return out

A = feats_from_part(partA)
if os.path.isfile(targetB):
    world = json.load(open(targetB))
    B = [(e["center"][0], e["center"][1], e["r"], e.get("label", "?"))
         for e in world if e.get("kind", "hole") in KINDS and e.get("r", 99) <= RMAX]
else:
    B = feats_from_part(targetB)

if len(A) < 2 or len(B) < 2:
    sys.exit(f"need >=2 features on both sides (A={len(A)}, B={len(B)}) — "
             f"lower --rmax filtering or add --kinds")

def apply(mirror, rot, tx, ty, p):
    x = -p[0] if mirror else p[0]
    y = p[1]
    c, s = math.cos(rot), math.sin(rot)
    return (c * x - s * y + tx, s * x + c * y + ty)

def score(mirror, rot, tx, ty):
    matches = []
    used = set()
    err2 = 0.0
    for a in A:
        wx, wy = apply(mirror, rot, tx, ty, a)
        best = None; bd = INL
        for j, b in enumerate(B):
            if j in used or abs(a[2] - b[2]) > TOL_R:
                continue
            d = math.hypot(wx - b[0], wy - b[1])
            if d < bd:
                bd = d; best = j
        if best is not None:
            used.add(best)
            matches.append((a, B[best], bd))
            err2 += bd * bd
    n = len(matches)
    rms = math.sqrt(err2 / n) if n else 99.0
    return n, rms, matches

cands = []
pairsA = list(itertools.combinations(range(len(A)), 2))
pairsB = list(itertools.combinations(range(len(B)), 2))
budget = 300000
seen = set()
for ia, ja in pairsA:
    a1, a2 = A[ia], A[ja]
    dA = math.hypot(a1[0] - a2[0], a1[1] - a2[1])
    for ib, jb in pairsB:
        if budget <= 0:
            break
        b1, b2 = B[ib], B[jb]
        dB = math.hypot(b1[0] - b2[0], b1[1] - b2[1])
        if abs(dA - dB) > TOL_D:
            continue
        for (p1, p2), (q1, q2) in (((a1, a2), (b1, b2)), ((a1, a2), (b2, b1))):
            if abs(p1[2] - q1[2]) > TOL_R or abs(p2[2] - q2[2]) > TOL_R:
                continue
            for mirror in (False, True):
                budget -= 1
                m1 = (-p1[0], p1[1]) if mirror else (p1[0], p1[1])
                m2 = (-p2[0], p2[1]) if mirror else (p2[0], p2[1])
                angA = math.atan2(m2[1] - m1[1], m2[0] - m1[0])
                angB = math.atan2(q2[1] - q1[1], q2[0] - q1[0])
                rot = angB - angA
                c, s = math.cos(rot), math.sin(rot)
                tx = q1[0] - (c * m1[0] - s * m1[1])
                ty = q1[1] - (s * m1[0] + c * m1[1])
                key = (mirror, round(math.degrees(rot) % 360, 0), round(tx, 1), round(ty, 1))
                if key in seen:
                    continue
                seen.add(key)
                n, rms, matches = score(mirror, rot, tx, ty)
                if n >= 2:
                    cands.append((n, rms, mirror, rot, tx, ty, matches))

cands.sort(key=lambda t: (-t[0], t[1]))
# dedup near-identical poses
final = []
for c in cands:
    dup = False
    for f in final:
        if c[2] == f[2] and abs((math.degrees(c[3] - f[3]) + 180) % 360 - 180) < 3 \
           and math.hypot(c[4] - f[4], c[5] - f[5]) < 1.0:
            dup = True; break
    if not dup:
        final.append(c)
    if len(final) >= TOP:
        break

print(f"A={partA}: {len(A)} features   B={targetB}: {len(B)} features")
if not final:
    print("NO pose found — loosen --tol-d/--tol-r/--rmax or check kinds")
for rank, (n, rms, mirror, rot, tx, ty, matches) in enumerate(final, 1):
    deg = math.degrees(rot) % 360
    print(f"#{rank}: mirror_x={mirror} rot_z={deg:.2f} loc=({tx:.2f},{ty:.2f})  "
          f"inliers={n}/{len(A)}  rms={rms:.3f}mm")
    for a, b, d in matches[:12]:
        print(f"     A r{a[2]:g}@({a[0]:.1f},{a[1]:.1f}) -> {b[3]} r{b[2]:g}@({b[0]:.1f},{b[1]:.1f})  d={d:.2f}")
if len(final) > 1 and final[0][0] == final[1][0] and abs(final[0][1] - final[1][1]) < 0.1:
    print("WARNING: top poses are a near-tie — get more features (bosses, asymmetric holes) "
          "or check against the manual before choosing.")
