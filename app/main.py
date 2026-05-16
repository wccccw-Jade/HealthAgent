from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.feishu import router as feishu_router
from app.config import get_settings
from app.scheduler.jobs import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if get_settings().enable_scheduler:
        start_scheduler()
    try:
        yield
    finally:
        if get_settings().enable_scheduler:
            stop_scheduler()


app = FastAPI(title="HealthAgent", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(chat_router)
app.include_router(feishu_router)
