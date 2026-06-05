from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from master.api.agent import router as agent_router
from master.api.hosts import router as hosts_router
from master.api.tasks import router as tasks_router
from master.config import settings
from master.database import Base, SessionLocal, engine
from master.monitor import reconcile_host_health
from master.scheduler import schedule_pending_tasks


async def _background_loop():
    while True:
        db = SessionLocal()
        try:
            reconcile_host_health(db)
            schedule_pending_tasks(db)
        finally:
            db.close()
        await asyncio.sleep(settings.scheduler_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    task = asyncio.create_task(_background_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(tasks_router, prefix=settings.api_prefix)
app.include_router(hosts_router, prefix=settings.api_prefix)
app.include_router(agent_router, prefix=settings.api_prefix)


@app.get("/healthz")
def healthz():
    return {"ok": True}
