#!/usr/bin/env python3
"""
part-assembler agent, powered by the OpenAI API.

Give it a directory of 3D part files (*.glb) plus an assembly manual (PDF),
and it autonomously assembles the model in headless Blender: it reads the
manual itself (vision), reverse-engineers hole positions from the meshes,
places parts, verifies by rendering and looking at the renders, and delivers
.blend / .glb / renders.

Usage:
    export OPENAI_API_KEY=sk-...
    # optional: export OPENAI_BASE_URL=https://...  (proxy/compatible endpoint)
    python3 part_assembler_agent.py /path/to/parts_dir \
        [--out /path/to/output_dir] [--model gpt-5.5] [--max-steps 150]

Requirements: a vision + tool-calling capable model (gpt-5.5 / gpt-5 / gpt-4.1 ...),
Blender reachable on the machine, pdftoppm (poppler-utils), pip install openai,
and ideally Pillow (to downscale images before sending).
"""

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import time

from openai import OpenAI

# ----------------------------------------------------------------------------
# system prompt: the assembly methodology
# ----------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a mechanical-assembly agent. Given a directory of 3D part files plus an
assembly manual, you reconstruct the fully assembled model in Blender (headless)
and deliver renders, a .blend file, and a .glb export. You work from the manual
and the mesh geometry alone.

# Environment
- Find Blender: try `which blender`, then `ls ~/Downloads/blender-*/blender`,
  then snap/flatpak. Run headless: `<blender> -b --factory-startup -P script.py`.
  Filter its noisy stdout with grep.
- Blender 5.x gotchas: the EEVEE engine enum is 'BLENDER_EEVEE' (there is no
  BLENDER_EEVEE_NEXT); glTF imports keep their own materials, so
  obj.data.materials.clear() before assigning yours; joining objects needs
  bpy.context.temp_override(...); `pdftoppm -png -r 300` rasterizes PDFs.
- You cannot see the Blender UI. Your eyes are the view_image tool: render,
  view the PNG, judge, iterate.
- Long jobs: write Python scripts with write_file, run them with bash.
- If the task message provides a Toolkit, ALWAYS use those ready-made tools instead
  of writing your own analysis/assembly code — your budget is limited.

# Method — work in phases; do not skip the verification renders.

## 1. Inventory the parts
Import every part in a loop (one headless run), record per part: object count,
triangle count, bounding-box min/max/dims. Detect unit mismatches: kits often
mix units (screws in millimeters, plates in meters — a part named screw_m3x16
should be ~19 units long in mm; a plate of ~0.1 units is meters). Normalize
everything to millimeters (scale mesh data, not object scale).

## 2. Read the manual yourself
Rasterize the PDF at 300 dpi, crop each step's region (plus any parts legend),
and view the crops. Extract: step order, which parts and screw sizes each step
uses, insertion directions (exploded-view axes), and part nicknames (e.g.
"split plate rear" ↔ which file). Re-crop and zoom whenever a detail matters.

## 3. Extract precise geometry from the meshes
Eyeballing renders is not enough for placement; extract coordinates:
- Hole detection: collect wall faces (|normal.z| < 0.4 for plate-like parts),
  union-find them into connected clusters via shared edges, then per cluster
  compute vertex centroid + radial min/avg/max. Small near-circular clusters
  are screw holes (M3 ≈ r1.5); larger ones are standoff/feature holes;
  elongated ones are slots. Record center (x, y, z-range) and radius per part.
- Orthographic top/front/side plus two perspective views per part; view them to
  understand 3D shape (steps, pockets, raised bosses, notches).
- Thickness profiles: histogram vertex z per region to find stepped thicknesses.
- Screw head ends: near each end of a screw's long axis, the max radial extent
  tells you which end is the head (M3 head ≈ r2.75, shaft ≈ r1.5).

## 4. Solve the assembly like a constraint puzzle
- Match hole patterns across parts: same radius + same relative positions ⇒
  those faces mate with aligned origins. Strongest alignment evidence.
