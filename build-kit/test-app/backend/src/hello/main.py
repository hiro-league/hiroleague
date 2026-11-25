"""What the service runs: `example-hello` (the manifest's command) starts uvicorn on 127.0.0.1:PORT."""

import uvicorn

from .app import create_app
from .config import config

app = create_app()


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=config.port, timeout_graceful_shutdown=3)
