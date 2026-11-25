"""Every admin route's rule (Permissions phase 2): the core features that open it, and the action it needs.

The rule's shape and matching are the commons' (``hiro_commons.rules``), the same as every app's; the check is the
SDK's one check (``hiro_channel_sdk.access.allowed``) over the roles a person holds. ``require_rule`` runs on every
``/api`` route (a dependency of ``api.py``'s router), matched by the route's declared path.

- **A route with no rule answers the owner only,** and the admin's contract test fails for one
  (``tests/test_route_rules.py``).
- **Reading (GET) needs ``see``;** any other method the action the rule names, else the feature's first action after
  ``see`` (``change`` for most).
- **A grant for their own things opens no admin route:** the conversations and memories rules name no ``whose``, so
  only a grant for everyone's passes. "Their own" is a device's and a chat channel's (Permissions phase 3).
- **A shared read names every feature whose page reads it** (the characters, the catalog, the preferences).
- **First match wins:** exact paths and narrow prefixes come before wide ones.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
from hiro_channel_sdk.access import SEE, allowed
from hiro_commons.log import Logger
from hiro_commons.rules import Rule, for_features, rule_for
from starlette.concurrency import run_in_threadpool

from hirocli.domain.access import AdminAccess, admin_access
from hirocli.domain.core_features import CORE_BY_ID, CORE_FEATURES, NOT_IN_ADMIN

log = Logger.get("ADMIN.RULES")

BY_ID = CORE_BY_ID
# Every feature that opens a page: what the shell's own reads (the top bar, the live status) need
ADMIN = tuple(f.id for f in CORE_FEATURES if f.id not in NOT_IN_ADMIN)
GET = ("GET",)
R = for_features

ADMIN_RULES: tuple[Rule, ...] = (
    # Signing in, and the Apps card: outside the features
    Rule("/api/auth", "public"),
    Rule("/api/apps", "signed_in"),
    # The shell, on every page
    R("/api/config", *ADMIN, methods=GET),
    R("/api/runtime/status", *ADMIN),
    R("/api/events/status", *ADMIN),
    # Server: workspaces, gateways, metrics
    # Any folder, opened on the server's own screen: the owner's
    Rule("/api/workspaces/open-folder", "owner"),
    Rule("/api/open-path", "owner"),
    R("/api/workspaces", "server"),
    R("/api/gateways", "server"),
    R("/api/metrics", "server"),
    # Extensions and the channel plugins
    # Permissions phase 8: approving an app reaches people and roles: the owner's alone
    Rule("/api/extensions/{extension_id}/approval", "owner"),
    R("/api/extensions", "extensions"),
    R("/api/channels", "extensions"),
    # Devices: Logs reads their names
    R("/api/devices", "devices", "logs", methods=GET),
    R("/api/devices", "devices"),
    # Hiro's characters: their names on Chats, Memories, Graph runs and the chat
    R("/api/characters/{character_id}/resolved", "assistant.characters", "conversations", methods=GET),
    R("/api/characters/{character_id}", "assistant.characters", "logs.runs", methods=GET),
    R("/api/characters", "assistant.characters", "conversations", "memories", "logs.runs", methods=GET),
    R("/api/characters", "assistant.characters"),
    # Conversations. Writing to Hiro is talking to it: the turn is the signed-in person's, in their own conversation
    R("/api/chat-channels/{channel_id}/messages/send", "assistant", action="talk"),
    R("/api/chat-channels/{channel_id}/messages", "conversations", methods=GET),
    R("/api/chat-channels", "conversations", "memories", "logs.runs", methods=GET),
    R("/api/chat-channels", "conversations"),
    # Memories: the graph's routes sit under /api/knowledge/graph, before the knowledge base's
    R("/api/knowledge/graph/export", "memories", action=SEE),
    R("/api/knowledge/graph/groups", "memories"),
    R("/api/knowledge/graph/episodes", "memories", action=SEE),
    R("/api/knowledge/graph/chunks-detail", "memories", action=SEE),
    R("/api/knowledge/graph/search-chunks", "memories", action=SEE),
    R("/api/memory/list", "memories"),
    R("/api/memory/delete", "memories"),
    R("/api/memory/clear-group", "memories"),
    Rule("/api/memory/clear", "owner"),
    Rule("/api/memory/{memory_id}", "owner"),
    # The knowledge base; the embedding and reranking models are also Settings' and Profiles'
    R("/api/knowledge/events", "knowledge", "memories"),
    R("/api/knowledge/embedders", "settings", "ai.profiles"),
    R("/api/knowledge/rerankers", "settings", "ai.profiles"),
    # Reading a folder or a file of the server to ingest it: changing the knowledge base (known limit: any path)
    R("/api/knowledge/scan-folder", "knowledge", action="change"),
    R("/api/knowledge/preview-file", "knowledge", action="change"),
    R("/api/knowledge/answer", "knowledge", action=SEE),
    R("/api/knowledge/search", "knowledge", action=SEE),
    R("/api/knowledge", "knowledge"),
    # AI: providers and models (keys, costs) apart from the profiles (which model and voice does each job)
    R("/api/catalog/reload", "ai.providers"),
    R("/api/catalog", "ai.providers", "ai.profiles", "assistant.characters", "settings", methods=GET),
    R("/api/providers", "ai.providers", "ai.profiles", "settings", methods=GET),
    R("/api/providers", "ai.providers"),
    R("/api/ai/usage", "logs.usage"),
    R("/api/ai/plans", "ai.providers", "ai.profiles", methods=GET),
    R("/api/ai/plans", "ai.providers"),
    R("/api/ai/local-servers", "ai.providers", "ai.profiles", methods=GET),
    R("/api/ai/local-servers", "ai.providers"),
    R("/api/ai", "ai.providers", "ai.profiles", methods=GET),
    R("/api/ai", "ai.profiles"),
    R("/api/voice/clip-cache", "settings"),
    R("/api/voice", "ai.profiles"),
    R("/api/search/uses", "ai.profiles"),
    R("/api/image-lab", "ai.images", action="run"),
    # Settings. Known limit: saving writes any section, so a profiles editor can write any setting
    R("/api/preferences/schema", "settings"),
    R("/api/preferences", "settings", "assistant.characters", "memories", "ai.profiles", methods=GET),
    R("/api/preferences", "settings", "ai.profiles"),
    # Logs, apart from the graph runs (what Hiro recalled about people)
    Rule("/api/logs/clear", "owner"),
    R("/api/logs", "logs"),
    R("/api/graph-runs", "logs.runs"),
    # People and roles are the owner's
    Rule("/api/people", "owner"),
    Rule("/api/roles", "owner"),
    # The ways into HiroLeague (People → Sign-in): the owner's
    Rule("/api/sign-in", "owner"),
)


def needed(rule: Rule, feature: str, method: str) -> str:
    """The action a route needs in one of its features: the rule's own, else ``see`` to read, else the feature's
    first action after ``see`` (``see`` for a feature that has nothing more, like the logs)."""
    if rule.action:
        return rule.action
    if method in ("GET", "HEAD"):
        return SEE
    ids = [r.id for r in BY_ID[feature].rights]
    return next((r for r in ids if r != SEE), SEE)


def rule_allows(access: AdminAccess, rule: Rule | None, method: str) -> bool:
    """Whether this access opens a route with this rule. No rule, or an owner's rule: the owner only."""
    if access.owner:
        return True
    if rule is None or rule.who == "owner":
        return False
    if rule.who in ("public", "signed_in"):
        return True
    return any(allowed(access.roles, f, needed(rule, f, method), BY_ID) for f in rule.features)


