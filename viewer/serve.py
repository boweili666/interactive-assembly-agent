#!/usr/bin/env python3
"""Live 3D viewer for the assembly: serves a glb and hot-reloads the browser
whenever the file changes on disk.
Usage: python3 serve.py <path/to/model.glb> [port=8765]
Then open http://localhost:8765
"""
import http.server, os, sys, json

GLB = os.path.abspath(sys.argv[1])
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
DIR = os.path.dirname(os.path.abspath(__file__))


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/model.glb"):
            if not os.path.exists(GLB):
                self.send_response(404); self.end_headers(); return
            data = open(GLB, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        elif self.path.startswith("/mtime"):
            m = os.path.getmtime(GLB) if os.path.exists(GLB) else 0
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"mtime": m}).encode())
        else:
            data = open(os.path.join(DIR, "index.html"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(data)

    def log_message(self, *a):
        pass


print(f"watching {GLB}")
print(f"open   http://localhost:{PORT}")
http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
