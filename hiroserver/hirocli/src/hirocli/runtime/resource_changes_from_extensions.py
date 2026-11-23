"""An extension says something it keeps changed (unified communication, phase 3): its ``resource.changed``.

The extension sends ``resource.changed {resource, ids?}`` as itself: a hint, never the data. The manager's one event
registry hands it here; the core checks the resource is one the extension's description names in ``offers.tells``,
then puts it on the core's bus (``DomainEventType.EXTENSION_RESOURCE_CHANGED``, with the extension's name), where
whichever feature keeps a copy of it subscribes and reads it again. A resource it never declared is dropped, with one
warning (Michel, Nov 24). Events aren't queued: a feature that keeps a copy also reads it when the extension connects.

The event of the same name the core sends phones (resource_change_broadcaster.py) is apart and untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import EVENT_TYPE_RESOURCE_CHANGED
from hiro_commons.log import Logger

from ..domain.events import DomainEvent, DomainEventType, get_domain_event_bus
from ..domain.extensions import KIND_APP, KIND_CHANNEL

if TYPE_CHECKING:
    from .extension_manager import ExtensionManager
    from .server_context import ServerContext

log = Logger.get("EXTENSIONS")

ANY_KIND: frozenset[str] = frozenset({KIND_APP, KIND_CHANNEL})


def declared_resources(info: dict[str, Any]) -> set[str]:
    """The resources an extension's description says it tells about (``offers.tells``)."""
    offers = info.get("offers") or {}
    return {str(t.get("resource") or "") for t in offers.get("tells") or [] if isinstance(t, dict)} - {""}


def change_from(info: dict[str, Any], data: dict[str, Any]) -> tuple[str, list[str]] | str:
    """The change an event says, ``(resource, ids)``; or, when it can't be passed on, why (pure)."""
    resource = data.get("resource")
    if not isinstance(resource, str) or not resource:
        return "it names no resource"
    if resource not in declared_resources(info):
        return f"{resource!r} isn't in its offers.tells"
    ids = data.get("ids") or []
    if not isinstance(ids, list):
        return "its ids aren't a list"
    return resource, [str(i) for i in ids]


class ResourceChangesFromExtensions:
    """Hands an extension's ``resource.changed`` to the core's bus."""

    def __init__(self, ctx: ServerContext, manager: ExtensionManager) -> None:
        self._ctx = ctx
        self._manager = manager

    def register(self) -> None:
        self._manager.register_event_handler(EVENT_TYPE_RESOURCE_CHANGED, self.handle, ANY_KIND)

    async def handle(self, extension_id: str, _event_type: str, data: dict[str, Any]) -> None:
        live = self._manager.snapshot(kind=None).get(extension_id) or {}
        name = str(live.get("name") or extension_id)
        change = change_from(dict(live.get("info") or {}), data)
        if isinstance(change, str):
            log.warning(f"⚠️ Extension change dropped — {name} · {change}", extension_id=extension_id)
            return
        resource, ids = change
        get_domain_event_bus().publish(DomainEvent(
            type=DomainEventType.EXTENSION_RESOURCE_CHANGED,
            workspace_path=self._ctx.workspace_path,
            payload={"extension": name, "resource": resource, "ids": ids},
        ))