- Screw-length arithmetic: thread length ≈ clamped stack (e.g. M3x22 = 2 mm
  plate + 3 mm leg + 17 mm into a 20 mm standoff). Use it to accept/reject
  stacking hypotheses; exact fits mean you found the right stack.
- Mirrored parts: one arm/bracket file may serve both sides — mirror with a
  negative-determinant matrix (scale x = -1) for the opposite hand.
- Pose from two features: land two known local features (hole + boss/arc) on
  two world targets; rotZ = atan2(world vec) − atan2(local vec).
- Keep a world frame (z=0 at a reference plate face); place everything with
  explicit matrix_world = T @ R @ S.
- Reject hypotheses that interpenetrate in z or leave a screw with nothing to
  thread into. If two hypotheses survive, prefer what the manual drawing shows.

## 5. Build the assembly script
One idempotent Python script: import each unique part once as a template
(normalize scale, clear materials), instantiate placements via linked mesh
data, assign simple Principled materials by part class, add lights + camera
helpers, render. Rerun the whole script after every change.

## 6. Verify by looking — then iterate
Render and view: top orthographic (whole model), hero 3/4, tight orthographic
closeups of every joint (top and front). Check: screw heads centered in holes;
mating hole patterns concentric; no interpenetration; left/right symmetry;
stance matches the manual's assembled drawing. Fix and re-render until right.
Never finish without having looked at the final renders.

## 7. Deliver
To the output directory: *.blend, *.glb (exclude helper ground/lights from the
export), renders (hero, top, front, joint closeup) and an exploded-view render
(offset each layer along z; keep the ground plane below the lowest part). Then
report: what the kit is, how each manual step maps to your placements, the
dimensional evidence (hole matches, screw-length checks), and any approximation
made where the manual was ambiguous — state those honestly.

# Principles
- Mesh-derived coordinates beat eyeballed positions; manual drawings beat
  guesses; screw-length arithmetic is ground truth for stacking order.
- Cluster centroids carry ~0.5 mm noise — trust patterns (pairs, symmetry) and
  symmetrize coordinates when placing.
- Micro-mechanics you cannot fully resolve may be approximated for visual
  correctness — but say so in the report.
- Scratch files go to the scratch directory; only deliverables to the output dir.
- When done, call the finish tool with your report, in the same language as the task.
"""

TOOLKIT_DOC = """
# Toolkit — READY-MADE analysis/assembly tools. USE THESE. Do NOT write your own
# Blender or analysis code unless a toolkit tool truly cannot do the job.
Toolkit dir: {tk}

1. Inventory (dims mm, unit auto-normalization, tris):
   bash {tk}/bl.sh {tk}/inventory.py <parts_dir> <out.json>
2. Hole extraction — least-squares circle fit, classified hole vs boss/outline vs slot,
   center/radius/fit-error/z-range per cluster:
   bash {tk}/bl.sh {tk}/holes.py <parts_dir> <out.json> [part_name ...]
3. Per-part views (ortho top/front/side + 2 persp PNGs):
   bash {tk}/bl.sh {tk}/render_parts.py <parts_dir> <out_dir> [part_name ...]
   CAD-style line drawings with a labeled mm grid (read coordinates off the image):
   bash {tk}/bl.sh {tk}/edges_extract.py <parts_dir> <edges.json> [part ...]
   python3 {tk}/edges_draw.py <edges.json> <out_dir> [part ...]
   Screw/standoff profiler (which end is the head, head/shaft radii, thread length):
   bash {tk}/bl.sh {tk}/screw_profile.py <parts_dir> [part ...]
   Contact sheet — tile many PNGs into ONE labeled image (cheaper to view):
   python3 {tk}/contact_sheet.py <out.png> <img1> <img2> ...
4. Manual reading: pdftoppm -png -r 300 manual.pdf <prefix>   then zoom with:
   python3 {tk}/crop.py <in.png> <out.png> --box x0 y0 x1 y1 --scale 2 [--invert --autocontrast]
