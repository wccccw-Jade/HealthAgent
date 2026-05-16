from __future__ import annotations

from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.feishu import router as feishu_router

app = FastAPI(title="HealthAgent")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(chat_router)
app.include_router(feishu_router)
