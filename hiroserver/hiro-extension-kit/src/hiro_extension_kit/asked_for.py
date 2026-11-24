"""The person an ask is for (unified communication, phase 3): when the core asks the app on someone's behalf (Hiro
reading the home for the person chatting), it names them in the params (`_for_person`, the SDK's FOR_PERSON), and the
app answers with that person's rights. The core never filters an answer: the app enforces rights for its own users
(design.md, rule 5).

    async def _state(params):
        who = await asked_for(params)  # None: the core asks for itself
        if who is not None and not who.can("people"):
            return {"note": "...may not see who is home"}

The person comes with their rights as the route check has a signed-in caller's (`auth.access.PersonRights`, one shape
for both): their roles and each role's rights from the family copy (family.py). Someone the app doesn't know, or
someone the owner gave No access to the app, has no rights.
"""

from typing import Any

from hiro_channel_sdk.constants import FOR_PERSON
from sqlmodel import Session

from .auth import access
from .auth.access import PersonRights
from .auth.models import AppUser, CorePerson
from .db import run_db


def _read(session: Session, person_id: str) -> PersonRights:
    person = session.get(CorePerson, person_id)
    if person is None:  # not in the app's family copy: someone it doesn't know
        return PersonRights(person_id)
    user = session.get(AppUser, person_id)
    if user is not None and user.denied:  # the owner chose No access to this app for them
        return PersonRights(person_id)
    return PersonRights(person_id, access.held(session, person.role_ids))


async def asked_for(params: dict[str, Any]) -> PersonRights | None:
    """The person the core asks for, with their rights; None when the core asks for itself."""
    person_id = params.get(FOR_PERSON)
    if person_id is None:
        return None
    return await run_db(_read, str(person_id))
