"""What an app may do to the core (Permissions phase 8, "What an app is approved for: the design", section 8).

An app reaches the core two ways: on its own (an automation at night, an alert), held to what the owner approved
for it at pairing; or for a person signed in to it, held to that person's own rights, proven by a token the core gave
the app at sign-in (``PARAM_SIGNED_IN``). This module is the one table both sides read: the core checks every app ask
against it, the backend kit's fake core answers by it, and the kit builds an app's ``asks`` from its ids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, Field

from .constants import (
    METHOD_AI_ASK,
    METHOD_AI_CHAT,
    METHOD_AI_EMBED,
    METHOD_AI_PROFILES,
    METHOD_AI_RERANK,
    METHOD_AI_USES_SET,
    METHOD_AUTH_CODE,
    METHOD_AUTH_END,
    METHOD_CORE_INFO,
    METHOD_EXTENSION_STATE,
    METHOD_EXTENSIONS_ASK,
    METHOD_EXTENSIONS_LIST,
    METHOD_KNOWLEDGE_SETTINGS,
    METHOD_LOGS_SEND,
    METHOD_MEMORY_SETTINGS,
    METHOD_NOTIFY,
    METHOD_PEOPLE_ADD,
    METHOD_PEOPLE_LIST,
    METHOD_PEOPLE_UPDATE,
    METHOD_ROLES_ADD,
    METHOD_ROLES_IMPORT_RIGHTS,
    METHOD_ROLES_REMOVE,
    METHOD_ROLES_RENAME,
    METHOD_SITES_CLAIM,
    METHOD_SITES_LIST,
    METHOD_VOICE_PROFILES,
    METHOD_VOICE_SPEAK,
    METHOD_VOICE_USES_SET,
    METHOD_WHATSAPP_CHECK,
    METHOD_WHATSAPP_SEND,
    METHOD_WHATSAPP_STATUS,
)

# ---------------------------------------------------------------------------
# The permissions an app asks for, approved one by one at pairing
# ---------------------------------------------------------------------------

PEOPLE_SEE: Final = "people.see"
PEOPLE_NOTIFY: Final = "people.notify"
AI_USE: Final = "ai.use"
VOICE_SPEAK: Final = "voice.speak"
AI_SEARCH: Final = "ai.search"
APPS_ASK: Final = "apps.ask"  # its subject: the app asked (``to``)
HIRO_TELL: Final = "hiro.tell"
PEOPLE_ACT: Final = "people.act"

# What is approved with the app itself, from its declaration and its claim: a different one waits
SITE_ADDRESS: Final = "site.address"  # its subject: the address people are sent to, with a sign-in code
SITE_NAME: Final = "site.name"  # its subject: "<name>:<port>", the LAN name and the port it fronts

# The owner's words for each (the Extensions page, the refusals)
WORDS: Final[dict[str, str]] = {
    PEOPLE_SEE: "read the people list: names, WhatsApp numbers, roles",
    PEOPLE_NOTIFY: "notify people on WhatsApp: text, a picture or a voice note",
    AI_USE: "ask AI for its jobs, on the profiles the owner picks",
    VOICE_SPEAK: "make spoken clips in the house's voices",
    AI_SEARCH: "use the search models: turn texts into vectors and rank them",
    APPS_ASK: "ask another app for its data",
    HIRO_TELL: "put text before Hiro when Hiro checks on the apps",
    PEOPLE_ACT: "act for the people signed in to it, with their own rights",
    SITE_ADDRESS: "send signed-in people to its address",
    SITE_NAME: "take a name on the network for a port on this machine",
}
ASKABLE: Final[frozenset[str]] = frozenset(
    {PEOPLE_SEE, PEOPLE_NOTIFY, AI_USE, VOICE_SPEAK, AI_SEARCH, APPS_ASK, HIRO_TELL, PEOPLE_ACT}
)


class AppAsk(BaseModel):
    """One thing an app asks to do on its own (its declaration's ``asks``). ``permission`` is a plain string: an id
    this core doesn't know is shown as not understood and never approved, and never refuses the connect."""

    permission: str
    to: str | None = None  # the app asked, for apps.ask only
    required: bool = True  # the app can't work without it: declining it declines the app
    why: str = ""  # one line for the owner


# ---------------------------------------------------------------------------
# Who may call what
# ---------------------------------------------------------------------------

ALWAYS: Final = "always"  # every paired app, unasked
NEVER: Final = "never"  # no app, and no person through an app
NOT_ON_ITS_OWN: Final = "not_on_its_own"  # only a person through the app (or nobody, with no person right)

OWNER_ONLY: Final[tuple[str, str]] = ("", "")  # a person right only the Owner holds (people and roles)
PersonRight = tuple[str, str] | None  # (core feature, action), OWNER_ONLY, or None: the app's own need decides


@dataclass(frozen=True)
class Need:
    """What one core method needs from an app: ``app`` on its own (ALWAYS, NEVER, NOT_ON_ITS_OWN or a permission
    id), and ``person``, the right a person signed in through the app needs (None: a proof changes nothing)."""

    app: str
    person: PersonRight = None


APP_METHODS: Final[dict[str, Need]] = {
    METHOD_CORE_INFO: Need(ALWAYS),
    METHOD_LOGS_SEND: Need(ALWAYS),
    METHOD_SITES_LIST: Need(ALWAYS),
    METHOD_EXTENSIONS_LIST: Need(ALWAYS),
    METHOD_ROLES_IMPORT_RIGHTS: Need(ALWAYS),
    METHOD_WHATSAPP_STATUS: Need(ALWAYS),
    METHOD_AI_PROFILES: Need(ALWAYS),
    METHOD_VOICE_PROFILES: Need(ALWAYS),
    METHOD_AUTH_CODE: Need(ALWAYS),
    METHOD_AUTH_END: Need(ALWAYS),
    METHOD_PEOPLE_LIST: Need(PEOPLE_SEE),
    METHOD_PEOPLE_ADD: Need(NOT_ON_ITS_OWN, OWNER_ONLY),
    METHOD_PEOPLE_UPDATE: Need(NOT_ON_ITS_OWN, OWNER_ONLY),
    METHOD_ROLES_ADD: Need(NEVER),
    METHOD_ROLES_RENAME: Need(NEVER),
    METHOD_ROLES_REMOVE: Need(NEVER),
    METHOD_NOTIFY: Need(PEOPLE_NOTIFY),
    METHOD_WHATSAPP_SEND: Need(NOT_ON_ITS_OWN),
    METHOD_WHATSAPP_CHECK: Need(NOT_ON_ITS_OWN, OWNER_ONLY),
    METHOD_AI_ASK: Need(AI_USE),
    METHOD_AI_CHAT: Need(AI_USE),
    METHOD_AI_USES_SET: Need(NOT_ON_ITS_OWN, ("ai.profiles", "change")),
    METHOD_VOICE_USES_SET: Need(NOT_ON_ITS_OWN, ("ai.profiles", "change")),
    METHOD_VOICE_SPEAK: Need(VOICE_SPEAK),
    METHOD_AI_EMBED: Need(AI_SEARCH),
    METHOD_AI_RERANK: Need(AI_SEARCH),
    METHOD_MEMORY_SETTINGS: Need(AI_SEARCH),
    METHOD_KNOWLEDGE_SETTINGS: Need(AI_SEARCH),
    METHOD_EXTENSIONS_ASK: Need(APPS_ASK),
    METHOD_SITES_CLAIM: Need(SITE_NAME),
}

# What the core asks of an app, and what the app must be approved for to be asked it
CORE_ASKS: Final[dict[str, str]] = {METHOD_EXTENSION_STATE: HIRO_TELL}

# ---------------------------------------------------------------------------
# On the wire
# ---------------------------------------------------------------------------

# The person's proof, in a request's params; the core strips it before the method's handler runs
PARAM_SIGNED_IN: Final = "_signed_in"

# The refusals (never at connect): data {permission, to?, waiting}, {right}, or nothing
NOT_APPROVED: Final = "not_approved"
NOT_ALLOWED: Final = "not_allowed"
SIGN_IN_AGAIN: Final = "sign_in_again"

# core → app: what it is approved for, and what waits, after the owner changed it: {approved: [...], waiting: [...]}
EVENT_APPROVAL_CHANGED: Final = "approval.changed"


class ApprovedItem(BaseModel):
    """One item the owner approved: a permission, and its subject where it has one (the app asked, the address,
    the name and port)."""

    permission: str
    subject: str = ""


class Approval(BaseModel):
    """What an app is approved for and what waits, as the welcome and ``approval.changed`` carry it. ``approved``
    None: an app paired before approvals, approved for everything until it declares what it asks."""

    approved: list[ApprovedItem] | None = None
    waiting: list[ApprovedItem] = Field(default_factory=list)