5. ASSEMBLE (the one tool that builds everything): write a layout JSON, then
   bash {tk}/bl.sh {tk}/assemble.py <layout.json>
   It imports parts (auto mm-normalization), places them, renders hero/top/front/low/center
   (+ optional extra_views and exploded views), saves <name>.blend and <name>.glb to out_dir.
   Layout JSON schema (all lengths mm, angles degrees):
   {{
     "parts_dir": "...", "out_dir": "...", "name": "assembly",
     "placements": [
       {{"part":"<glb basename>", "label":"unique_name", "material":"carbon|plastic|alu|steel",
         "color":[r,g,b],                      // optional override 0..1
         "loc":[x,y,z],                        // OR use pivot pair below
         "rot_z":deg, "rot_x":deg, "rot_y":deg, "mirror_x":true|false,
         "pivot_local":[x,y,z], "pivot_world":[x,y,z]  // land local point on world point
       }}, ...
     ],
     "explode": {{"label_prefix": dz, ...}},     // optional exploded-view offsets
     "extra_views": [{{"name":"joint","loc":[x,y,z],"target":[x,y,z],"ortho_scale":mm}}],
     "check_holes": "/abs/path/holes.json"       // optional: prints a numeric hole-alignment
   }}                                            // report (coaxial stacks + misalignment flags)
   Matrix order: T @ RZ @ RY @ RX @ mirror. Same part may be placed many times.
   Screws: place by computing head position from hole coords (screw glbs are modeled
   around their own origin; check inventory bbox + a persp render to see head end).

