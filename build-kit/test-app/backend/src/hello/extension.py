"""What Hello is as an extension of the core: its key, version and port (the manifest is written from these)."""

from importlib.metadata import version

from hiro_channel_sdk.approvals import PEOPLE_NOTIFY, PEOPLE_SEE
from hiro_extension_kit.extension import Extension, ask

VERSION = version("example-hello")

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
    asks=(
        ask(PEOPLE_SEE, "It greets people by name"),
        ask(PEOPLE_NOTIFY, "It can say hello on WhatsApp", required=False),
    ),
)
