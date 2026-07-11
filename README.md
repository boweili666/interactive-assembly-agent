# part-assembler

An LLM agent that assembles 3D part kits (`.glb`) into a complete model by **reading the
assembly manual itself** — powered by the OpenAI API and headless Blender.

Give it a folder of parts and a PDF manual. It inventories the parts, reads the manual
(vision), reverse-engineers exact hole positions from the meshes, solves part placements
as a constraint problem, verifies by rendering and *looking* at the renders, and delivers
`.blend` / `.glb` / renders / an exploded view.

Two ways to run it:

- **CLI** — fully autonomous, one command.
- **Web workbench** — human-in-the-loop: a chat panel drives the agent while a live 3D
  viewer shows every assembly update in real time; the agent pauses at checkpoints so you
  can inspect the model and steer it ("the arms are backwards — wide motor end goes outward").

## How it works

```
part_assembler_agent.py   agent loop (Chat Completions; Responses API for *-pro models)
toolkit_pro/              ready-made analysis & assembly tools the agent calls
toolkit_fable/            alternative toolkit (simpler hole analysis) for A/B testing
webui/                    human-in-the-loop web workbench (chat + live 3D)
viewer/                   standalone live glb viewer
```

The agent does not write Blender code. Each toolkit ships small CLI tools it composes:

| Tool | Purpose |
|---|---|
| `inventory.py` | part dims (mm), automatic unit normalization (mixed mm/m kits), triangle counts |
| `holes.py` | hole extraction: least-squares circle fit, hole vs boss vs slot classification, center/radius/z-range |
| `cylinders.py` | axis-agnostic cylindrical feature detector (finds horizontal holes a Z-only pass misses) |
| `screw_profile.py` | which end of a screw is the head; head/shaft radii; thread length (pro toolkit) |
| `render_parts.py` | orthographic + perspective views per part |
| `edges_extract.py` + `edges_draw.py` | CAD-style line drawings with a labeled mm grid (pro toolkit) |
| `section_extract.py` + `section_draw.py` | exact cross-sections — see slot floors and pockets instead of guessing |
| `mate_solve.py` | pose solver: enumerates candidate poses of part A onto part B from hole-pattern correspondences, ranked by inlier count + RMS |
| `assemble.py` | builds the assembly from a declarative layout JSON; renders standard + exploded views; exports `.blend`/`.glb`; numeric hole-alignment report |
| `crop.py`, `contact_sheet.py`, `compare.py` | manual zooming/enhancement, image tiling, manual-vs-render comparison |

`assemble.py` enforces two **hard gates**: every rotated/mirrored placement must cite
evidence (a `pivot_local`/`pivot_world` pair or a `mate_solve` result), and the layout
must reference the manual figure so a `compare_manual.png` side-by-side is produced for
verification. See `toolkit_pro/TOOLKIT.md` for the full tool reference and the layout
JSON schema.

## Requirements

- **Python 3.10+** with `pip install openai pillow`
- **Blender 3.6+** (tested on 5.0) — on `PATH`, or in `~/Downloads/blender-*/`
- **poppler-utils** (`pdftoppm`) for manual rasterization: `sudo apt install poppler-utils`
- An **OpenAI API key** and a vision + tool-calling model
  (default `gpt-5.5`; `*-pro` models are used automatically via the Responses API)

## Setup

```bash
git clone git@github.com:boweili666/part-assembler.git
cd part-assembler
pip install openai pillow
export OPENAI_API_KEY=sk-...
# optional, for proxies / compatible endpoints:
# export OPENAI_BASE_URL=https://your-endpoint/v1
```

## Usage

### Web workbench (recommended)

```bash
python3 webui/app.py            # default port 8770
# open http://localhost:8770
```

1. Pick the parts folder (or individual part files — a checkbox list lets you include
   only some parts) and the manual PDF; they are uploaded into a per-session workspace.
2. Choose toolkit (`pro` is the default) and model, then **Start assembly**.
3. Watch the agent work in the chat panel; the right pane is a live 3D view that
   hot-reloads on every assembly update.
4. At every checkpoint the agent pauses: inspect the 3D model, then type feedback
   (any language) or press **Continue**. Press **Accept & finish** to end the session.
5. Deliverables land in `webui/workspaces/<session>/assembled_webui/`, including
   numbered `compare_ckpt_NNN.png` snapshots of every checkpoint.

### CLI (autonomous)

```bash
python3 part_assembler_agent.py /path/to/parts_dir \
    --out /path/to/output_dir \
    --model gpt-5.5 \
    --toolkit toolkit_pro \
    --max-steps 60
```

The parts dir must contain the `.glb` files and the manual PDF. Add `--api responses`
to force the Responses API (automatic for models containing "pro").

### Standalone live viewer

```bash
python3 viewer/serve.py /path/to/some.glb 8765   # open http://localhost:8765
```

## Notes

- **Cost**: a full assembly run with `gpt-5.5` is typically 25–60 agent steps. The
  toolkit exists precisely to keep costs down — the model reads tool output and edits a
  layout JSON instead of writing Blender code.
- **Security**: the web server binds `0.0.0.0` with no authentication and can execute
  the agent's shell commands on your machine. Run it on a trusted machine/network only.
- **Known limitation**: geometric tools eliminate most placement errors, but semantic
  mistakes (e.g. which end of an arm is the motor mount) can survive fully autonomous
  runs — that is exactly what the human-in-the-loop workbench is for.

## License

MIT
