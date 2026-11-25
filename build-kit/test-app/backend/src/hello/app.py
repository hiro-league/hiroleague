"""The Hello app: its health path and its UI. At start its migrations, then its workers; they stop in reverse.

No sign-in guard: Hello answers only its health and a static page, and exists to be installed, upgraded and removed.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from hiro_channel_sdk.workers import Worker
from pydantic import BaseModel

from hiro_extension_kit import errors, events, logs
from hiro_extension_kit.db import migrate
from hiro_extension_kit.errors import failed
from hiro_extension_kit.hiroleague import link as hiroleague_link
from hiro_extension_kit.stopping import watch as watch_stop_signals
from hiro_extension_kit.ui import router as ui_router
from hiro_extension_kit.watchdog import watchdog

from .config import config
from .extension import VERSION

logs.setup(config.data_dir / "logs")
log = logging.getLogger("hello.app")

WORKERS: list[Worker] = [watchdog, hiroleague_link]

system = APIRouter()


class Health(BaseModel):
    status: str
    version: str


@system.get("/api/health")
def health() -> Health:
    return Health.model_validate({"status": "ok", "version": VERSION})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    events.bind()
    watch_stop_signals()
    migrate()
    started: list[Worker] = []
    try:
        for worker in WORKERS:
            worker.start()
            started.append(worker)
        yield
    finally:
        for worker in reversed(started):
            try:
                await worker.stop()
            except Exception as exc:  # one failing stop doesn't keep the others from stopping
                failed(log, f"Stopping {worker.name}", exc)


def create_app() -> FastAPI:
    app = FastAPI(title="Hello", version=VERSION, lifespan=lifespan)
    errors.install(app)
    app.include_router(system)
    app.include_router(ui_router)
    return app
