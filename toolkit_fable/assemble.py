"""Build an assembly from a layout JSON; render standard views (+ exploded);
save .blend and export .glb.
Usage: bash bl.sh assemble.py <layout.json>

Layout JSON:
{
  "parts_dir": "/abs/path",
  "out_dir": "/abs/path",                  // deliverables
  "name": "assembly",                      // file basename
  "placements": [
    {
      "part": "carbon_board",              // glb basename, no extension
      "label": "rear_plate",               // unique object name
      "material": "carbon",                // carbon|plastic|alu|steel (default plastic)
      "color": [0.7,0.1,0.4],              // optional base-color override (0..1)
      "loc": [0,0,-2],                     // translation, mm
      "rot_z": 51.9, "rot_x": 0, "rot_y": 0,   // degrees; applied as T@RZ@RY@RX@MIRROR
      "mirror_x": false,                   // mirror in local x (opposite-hand part)
      "pivot_local": [-10.58, 83.71, 0],   // optional: instead of loc, land this local
      "pivot_world": [14.9, -26.3, 0]      //   point on this world point (rotation still applies)
    }, ...
  ],
  "explode": {"rear_plate": -45, "arm_": -20},   // optional: label-prefix -> z offset for exploded render
  "extra_views": [ {"name":"joint", "loc":[90,-90,90], "target":[0,0,5], "ortho_scale": 70}, ... ],
  "check_holes": "/abs/path/holes.json"          // optional: from holes.py -> prints a numeric
                                                 // hole-alignment report (coaxial stacks + offsets)
}
All standard renders are written to out_dir: hero, top(ortho), front, low, center
plus exploded_hero/exploded_front when "explode" is present.
"""
import bpy, os, sys, json, math
from mathutils import Vector, Matrix
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tklib import argv, reset, import_part_mm, bbox, look_at

layout = json.load(open(argv()[0]))
parts_dir = layout["parts_dir"]
out_dir = layout["out_dir"]
name = layout.get("name", "assembly")

# ---- HARD GATES (checked before any work) ----
# 1. Every rotated/mirrored placement must be evidence-based: either a
#    pivot_local/pivot_world pair, or an "evidence" string citing the mate_solve
#    result / manual feature that fixes its pose.
_bad = []
for _p in layout["placements"]:
    _rot = any(abs(_p.get(k, 0)) > 1e-6 for k in ("rot_z", "rot_x", "rot_y")) or _p.get("mirror_x")
    _ok = ("pivot_local" in _p and "pivot_world" in _p) or _p.get("evidence")
    if _rot and not _ok:
        _bad.append(_p.get("label", _p.get("part", "?")))
if _bad:
    sys.exit("GATE FAILED — rotated/mirrored placements need pivot_local+pivot_world "
             "(preferred) or an 'evidence' string citing a mate_solve result or manual "
             "feature: " + ", ".join(_bad))
# 2. Layout must reference the manual's assembled-view figure for side-by-side
#    verification; compare_manual.png is produced at the end and MUST be viewed.
_mref = layout.get("manual_ref")
if not _mref or not os.path.isfile(_mref):
    sys.exit("GATE FAILED — layout must include \"manual_ref\": path to a cropped image "
             "of the manual's assembled/step view (crop it from the rasterized PDF). "
             "After assembling you must view compare_manual.png and check orientations.")

os.makedirs(out_dir, exist_ok=True)

reset()
scene = bpy.context.scene

PRESETS = {  # base color, metallic, roughness
    "carbon":  ((0.03, 0.03, 0.035), 0.15, 0.32),
    "plastic": ((0.09, 0.09, 0.10), 0.0, 0.45),
    "alu":     ((0.80, 0.80, 0.82), 0.95, 0.35),
    "steel":   ((0.18, 0.18, 0.19), 0.9, 0.42),
}
_mats = {}
def get_mat(preset, color):
    key = (preset, tuple(color) if color else None)
    if key in _mats:
        return _mats[key]
    base, met, rough = PRESETS.get(preset, PRESETS["plastic"])
    if color:
        base = tuple(color)
    m = bpy.data.materials.new(f"{preset}_{len(_mats)}")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*base, 1)
    b.inputs["Metallic"].default_value = met
    b.inputs["Roughness"].default_value = rough
    _mats[key] = m
    return m

