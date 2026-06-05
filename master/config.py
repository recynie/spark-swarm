from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPARK_SWARM_", extra="ignore")

    app_name: str = "spark-swarm-master"
    api_prefix: str = "/api/v1"
    database_url: str = Field(default=f"sqlite:///{Path('spark_swarm.db').absolute()}")
    scheduler_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 5
    heartbeat_timeout_seconds: int = 15


settings = Settings()
