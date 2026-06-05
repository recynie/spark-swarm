from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from master.config import settings
from master.models import Host, HostStatus, Task, TaskStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_host_eligible(host: Host, task: Task, now: datetime) -> bool:
    if host.status != HostStatus.ONLINE:
        return False
    if _as_utc(host.last_heartbeat) < now - timedelta(seconds=settings.heartbeat_timeout_seconds):
        return False
    if task.cpu_limit is not None and host.cpu_available < task.cpu_limit:
        return False
    if task.memory_limit_mb is not None and host.memory_available_mb < task.memory_limit_mb:
        return False
    return True


def _host_score(host: Host, task: Task) -> tuple[float, int]:
    remaining_cpu = host.cpu_available - (task.cpu_limit or 0)
    remaining_mem = host.memory_available_mb - (task.memory_limit_mb or 0)
    return (remaining_cpu, remaining_mem)


def schedule_pending_tasks(db: Session) -> int:
    now = utcnow()
    hosts = list(db.scalars(select(Host)).all())
    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.status == TaskStatus.PENDING)
            .order_by(Task.priority.asc(), Task.created_at.asc())
        ).all()
    )
    scheduled = 0
    for task in tasks:
        candidates = [host for host in hosts if _is_host_eligible(host, task, now)]
        if not candidates:
            continue
        best_host = min(candidates, key=lambda host: _host_score(host, task))
        task.assigned_host_id = best_host.id
        task.status = TaskStatus.SCHEDULED
        task.scheduled_at = now
        if task.cpu_limit is not None:
            best_host.cpu_available -= task.cpu_limit
        if task.memory_limit_mb is not None:
            best_host.memory_available_mb -= task.memory_limit_mb
        scheduled += 1
    if scheduled:
        db.commit()
    return scheduled
