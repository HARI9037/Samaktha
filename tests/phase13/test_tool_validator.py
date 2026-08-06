"""Phase 13.7 — ToolValidator: input, resource and permission validation."""

from app.tools.framework import (
    ToolContext,
    ToolPermission,
    ToolPolicy,
    ToolValidator,
)

SCHEMA = {
    "command": {"type": "string", "required": True, "max_length": 64},
    "timeout_s": {"type": "int", "min": 1, "max": 300},
    "mode": {"type": "string", "enum": ["fast", "safe"]},
    "ratio": {"type": "float"},
    "tags": {"type": "list"},
}


def test_required_field_missing():
    errors = ToolValidator().validate_arguments("shell", {"timeout_s": 5}, SCHEMA)
    assert any("command" in error and "missing required" in error for error in errors)


def test_valid_arguments():
    assert (
        ToolValidator().validate_arguments(
            "shell",
            {"command": "echo hi", "timeout_s": 5, "mode": "safe", "ratio": 0.5, "tags": ["a"]},
            SCHEMA,
        )
        == []
    )


def test_type_mismatch():
    errors = ToolValidator().validate_arguments("shell", {"timeout_s": "fast"}, SCHEMA)
    assert any("timeout_s" in error and "integer" in error for error in errors)


def test_enum_violation():
    errors = ToolValidator().validate_arguments("shell", {"mode": "nope"}, SCHEMA)
    assert any("one of" in error for error in errors)


def test_length_bounds():
    errors = ToolValidator().validate_arguments(
        "shell", {"command": "x" * 100}, SCHEMA
    )
    assert any("max length" in error for error in errors)


def test_numeric_bounds():
    errors = ToolValidator().validate_arguments(
        "shell", {"timeout_s": 999}, SCHEMA
    )
    assert any("above maximum" in error for error in errors)
    errors = ToolValidator().validate_arguments(
        "shell", {"timeout_s": 0}, SCHEMA
    )
    assert any("below minimum" in error for error in errors)


def test_empty_schema_accepts_anything():
    assert ToolValidator().validate_arguments("tool", {"whatever": object()}, {}) == []


def test_resource_arguments_must_not_be_empty():
    for key in ("path", "url", "command", "query"):
        errors = ToolValidator().validate_arguments("tool", {key: "   "}, SCHEMA)
        assert any(key in error and "not be empty" in error for error in errors)


def test_validate_or_raise():
    from app.tools.framework import ToolValidationError

    import pytest

    validator = ToolValidator()
    validator.validate_arguments_or_raise("shell", {"command": "echo hi"}, SCHEMA)
    with pytest.raises(ToolValidationError):
        validator.validate_arguments_or_raise("shell", {}, SCHEMA)


def test_missing_permissions_none_context():
    policy = ToolPolicy(permissions=(ToolPermission.EXECUTE,))
    assert ToolValidator().missing_permissions(policy, None) == []


def test_missing_permissions_with_context():
    policy = ToolPolicy(permissions=(ToolPermission.READ, ToolPermission.EXECUTE))
    context = ToolContext(granted_permissions=("read",))
    missing = ToolValidator().missing_permissions(policy, context)
    assert missing == [ToolPermission.EXECUTE]


def test_missing_permissions_fully_granted():
    policy = ToolPolicy(permissions=(ToolPermission.READ,))
    context = ToolContext(granted_permissions=("read",))
    assert ToolValidator().missing_permissions(policy, context) == []


def test_policy_without_permissions_needs_nothing():
    policy = ToolPolicy()
    context = ToolContext()
    assert ToolValidator().missing_permissions(policy, context) == []
