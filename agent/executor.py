from __future__ import annotations

import base64
import io
import tarfile
from dataclasses import dataclass
from pathlib import Path

import docker


@dataclass
class OutputArtifact:
    path: str
    content_base64: str


@dataclass
class ExecutionResult:
    status: str
    stdout_log: str
    stderr_log: str
    exit_code: int | None
    error_message: str | None
    output_files: list[str]
    artifacts: list[OutputArtifact]


def _build_context(dockerfile_content: str) -> bytes:
    fileobj = io.BytesIO()
    with tarfile.open(fileobj=fileobj, mode="w") as archive:
        content = dockerfile_content.encode("utf-8")
        info = tarfile.TarInfo(name="Dockerfile")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    fileobj.seek(0)
    return fileobj.read()


def _output_files(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root).as_posix())
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _collect_artifacts(root: Path, max_artifact_bytes: int) -> list[OutputArtifact]:
    artifacts: list[OutputArtifact] = []
    total_bytes = 0
    for rel_path in _output_files(root):
        path = root / rel_path
        size = path.stat().st_size
        if total_bytes + size > max_artifact_bytes:
            raise ValueError(f"Output artifacts exceed max_artifact_bytes={max_artifact_bytes}")
        total_bytes += size
        content_base64 = base64.b64encode(path.read_bytes()).decode("ascii")
        artifacts.append(OutputArtifact(path=rel_path, content_base64=content_base64))
    return artifacts


def execute_task(
    task: dict,
    output_root: str,
    *,
    enable_gpu: bool = False,
    model_cache_dir: str | None = None,
    max_artifact_bytes: int = 100 * 1024 * 1024,
) -> ExecutionResult:
    client = docker.from_env()
    image_tag = f"spark-swarm-task:{task['id']}"
    output_dir = Path(output_root) / task["id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    stderr_chunks: list[str] = []
    stdout_log = ""
    exit_code: int | None = None
    container = None

    try:
        context = _build_context(task["dockerfile_content"])
        image, build_logs = client.images.build(fileobj=io.BytesIO(context), custom_context=True, tag=image_tag, rm=True)
        for entry in build_logs:
            if "stream" in entry:
                stdout_log += entry["stream"]
            if "error" in entry:
                stderr_chunks.append(entry["error"])

        volumes = {str(output_dir): {"bind": "/output", "mode": "rw"}}
        if model_cache_dir:
            cache_dir = Path(model_cache_dir).expanduser().absolute()
            cache_dir.mkdir(parents=True, exist_ok=True)
            volumes[str(cache_dir)] = {"bind": "/models", "mode": "rw"}

        run_kwargs = {
            "detach": True,
            "remove": False,
            "volumes": volumes,
        }
        if enable_gpu:
            run_kwargs["device_requests"] = [docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])]

        container = client.containers.run(image.id, **run_kwargs)
        result = container.wait(timeout=task.get("timeout_seconds"))
        exit_code = int(result.get("StatusCode", 1))
        stdout_log += container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
        stderr_chunks.append(container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace"))
        output_files = _output_files(output_dir)
        return ExecutionResult(
            status="SUCCESS" if exit_code == 0 else "FAILED",
            stdout_log=stdout_log,
            stderr_log="".join(stderr_chunks),
            exit_code=exit_code,
            error_message=None if exit_code == 0 else "Container exited with non-zero status",
            output_files=output_files,
            artifacts=_collect_artifacts(output_dir, max_artifact_bytes),
        )
    except Exception as exc:
        output_files = _output_files(output_dir)
        return ExecutionResult(
            status="FAILED",
            stdout_log=stdout_log,
            stderr_log="".join(stderr_chunks),
            exit_code=exit_code,
            error_message=str(exc),
            output_files=output_files,
            artifacts=[],
        )
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