Your workflow: run tools 1-4 to gather evidence -> decide placements -> write the
layout JSON -> run assemble -> view the renders -> fix numbers in the JSON -> rerun
assemble -> repeat until correct -> finish. All heavy code already exists; your job
is reading evidence and choosing coordinates.
"""

# ----------------------------------------------------------------------------
# tools
# ----------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command on the host and return stdout+stderr (truncated). Use for blender, pdftoppm, ls, grep, python3, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run with bash -c"},
                    "timeout_s": {"type": "integer", "description": "Timeout in seconds (default 300)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write (overwrite) a UTF-8 text file, creating parent directories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file (truncated to 40 kB). Not for images/PDFs.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_image",
            "description": "Look at a PNG/JPEG image (e.g. a Blender render or a manual page crop). The image is attached to the conversation so you can visually inspect it.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Finish the task and deliver the final report to the user.",
            "parameters": {
                "type": "object",
                "properties": {"report": {"type": "string", "description": "Final report in the task's language"}},
                "required": ["report"],
            },
        },
    },
]

MAX_TOOL_OUTPUT = 6000
MAX_IMAGES_KEPT = 8  # older image payloads are evicted to keep context small


def run_bash(command: str, timeout_s: int = 300) -> str:
    try:
        p = subprocess.run(
            ["bash", "-c", command],
            capture_output=True, text=True, timeout=timeout_s,
        )
        out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr.strip() else "")
        out = out.strip() or "(no output)"
        if len(out) > MAX_TOOL_OUTPUT:
            out = out[: MAX_TOOL_OUTPUT // 2] + "\n...[truncated]...\n" + out[-MAX_TOOL_OUTPUT // 2:]
        return f"exit={p.returncode}\n{out}"
    except subprocess.TimeoutExpired:
        return f"error: command timed out after {timeout_s}s"


def write_file(path: str, content: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"wrote {len(content)} bytes to {path}"


def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read(40000)
        more = f.read(1) if False else ""
        return data + ("\n...[truncated]" if len(data) == 40000 else "")
    except Exception as e:
        return f"error: {e}"


def image_data_url(path: str, max_px: int = 1400) -> tuple[str, str]:
    """Return (data_url, note). Downscale with Pillow when available."""
    raw = open(path, "rb").read()
    note = ""
    try:
        from PIL import Image  # type: ignore
        im = Image.open(io.BytesIO(raw))
        w, h = im.size
        if max(w, h) > max_px:
            im.thumbnail((max_px, max_px))
            note = f" (downscaled from {w}x{h} to {im.size[0]}x{im.size[1]})"
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=88)
        raw = buf.getvalue()
        mime = "image/jpeg"
    except Exception:
        mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        if len(raw) > 6_000_000:
            raise RuntimeError("image too large and Pillow unavailable to downscale")
    b64 = base64.b64encode(raw).decode()
    return f"data:{mime};base64,{b64}", note


def evict_old_images(messages: list) -> None:
    """Keep only the most recent MAX_IMAGES_KEPT image payloads."""
    seen = 0
    for msg in reversed(messages):
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            for part in msg["content"]:
                if part.get("type") == "image_url":
                    seen += 1
                    if seen > MAX_IMAGES_KEPT:
                        part["type"] = "text"
                        part.pop("image_url", None)
                        part["text"] = "[image evicted to save context — call view_image again if needed]"


# ----------------------------------------------------------------------------
# responses-API loop (required for *-pro models; also works for gpt-5.x)
# ----------------------------------------------------------------------------

def exec_tool(name: str, fargs: dict, step: int):
    """Execute one tool call. Returns (result_text, image_payload_or_None, finished_report_or_None)."""
    print(f"[step {step}] tool: {name} {str(fargs)[:200]}")
    if name == "bash":
        return run_bash(fargs.get("command", ""), int(fargs.get("timeout_s") or 300)), None, None
    if name == "write_file":
        return write_file(fargs["path"], fargs["content"]), None, None
    if name == "read_file":
        return read_file(fargs["path"]), None, None
    if name == "view_image":
        try:
            url, note = image_data_url(fargs["path"])
            return f"image attached below{note}", (fargs["path"], url), None
        except Exception as e:
            return f"error: {e}", None, None
    if name == "finish":
        return "", None, fargs.get("report", "(empty report)")
    return f"error: unknown tool {name}", None, None


def responses_loop(client: OpenAI, model: str, task: str, max_steps: int) -> None:
    tools_r = [
        {
            "type": "function",
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "parameters": t["function"]["parameters"],
        }
        for t in TOOLS
    ]
    prev_id = None
    next_input: list = [{"role": "user", "content": [{"type": "input_text", "text": task}]}]

    for step in range(1, max_steps + 1):
        for attempt in range(5):
            try:
                resp = client.responses.create(
                    model=model,
                    instructions=SYSTEM_PROMPT,
                    input=next_input,
                    tools=tools_r,
                    tool_choice="auto",
                    previous_response_id=prev_id,
                )
                break
            except Exception as e:
                wait = 2 ** attempt * 10
                print(f"[api error: {e}; retry in {wait}s]", file=sys.stderr)
                time.sleep(wait)
        else:
            sys.exit("API kept failing; aborting")

        prev_id = resp.id
        next_input = []
        had_call = False

        for item in resp.output:
            itype = getattr(item, "type", None)
            if itype == "message":
                for part in getattr(item, "content", []) or []:
                    if getattr(part, "type", "") == "output_text" and part.text:
                        print(f"\n[step {step}] {part.text[:600]}")
            elif itype == "function_call":
                had_call = True
                try:
                    fargs = json.loads(item.arguments or "{}")
                except json.JSONDecodeError:
                    fargs = {}
                result, image, report = exec_tool(item.name, fargs, step)
                if report is not None:
                    print("\n" + "=" * 70 + "\nFINAL REPORT\n" + "=" * 70)
                    print(report)
                    return
                next_input.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": result,
                })
                if image:
                    path, url = image
                    next_input.append({
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": f"[image] {path}"},
                            {"type": "input_image", "image_url": url, "detail": "high"},
                        ],
                    })

        if not had_call:
            next_input = [{"role": "user", "content": [{"type": "input_text",
                          "text": "Continue. When fully done, call the finish tool."}]}]

    sys.exit(f"reached max steps ({max_steps}) without finish; increase --max-steps")


# ----------------------------------------------------------------------------
# agent loop
# ----------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("parts_dir")
    ap.add_argument("--out", default=None, help="output dir (default <parts_dir>/assembled_openai)")
    ap.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-5.5"))
    ap.add_argument("--max-steps", type=int, default=150)
    ap.add_argument("--scratch", default="/tmp/part_assembler_scratch")
    ap.add_argument("--api", choices=["auto", "chat", "responses"], default="auto",
                    help="pro models require the Responses API (auto: responses if model contains 'pro')")
    ap.add_argument("--toolkit", default=None,
                    help="toolkit dir (e.g. .../toolkit_fable or .../toolkit_pro); its TOOLKIT.md is injected into the task")
    args = ap.parse_args()

    parts_dir = os.path.abspath(args.parts_dir)
    out_dir = os.path.abspath(args.out or os.path.join(parts_dir, "assembled_openai"))
    os.makedirs(args.scratch, exist_ok=True)

    client = OpenAI(timeout=3600)  # OPENAI_API_KEY / OPENAI_BASE_URL from env; pro calls are slow

    toolkit_dir = args.toolkit or os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit_fable")
    tk_md = os.path.join(toolkit_dir, "TOOLKIT.md")
    if os.path.exists(tk_md):
        tk_doc = open(tk_md).read().replace("<TK>", toolkit_dir)
    else:
        tk_doc = TOOLKIT_DOC.format(tk=toolkit_dir)
    task = (
        f"Task: assemble the parts (*.glb) in {parts_dir} into the complete model, following the "
        f"assembly manual (PDF) found in that directory. Output dir: {out_dir} (.blend, .glb, renders, "
        f"exploded view). Scratch dir: {args.scratch}. If the parts directory contains someone else's "
        f"output folders (e.g. assembled*/), ignore them completely - do not read or reference them. "
        f"When done, call finish and report: what the kit is, how each step maps to the manual, "
        f"the dimensional evidence, and every approximation you made.\n\n"
        + tk_doc
    )

    use_responses = args.api == "responses" or (args.api == "auto" and "pro" in args.model)
    if use_responses:
        responses_loop(client, args.model, task, args.max_steps)
        return

    messages: list = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for step in range(1, args.max_steps + 1):
        for attempt in range(5):
            try:
                resp = client.chat.completions.create(
                    model=args.model, messages=messages, tools=TOOLS, tool_choice="auto",
                )
                break
            except Exception as e:
                wait = 2 ** attempt * 5
                print(f"[api error: {e}; retry in {wait}s]", file=sys.stderr)
                time.sleep(wait)
        else:
            sys.exit("API kept failing; aborting")

        msg = resp.choices[0].message
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            **({"tool_calls": [tc.model_dump() for tc in msg.tool_calls]} if msg.tool_calls else {}),
        })
        if msg.content:
            print(f"\n[step {step}] {msg.content[:500]}")

        if not msg.tool_calls:
            # nudge the model to keep working or finish explicitly
            messages.append({"role": "user", "content": "Continue. When fully done, call the finish tool."})
            continue

        pending_images = []
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                fargs = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                fargs = {}
            print(f"[step {step}] tool: {name} {str(fargs)[:200]}")

            if name == "bash":
                result = run_bash(fargs.get("command", ""), int(fargs.get("timeout_s") or 300))
            elif name == "write_file":
                result = write_file(fargs["path"], fargs["content"])
            elif name == "read_file":
                result = read_file(fargs["path"])
            elif name == "view_image":
                try:
                    url, note = image_data_url(fargs["path"])
                    pending_images.append((fargs["path"], url))
                    result = f"image attached below{note}"
                except Exception as e:
                    result = f"error: {e}"
            elif name == "finish":
                print("\n" + "=" * 70 + "\nFINAL REPORT\n" + "=" * 70)
                print(fargs.get("report", ""))
                return
            else:
                result = f"error: unknown tool {name}"

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        for path, url in pending_images:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": f"[image] {path}"},
                    {"type": "image_url", "image_url": {"url": url, "detail": "high"}},
                ],
            })
        evict_old_images(messages)

    sys.exit(f"reached max steps ({args.max_steps}) without finish; increase --max-steps")


if __name__ == "__main__":
    main()
