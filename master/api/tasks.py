from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from master.database import get_db
from master.models import Task, TaskStatus
from master.schemas import TaskCreate, TaskDetail, TaskSummary
from master.scheduler import schedule_pending_tasks

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _to_detail(task: Task) -> TaskDetail:
    return TaskDetail(
        id=task.id,
        name=task.name,
        status=task.status,
        priority=task.priority,
        assigned_host_id=task.assigned_host_id,
        created_at=task.created_at,
        scheduled_at=task.scheduled_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        cpu_limit=task.cpu_limit,
        memory_limit_mb=task.memory_limit_mb,
        timeout_seconds=task.timeout_seconds,
        stdout_log=task.stdout_log,
        stderr_log=task.stderr_log,
        exit_code=task.exit_code,
        error_message=task.error_message,
        output_files=json.loads(task.output_files_json or "[]"),
    )


@router.post("", response_model=TaskDetail, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    dockerfile_content = payload.dockerfile_content
    if not dockerfile_content:
        raise HTTPException(status_code=400, detail="dockerfile_content is required")
    task = Task(
        name=payload.name,
        dockerfile_content=dockerfile_content,
        priority=payload.priority,
        cpu_limit=payload.cpu_limit,
        memory_limit_mb=payload.memory_limit_mb,
        timeout_seconds=payload.timeout_seconds,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    schedule_pending_tasks(db)
    db.refresh(task)
    return _to_detail(task)


@router.get("", response_model=list[TaskSummary])
def list_tasks(status: TaskStatus | None = Query(default=None), db: Session = Depends(get_db)):
    stmt = select(Task).order_by(Task.created_at.desc())
    if status is not None:
        stmt = stmt.where(Task.status == status)
    return list(db.scalars(stmt).all())


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _to_detail(task)


_DELETABLE_STATUSES = {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED}


@router.delete("/{task_id}")
def delete_or_cancel_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status == TaskStatus.PENDING:
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        return {"detail": "Task cancelled"}
    if task.status in _DELETABLE_STATUSES:
        db.delete(task)
        db.commit()
        return {"detail": "Task deleted"}
    raise HTTPException(status_code=409, detail="Can only cancel PENDING or delete completed tasks")
