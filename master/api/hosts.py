from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from master.database import get_db
from master.models import Host, HostStatus, Task, TaskStatus
from master.schemas import HeartbeatResponse, HostHeartbeat, HostSummary
from master.scheduler import schedule_pending_tasks

router = APIRouter(tags=["hosts"])


@router.get("/hosts", response_model=list[HostSummary])
def list_hosts(db: Session = Depends(get_db)):
    return list(db.scalars(select(Host).order_by(Host.hostname.asc())).all())


@router.post("/agent/heartbeat", response_model=HeartbeatResponse)
def heartbeat(payload: HostHeartbeat, request: Request, db: Session = Depends(get_db)):
    # Use the actual remote IP from the TCP connection, not what the agent reports
    real_ip = request.client.host if request.client else payload.ip_address

    host = db.get(Host, payload.host_id) if payload.host_id else None
    if host is None:
        host = Host(hostname=payload.hostname, ip_address=real_ip)
        db.add(host)
        db.flush()

    host.hostname = payload.hostname
    host.ip_address = real_ip
    host.status = HostStatus.ONLINE
    host.cpu_total = payload.cpu_total
    host.cpu_available = payload.cpu_available
    host.memory_total_mb = payload.memory_total_mb
    host.memory_available_mb = payload.memory_available_mb
    host.disk_total_mb = payload.disk_total_mb
    host.disk_available_mb = payload.disk_available_mb
    host.last_heartbeat = datetime.now(timezone.utc)
    db.commit()
    db.refresh(host)

    schedule_pending_tasks(db)
    task = db.scalars(
        select(Task).where(Task.assigned_host_id == host.id, Task.status == TaskStatus.SCHEDULED).order_by(Task.scheduled_at.asc())
    ).first()
    assigned_task = None
    if task:
        assigned_task = {
            "id": task.id,
            "name": task.name,
            "dockerfile_content": task.dockerfile_content,
            "cpu_limit": task.cpu_limit,
            "memory_limit_mb": task.memory_limit_mb,
            "timeout_seconds": task.timeout_seconds,
        }
    return HeartbeatResponse(host_id=host.id, assigned_task=assigned_task)
