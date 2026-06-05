from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from master.models import HostStatus, TaskStatus


class TaskCreate(BaseModel):
    name: str
    dockerfile_content: str | None = None
    dockerfile_path: str | None = None
    priority: int = 10
    cpu_limit: float | None = None
    memory_limit_mb: int | None = None
    timeout_seconds: int | None = None


class TaskSummary(BaseModel):
    id: str
    name: str
    status: TaskStatus
    priority: int
    assigned_host_id: str | None
    created_at: datetime
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class TaskDetail(TaskSummary):
    cpu_limit: float | None
    memory_limit_mb: int | None
    timeout_seconds: int | None
    stdout_log: str | None
    stderr_log: str | None
    exit_code: int | None
    error_message: str | None
    output_files: list[str] = Field(default_factory=list)


class TaskResultUpdate(BaseModel):
    status: TaskStatus
    stdout_log: str | None = None
    stderr_log: str | None = None
    exit_code: int | None = None
    error_message: str | None = None
    output_files: list[str] = Field(default_factory=list)


class TaskStatusUpdate(BaseModel):
    status: TaskStatus


class HostHeartbeat(BaseModel):
    host_id: str | None = None
    hostname: str
    ip_address: str
    cpu_total: int
    cpu_available: float
    memory_total_mb: int
    memory_available_mb: int
    disk_total_mb: int
    disk_available_mb: int


class HostSummary(BaseModel):
    id: str
    hostname: str
    ip_address: str
    status: HostStatus
    cpu_total: int
    cpu_available: float
    memory_total_mb: int
    memory_available_mb: int
    disk_total_mb: int
    disk_available_mb: int
    last_heartbeat: datetime

    model_config = {"from_attributes": True}


class HeartbeatResponse(BaseModel):
    host_id: str
    assigned_task: dict[str, Any] | None = None
