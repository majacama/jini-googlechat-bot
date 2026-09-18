import logging

from fastapi import FastAPI

from app.config import get_settings
from app.routers import chat, start

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Jin Investigator Agent", version="0.1.0")
app.include_router(start.router)
app.include_router(chat.router)
if get_settings().app_env == "dev":
    from app.routers import dev

    app.include_router(dev.router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "agent-formulaire-gchat",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "POST /start": "Déclenche une conversation (Bearer requis)",
            "POST /chat": "Événements Google Chat",
            "GET /conversations": "État d'une conversation (dev)",
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
