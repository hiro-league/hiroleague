"""What Hello is as an extension of the core: its key, version and port (the manifest is written from these)."""

from importlib.metadata import version

from hiro_extension_kit.extension import Extension

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
    asks=(),
)
