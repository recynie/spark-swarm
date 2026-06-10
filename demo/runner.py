from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer

import requests

DEMO_DIR = Path(__file__).resolve().parent
STATIC_DIR = DEMO_DIR / "static"
MASTER_PORT = 8000
UI_PORT = 3000
AGENT_COUNT = 3

running = True


def _wait_for_master(timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"http://127.0.0.1:{MASTER_PORT}/healthz", timeout=1)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _make_agent_env(i: int) -> dict[str, str]:
    env = os.environ.copy()
    env["SPARK_SWARM_AGENT_MASTER_URL"] = f"http://127.0.0.1:{MASTER_PORT}"
    env["SPARK_SWARM_AGENT_HOSTNAME"] = f"worker-{i + 1}"
    env["SPARK_SWARM_AGENT_IP_ADDRESS"] = f"192.168.5.{10 + i}"
    env["SPARK_SWARM_AGENT_HOST_ID_FILE"] = str(DEMO_DIR / f".agent-id-{i + 1}")
    env["SPARK_SWARM_AGENT_OUTPUT_DIR"] = str(DEMO_DIR / f"agent-output-{i + 1}")
    return env


class DemoHandler(SimpleHTTPRequestHandler):
    static_dir = str(STATIC_DIR)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=self.static_dir, **kwargs)

    def _proxy(self, method: str) -> None:
        url = f"http://127.0.0.1:{MASTER_PORT}{self.path}"
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
        if "/api/" in (args[0] if args else ""):
            sys.stdout.write(f"  [proxy] {args[0]}\n")
        else:
            pass  # suppress static file logs


def main() -> int:
    global running
    procs: list[subprocess.Popen] = []

    def _cleanup(*_):
        global running
        running = False
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    print("=" * 56)
    print("  Spark-Swarm Demo Runner")
    print("=" * 56)

    # ── Start Master ──
    print(f"\n[1/3] Starting Master on port {MASTER_PORT}...")
    master = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "master.main:app", "--host", "0.0.0.0", "--port", str(MASTER_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    procs.append(master)

    if not _wait_for_master():
        print("  ERROR: Master failed to start. Is the project installed?")
        _cleanup()
        return 1
    print("  Master ready.")

    # ── Start Agents ──
    print(f"\n[2/3] Starting {AGENT_COUNT} agents...")
    for i in range(AGENT_COUNT):
        env = _make_agent_env(i)
        agent = subprocess.Popen(
            [sys.executable, "-m", "agent.main"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(agent)
        print(f"  Agent {i + 1}: {env['SPARK_SWARM_AGENT_HOSTNAME']} ({env['SPARK_SWARM_AGENT_IP_ADDRESS']})")
        time.sleep(0.5)

    # ── Start UI Server ──
    print(f"\n[3/3] Starting Dashboard UI on port {UI_PORT}...")
    httpd = ThreadingTCPServer(("", UI_PORT), DemoHandler)

    ui_url = f"http://localhost:{UI_PORT}"
    print("\n" + "=" * 56)
    print(f"  Dashboard:  {ui_url}")
    print(f"  Master API: http://localhost:{MASTER_PORT}")
    print(f"  Swagger:    http://localhost:{MASTER_PORT}/docs")
    print("=" * 56)
    print("\n  Press Ctrl+C to stop all components.\n")

    # Open browser
    try:
        webbrowser.open(ui_url)
    except Exception:
        pass

    # Serve until interrupted
    try:
        while running:
            httpd.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down...")
        httpd.server_close()
        _cleanup()
        print("All processes stopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
