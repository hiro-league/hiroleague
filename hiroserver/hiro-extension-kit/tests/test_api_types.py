"""The frontend's types from the API description (api_types.py): models that share a name are caught, whoever's."""

import pytest

from hiro_extension_kit.api_types import clashes, generate


def test_module_qualified_names_are_clashes_and_fastapis_form_bodies_are_not():
    schemas = {"nethiro__auth__api__UserIn": {}, "hiro_extension_kit__auth__api__UserIn": {}, "Board": {},
               "Body_upload_image_api_floors__floor_id__plan_image_post": {}}
    assert clashes({"components": {"schemas": schemas}}) == ["hiro_extension_kit__auth__api__UserIn", "nethiro__auth__api__UserIn"]
    with pytest.raises(SystemExit, match="share a name"):
        generate({"components": {"schemas": schemas}})


def test_a_model_becomes_a_type_with_its_line():
    spec = {"components": {"schemas": {"Ok": {"description": "It worked.", "type": "object", "required": ["ok"],
                                              "properties": {"ok": {"type": "boolean"}}}}}}
    out = generate(spec)
    assert "/** It worked. */" in out and "export type Ok = {" in out and "ok: boolean;" in out


def test_types_for_the_shapes_the_models_use():
    """Shared-code plan, step 1: every app's tests had this."""
    from hiro_extension_kit.api_types import ts

    assert ts({"anyOf": [{"type": "string"}, {"type": "null"}]}) == "string | null"
    assert ts({"type": "array", "prefixItems": [{"type": "string"}, {"type": "integer"}]}) == "[string, number]"
    assert ts({"type": "object", "additionalProperties": {"type": "number"}}) == "Record<string, number>"
    assert ts({"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "null"}]}}) == "(string | null)[]"
    assert ts({"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "string", "default": ""},
                                                "in": {"type": "number"}},
               "required": ["a", "in"], "additionalProperties": True}) == \
        '{\n\ta: number;\n\tb?: string;\n\tin: number;\n}'  # (no index signature for extra keys)
    assert ts({"$ref": "#/components/schemas/PlanDoc-Input"}) == "PlanDocInput"
