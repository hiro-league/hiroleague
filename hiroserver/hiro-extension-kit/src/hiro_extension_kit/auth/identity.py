"""Who is asking. A user is a person in HiroLeague's family list; a request says who it comes from in one of these ways:

- **Signed in at the app's address** through HiroLeague's sign-in (Phase 8): a session cookie (api.py).
- **Sign-in off** (AUTH=off, a dev copy): everyone is the owner.

- **Another way in**, the app's own (`Extension.other_way`): HomeHiro's HA add-on, whose headers name an HA user;
  api.py maps them to the core person through the app's links.

Pure: it reads the headers and whether sign-in is on.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Way = Literal["ha", "web", "dev"]  # "ha": HomeHiro's other way in (HA's add-on)


@dataclass(frozen=True)
class Caller:
    # the core person's id (AppUser.id); "dev" with sign-in off; "" for someone the other way in names who isn't
    # linked to anyone in the family list (they wait)
    user_id: str
    name: str
    way: Way
    device: str  # "iPhone", "Android phone", "Windows PC"... from the browser's User-Agent
    other_id: str = ""  # through the other way in: who it names there (HomeHiro: the HA user's id)


DEV = "dev"  # the user id with sign-in off


def caller_of(headers: Mapping[str, str], auth: bool) -> Caller | None:
    """Who sent a request with these headers (lower-case names) without a session: everyone with sign-in off (`auth`
    False), else None (api.py then reads the session cookie)."""
    if not auth:
        return Caller(DEV, "Sign-in off", "dev", device_of(headers.get("user-agent", "")))
    return None


def device_of(user_agent: str) -> str:
    """A short name for the device a request came from, for people to read ("Last here … from an iPhone")."""
    ua = user_agent.lower()
    if "iphone" in ua or ("ios" in ua and "home assistant" in ua):  # the iOS HA app says "iOS", not "iPhone"
        return "iPhone"
    if "ipad" in ua:
        return "iPad"
    if "android" in ua:
        return "Android tablet" if "mobile" not in ua and "wv" not in ua else "Android phone"
    if "windows" in ua:
        return "Windows PC"
    if "macintosh" in ua or "mac os" in ua:
        return "Mac"
    if "linux" in ua:
        return "Linux"
    return "a browser"
