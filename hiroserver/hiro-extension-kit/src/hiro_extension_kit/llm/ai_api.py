"""The HiroLeague core's AI profiles and the app's use (llm/core_ai.py), for Settings → AI from HiroLeague and the
app's profile pickers: read by every role that edits one of those
(auth/guard.py)."""

from fastapi import APIRouter
from pydantic import BaseModel

from ..hiroleague import link
from . import core_ai
from .core_ai import CoreAi

router = APIRouter(prefix="/api/ai")


class CoreAiOut(CoreAi):
    admin_url: str = ""  # Phase 7b: the core's admin ("" while unknown), for the Edit links


@router.get("")
async def core_ai_profiles() -> CoreAiOut:
    """The core's profiles and which one each use asks with; while the core doesn't answer, the last list it sent, with
    when it was read and why it's old."""
    return CoreAiOut(**(await core_ai.read()).model_dump(), admin_url=link.admin_url())


class UsePick(BaseModel):
    profile_id: str | None = None  # None: no profile picked (the use asks nothing until one is)


@router.put("/uses/{use}")
async def set_use(use: str, body: UsePick) -> CoreAiOut:
    """Phase 7b: pick the core's profile one of the app's uses asks with, saved in HiroLeague (`ai.uses.set`)."""
    await core_ai.set_use(use, body.profile_id)
    return await core_ai_profiles()
