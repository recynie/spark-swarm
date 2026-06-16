from __future__ import annotations

import base64

import pytest

from agent.main import collect_resources
from agent.executor import _collect_artifacts


def test_collect_resources_shape():
    payload = collect_resources()
    assert payload["cpu_total"] >= 0
    assert payload["memory_total_mb"] >= payload["memory_available_mb"]
    assert payload["disk_total_mb"] >= payload["disk_available_mb"]


def test_collect_artifacts_encodes_files(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "result.txt").write_bytes(b"hello")

    artifacts = _collect_artifacts(tmp_path, 1024)

    assert len(artifacts) == 1
    assert artifacts[0].path == "nested/result.txt"
    assert artifacts[0].content_base64 == base64.b64encode(b"hello").decode("ascii")


def test_collect_artifacts_rejects_oversized_payload(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * 8)

    with pytest.raises(ValueError):
        _collect_artifacts(tmp_path, 4)
