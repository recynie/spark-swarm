from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from master.database import get_db
from master.models import Task, TaskStatus
from master.schemas import TaskDetail, TaskResultUpdate, TaskStatusUpdate

router = APIRouter(prefix="/agent/tasks", tags=["agent"])


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


@router.put("/{task_id}/status", response_model=TaskDetail)
def update_task_status(task_id: str, payload: TaskStatusUpdate, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = payload.status
    now = datetime.now(timezone.utc)
    if payload.status in {TaskStatus.BUILDING, TaskStatus.RUNNING} and task.started_at is None:
        task.started_at = now
    if payload.status in {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED}:
        task.completed_at = now
    db.commit()
    db.refresh(task)
    return _to_detail(task)


@router.put("/{task_id}/result", response_model=TaskDetail)
def update_task_result(task_id: str, payload: TaskResultUpdate, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = payload.status
    task.stdout_log = payload.stdout_log
    task.stderr_log = payload.stderr_log
    task.exit_code = payload.exit_code
    task.error_message = payload.error_message
    task.output_files_json = json.dumps(payload.output_files)
    task.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(task)
    return _to_detail(task)
