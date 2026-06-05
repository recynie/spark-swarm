from __future__ import annotations

from agent.main import collect_resources


def test_collect_resources_shape():
    payload = collect_resources()
    assert payload["cpu_total"] >= 0
    assert payload["memory_total_mb"] >= payload["memory_available_mb"]
    assert payload["disk_total_mb"] >= payload["disk_available_mb"]
