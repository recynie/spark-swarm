from __future__ import annotations

import base64


def test_task_submission_and_heartbeat_assignment(client):
    create_task = client.post(
        "/api/v1/tasks",
        json={
            "name": "demo",
            "dockerfile_content": "FROM busybox\nCMD echo hello\n",
            "cpu_limit": 1.0,
            "memory_limit_mb": 128,
        },
    )
    assert create_task.status_code == 201
    task_id = create_task.json()["id"]

    heartbeat = client.post(
        "/api/v1/agent/heartbeat",
        json={
            "hostname": "worker-1",
            "ip_address": "192.168.5.10",
            "cpu_total": 8,
            "cpu_available": 4.0,
            "memory_total_mb": 8192,
            "memory_available_mb": 4096,
            "disk_total_mb": 102400,
            "disk_available_mb": 51200,
        },
    )
    assert heartbeat.status_code == 200
    assigned_task = heartbeat.json()["assigned_task"]
    assert assigned_task is not None
    assert assigned_task["id"] == task_id


def test_agent_status_and_result_update(client):
    task = client.post(
        "/api/v1/tasks",
        json={"name": "demo", "dockerfile_content": "FROM busybox\nCMD true\n"},
    ).json()
    task_id = task["id"]

    host = client.post(
        "/api/v1/agent/heartbeat",
        json={
            "hostname": "worker-1",
            "ip_address": "192.168.5.10",
            "cpu_total": 8,
            "cpu_available": 4.0,
            "memory_total_mb": 8192,
            "memory_available_mb": 4096,
            "disk_total_mb": 102400,
            "disk_available_mb": 51200,
        },
    ).json()
    assert host["assigned_task"]["id"] == task_id

    building = client.put(f"/api/v1/agent/tasks/{task_id}/status", json={"status": "BUILDING"})
    assert building.status_code == 200
    assert building.json()["status"] == "BUILDING"

    result = client.put(
        f"/api/v1/agent/tasks/{task_id}/result",
        json={
            "status": "SUCCESS",
            "stdout_log": "ok",
            "stderr_log": "",
            "exit_code": 0,
            "error_message": None,
            "output_files": ["artifact.txt"],
        },
    )
    assert result.status_code == 200
    assert result.json()["status"] == "SUCCESS"
    assert result.json()["output_files"] == ["artifact.txt"]


def test_agent_result_uploads_and_serves_artifacts(client):
    task = client.post(
        "/api/v1/tasks",
        json={"name": "artifact-demo", "dockerfile_content": "FROM busybox\nCMD true\n"},
    ).json()
    task_id = task["id"]

    result = client.put(
        f"/api/v1/agent/tasks/{task_id}/result",
        json={
            "status": "SUCCESS",
            "stdout_log": "ok",
            "stderr_log": "",
            "exit_code": 0,
            "error_message": None,
            "output_files": ["nested/result.txt"],
            "artifacts": [
                {
                    "path": "nested/result.txt",
                    "content_base64": base64.b64encode(b"artifact content").decode("ascii"),
                }
            ],
        },
    )

    assert result.status_code == 200
    payload = result.json()
    assert payload["output_files"] == ["nested/result.txt"]
    assert payload["artifact_urls"] == {
        "nested/result.txt": f"/api/v1/tasks/{task_id}/artifacts/nested/result.txt",
    }

    artifact = client.get(payload["artifact_urls"]["nested/result.txt"])
    assert artifact.status_code == 200
    assert artifact.content == b"artifact content"


def test_agent_result_rejects_unsafe_artifact_paths(client):
    task = client.post(
        "/api/v1/tasks",
        json={"name": "artifact-demo", "dockerfile_content": "FROM busybox\nCMD true\n"},
    ).json()

    result = client.put(
        f"/api/v1/agent/tasks/{task['id']}/result",
        json={
            "status": "SUCCESS",
            "output_files": ["../escape.txt"],
            "artifacts": [
                {
                    "path": "../escape.txt",
                    "content_base64": base64.b64encode(b"nope").decode("ascii"),
                }
            ],
        },
    )

    assert result.status_code == 400
