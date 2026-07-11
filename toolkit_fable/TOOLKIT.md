# Toolkit (Fable) — READY-MADE tools. USE THESE; do NOT write your own analysis code.

All Blender tools run via: `bash <TK>/bl.sh <TK>/<tool>.py <args...>` where <TK> is this directory.

1. Inventory — dims (mm), unit auto-normalization, tris:
   `bash <TK>/bl.sh <TK>/inventory.py <parts_dir> <out.json>`
2. Holes — wall-cluster extraction; circular holes with center/radius/z-range:
   `bash <TK>/bl.sh <TK>/holes.py <parts_dir> <out.json> [part ...]`
3. Part views — ortho top/front/side + 2 persp PNGs per part:
   `bash <TK>/bl.sh <TK>/render_parts.py <parts_dir> <out_dir> [part ...]`
4. Manual: `pdftoppm -png -r 300 manual.pdf <prefix>`, zoom/enhance:
   `python3 <TK>/crop.py <in.png> <out.png> --box x0 y0 x1 y1 --scale 2 [--invert --autocontrast]`
5. ASSEMBLE — builds everything from a layout JSON; renders hero/top/front/low/center
   (+ extra_views + exploded), saves <name>.blend/.glb; optional numeric hole-alignment report:
   `bash <TK>/bl.sh <TK>/assemble.py <layout.json>`

Layout JSON (lengths mm, angles deg):
```json
{
  "parts_dir": "...", "out_dir": "...", "name": "assembly",
  "placements": [
    {"part":"<glb basename>", "label":"unique", "material":"carbon|plastic|alu|steel",
     "color":[r,g,b],
     "loc":[x,y,z],
     "rot_z":0, "rot_x":0, "rot_y":0, "mirror_x":false,
     "pivot_local":[x,y,z], "pivot_world":[x,y,z]}
  ],
  "explode": {"label_prefix": dz},
  "extra_views": [{"name":"joint","loc":[x,y,z],"target":[x,y,z],"ortho_scale":70}],
  "check_holes": "/abs/path/holes.json"
}
```
Matrix order: T @ RZ @ RY @ RX @ mirror. `pivot_local`/`pivot_world` land a local feature
(e.g. a hole) exactly on a world point — use this instead of hand-computing loc for rotated parts.
Same part may be placed many times. `check_holes` prints coaxial hole stacks and flags
misalignment > 0.5 mm — use it to verify numerically before trusting renders.

Workflow: inventory + holes + views -> read manual -> decide placements -> layout JSON ->
assemble -> view renders + alignment report -> fix numbers -> repeat -> finish.

## Constraint tools (new)

6. Pose solver — enumerate & score candidate poses of part A onto part B (or the assembled
   world) from hole-pattern correspondences. USE THIS for every rotated/symmetric part:
   `python3 <TK>/mate_solve.py <holes.json> <partA> <partB>` or
   `python3 <TK>/mate_solve.py <holes.json> <partA> <out_dir>/world_holes.json`
   (options: --rmax 6 to include bosses, --kinds hole,boss/outline, --top 5)
   Prints top poses: mirror_x / rot_z / loc / inliers / rms + matched holes. Near-tie warning
   means the pattern is too symmetric — add features or check the manual.
7. Cross-sections — see INTERNAL structure (slot floors, pockets, tunnels) instead of
   guessing from silhouettes:
   `bash <TK>/bl.sh <TK>/section_extract.py <parts_dir> <sec.json> <part> <x|y|z> <value> [...]`
   `python3 <TK>/section_draw.py <sec.json> <out_dir>`   (red profile on mm grid)
8. Axis-agnostic cylinder detector — holes/bosses along ANY axis (horizontal holes the
   Z-based holes.py misses): `bash <TK>/bl.sh <TK>/cylinders.py <parts_dir> [part ...]`
   Reports kind/r/axis/center/length per cylindrical feature.

## Placement discipline (MANDATORY)

- Every placement must cite evidence: a pivot_local/pivot_world pair, or a mate_solve
  result. Hardcoding an angle because "it looks like the picture" is FORBIDDEN.
- Before placing a part, view its renders and the manual figure and state which end/face
  is which (e.g. motor end vs root) in one sentence.
- Symmetric-looking parts: run mate_solve and compare the top candidates — do not take the
  first plausible pose; consider mirror candidates (mirror_x) explicitly.
- After every assemble, read the HOLE ALIGNMENT REPORT; fix or explicitly justify every
  MISALIGNED line. Place later parts against out_dir/world_holes.json with mate_solve.
- Cross-check screw length vs the stack it clamps; a mismatch means the stacking
  hypothesis is wrong — investigate with sections, do not paper over it.

## HARD GATES in assemble.py (it refuses to run otherwise)

- Every placement with any rotation or mirror_x MUST carry either
  `"pivot_local"+"pivot_world"` (preferred — lands a real feature on a real hole) or an
  `"evidence"` string citing the mate_solve result / manual feature that fixes the pose
  (e.g. `"evidence":"mate_solve #1 rms 0.30, motor end outward per manual step 2"`).
- The layout MUST include `"manual_ref": "<path>"` — a cropped image of the manual's
  assembled/step view. assemble.py then writes `compare_manual.png` (manual | hero | top).
  You MUST view compare_manual.png and explicitly verify, in your reasoning: (a) motor
  ends point OUTWARD, (b) each part's orientation matches the manual figure, (c) stack
  order matches. If anything differs, fix the layout and re-run — do not finish with a
  mismatch.
