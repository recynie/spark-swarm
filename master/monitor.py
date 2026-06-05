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


def reconcile_host_health(db: Session) -> dict[str, int]:
    now = utcnow()
    offline_threshold = now - timedelta(seconds=settings.heartbeat_timeout_seconds)
    hosts = list(db.scalars(select(Host)).all())
    marked_offline = 0
    requeued = 0

    for host in hosts:
        should_be_online = _as_utc(host.last_heartbeat) >= offline_threshold
        if should_be_online and host.status != HostStatus.ONLINE:
            host.status = HostStatus.ONLINE
        if not should_be_online and host.status != HostStatus.OFFLINE:
            host.status = HostStatus.OFFLINE
            marked_offline += 1
            tasks = db.scalars(
                select(Task).where(
                    Task.assigned_host_id == host.id,
                    Task.status.in_([TaskStatus.SCHEDULED, TaskStatus.BUILDING, TaskStatus.RUNNING]),
                )
            ).all()
            for task in tasks:
                task.status = TaskStatus.PENDING
                task.assigned_host_id = None
                task.scheduled_at = None
                task.started_at = None
                requeued += 1
    db.commit()
    return {"marked_offline": marked_offline, "requeued": requeued}
