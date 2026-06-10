from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import psutil
import typer

from agent.config import settings
from agent.executor import execute_task
from agent.reporter import post_heartbeat, update_status, upload_result

app = typer.Typer(add_completion=False)


def _detect_ip_address() -> str:
    # 1. Explicit config takes priority
    if settings.ip_address != "127.0.0.1":
        return settings.ip_address
    # 2. Pick first non-loopback interface IP
    try:
        for _name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    return a.address
    except Exception:
        pass
    return settings.ip_address


def _load_host_id() -> str | None:
    path = Path(settings.host_id_file)
    if not path.exists():
        return None
    return path.read_text().strip() or None


def _store_host_id(host_id: str) -> None:
    Path(settings.host_id_file).write_text(host_id)


def collect_resources() -> dict[str, float | int]:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_total": psutil.cpu_count() or 0,
        "cpu_available": max(0.0, float(psutil.cpu_count() or 0) * (1.0 - psutil.cpu_percent(interval=0.2) / 100.0)),
        "memory_total_mb": int(memory.total / 1024 / 1024),
        "memory_available_mb": int(memory.available / 1024 / 1024),
        "disk_total_mb": int(disk.total / 1024 / 1024),
        "disk_available_mb": int(disk.free / 1024 / 1024),
    }


def _start_task_heartbeat_loop(host_id: str) -> tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()

    def _heartbeat_worker() -> None:
        while not stop_event.wait(settings.poll_interval_seconds):
            payload = {
                "host_id": host_id,
                "hostname": settings.hostname,
                "ip_address": _detect_ip_address(),
                **collect_resources(),
            }
            post_heartbeat(settings.master_url, payload)

    thread = threading.Thread(target=_heartbeat_worker, daemon=True)
    thread.start()
    return stop_event, thread


def run_loop(iterations: int | None = None) -> None:
    remaining = iterations
    host_id = _load_host_id()
    while remaining is None or remaining > 0:
        try:
            payload = {
                "host_id": host_id,
                "hostname": settings.hostname,
                "ip_address": _detect_ip_address(),
                **collect_resources(),
            }
            response = post_heartbeat(settings.master_url, payload)
            host_id = response["host_id"]
            _store_host_id(host_id)
            assigned_task = response.get("assigned_task")
            if assigned_task:
                update_status(settings.master_url, assigned_task["id"], "BUILDING")
                task_heartbeat_stop, task_heartbeat_thread = _start_task_heartbeat_loop(host_id)
                try:
                    result = execute_task(assigned_task, settings.output_dir)
                    if result.error_message and result.exit_code is None:
                        upload_result(
                            settings.master_url,
                            assigned_task["id"],
                            {
                                "status": result.status,
                                "stdout_log": result.stdout_log,
                                "stderr_log": result.stderr_log,
                                "exit_code": result.exit_code,
                                "error_message": result.error_message,
                                "output_files": result.output_files,
                            },
                        )
                    else:
                        update_status(settings.master_url, assigned_task["id"], "RUNNING")
                        upload_result(
                            settings.master_url,
                            assigned_task["id"],
                            {
                                "status": result.status,
                                "stdout_log": result.stdout_log,
                                "stderr_log": result.stderr_log,
                                "exit_code": result.exit_code,
                                "error_message": result.error_message,
                                "output_files": result.output_files,
                            },
                        )
                finally:
                    task_heartbeat_stop.set()
                    task_heartbeat_thread.join(timeout=1)
        except Exception as exc:
            print(f"[{settings.hostname}] loop error: {exc}", flush=True)
        if remaining is not None:
            remaining -= 1
            if remaining == 0:
                break
        time.sleep(settings.poll_interval_seconds)


@app.command()
def main(iterations: int | None = typer.Option(default=None, help="Run a fixed number of loop iterations")) -> None:
    run_loop(iterations=iterations)


if __name__ == "__main__":
    app()