_templates = {}
def template(part):
    if part not in _templates:
        obj, _ = import_part_mm(os.path.join(parts_dir, part + ".glb"))
        obj.name = "tpl_" + part
        _templates[part] = obj
    return _templates[part]

def RZ(d): return Matrix.Rotation(math.radians(d), 4, 'Z')
def RY(d): return Matrix.Rotation(math.radians(d), 4, 'Y')
def RX(d): return Matrix.Rotation(math.radians(d), 4, 'X')

placed = []
for p in layout["placements"]:
    tpl = template(p["part"])
    o = bpy.data.objects.new(p["label"], tpl.data)
    scene.collection.objects.link(o)
    R = RZ(p.get("rot_z", 0)) @ RY(p.get("rot_y", 0)) @ RX(p.get("rot_x", 0))
    S = Matrix.Scale(-1, 4, (1, 0, 0)) if p.get("mirror_x") else Matrix.Identity(4)
    if "pivot_local" in p and "pivot_world" in p:
        pw = Vector(p["pivot_world"])
        t = pw - (R @ S @ Vector(p["pivot_local"]))
    else:
        t = Vector(p.get("loc", [0, 0, 0]))
    o.matrix_world = Matrix.Translation(t) @ R @ S
    mat = get_mat(p.get("material", "plastic"), p.get("color"))
    if len(o.data.materials) == 0:
        o.data.materials.append(mat)
    else:
        o.data.materials[0] = mat
    placed.append(o)

for tpl in _templates.values():
    bpy.data.objects.remove(tpl, do_unlink=True)

# ---- numeric hole-alignment report + world-frame hole dump ----
if layout.get("check_holes"):
    holes_db = json.load(open(layout["check_holes"]))
    pts = []  # (label, world_xy, r, world_z_range)
    world_dump = []
    for p, o in zip(layout["placements"], placed):
        for h in holes_db.get(p["part"], []):
            zmid = sum(h["z"]) / 2 if "z" in h else 0
            w = o.matrix_world @ Vector((h["center"][0], h["center"][1], zmid))
            dz = (h["z"][1] - h["z"][0]) / 2 if "z" in h else 0
            world_dump.append({"label": o.name, "part": p["part"],
                               "kind": h.get("kind", "hole"), "r": h.get("r", 0),
                               "center": [round(w.x, 2), round(w.y, 2)],
                               "z": [round(w.z - dz, 2), round(w.z + dz, 2)]})
            if h.get("kind", "hole") != "hole" or h.get("r", 99) > 3.5:
                continue
            pts.append((o.name, w, h["r"], (w.z - dz, w.z + dz)))
    with open(os.path.join(out_dir, "world_holes.json"), "w") as fh:
        json.dump(world_dump, fh, indent=1)
    print("WROTE", os.path.join(out_dir, "world_holes.json"),
          "(use with mate_solve.py to place parts against the assembled stack)")
    used = [False] * len(pts)
    groups = []
    for i in range(len(pts)):
        if used[i]:
            continue
        g = [i]; used[i] = True
        for j in range(i + 1, len(pts)):
            if not used[j] and (pts[j][1].xy - pts[i][1].xy).length < 0.8:
                g.append(j); used[j] = True
        if len(g) > 1:
            xs = [pts[k][1].x for k in g]; ys = [pts[k][1].y for k in g]
            spread = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
            groups.append((spread, g))
    groups.sort(key=lambda t: -t[0])
    print("== HOLE ALIGNMENT REPORT (coaxial stacks across parts) ==")
    for spread, g in groups:
        labs = ", ".join(f"{pts[k][0]}(r{pts[k][2]:g}, z{pts[k][3][0]:.0f}..{pts[k][3][1]:.0f})" for k in g)
        flag = "  <-- MISALIGNED?" if spread > 0.5 else ""
        print(f"  xy=({pts[g[0]][1].x:7.2f},{pts[g[0]][1].y:7.2f}) spread={spread:.2f}mm : {labs}{flag}")
    lone = [k for k in range(len(pts)) if not any(k in g for _, g in groups)]
    print(f"  ({len(lone)} holes matched nothing — fine for plate-only holes)")

# ---- lights / world / ground ----
scene.render.engine = 'BLENDER_EEVEE'
world = bpy.data.worlds.new("w"); scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.92, 0.92, 0.94, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.7

def add_light(loc, energy):
    ld = bpy.data.lights.new("l", 'AREA'); ld.energy = energy; ld.size = 200
    lo = bpy.data.objects.new("l", ld); scene.collection.objects.link(lo)
    lo.location = loc; look_at(lo, (0, 0, 0))
