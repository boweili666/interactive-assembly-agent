#!/usr/bin/env python3
"""Web UI for the part-assembler agent: chat (human-in-the-loop) + live 3D view.

Usage:
    export OPENAI_API_KEY=sk-...
    python3 app.py [port=8770]
Then open http://localhost:8770 , fill in parts dir + manual path, start, and chat.
"""
import http.server, json, os, sys, threading, queue, time, glob as _glob


def find_latest_glb():
    """Locate the live glb even if the agent chose a different out_dir."""
    od = STATE.get("out_dir")
    if not od:
        return None
    p = os.path.join(od, "latest.glb")
    if os.path.exists(p):
        return p
    ws = os.path.dirname(od)
    cands = _glob.glob(ws + "/**/latest.glb", recursive=True) + \
        _glob.glob(ws + "/**/*.glb", recursive=True)
    cands = [c for c in cands if "/assembled" in c or c.endswith("latest.glb")]
    return max(cands, key=os.path.getmtime) if cands else None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from part_assembler_agent import (SYSTEM_PROMPT, TOOLS, run_bash, write_file,
                                  read_file, image_data_url, evict_old_images)
from openai import OpenAI

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8770

STATE = {"entries": [], "status": "idle", "out_dir": None, "detail": ""}
LOCK = threading.Lock()
USERQ = queue.Queue()
WORKER = None


def post(role, text, image=None):
    with LOCK:
        STATE["entries"].append({"i": len(STATE["entries"]), "role": role,
                                 "text": text, "image": image, "t": time.strftime("%H:%M:%S")})


def set_status(s, detail=""):
    with LOCK:
        STATE["status"] = s
        STATE["detail"] = detail


def wait_user(prompt):
    """Block until the user sends something. Returns '' for accept/continue."""
    set_status("awaiting", prompt)
    post("status", prompt)
    txt = USERQ.get()
    set_status("running")
    return "" if txt in ("__ACCEPT__", "__CONTINUE__") else txt


def drain_user(messages):
    try:
        while True:
            txt = USERQ.get_nowait()
            if txt not in ("__ACCEPT__", "__CONTINUE__"):
                messages.append({"role": "user", "content": "[user feedback] " + txt})
    except queue.Empty:
        pass


def agent_thread(cfg):
    try:
        client = OpenAI(timeout=3600)
        tk = cfg["toolkit"]
        tk_doc = open(os.path.join(tk, "TOOLKIT.md")).read().replace("<TK>", tk)
        out_dir = cfg["out_dir"]
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(cfg["scratch"], exist_ok=True)
        task = (
            f"Task: assemble the parts (*.glb) in {cfg['parts_dir']} into the complete model. "
            f"The assembly manual is at {cfg['manual']}. Output dir: {out_dir}. Scratch dir: {cfg['scratch']}. "
            f"This is a human-in-the-loop session: after every assemble and whenever you call finish, "
            f"the user inspects the live 3D result and may send feedback; messages prefixed "
            f"[user feedback] must be addressed with priority. Call finish with your final report when done.\n\n" + tk_doc)
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": task}]
        set_status("running")
        for step in range(1, int(cfg.get("max_steps", 120)) + 1):
            drain_user(messages)
            resp = None
            for attempt in range(5):
                try:
                    resp = client.chat.completions.create(
                        model=cfg["model"], messages=messages, tools=TOOLS, tool_choice="auto")
                    break
                except Exception as e:
                    post("status", f"API error (retry {attempt+1}/5): {str(e)[:200]}")
                    time.sleep(2 ** attempt * 5)
            if resp is None:
                set_status("error", "API kept failing")
                return
            msg = resp.choices[0].message
            messages.append({"role": "assistant", "content": msg.content or "",
                             **({"tool_calls": [tc.model_dump() for tc in msg.tool_calls]} if msg.tool_calls else {})})
            if msg.content:
                post("assistant", msg.content)
            if not msg.tool_calls:
                messages.append({"role": "user", "content": "Continue. When fully done, call the finish tool."})
                continue

            pending_images, did_assemble = [], False
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    fargs = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    fargs = {}
                if name == "bash":
                    cmd = fargs.get("command", "")
                    post("tool", f"$ {cmd[:300]}")
                    result = run_bash(cmd, int(fargs.get("timeout_s") or 300))
                    if "assemble.py" in cmd and "GATE FAILED" not in result and "exit=0" in result.split("\n")[0]:
                        did_assemble = True
                elif name == "write_file":
                    result = write_file(fargs["path"], fargs["content"])
                    post("tool", f"write {fargs['path'].split('/')[-1]} ({len(fargs['content'])}B)")
                elif name == "read_file":
                    result = read_file(fargs["path"])
                    post("tool", f"read {fargs['path'].split('/')[-1]}")
                elif name == "view_image":
                    try:
                        url, note = image_data_url(fargs["path"])
                        pending_images.append((fargs["path"], url))
                        result = f"image attached below{note}"
                        rel = os.path.relpath(fargs["path"], out_dir)
                        post("tool", f"viewed image: {os.path.basename(fargs['path'])}",
                             image=("/file?p=" + rel) if not rel.startswith("..") else None)
                    except Exception as e:
                        result = f"error: {e}"
                elif name == "finish":
                    report = fargs.get("report", "")
                    post("assistant", "[FINAL REPORT]\n" + report)
                    fb = wait_user("Agent proposes to finish. Press Accept to end, or send feedback to continue.")
                    if not fb:
                        set_status("done", "accepted")
                        return
                    result = "User rejected finish. Feedback: " + fb + " -- address it, then call finish again."
                else:
                    result = f"error: unknown tool {name}"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

            for path, url in pending_images:
                messages.append({"role": "user", "content": [
                    {"type": "text", "text": f"[image] {path}"},
                    {"type": "image_url", "image_url": {"url": url, "detail": "high"}}]})
            evict_old_images(messages)

            if did_assemble:
                cmp_src = os.path.join(out_dir, "compare_manual.png")
                if os.path.exists(cmp_src):
                    # archive per-checkpoint so history survives later overwrites
                    cfg["ckpt"] = cfg.get("ckpt", 0) + 1
                    arch = f"compare_ckpt_{cfg['ckpt']:03d}.png"
                    import shutil
                    shutil.copyfile(cmp_src, os.path.join(out_dir, arch))
                    post("status", "Assembly updated (the 3D view refreshes automatically)", image="/file?p=" + arch)
                fb = wait_user("Inspect the 3D result. Send feedback to request changes, or press Continue.")
                if fb:
                    messages.append({"role": "user", "content": "[user feedback] " + fb})
        set_status("error", "step limit reached")
    except Exception as e:
        set_status("error", str(e)[:300])
        post("status", "worker crashed: " + str(e)[:300])


