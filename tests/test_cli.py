from __future__ import annotations

from typer.testing import CliRunner

from cli.main import app


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_hosts_command_uses_master_url_option(monkeypatch):
    runner = CliRunner()
    calls = {}

    def fake_get(url, *, timeout, params=None):
        calls["url"] = url
        calls["timeout"] = timeout
        calls["params"] = params
        return FakeResponse([])

    monkeypatch.setattr("cli.main.requests.get", fake_get)

    result = runner.invoke(app, ["hosts", "--master-url", "http://master.example:9000/"])

    assert result.exit_code == 0
    assert calls == {
        "url": "http://master.example:9000/api/v1/hosts",
        "timeout": 10,
        "params": None,
    }


def test_status_command_uses_master_url_env(monkeypatch):
    runner = CliRunner()
    calls = {}

    def fake_get(url, *, timeout, params=None):
        calls["url"] = url
        calls["timeout"] = timeout
        calls["params"] = params
        return FakeResponse({"id": "task-1"})

    monkeypatch.setenv("SPARK_SWARM_MASTER_URL", "http://env-master:8000/")
    monkeypatch.setattr("cli.main.requests.get", fake_get)

    result = runner.invoke(app, ["status", "task-1"])

    assert result.exit_code == 0
    assert calls == {
        "url": "http://env-master:8000/api/v1/tasks/task-1",
        "timeout": 10,
        "params": None,
    }
