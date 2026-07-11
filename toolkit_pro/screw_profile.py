"""Analyze elongated parts (screws/standoffs): long axis, which end is the head,
head/shaft radii and lengths. Usage:
bash bl.sh screw_profile.py <parts_dir> [part_name ...]"""
import bpy, os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tklib import argv, reset, import_part_mm, bbox, part_files

args = argv()
parts_dir = args[0]
reset()
for f in part_files(parts_dir, args[1:]):
    name = os.path.splitext(os.path.basename(f))[0]
    obj, _ = import_part_mm(f)
    mins, maxs = bbox([obj])
    dims = [maxs[i] - mins[i] for i in range(3)]
    li = max(range(3), key=lambda i: dims[i])
    if dims[li] < 1.8 * sorted(dims)[1] or sorted(dims)[1] > 12:
        print(f"{name:14s} not screw-like (dims {[round(d,1) for d in dims]}) — skipped")
        bpy.data.objects.remove(obj, do_unlink=True)
        continue
    ri = [i for i in range(3) if i != li]
    c0, c1 = (mins[ri[0]] + maxs[ri[0]]) / 2, (mins[ri[1]] + maxs[ri[1]]) / 2
    verts = [v.co for v in obj.data.vertices]
    NB = 40
    lo, hi = mins[li], maxs[li]
    prof = [0.0] * NB
    for v in verts:
        b = min(NB - 1, int((v[li] - lo) / (hi - lo) * NB))
        r = math.hypot(v[ri[0]] - c0, v[ri[1]] - c1)
        prof[b] = max(prof[b], r)
    interior = [p for p in prof[NB // 5: -NB // 5] if p > 0]
    shaft_r = min(interior) if interior else max(prof)
    head_low, head_high = prof[0], prof[-1]
    head_end = "min" if head_low > head_high else "max"
    head_r = max(head_low, head_high)
    hp = prof if head_end == "min" else prof[::-1]
    nhead = 0
    for p in hp:
        if p > shaft_r * 1.15:
            nhead += 1
        else:
            break
    head_len = nhead / NB * (hi - lo)
    axis = "xyz"[li]
    print(f"{name:14s} axis={axis} len={hi-lo:5.1f}  head at {axis}={'%.1f' % (lo if head_end=='min' else hi)} "
          f"(r{head_r:.2f}, ~{head_len:.1f} long)  shaft r{shaft_r:.2f}  thread_len~{hi-lo-head_len:.1f}")
    bpy.data.objects.remove(obj, do_unlink=True)
