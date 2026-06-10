from __future__ import annotations

import json
from pathlib import Path

import requests
import typer

app = typer.Typer(add_completion=False)


def _master_url() -> str:
    return "http://127.0.0.1:8000"


def _print_json(payload) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@app.command()
def submit(
    dockerfile_path: Path,
    name: str = typer.Option(...),
    cpu: float | None = typer.Option(default=None),
    memory: int | None = typer.Option(default=None),
    timeout: int | None = typer.Option(default=None),
    priority: int = typer.Option(default=10),
) -> None:
    payload = {
        "name": name,
        "dockerfile_content": dockerfile_path.read_text(),
        "cpu_limit": cpu,
        "memory_limit_mb": memory,
        "timeout_seconds": timeout,
        "priority": priority,
    }
    response = requests.post(f"{_master_url()}/api/v1/tasks", json=payload, timeout=10)
    response.raise_for_status()
    _print_json(response.json())


@app.command()
def status(task_id: str) -> None:
    response = requests.get(f"{_master_url()}/api/v1/tasks/{task_id}", timeout=10)
    response.raise_for_status()
    _print_json(response.json())


@app.command("tasks")
def list_tasks(status: str | None = typer.Option(default=None)) -> None:
    response = requests.get(f"{_master_url()}/api/v1/tasks", params={"status": status} if status else None, timeout=10)
    response.raise_for_status()
    _print_json(response.json())


@app.command()
def hosts() -> None:
    response = requests.get(f"{_master_url()}/api/v1/hosts", timeout=10)
    response.raise_for_status()
    _print_json(response.json())


@app.command()
def cancel(task_id: str) -> None:
    """Cancel a PENDING task, or delete a completed (SUCCESS/FAILED/CANCELLED) task."""
    response = requests.delete(f"{_master_url()}/api/v1/tasks/{task_id}", timeout=10)
    response.raise_for_status()
    _print_json(response.json())


@app.command()
def logs(task_id: str) -> None:
    response = requests.get(f"{_master_url()}/api/v1/tasks/{task_id}", timeout=10)
    response.raise_for_status()
    payload = response.json()
    typer.echo(payload.get("stdout_log") or "")
    stderr_log = payload.get("stderr_log")
    if stderr_log:
        typer.echo(stderr_log, err=True)


if __name__ == "__main__":
    app()
