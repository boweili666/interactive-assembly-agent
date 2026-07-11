"""Shared helpers for toolkit Blender scripts."""
import bpy, os, sys, math
from mathutils import Vector, Matrix


def argv():
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_part_mm(path):
    """Import a glb; join meshes; normalize units to millimeters.
    Returns (mesh_object, scale_applied). Heuristic: if the largest bbox
    dimension is < 2 units the file is in meters -> scale x1000."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == 'MESH']
    for o in new:
        if o.type != 'MESH':
            for c in list(o.children):
                mw = c.matrix_world.copy()
                c.parent = None
                c.matrix_world = mw
    for o in new:
        if o.type != 'MESH':
            bpy.data.objects.remove(o, do_unlink=True)
    if len(meshes) > 1:
        with bpy.context.temp_override(active_object=meshes[0],
                                       selected_editable_objects=meshes):
            bpy.ops.object.join()
    obj = meshes[0]
    mins, maxs = bbox([obj])
    maxdim = max(maxs - mins)
    scale = 1000.0 if maxdim < 2.0 else 1.0
    if scale != 1.0:
        obj.data.transform(Matrix.Scale(scale, 4))
        obj.data.update()
    obj.matrix_world = Matrix.Identity(4)
    obj.data.materials.clear()
    bpy.context.view_layer.update()
    return obj, scale


def bbox(objs):
    mins = Vector((1e18,) * 3)
    maxs = Vector((-1e18,) * 3)
    for o in objs:
        for c in o.bound_box:
            wc = o.matrix_world @ Vector(c)
            mins = Vector(map(min, mins, wc))
            maxs = Vector(map(max, maxs, wc))
    return mins, maxs


def part_files(parts_dir, names):
    import glob
    files = sorted(glob.glob(os.path.join(parts_dir, "*.glb")))
    if names:
        files = [f for f in files if os.path.splitext(os.path.basename(f))[0] in names]
    return files


def look_at(cam_obj, target):
    d = Vector(target) - cam_obj.location
    cam_obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
