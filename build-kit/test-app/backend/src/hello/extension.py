"""What Hello is as an extension of the core: its key, version and port (the manifest is written from these)."""

from importlib.metadata import version

from hiro_channel_sdk.approvals import PEOPLE_NOTIFY, PEOPLE_SEE
from hiro_extension_kit.extension import Extension, SetupStep, ask

VERSION = version("example-hello")


def has_a_greeting() -> bool:
    """Whether Hello has a greeting yet: its one thing to set, so the Extensions page shows one."""
    from sqlmodel import Session, select

    from hiro_extension_kit.db import engine

    from .models import Greeting

    with Session(engine) as session:
        return session.exec(select(Greeting)).first() is not None

EXTENSION = Extension(
    name="example.hello",  # its key: a publisher's (example), since only Hiro League's own have a bare key
    version=VERSION,
    description="The test app the core installs, upgrades and removes",
    repo="hiroleague",
    port=8190,
    site_title="Hello",
    site_icon="hand",
    features=(),
    # One required ask and one optional one, so an install shows both (Hello uses neither)
    setup=(SetupStep("greeting", "Write its greeting", "/", has_a_greeting),),
    asks=(
        ask(PEOPLE_SEE, "It greets people by name"),
        ask(PEOPLE_NOTIFY, "It can say hello on WhatsApp", required=False),
    ),
)
