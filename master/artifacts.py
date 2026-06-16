from __future__ import annotations

import base64
import binascii
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from fastapi import HTTPException

from master.config import settings
from master.schemas import OutputArtifact


def artifact_root(task_id: str) -> Path:
    return Path(settings.artifact_dir) / task_id


def safe_artifact_path(task_id: str, artifact_path: str) -> Path:
    raw_path = artifact_path.strip()
    pure = PurePosixPath(raw_path)
    if not raw_path or not pure.parts or pure.is_absolute() or ".." in pure.parts:
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    root = artifact_root(task_id)
    path = root.joinpath(*pure.parts)
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid artifact path") from exc
    return path


def artifact_urls(task_id: str, output_files: list[str]) -> dict[str, str]:
    urls: dict[str, str] = {}
    for path in output_files:
        try:
            artifact_path = safe_artifact_path(task_id, path)
        except HTTPException:
            continue
        if artifact_path.is_file():
            urls[path] = f"{settings.api_prefix}/tasks/{task_id}/artifacts/{quote(path)}"
    return urls


def save_artifacts(task_id: str, artifacts: list[OutputArtifact]) -> None:
    for artifact in artifacts:
        path = safe_artifact_path(task_id, artifact.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_bytes(base64.b64decode(artifact.content_base64, validate=True))
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid artifact content for {artifact.path}") from exc
