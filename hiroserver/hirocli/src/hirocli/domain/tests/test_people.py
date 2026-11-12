"""Phase 6: the family list, its roles, and the admin's own sign-in."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.domain.admin_sign_in import (
    check_password,
    end_session,
    give_sign_in,
    hash_password,
    password_matches,
    session_person,
    start_session,
)
from hirocli.domain.people import (
    PeopleError,
    add_person,
    add_role,
    anyone_signs_in,
    clear_sign_in,
    find_by_number,
    list_people,
    list_roles,
    remove_person,
    remove_role,
    rename_role,
    update_person,
)


def test_owner_adult_and_kid_are_there_from_the_start(tmp_path: Path) -> None:
    roles = list_roles(tmp_path)
    assert [(r.role_id, r.name, r.built_in) for r in roles] == [
        ("owner", "Owner", True),
        ("adult", "Adult", False),
        ("kid", "Kid", False),
    ]


def test_people_are_listed_by_role_then_name(tmp_path: Path) -> None:
    add_person(tmp_path, name="Nour", role_id="kid")
    add_person(tmp_path, name="Mona", role_id="adult", whatsapp="+20 100 000 0002")
    add_person(tmp_path, name="Michel", role_id="owner")
    people = list_people(tmp_path)
    assert [p.name for p in people] == ["Michel", "Mona", "Nour"]
    assert people[1].whatsapp == "201000000002"


def test_a_number_belongs_to_one_person_and_needs_the_country_code(tmp_path: Path) -> None:
    add_person(tmp_path, name="Mona", role_id="adult", whatsapp="201000000002")
    with pytest.raises(PeopleError, match="already has that WhatsApp number"):
        add_person(tmp_path, name="Sara", role_id="adult", whatsapp="+20 100 000 0002")
    with pytest.raises(PeopleError, match="country code"):
        add_person(tmp_path, name="Sara", role_id="adult", whatsapp="1234")
    assert find_by_number(tmp_path, "+20-100-000-0002").name == "Mona"


def test_an_unknown_role_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PeopleError, match="no role"):
        add_person(tmp_path, name="Sara", role_id="guest")


def test_the_only_owner_stays_owner(tmp_path: Path) -> None:
    michel = add_person(tmp_path, name="Michel", role_id="owner")
    with pytest.raises(PeopleError, match="only Owner"):
        update_person(tmp_path, michel.person_id, role_id="adult")
    with pytest.raises(PeopleError, match="only Owner"):
        remove_person(tmp_path, michel.person_id)
    add_person(tmp_path, name="Mona", role_id="owner")
    assert update_person(tmp_path, michel.person_id, role_id="adult").role_id == "adult"


def test_roles_can_be_added_renamed_and_removed_but_not_owner_or_one_in_use(tmp_path: Path) -> None:
    guest = add_role(tmp_path, "Guest")
    assert guest.role_id == "guest"
    assert add_role(tmp_path, "Guest!").role_id == "guest-2"
    with pytest.raises(PeopleError, match="already a role"):
        add_role(tmp_path, "guest")
    assert rename_role(tmp_path, "guest", "Visitor").name == "Visitor"
    with pytest.raises(PeopleError, match="built in"):
        rename_role(tmp_path, "owner", "Boss")
    sara = add_person(tmp_path, name="Sara", role_id="guest")
    with pytest.raises(PeopleError, match="still given to Sara"):
        remove_role(tmp_path, "guest")
    update_person(tmp_path, sara.person_id, role_id="adult")
    remove_role(tmp_path, "guest")
    with pytest.raises(PeopleError, match="built in"):
        remove_role(tmp_path, "owner")


def test_passwords_are_hashed_and_checked() -> None:
    stored = hash_password("correct horse")
    assert stored.startswith("scrypt$") and "correct horse" not in stored
    assert password_matches("correct horse", stored)
    assert not password_matches("wrong horse", stored)
    with pytest.raises(PeopleError, match="at least 8"):
        hash_password("short")


def test_sign_in_and_sessions(tmp_path: Path) -> None:
    assert not anyone_signs_in(tmp_path)
    michel = add_person(tmp_path, name="Michel", role_id="owner")
    give_sign_in(tmp_path, michel.person_id, sign_in="michel", password="correct horse")
    assert anyone_signs_in(tmp_path)
    assert check_password(tmp_path, "MICHEL", "correct horse").person_id == michel.person_id
    assert check_password(tmp_path, "michel", "wrong horse") is None
    assert check_password(tmp_path, "nobody", "correct horse") is None

    token, _ = start_session(tmp_path, michel.person_id)
    assert session_person(tmp_path, token).name == "Michel"
    assert session_person(tmp_path, "made-up") is None
    end_session(tmp_path, token)
    assert session_person(tmp_path, token) is None


def test_someone_signed_in_by_an_offered_way_has_a_session_without_a_password(tmp_path: Path) -> None:
    """Home Assistant's login (an extension's offered way) gives a person a session though they have no name and
    password of their own; removing them still ends it."""
    mark = add_person(tmp_path, name="Mark", role_id="adult")
    assert mark.sign_in is None
    token, _ = start_session(tmp_path, mark.person_id)
    assert session_person(tmp_path, token).name == "Mark"
    remove_person(tmp_path, mark.person_id)
    assert session_person(tmp_path, token) is None


def test_a_new_password_ends_the_old_sessions(tmp_path: Path) -> None:
    michel = add_person(tmp_path, name="Michel", role_id="owner")
    give_sign_in(tmp_path, michel.person_id, sign_in="michel", password="correct horse")
    token, _ = start_session(tmp_path, michel.person_id)
    give_sign_in(tmp_path, michel.person_id, sign_in="michel", password="battery staple")
    assert session_person(tmp_path, token) is None


def test_the_last_sign_in_is_kept_and_names_are_unique(tmp_path: Path) -> None:
    michel = add_person(tmp_path, name="Michel", role_id="owner")
    mona = add_person(tmp_path, name="Mona", role_id="adult")
    give_sign_in(tmp_path, michel.person_id, sign_in="michel", password="correct horse")
    with pytest.raises(PeopleError, match="already signs in as"):
        give_sign_in(tmp_path, mona.person_id, sign_in="Michel", password="correct horse")
    with pytest.raises(PeopleError, match="only one who can sign in"):
        clear_sign_in(tmp_path, michel.person_id)
    give_sign_in(tmp_path, mona.person_id, sign_in="mona", password="correct horse")
    token, _ = start_session(tmp_path, mona.person_id)
    clear_sign_in(tmp_path, mona.person_id)
    assert session_person(tmp_path, token) is None
    with pytest.raises(PeopleError, match="spaces"):
        give_sign_in(tmp_path, mona.person_id, sign_in="mona h", password="correct horse")