add_light((150, -120, 260), 900000)
add_light((-200, 150, 180), 500000)
add_light((0, 250, -160), 250000)

mins, maxs = bbox(placed)
center = (mins + maxs) / 2
dims = maxs - mins
diag = max(dims.length, 50)

gm = get_mat("plastic", (0.88, 0.88, 0.9))
gz = mins.z - 10
me = bpy.data.meshes.new("g")
me.from_pydata([(-6*diag,-6*diag,gz),(6*diag,-6*diag,gz),(6*diag,6*diag,gz),(-6*diag,6*diag,gz)], [], [(0,1,2,3)])
ground = bpy.data.objects.new("ground", me)
scene.collection.objects.link(ground)
ground.data.materials.append(gm)

cam = bpy.data.cameras.new("cam"); cam.clip_end = 1e6
co = bpy.data.objects.new("cam", cam); scene.collection.objects.link(co)
scene.camera = co
scene.render.resolution_x = 1600
scene.render.resolution_y = 1200

def shoot(fname, loc, target=None, ortho_scale=None):
    co.location = loc
    look_at(co, Vector(target) if target else center)
    cam.type = 'ORTHO' if ortho_scale else 'PERSP'
    if ortho_scale:
        cam.ortho_scale = ortho_scale
    else:
        cam.lens = 60
    scene.render.filepath = os.path.join(out_dir, fname)
    bpy.ops.render.render(write_still=True)
    print("RENDER", fname)

import subprocess
shoot("hero.png",  center + Vector(( 0.65, -0.65, 0.5)) * diag)
shoot("top.png",   (center.x, center.y + 0.001, maxs.z + diag), ortho_scale=1.15 * max(dims.x, dims.y))
shoot("front.png", center + Vector((0, -0.85, 0.16)) * diag)
shoot("low.png",   center + Vector((0.75, 0.45, 0.15)) * diag)
shoot("center.png", center + Vector((0.24, -0.24, 0.24)) * diag, target=center)
for v in layout.get("extra_views", []):
    shoot(v["name"] + ".png", Vector(v["loc"]), target=v.get("target"), ortho_scale=v.get("ortho_scale"))

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, name + ".blend"))
bpy.data.objects.remove(ground, do_unlink=True)
bpy.ops.export_scene.gltf(filepath=os.path.join(out_dir, name + ".glb"), export_format='GLB')
import shutil
shutil.copyfile(os.path.join(out_dir, name + ".glb"), os.path.join(out_dir, "latest.glb"))
print("SAVED", name + ".blend", name + ".glb", "(+latest.glb for live viewer)")

explode = layout.get("explode")
if explode:
    for o in placed:
        for prefix, dz in explode.items():
            if o.name.startswith(prefix):
                o.location.z += dz
                break
    mins2, maxs2 = bbox(placed)
    c2 = (mins2 + maxs2) / 2
    d2 = max((maxs2 - mins2).length, 50)
    me2 = bpy.data.meshes.new("g2")
    gz2 = mins2.z - 10
    me2.from_pydata([(-6*d2,-6*d2,gz2),(6*d2,-6*d2,gz2),(6*d2,6*d2,gz2),(-6*d2,6*d2,gz2)], [], [(0,1,2,3)])
    g2 = bpy.data.objects.new("ground", me2)
    scene.collection.objects.link(g2)
    g2.data.materials.append(gm)
    shoot("exploded_hero.png",  c2 + Vector((0.8, -0.8, 0.6)) * d2, target=c2)
    shoot("exploded_front.png", c2 + Vector((0, -1.1, 0.1)) * d2, target=c2)

# side-by-side with the manual figure — VIEW THIS and verify orientations
cmp_out = os.path.join(out_dir, "compare_manual.png")
r = subprocess.run(["python3", os.path.join(os.path.dirname(os.path.abspath(__file__)), "compare.py"),
                    cmp_out, _mref, os.path.join(out_dir, "hero.png"), os.path.join(out_dir, "top.png")],
                   capture_output=True, text=True)
print(r.stdout.strip() or r.stderr.strip())
print("MANDATORY: view compare_manual.png — check arm/motor directions, part orientations "
      "and stack order against the manual before finishing.")
print("ASSEMBLE DONE ->", out_dir)
