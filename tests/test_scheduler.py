from __future__ import annotations

from datetime import datetime, timezone

from master.models import Host, HostStatus, Task, TaskStatus
from master.scheduler import schedule_pending_tasks


def test_best_fit_scheduling_prefers_tighter_host():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from master.database import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        db.add_all(
            [
                Host(
                    hostname="large",
                    ip_address="1.1.1.1",
                    status=HostStatus.ONLINE,
                    cpu_total=16,
                    cpu_available=8.0,
                    memory_total_mb=32768,
                    memory_available_mb=16384,
                    disk_total_mb=1000,
                    disk_available_mb=800,
                    last_heartbeat=datetime.now(timezone.utc),
                ),
                Host(
                    hostname="tight",
                    ip_address="1.1.1.2",
                    status=HostStatus.ONLINE,
                    cpu_total=8,
                    cpu_available=2.0,
                    memory_total_mb=8192,
                    memory_available_mb=1024,
                    disk_total_mb=1000,
                    disk_available_mb=800,
                    last_heartbeat=datetime.now(timezone.utc),
                ),
                Task(
                    name="demo",
                    dockerfile_content="FROM busybox",
                    status=TaskStatus.PENDING,
                    cpu_limit=1.0,
                    memory_limit_mb=512,
                ),
            ]
        )
        db.commit()
        assert schedule_pending_tasks(db) == 1
        task = db.query(Task).one()
        assert task.assigned_host is not None
        assert task.assigned_host.hostname == "tight"
