"""Every route's rule (hiro_commons.rules): the shape the kit's route check and the core admin's share, and its
matching."""

import pytest

from hiro_commons.rules import LIST, Rule, Whose, by_lookup, by_person, for_features, matches, rule_for

RULES = (
    Rule("/api/health", "public"),
    for_features("/api/items/{item_id}", "items", methods=("DELETE",), action="delete"),
    for_features("/api/items", "items"),
    Rule("/api/users", "owner"),
)


def test_a_path_covers_itself_and_what_is_under_it_by_whole_parts():
    rule = for_features("/api/logs", "logs")
    assert matches(rule, "GET", "/api/logs")
    assert matches(rule, "GET", "/api/logs/today")
    assert not matches(rule, "GET", "/api/logsx")


def test_methods_narrow_a_rule_and_a_head_is_a_get():
    rule = for_features("/api/items", "items", methods=("GET",))
    assert matches(rule, "HEAD", "/api/items")
    assert not matches(rule, "POST", "/api/items")
    assert matches(for_features("/api/items", "items"), "PUT", "/api/items")  # no methods: every method


def test_the_first_rule_that_matches_wins_and_a_route_without_one_has_none():
    assert rule_for(RULES, "DELETE", "/api/items/{item_id}") is RULES[1]
    assert rule_for(RULES, "PUT", "/api/items/{item_id}") is RULES[2]  # the narrow rule names DELETE only
    assert rule_for(RULES, "GET", "/api/nowhere") is None


def test_a_features_rule_keeps_what_it_is_given():
    rule = for_features("/api/study/{person_id}", "study", "reports", methods=["GET"], action="see",
                        whose=by_person("person_id"))
    assert rule == Rule("/api/study/{person_id}", "features", ("study", "reports"), ("GET",), "see",
                        Whose("param", param="person_id"))


def test_whose_names_where_a_records_person_comes_from():
    assert by_person("person_id") == Whose("param", param="person_id")
    assert by_lookup("study", "study_id") == Whose("lookup", param="study_id", lookup="study")
    assert LIST == Whose("list")
    assert for_features("/api/x", "x").whose is None  # not about people's things


@pytest.mark.parametrize("make", [lambda: by_person(""), lambda: by_lookup("", "id"), lambda: by_lookup("study", "")])
def test_whose_refuses_a_missing_name(make):
    with pytest.raises(ValueError):
        make()
