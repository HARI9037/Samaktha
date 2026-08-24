"""Input, resource and permission validation for tools."""

from __future__ import annotations

from typing import Any

from app.tools.framework.errors import ToolValidationError
from app.tools.framework.models import ToolContext, ToolPermission, ToolPolicy

_TYPE_CHECKS = {
    "string": (str, "string"),
    "int": (int, "integer"),
    "integer": (int, "integer"),
    "float": (float, "float"),
    "number": ((int, float), "number"),
    "bool": (bool, "boolean"),
    "boolean": (bool, "boolean"),
    "list": (list, "list"),
    "array": (list, "array"),
    "dict": (dict, "object"),
    "object": (dict, "object"),
}


class ToolValidator:
    """Validates arguments against a tool's declared input schema.

    The schema is a plain dict in the form::

        {
          "command": {"type": "string", "required": True, "max_length": 1024},
          "timeout_s": {"type": "int", "min": 1, "max": 300},
        }

    Tools with an empty schema accept any arguments (backwards
    compatibility with legacy tools that self-validate).
    """

    def validate_arguments(
        self, tool_id: str, arguments: dict[str, Any], input_schema: dict[str, Any]
    ) -> list[str]:
        """Return a list of human-readable errors (empty when valid)."""
        if not input_schema:
            return []
        if arguments is None:
            arguments = {}

        # Native tools use both the historical flat schema and standard
        # JSON Schema object/properties/required form. Normalize the latter
        # without weakening the former.
        if input_schema.get("type") == "object" and isinstance(
            input_schema.get("properties"), dict
        ):
            required = set(input_schema.get("required") or ())
            input_schema = {
                name: {**spec, "required": name in required}
                for name, spec in input_schema["properties"].items()
                if isinstance(spec, dict)
            }

        errors: list[str] = []
        for field, spec in input_schema.items():
            if not isinstance(spec, dict):
                continue
            present = field in arguments
            if spec.get("required") and not present:
                errors.append(f"{tool_id}: missing required argument '{field}'")
                continue
            if not present:
                continue

            value = arguments[field]
            expected_type = spec.get("type", "string")
            if expected_type in _TYPE_CHECKS:
                expected_kind, label = _TYPE_CHECKS[expected_type]
                if not isinstance(value, expected_kind) or isinstance(value, bool) and expected_kind is int:
                    if not (expected_kind is float and isinstance(value, (int, float)) and not isinstance(value, bool)):
                        errors.append(
                            f"{tool_id}: argument '{field}' must be a {label}, got {type(value).__name__}"
                        )
                        continue

            if expected_type in ("string",) and isinstance(value, str):
                max_length = spec.get("max_length", spec.get("maxLength"))
                if max_length is not None and len(value) > max_length:
                    errors.append(
                        f"{tool_id}: argument '{field}' exceeds max length {max_length}"
                    )
                min_length = spec.get("min_length", spec.get("minLength"))
                if min_length is not None and len(value) < min_length:
                    errors.append(
                        f"{tool_id}: argument '{field}' below min length {min_length}"
                    )
                enum_values = spec.get("enum")
                if enum_values and value not in enum_values:
                    errors.append(
                        f"{tool_id}: argument '{field}' must be one of {enum_values}"
                    )

            if expected_type in ("int", "integer", "float", "number") and isinstance(value, (int, float)) and not isinstance(value, bool):
                minimum = spec.get("min", spec.get("minimum"))
                if minimum is not None and value < minimum:
                    errors.append(f"{tool_id}: argument '{field}' below minimum {minimum}")
                maximum = spec.get("max", spec.get("maximum"))
                if maximum is not None and value > maximum:
                    errors.append(f"{tool_id}: argument '{field}' above maximum {maximum}")

        for key in ("path", "url", "command", "query"):
            if key in arguments:
                value = arguments[key]
                if value is None or (isinstance(value, str) and not value.strip()):
                    errors.append(f"{tool_id}: argument '{key}' must not be empty")
        return errors

    def validate_arguments_or_raise(
        self, tool_id: str, arguments: dict[str, Any], input_schema: dict[str, Any]
    ) -> None:
        errors = self.validate_arguments(tool_id, arguments, input_schema)
        if errors:
            raise ToolValidationError("; ".join(errors))

    def missing_permissions(
        self, policy: ToolPolicy, context: ToolContext | None
    ) -> list[ToolPermission]:
        """Return the policy permissions the context has not granted."""
        if context is None or not policy.permissions:
            return []
        return [permission for permission in policy.permissions if not context.permits(permission)]