def refusal(rule: Rule | None, method: str) -> str:
    """The words a refusal says: the permission that would open the route."""
    if rule is None or rule.who == "owner":
        return "Only an owner can do this."
    wanted = []
    for f in rule.features:
        action = needed(rule, f, method)
        name = next((r.name for r in BY_ID[f].rights if r.id == action), action)
        wanted.append(BY_ID[f].name if action == SEE else f"{BY_ID[f].name}: {name}")
    return f"Your roles don't include {' or '.join(wanted)}; ask the owner to give it on People → Roles."


async def require_rule(request: Request) -> None:
    """A dependency of every /api route: the route's rule against the signed-in person's roles (the sign-in
    middleware, admin_svelte/routes/auth.py, has already refused anyone not signed in, and keeps the person here)."""
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    rule = rule_for(ADMIN_RULES, request.method, path)
    if rule is not None and rule.who == "public":
        return
    person = getattr(request.state, "admin_person", None)
    if person is None:
        raise HTTPException(status_code=401, detail="Sign in to the admin first.")
    access = await run_in_threadpool(admin_access, Path(request.app.state.ctx.workspace_path), person.role_ids)
    if not rule_allows(access, rule, request.method):
        log.warning(f"⚠️ Admin route refused — {person.name} · {request.method} {path}", rule=rule.path if rule else "")
        raise HTTPException(status_code=403, detail=refusal(rule, request.method))
