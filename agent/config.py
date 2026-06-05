from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPARK_SWARM_AGENT_", extra="ignore")

    master_url: str = "http://127.0.0.1:8000"
    poll_interval_seconds: int = 5
    hostname: str = "worker"
    ip_address: str = "127.0.0.1"
    host_id_file: str = str(Path(".spark-swarm-agent-id").absolute())
    output_dir: str = str(Path("./agent-output").absolute())


settings = AgentSettings()