class H(http.server.BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path.startswith("/events"):
            import urllib.parse
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            since = int(q.get("since", ["0"])[0])
            with LOCK:
                self._json({"entries": STATE["entries"][since:], "status": STATE["status"],
                            "detail": STATE["detail"]})
        elif self.path.startswith("/model.glb"):
            p = find_latest_glb()
            if not p:
                self.send_response(404); self.end_headers(); return
            data = open(p, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(data)
        elif self.path.startswith("/mtime"):
            p = find_latest_glb()
            m = os.path.getmtime(p) if p else 0
            self._json({"mtime": m})
        elif self.path.startswith("/file"):
            import urllib.parse
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            rel = q.get("p", [""])[0]
            p = os.path.normpath(os.path.join(STATE["out_dir"] or "", rel))
            if not STATE["out_dir"] or not p.startswith(os.path.abspath(STATE["out_dir"])) or not os.path.exists(p):
                self.send_response(404); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(open(p, "rb").read())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(open(os.path.join(HERE, "index.html"), "rb").read())

    def do_POST(self):
        global WORKER
        if self.path == "/start":
            if WORKER and WORKER.is_alive():
                self._json({"error": "a job is already running"}, 400); return
            b = self._body()
            parts_dir = os.path.abspath(os.path.expanduser(b.get("parts_dir", "")))
            manual = os.path.abspath(os.path.expanduser(b.get("manual", "")))
            if not os.path.isdir(parts_dir):
                self._json({"error": f"parts dir not found: {parts_dir}"}, 400); return
            if not os.path.isfile(manual):
                self._json({"error": f"manual not found: {manual}"}, 400); return
            if b.get("api_key"):
                os.environ["OPENAI_API_KEY"] = b["api_key"]
            if not os.environ.get("OPENAI_API_KEY"):
                self._json({"error": "missing OPENAI_API_KEY (export it before starting the server, or fill the form field)"}, 400); return
            tkname = b.get("toolkit_name") or "pro"
            tk = os.path.join(os.path.dirname(HERE), "toolkit_" + tkname)
            if not os.path.isdir(tk):
                self._json({"error": f"toolkit not found: {tk}"}, 400); return
            cfg = {
                "parts_dir": parts_dir, "manual": manual,
                "toolkit": tk,
                "model": b.get("model") or "gpt-5.5",
                "out_dir": os.path.join(parts_dir, "assembled_webui"),
                "scratch": os.path.join(parts_dir, ".webui_scratch"),
                "max_steps": 120,
            }
            with LOCK:
                STATE["entries"].clear()
                STATE["out_dir"] = cfg["out_dir"]
            post("status", f"Session started: {parts_dir} | model {cfg['model']} | toolkit {os.path.basename(tk)}")
            WORKER = threading.Thread(target=agent_thread, args=(cfg,), daemon=True)
            WORKER.start()
            self._json({"ok": True})
        elif self.path == "/upload":
            import base64
            b = self._body()
            ws = os.path.join(HERE, "workspaces", time.strftime("%m%d_%H%M%S"))
            os.makedirs(ws, exist_ok=True)
            n_parts = 0
            for f in b.get("files", []):
                fn = os.path.basename(f.get("name", ""))
                if not fn.lower().endswith((".glb", ".gltf", ".stl", ".obj")):
                    continue
                with open(os.path.join(ws, fn), "wb") as fh:
                    fh.write(base64.b64decode(f["b64"]))
                n_parts += 1
            manual = None
            if b.get("manual"):
                fn = os.path.basename(b["manual"]["name"])
                manual = os.path.join(ws, fn)
                with open(manual, "wb") as fh:
                    fh.write(base64.b64decode(b["manual"]["b64"]))
            if n_parts == 0:
                self._json({"error": "no 3D part files (.glb/.gltf/.stl/.obj) in the selection"}, 400); return
            self._json({"parts_dir": ws, "manual": manual, "count": n_parts})
        elif self.path == "/say":
            b = self._body()
            txt = (b.get("text") or "").strip()
            if txt:
                if txt not in ("__ACCEPT__", "__CONTINUE__"):
                    post("user", txt)
                USERQ.put(txt)
            self._json({"ok": True})
        else:
            self._json({"error": "unknown"}, 404)

    def log_message(self, *a):
        pass


print(f"open  http://localhost:{PORT}")
http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
