from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer
from urllib.parse import urlparse

from app.image_generation_case.campaign import (
    DEFAULT_BASE_IMAGE,
    DEFAULT_IMAGE_COUNT,
    DEFAULT_MASTER_URL,
    DEFAULT_MODEL_ID,
    DEFAULT_NEGATIVE_PROMPT,
    DEFAULT_PROMPT,
    RUNS_DIR,
    STATIC_DIR,
)
from app.image_generation_case.reporting import read_json, write_json
from app.image_generation_case.swarm_client import SwarmClient
from app.image_generation_case.workflow import (
    compare_runs,
    create_local_generation,
    list_runs,
    read_run_state,
    refresh_run,
    run_local_generation,
    submit_campaign,
)


MASTER_URL = os.environ.get("IMAGE_CASE_MASTER_URL", DEFAULT_MASTER_URL)
MODEL_ID = os.environ.get("IMAGE_CASE_MODEL_ID", DEFAULT_MODEL_ID)
BASE_IMAGE = os.environ.get("IMAGE_CASE_BASE_IMAGE", DEFAULT_BASE_IMAGE)
DEPS_PREINSTALLED = os.environ.get("IMAGE_CASE_DEPS_PREINSTALLED", "false").lower() in {"1", "true", "yes"}
PORT = int(os.environ.get("IMAGE_CASE_PORT", "3100"))
LOCAL_THREADS: dict[str, threading.Thread] = {}
THREAD_LOCK = threading.Lock()


class ReusableThreadingTCPServer(ThreadingTCPServer):
    allow_reuse_address = True


class CaseHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/case/api/state":
                self._json(case_state())
                return
            if parsed.path == "/case/api/runs":
                self._json({"runs": list_runs()})
                return
            if parsed.path.startswith("/case/api/runs/"):
                self._run_detail(parsed.path)
                return
            if parsed.path.startswith("/runs/"):
                self._serve_run_file(parsed.path)
                return
            super().do_GET()
        except Exception as exc:
            self._json({"detail": str(exc)}, status=500)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/case/api/generate/swarm" or parsed.path == "/case/api/campaigns":
                payload = self._read_json()
                state = submit_campaign(
                    master_url=payload.get("master_url") or MASTER_URL,
                    model_id=payload.get("model_id") or MODEL_ID,
                    base_image=payload.get("base_image") or BASE_IMAGE,
                    deps_preinstalled=bool(payload.get("deps_preinstalled", DEPS_PREINSTALLED)),
                    timeout_seconds=int(payload.get("timeout_seconds") or 900),
                    prompt=payload.get("prompt") or DEFAULT_PROMPT,
                    negative_prompt=payload.get("negative_prompt") or DEFAULT_NEGATIVE_PROMPT,
                    image_count=int(payload.get("image_count") or DEFAULT_IMAGE_COUNT),
                    width=int(payload.get("width") or 768),
                    height=int(payload.get("height") or 768),
                    seed_base=int(payload.get("seed_base") or 4200),
                    steps=int(payload.get("steps") or 4),
                    guidance_scale=float(payload.get("guidance_scale", 0.0)),
                )
                self._json(state, status=201)
                return
            if parsed.path == "/case/api/generate/local" or parsed.path == "/case/api/local-baseline":
                payload = self._read_json()
                state = create_local_generation(
                    model_id=payload.get("model_id") or MODEL_ID,
                    base_image=payload.get("base_image") or BASE_IMAGE,
                    deps_preinstalled=bool(payload.get("deps_preinstalled", DEPS_PREINSTALLED)),
                    prompt=payload.get("prompt") or DEFAULT_PROMPT,
                    negative_prompt=payload.get("negative_prompt") or DEFAULT_NEGATIVE_PROMPT,
                    image_count=int(payload.get("image_count") or DEFAULT_IMAGE_COUNT),
                    width=int(payload.get("width") or 768),
                    height=int(payload.get("height") or 768),
                    seed_base=int(payload.get("seed_base") or 4200),
                    steps=int(payload.get("steps") or 4),
                    guidance_scale=float(payload.get("guidance_scale", 0.0)),
                )
                _start_local_thread(
                    state["run_id"],
                    enable_gpu=bool(payload.get("enable_gpu", True)),
                    model_cache_dir=payload.get("model_cache_dir") or os.environ.get("IMAGE_CASE_MODEL_CACHE_DIR"),
                )
                self._json(state, status=201)
                return
            if parsed.path == "/case/api/manual-task":
                payload = self._read_json()
                client = SwarmClient(payload.get("master_url") or MASTER_URL)
                task = client.submit_task(
                    name=payload["name"],
                    dockerfile_content=payload["dockerfile_content"],
                    priority=int(payload.get("priority") or 10),
                    cpu_limit=float(payload.get("cpu_limit") or 0) or None,
                    memory_limit_mb=int(payload.get("memory_limit_mb") or 0) or None,
                    timeout_seconds=int(payload.get("timeout_seconds") or 900),
                )
                self._json(task, status=201)
                return
            if parsed.path.endswith("/refresh"):
                run_id = parsed.path.split("/")[-2]
                self._json(refresh_run(run_id))
                return
            if parsed.path == "/case/api/compare":
                payload = self._read_json()
                self._json(compare_runs(swarm_run_id=payload["swarm_run_id"], local_run_id=payload["local_run_id"]))
                return
            self.send_error(404)
        except Exception as exc:
            self._json({"detail": str(exc)}, status=500)

    def _run_detail(self, path: str) -> None:
        run_id = path.split("/")[-1]
        run_dir = RUNS_DIR / run_id
        if not run_dir.is_dir():
            self.send_error(404)
            return
        state_path = run_dir / "state.json"
        local_path = run_dir / "local-metrics.json"
        payload = {"run_id": run_id}
        if state_path.exists():
            payload["state"] = read_run_state(run_id)
        if local_path.exists():
            payload["local"] = read_json(local_path)
        benchmark_path = run_dir / "benchmark.json"
        if benchmark_path.exists():
            payload["benchmark"] = read_json(benchmark_path)
        payload["gallery_url"] = f"/runs/{run_id}/campaign-gallery.html" if (run_dir / "campaign-gallery.html").exists() else None
        self._json(payload)

    def _serve_run_file(self, path: str) -> None:
        relative = path.removeprefix("/runs/")
        candidate = (RUNS_DIR / relative).resolve()
        root = RUNS_DIR.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self.send_error(404)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        content_type = self.guess_type(str(candidate))
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json(self, payload: dict, *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        first = str(args[0]) if args else ""
        sys.stdout.write(f"[image-case] {first}\n")


def case_state() -> dict:
    client = SwarmClient(MASTER_URL)
    runs = _runs_with_runtime_state()
    payload = {
        "master_url": MASTER_URL,
        "model_id": MODEL_ID,
        "base_image": BASE_IMAGE,
        "deps_preinstalled": DEPS_PREINSTALLED,
        "default_prompt": DEFAULT_PROMPT,
        "default_negative_prompt": DEFAULT_NEGATIVE_PROMPT,
        "default_image_count": DEFAULT_IMAGE_COUNT,
        "runs": runs,
    }
    try:
        payload["hosts"] = client.hosts()
        payload["tasks"] = [task for task in client.tasks() if task["name"].startswith("image-case:")]
        payload["master_ok"] = True
    except Exception as exc:
        payload["hosts"] = []
        payload["tasks"] = []
        payload["master_ok"] = False
        payload["error"] = str(exc)
    return payload


def _runs_with_runtime_state() -> list[dict]:
    runs = list_runs()
    for run in runs:
        if run.get("type") != "local" or run.get("status") not in {"PENDING", "BUILDING", "RUNNING"}:
            continue
        with THREAD_LOCK:
            thread = LOCAL_THREADS.get(run["run_id"])
            alive = bool(thread and thread.is_alive())
        run["local_worker_active"] = alive
        if not alive:
            run["stale"] = True
            _mark_local_run_interrupted(run["run_id"])
            run["status"] = "FAILED"
    return runs


def _mark_local_run_interrupted(run_id: str) -> None:
    run_dir = RUNS_DIR / run_id
    state_path = run_dir / "state.json"
    if not state_path.exists():
        return
    state = read_json(state_path)
    if state.get("mode") != "local" or state.get("status") not in {"PENDING", "BUILDING", "RUNNING"}:
        return
    state["status"] = "FAILED"
    state["error"] = "Local generation was interrupted because the UI server is no longer running its background worker."
    state["completed_at"] = state.get("completed_at") or time.time()
    for item in state.get("tasks", []):
        task = item.get("task", {})
        if task.get("status") in {"PENDING", "BUILDING", "RUNNING"}:
            task["status"] = "FAILED"
            task["error_message"] = state["error"]
            break
    write_json(state_path, state)


def _start_local_thread(run_id: str, *, enable_gpu: bool, model_cache_dir: str | None) -> None:
    with THREAD_LOCK:
        existing = LOCAL_THREADS.get(run_id)
        if existing and existing.is_alive():
            return

        def _worker() -> None:
            try:
                run_local_generation(run_id, enable_gpu=enable_gpu, model_cache_dir=model_cache_dir)
            except Exception as exc:
                sys.stdout.write(f"[image-case] local run {run_id} failed: {exc}\n")

        thread = threading.Thread(target=_worker, daemon=True)
        LOCAL_THREADS[run_id] = thread
        thread.start()


def main() -> int:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{PORT}"
    print("=" * 64)
    print("Text-to-Image Swarm Studio")
    print("=" * 64)
    print(f"Master: {MASTER_URL}")
    print(f"Model:  {MODEL_ID}")
    print(f"Image:  {BASE_IMAGE}")
    print(f"UI:     {url}")
    print("=" * 64)
    with ReusableThreadingTCPServer(("", PORT), CaseHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
