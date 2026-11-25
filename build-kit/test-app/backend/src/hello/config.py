"""Hello's settings from the environment, read once when the app is loaded.

| Variable   | Default                                   | What                                          |
|------------|-------------------------------------------|-----------------------------------------------|
| DATA_DIR   | backend/data                              | the database and every stored file            |
| STATIC_DIR | the package's static/, else frontend/build | the built UI (inside the package once built) |
| PORT       | 8190                                      | where it listens, on 127.0.0.1                |
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_PACKAGE = Path(__file__).parent
_BACKEND = _PACKAGE.parents[1]


@dataclass(frozen=True)
class Config:
    data_dir: Path
    static_dir: Path
    port: int

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Config":
        # An installed release carries its UI inside the package (build-kit/package.py puts it in static/); a checkout
        # has it in frontend/build
        built = _PACKAGE / "static"
        static = built if built.is_dir() else _BACKEND.parent / "frontend" / "build"
        return cls(
            data_dir=Path(env.get("DATA_DIR", _BACKEND / "data")).resolve(),
            static_dir=Path(env.get("STATIC_DIR", static)).resolve(),
            port=int(env.get("PORT", "8190")),
        )


config = Config.from_env()
