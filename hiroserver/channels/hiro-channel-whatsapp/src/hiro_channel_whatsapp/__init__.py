import os
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# neonize 0.5.2's Go side tags every one-to-one message to a phone-number address as a business bot
# (<bot biz_bot="1"/>) unless NEONIZE_BOT_TAG says off. WhatsApp's server accepts such a message from a personal
# account and then delivers it to no device (no receipt, nothing on the phone); later neonize turns the tag off by
# default. Go reads the variable when neonize's library loads, so it is set here, before any module imports neonize.
os.environ.setdefault("NEONIZE_BOT_TAG", "off")

# Version from this package's own installed metadata (source of truth =
# pyproject.toml); stdlib-only, no sibling-package import.
try:
    __version__ = _pkg_version("hiro-channel-whatsapp")
except PackageNotFoundError:  # raw source tree, not installed
    __version__ = "0.0.0+unknown"
