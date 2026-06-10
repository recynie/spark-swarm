from __future__ import annotations

import sys
from pathlib import Path
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer

import requests

DEMO_DIR = Path(__file__).resolve().parent
STATIC_DIR = DEMO_DIR / "static"
UI_PORT = 3000

# Override these via CLI args or edit here
MASTER_HOST = "192.168.5.17"
MASTER_PORT = 8000


class UIHandler(SimpleHTTPRequestHandler):
    static_dir = str(STATIC_DIR)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=self.static_dir, **kwargs)

    def _proxy(self, method: str) -> None:
        url = f"http://{MASTER_HOST}:{MASTER_PORT}{self.path}"
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else None

        headers = {}
        for key in ("content-type", "accept", "authorization"):
            if key in self.headers:
                headers[key] = self.headers[key]

        try:
            resp = requests.request(method, url, headers=headers, data=body, timeout=30)
        except requests.RequestException:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"detail":"Master not available"}')
            return

        self.send_response(resp.status_code)
        for k, v in resp.headers.items():
            low = k.lower()
            if low in ("transfer-encoding", "content-encoding", "content-length", "connection"):
                continue
            self.send_header(k, v)
        content = resp.content
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy("POST")
        else:
            super().do_POST()

    def do_PUT(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy("PUT")
        else:
            super().do_PUT()

    def do_DELETE(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy("DELETE")
        else:
            super().do_DELETE()

    def log_message(self, format, *args):
        first = str(args[0]) if args else ""
        if "/api/" in first:
            sys.stdout.write(f"  [proxy] {first}\n")


def main() -> int:
    global MASTER_HOST, MASTER_PORT

    if len(sys.argv) > 1:
        MASTER_HOST = sys.argv[1]
    if len(sys.argv) > 2:
        MASTER_PORT = int(sys.argv[2])

    ui_url = f"http://localhost:{UI_PORT}"
    print("=" * 56)
    print("  Spark-Swarm Dashboard (UI only)")
    print("=" * 56)
    print(f"  Master:    http://{MASTER_HOST}:{MASTER_PORT}")
    print(f"  Dashboard: {ui_url}")
    print(f"  Press Ctrl+C to stop.")
    print("=" * 56 + "\n")

    httpd = ThreadingTCPServer(("", UI_PORT), UIHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
