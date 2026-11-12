"""The backend every HiroLeague extension app is built on: what HomeHiro, NetHiro and TrainHiro each had a copy of.

An app's package starts by saying which app it is, and what it is as an extension (its `__init__.py`):

    import hiro_extension_kit
    from .extension import EXTENSION   # Extension(name="net", port=8130, features=..., rules=..., ...)

    hiro_extension_kit.setup(name="nethiro", title="NetHiro", package=Path(__file__).parent,
                             data_dir=config.data_dir, static_dir=config.static_dir, extension=EXTENSION)

and then imports what it needs. The README lists every module.

The SDK (`hiro_channel_sdk`) stays the contract with the core (the extension socket, `Worker`, the rights check) and
depends on nothing heavy; this package is the app around it and needs FastAPI, SQLModel and Alembic.
"""

from pathlib import Path

from hiro_channel_sdk import workers as sdk_workers

from . import extension as _extension
from . import identity
from .extension import Extension


def setup(*, name: str, title: str, package: Path, data_dir: Path, static_dir: Path,
          extension: Extension | None = None) -> identity.Identity:
    """Say which app this is (identity.py) and what it is as an extension (extension.py; backend kit step 3), and have
    the SDK's background workers log their failures the apps' way: an expected error as one line, anything else with
    its traceback (errors.failed)."""
    me = identity.setup(name=name, title=title, package=package, data_dir=data_dir, static_dir=static_dir)
    if extension is not None:
        _extension.setup(extension)
    from . import errors  # after identity: its logger is the app's

    sdk_workers.configure(failed=errors.failed)
    return me
