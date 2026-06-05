from __future__ import annotations

import io
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

import docker


@dataclass
class ExecutionResult:
    status: str
    stdout_log: str
    stderr_log: str
    exit_code: int | None
    error_message: str | None
    output_files: list[str]


def _build_context(dockerfile_content: str) -> bytes:
    fileobj = io.BytesIO()
    with tarfile.open(fileobj=fileobj, mode="w") as archive:
        content = dockerfile_content.encode("utf-8")
        info = tarfile.TarInfo(name="Dockerfile")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    fileobj.seek(0)
    return fileobj.read()


def execute_task(task: dict, output_root: str) -> ExecutionResult:
    client = docker.from_env()
    image_tag = f"spark-swarm-task:{task['id']}"
    output_dir = Path(output_root) / task["id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    stderr_chunks: list[str] = []
    stdout_log = ""
    exit_code: int | None = None

    try:
        context = _build_context(task["dockerfile_content"])
        image, build_logs = client.images.build(fileobj=io.BytesIO(context), custom_context=True, tag=image_tag, rm=True)
        for entry in build_logs:
            if "stream" in entry:
                stdout_log += entry["stream"]
            if "error" in entry:
                stderr_chunks.append(entry["error"])

        container = client.containers.run(
            image.id,
            detach=True,
            remove=False,
            volumes={str(output_dir): {"bind": "/output", "mode": "rw"}},
        )
        result = container.wait(timeout=task.get("timeout_seconds"))
        exit_code = int(result.get("StatusCode", 1))
        stdout_log += container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
        stderr_chunks.append(container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace"))
        container.remove(force=True)
        return ExecutionResult(
            status="SUCCESS" if exit_code == 0 else "FAILED",
            stdout_log=stdout_log,
            stderr_log="".join(stderr_chunks),
            exit_code=exit_code,
            error_message=None if exit_code == 0 else "Container exited with non-zero status",
            output_files=sorted(str(path.relative_to(output_dir)) for path in output_dir.rglob("*") if path.is_file()),
        )
    except Exception as exc:
        return ExecutionResult(
            status="FAILED",
            stdout_log=stdout_log,
            stderr_log="".join(stderr_chunks),
            exit_code=exit_code,
            error_message=str(exc),
            output_files=[],
        )
