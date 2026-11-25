"""The app's side of the one sign-in, as far as it talks to the core (design.md §5.3): where a signed-out browser is
sent, whose one-time code it came back with (`auth.code`), and where signing out goes on to.

The kit's sign-in (api.py) is built on it, with its users, sessions and family copy. CodeHiro uses it alone: it
keeps its own sessions and lets the owner only in, in its own SQLite store (it isn't on the kit's database), and
talks to the core about signing in this way. So nothing here reads a database: it takes the link it asks through.

Permissions phase 8: the core's answer to the code also carries `token`, the person's proof for this app alone. The app
keeps it with its session (the kit's `WebSession.core_token`) and sends it with what it asks the core for that person
(hiroleague.as_person); signing out ends it in the core (`end`).
"""

from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlsplit

from hiro_channel_sdk import ExtensionRequestError
from hiro_channel_sdk.constants import AUTH_ERROR_INVALID_CODE, METHOD_AUTH_CODE, METHOD_AUTH_END

from .. import identity
from ..errors import Invalid, OutsideError, Unavailable
from ..extension import ext

if TYPE_CHECKING:
    from ..hiroleague import HiroLeagueLink

REDEEM_TIMEOUT = 10.0  # seconds: asking the core whose sign-in code it is
END_TIMEOUT = 5.0  # seconds: telling the core someone signed out (someone waits on the Sign out button)

log = identity.logger("auth")


def _title() -> str:
    return identity.app().title  # "NetHiro", in messages


def local_path(path: str) -> str:
    """Only a path on the app itself, never another site ("//evil.example", "https://...")."""
    return path if path.startswith("/") and not path.startswith(("//", "/\\")) else "/"


def origin(url: str) -> str | None:
    """`scheme://host[:port]` of an http(s) address; None when it isn't one."""
    parts = urlsplit(url or "")
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme in ("http", "https") and parts.netloc else None


def sign_in_url(link: "HiroLeagueLink", next: str) -> str | None:
    """The core's sign-in page for this app, back to `next` after it; None while the core's address isn't known."""
    admin = link.admin_url()
    return f"{admin}/sign-in?{urlencode({'for': ext().name, 'next': local_path(next)})}" if admin else None


def sign_out_url(link: "HiroLeagueLink") -> str | None:
    """Where the page goes after the app's own sign-out, to be signed out of the core too; None: nowhere."""
    admin = link.admin_url()
    return f"{admin}/api/auth/sign-out?{urlencode({'for': ext().name})}" if admin else None


def after_core_sign_out(link: "HiroLeagueLink", next: str) -> str:
    """Where the core's Sign out goes on to, once it passed through the app: only ever back to the core's own
    address; anything else, the app's first page."""
    admin = origin(link.admin_url() or "")
    return next if admin and origin(next) == admin else "/"


async def redeem(link: "HiroLeagueLink", code: str) -> dict[str, Any]:
    """Whose one-time code this is, asked of the core (`auth.code`): {person_id, name, role_id, role_name, token}.
    `token` is their proof for this app (a core from before approvals sends none)."""
    if not code:
        raise Invalid("The sign-in came back without its code. Sign in again.")
    client = link.client
    if not client.connected:
        raise Unavailable(f"{_title()} isn't connected to HiroLeague right now, so it can't finish signing you in. "
                          "Try again in a minute.")
    try:
        answer = await client.request(METHOD_AUTH_CODE, {"code": code}, timeout=REDEEM_TIMEOUT)
    except ExtensionRequestError as exc:
        if exc.code == AUTH_ERROR_INVALID_CODE:
            raise Invalid("This sign-in has expired or was used already. Sign in again.") from exc
        if exc.code in ("not_connected", "timeout"):
            raise Unavailable(f"HiroLeague didn't answer, so {_title()} can't finish signing you in. Try again in a "
                              "minute.") from exc
        raise OutsideError(f"HiroLeague couldn't say who signed in ({exc.code}): {exc.message}") from exc
    if not isinstance(answer.get("person_id"), str) or not answer["person_id"]:
        raise OutsideError("HiroLeague's answer about who signed in can't be read")
    return answer


async def end(link: "HiroLeagueLink", token: str | None) -> None:
    """Someone signed out of the app: the proof the core gave it for them ends there too (`auth.end`). Best effort:
    the app's own session ends either way, and a proof nobody uses lapses in the core by itself; a failure is logged."""
    if not token:
        return
    client = link.client
    if not client.connected:
        log.info("Users: signed out while HiroLeague is away; their proof there lapses by itself")
        return
    try:
        await client.request(METHOD_AUTH_END, {"token": token}, timeout=END_TIMEOUT)
    except ExtensionRequestError as exc:  # said once, here: the sign-out itself went through
        log.warning("Users: HiroLeague didn't end the proof of someone who signed out (%s: %s); it lapses by itself",
                    exc.code, exc.message)
