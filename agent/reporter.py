from __future__ import annotations

from typing import Any

import requests


def post_heartbeat(master_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{master_url}/api/v1/agent/heartbeat", json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def update_status(master_url: str, task_id: str, status: str) -> dict[str, Any]:
    response = requests.put(
        f"{master_url}/api/v1/agent/tasks/{task_id}/status",
        json={"status": status},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def upload_result(master_url: str, task_id: str, result: dict[str, Any]) -> dict[str, Any]:
    response = requests.put(f"{master_url}/api/v1/agent/tasks/{task_id}/result", json=result, timeout=30)
    response.raise_for_status()
    return response.json()
