from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

import requests


class SwarmClient:
    def __init__(self, master_url: str, *, timeout: int = 30) -> None:
        self.master_url = master_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> dict:
        response = requests.get(f"{self.master_url}/healthz", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def hosts(self) -> list[dict]:
        response = requests.get(f"{self.master_url}/api/v1/hosts", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def tasks(self) -> list[dict]:
        response = requests.get(f"{self.master_url}/api/v1/tasks", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def task(self, task_id: str) -> dict:
        response = requests.get(f"{self.master_url}/api/v1/tasks/{task_id}", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def submit_task(
        self,
        *,
        name: str,
        dockerfile_content: str,
        priority: int,
        cpu_limit: float | None,
        memory_limit_mb: int | None,
        timeout_seconds: int,
    ) -> dict:
        response = requests.post(
            f"{self.master_url}/api/v1/tasks",
            json={
                "name": name,
                "dockerfile_content": dockerfile_content,
                "priority": priority,
                "cpu_limit": cpu_limit,
                "memory_limit_mb": memory_limit_mb,
                "timeout_seconds": timeout_seconds,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def download_artifact(self, artifact_url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = urljoin(self.master_url + "/", artifact_url.lstrip("/"))
        with requests.get(url, timeout=self.timeout, stream=True) as response:
            response.raise_for_status()
            with destination.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
