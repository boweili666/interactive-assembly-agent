"""Render each part: orthographic top/front/side + 2 perspective views.
Usage: bash bl.sh render_parts.py <parts_dir> <out_dir> [part_name ...]"""
import bpy, os, sys, math
from mathutils import Vector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tklib import argv, reset, import_part_mm, bbox, part_files, look_at

args = argv()
parts_dir, out_dir = args[0], args[1]
os.makedirs(out_dir, exist_ok=True)

for f in part_files(parts_dir, args[2:]):
    name = os.path.splitext(os.path.basename(f))[0]
    reset()
    obj, _ = import_part_mm(f)
    mins, maxs = bbox([obj])
    center = (mins + maxs) / 2
    dims = maxs - mins
    diag = dims.length

    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.show_cavity = True
    scene.render.resolution_x = scene.render.resolution_y = 1000
    world = bpy.data.worlds.new("w"); scene.world = world

    cam = bpy.data.cameras.new("c"); cam.clip_end = 1e6
    co = bpy.data.objects.new("c", cam)
    scene.collection.objects.link(co); scene.camera = co

    views = {
        "top":   ((center.x, center.y, maxs.z + 100), max(dims.x, dims.y) * 1.15, True),
        "front": ((center.x, mins.y - 100, center.z), max(dims.x, dims.z) * 1.3, True),
        "side":  ((maxs.x + 100, center.y, center.z), max(dims.y, dims.z) * 1.3, True),
        "persp0": (tuple(center + Vector((1, -1, 0.9)) * diag * 1.1), None, False),
        "persp1": (tuple(center + Vector((-1, 1, 0.9)) * diag * 1.1), None, False),
    }
    for vname, (loc, oscale, ortho) in views.items():
        co.location = loc
        look_at(co, center)
        cam.type = 'ORTHO' if ortho else 'PERSP'
        if ortho:
            cam.ortho_scale = max(oscale, 1.0)
        scene.render.filepath = os.path.join(out_dir, f"{name}_{vname}.png")
        bpy.ops.render.render(write_still=True)
    print("RENDERED", name)
print("DONE ->", out_dir)
