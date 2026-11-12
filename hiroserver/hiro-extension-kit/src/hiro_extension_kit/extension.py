"""What the app is as a HiroLeague extension: told once, beside which app it is (`hiro_extension_kit.setup(...,
extension=Extension(...))`), and read by the link, sign-in, the family copy and the route check when they run.

Backend kit, step 3: each app's hiroleague.py, auth/access.py and auth/guard.py held these as constants; the code
around them was the same in every app and is the kit's now.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from hiro_channel_sdk import ExtensionFeature, ExtensionUse, ExtensionVoiceUse

from .auth.rules import Rule


@dataclass(frozen=True)
class Extension:
    name: str  # its name in the core ("net"): the core's sign-in page is asked `?for=net`, other apps ask `net.*`
    version: str  # the app's version, declared to the core
    description: str  # one line, shown in the core's admin
    repo: str  # its repo ("nethiro"): the code reports keep a report for it (the core's extensions.list)
    port: int  # where it listens on the core's machine (its Dockerfile's uvicorn port): sent with a name claim
    site_title: str  # its Apps card in the core ("Network")
    site_icon: str  # the card's icon ("network")
    features: Sequence[ExtensionFeature]  # what a role may do in it, granted per role in the core
    # Every route's rule (auth/guard.py), first match wins. Only for an app on the kit's route check (HomeHiro keeps
    # its own for now: its users come in one more way).
    rules: Sequence[Rule] = ()
    knows: Sequence[dict[str, Any]] = ()  # the questions other apps may ask it (offers.knows)
    can_do: Sequence[dict[str, Any]] = ()  # what other apps may ask it to do, and sign-ins it offers (offers.can_do)
    uses: Sequence[ExtensionUse] = ()  # what it asks the core's AI for
    voice_uses: Sequence[ExtensionVoiceUse] = ()  # what it asks the core to say aloud
    # Its address until a name is claimed, e.g. HomeHiro's hand-written http://homehiro.local. "": none, and the app
    # claims <name>.hiro.local by itself on its first connection.
    site_default: str = ""
    auth: bool = True  # False: sign-in off (AUTH=off, a dev copy), everyone is the owner
    outputs: bool = True  # False: nothing is sent or spoken (OUTPUTS=off, a dev copy): whatsapp.py logs it instead
    # Where each role's rights were copied from once, when this app took a feature over from another (Phase 9b, 9c:
    # "home"), and that feature's name for the log line ("System health"). None: nothing to copy.
    rights_from: str | None = None
    rights_from_what: str = ""
    by_id: dict[str, ExtensionFeature] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "by_id", {f.id: f for f in self.features})


_extension: Extension | None = None


def setup(extension: Extension) -> None:
    global _extension
    _extension = extension


def ext() -> Extension:
    """What this app declares as an extension."""
    if _extension is None:
        raise RuntimeError("hiro_extension_kit isn't set up as an extension: the app's package passes "
                           "extension=Extension(...) to hiro_extension_kit.setup(...)")
    return _extension
