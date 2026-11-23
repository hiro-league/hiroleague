"""What an extension offers, typed, and one form for a link to a page (the unified communication plan's phase 3).

An extension's description (``ExtensionInfo.offers``) holds four slots, each a list of typed entries, one type per
row: the core reads them by their type and refuses a description whose entry fits none (at sign-in, naming it), so it
can list and check what every extension offers without knowing the extension. A new kind of entry joins a slot as a
new type with its own fields.

=========  ============================================================  =====================================
Slot       Entry                                                         Fields
=========  ============================================================  =====================================
knows      A method other extensions may ask (a question)                method, name, says
can_do     A method other extensions may ask (an action)                 method, name, says
can_do     An offered sign-in (HomeHiro: Home Assistant)                 kind "sign_in", id, label
tells      Something it sends ``resource.changed`` for                   resource, name, says
shows      Its site: the app switcher, the Apps card, the one sign-in   kind "site", title, icon, url, roles
=========  ============================================================  =====================================

A link to a page is ``PageLink``: the app's name (``home``) or none for the core's admin, and the page with its query.
It holds no sign-in: the one sign-in already lands a signed-out person on the page. The core turns it into an address
when it shows it (hirocli ``runtime/page_links.py``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Entry(BaseModel):
    # An entry with a field its type doesn't have is refused: it is a mistake, or a type the core doesn't know yet.
    model_config = ConfigDict(extra="forbid")


class MethodEntry(_Entry):
    """A method other extensions may ask, through the core (``extensions.ask``); answered with ``register_request``."""

    method: str = Field(min_length=1)
    name: str = Field(min_length=1)
    says: str = ""


class SignInEntry(_Entry):
    """Another way to sign in, shown on the core's sign-in page while the extension is connected (constants:
    ``OFFER_KIND_SIGN_IN``); the core calls the extension's ``sign_in.start`` / ``sign_in.finish``."""

    kind: Literal["sign_in"]
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class TellsEntry(_Entry):
    """Something the extension says changed with ``resource.changed {resource, ids?}``: a hint, never the data. The
    core drops a ``resource.changed`` for a resource no entry names, with a warning."""

    resource: str = Field(min_length=1)
    name: str = Field(min_length=1)
    says: str = ""


class SiteEntry(_Entry):
    """The extension's site (constants: ``OFFER_KIND_SITE``): its card in the app switcher and the Apps card, and
    where the one sign-in sends a person back. ``roles`` [] = every role."""

    kind: Literal["site"]
    title: str = Field(min_length=1)
    icon: str = ""
    url: str = Field(min_length=1)
    roles: list[str] = Field(default_factory=list)


class ExtensionOffers(BaseModel):
    """What the extension offers: four slots of typed entries."""

    knows: list[MethodEntry] = Field(default_factory=list)  # questions it answers
    can_do: list[SignInEntry | MethodEntry] = Field(default_factory=list)  # actions it takes, sign-ins it offers
    tells: list[TellsEntry] = Field(default_factory=list)  # what it says changed
    shows: list[SiteEntry] = Field(default_factory=list)  # its site


class PageLink(BaseModel):
    """A link to one page: an app's (``app``, its name: ``home``) or the core admin's (``app`` None), and the page with
    its query (``/streams?cam=cam3``)."""

    model_config = ConfigDict(extra="forbid")

    app: str | None = None
    path: str

    @field_validator("path")
    @classmethod
    def _a_page_on_the_site(cls, path: str) -> str:
        # Only a page on that site: never another site ("//evil.example", "https://...").
        if not path.startswith("/") or path.startswith(("//", "/\\")):
            raise ValueError("a page's path starts with one / (/streams?cam=cam3)")
        return path
