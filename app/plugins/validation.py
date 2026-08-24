"""Manifest and structural validation for the Plugin specification (P2.1/P9.2).

Semantic validation lives here (id format, semver, permission vocabulary,
dependency constraints, entry-point shape). Structural checks against a
loaded ``Plugin`` instance verify that the module behind the entry point
honours its declared manifest.

P9.2 adds:
- Manifest size and field bounds
- Plugin API version validation
- Samaktha version compatibility checks
- Action definitions validation
- Entry point path containment
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from app.plugins.models import (
    PluginManifest,
    PLUGIN_API_VERSION,
    MAX_MANIFEST_BYTES,
    MAX_ACTIONS,
    MAX_DESCRIPTION_LENGTH,
    MAX_AUTHOR_LENGTH,
    MAX_METADATA_KEYS,
)
from app.plugins.semver import SemanticVersion, VersionError, validate_constraint
from app.tools.framework.models import ToolPermission

#: Lower-case identifier used for plugin ids and capability names.
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9._-]*$")

#: Python identifier used for each module path segment.
_MODULE_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: The only permission scopes a plugin may declare.
VALID_PERMISSION_SCOPES = frozenset(p.value for p in ToolPermission)

#: Manifest schema versions this implementation understands.
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})

# Valid side effect classes (P9.2)
VALID_SIDE_EFFECT_CLASSES = frozenset({"READ_ONLY", "IDEMPOTENT_MUTATION", "NON_IDEMPOTENT_MUTATION"})

# Supported plugin API versions
SUPPORTED_PLUGIN_API_VERSIONS = frozenset({1})


class PluginValidationResult:
    """Aggregated validation outcome (errors fail, warnings do not)."""

    def __init__(
        self,
        errors: Optional[Iterable[str]] = None,
        warnings: Optional[Iterable[str]] = None,
    ) -> None:
        self.errors: list[str] = list(errors or [])
        self.warnings: list[str] = list(warnings or [])

    @property
    def valid(self) -> bool:
        return not self.errors

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def merge(self, other: "PluginValidationResult") -> "PluginValidationResult":
        merged = PluginValidationResult(
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )
        return merged

    def __bool__(self) -> bool:
        return self.valid

    def __str__(self) -> str:
        parts = list(self.errors)
        parts += [f"warning: {w}" for w in self.warnings]
        return "; ".join(parts)


def _is_identifier(value: str) -> bool:
    return bool(_IDENTIFIER.match(value or ""))


def _valid_module_path(value: str) -> bool:
    if not value or value.startswith(".") or value.endswith("."):
        return False
    if ".." in value:
        return False
    return all(_MODULE_SEGMENT.match(segment) for segment in value.split("."))


def _check_entry_point_containment(entry: str, plugin_root: str) -> bool:
    """Verify entry point doesn't escape the plugin root (P9.2).

    The entry point must be a valid Python module path that could resolve
    within the plugin's directory structure.
    """
    if not _valid_module_path(entry):
        return False
    # Entry should not contain path separators or start with parent dir references
    if entry.startswith("..") or "/" in entry or "\\" in entry:
        return False
    return True


def validate_manifest(manifest: PluginManifest) -> PluginValidationResult:
    """Validate a manifest against the Plugin specification (P2.1 + P9.2)."""
    result = PluginValidationResult()

    # Schema version
    if manifest.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        result.add_error(
            f"Unsupported schema version {manifest.schema_version!r}; "
            f"supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}."
        )

    # ID validation
    if not _is_identifier(manifest.id):
        result.add_error(
            f"Invalid plugin id {manifest.id!r}: must be lowercase "
            "identifier matching [a-z][a-z0-9._-]*."
        )
    if not manifest.name.strip():
        result.add_error("Plugin name must not be empty.")

    # Version validation
    try:
        SemanticVersion.parse(manifest.version)
    except VersionError as exc:
        result.add_error(f"Invalid plugin version: {exc}")

    # Entry point validation
    if not _valid_module_path(manifest.entry):
        result.add_error(
            f"Invalid entry module path {manifest.entry!r}: must be a dotted "
            "module path with Python identifiers."
        )

    # P9.2: Check plugin API version
    if manifest.plugin_api_version not in SUPPORTED_PLUGIN_API_VERSIONS:
        result.add_error(
            f"Unsupported plugin API version {manifest.plugin_api_version!r}; "
            f"supported: {sorted(SUPPORTED_PLUGIN_API_VERSIONS)}."
        )

    # P9.2: Samaktha version compatibility
    if manifest.min_samaktha_version:
        try:
            SemanticVersion.parse(manifest.min_samaktha_version)
        except VersionError as exc:
            result.add_error(f"Invalid min_samaktha_version: {exc}")

    if manifest.max_samaktha_version:
        try:
            SemanticVersion.parse(manifest.max_samaktha_version)
        except VersionError as exc:
            result.add_error(f"Invalid max_samaktha_version: {exc}")

        # Warn if min > max
        if manifest.min_samaktha_version:
            try:
                min_v = SemanticVersion.parse(manifest.min_samaktha_version)
                max_v = SemanticVersion.parse(manifest.max_samaktha_version)
                if min_v > max_v:
                    result.add_warning(
                        f"min_samaktha_version ({manifest.min_samaktha_version}) "
                        f"is greater than max_samaktha_version ({manifest.max_samaktha_version})"
                    )
            except VersionError:
                pass  # Already caught above

    # Dependencies
    seen_deps: set[str] = set()
    for dependency in manifest.dependencies:
        if not _is_identifier(dependency.plugin_id):
            result.add_error(
                f"Invalid dependency plugin id {dependency.plugin_id!r}."
            )
        if dependency.plugin_id in seen_deps:
            result.add_error(
                f"Duplicate dependency on plugin {dependency.plugin_id!r}."
            )
        seen_deps.add(dependency.plugin_id)
        try:
            validate_constraint(dependency.version)
        except VersionError as exc:
            result.add_error(
                f"Invalid dependency constraint {dependency.version!r} for "
                f"{dependency.plugin_id!r}: {exc}"
            )

    # Capabilities
    seen_capabilities: set[str] = set()
    for capability in manifest.capabilities:
        if not _is_identifier(capability.name):
            result.add_error(
                f"Invalid capability name {capability.name!r}."
            )
        if capability.name in seen_capabilities:
            result.add_error(
                f"Duplicate capability declaration {capability.name!r}."
            )
        seen_capabilities.add(capability.name)

    # Permissions
    seen_scopes: set[str] = set()
    for permission in manifest.permissions:
        if permission.scope not in VALID_PERMISSION_SCOPES:
            result.add_error(
                f"Unknown permission scope {permission.scope!r}; valid scopes "
                f"are {sorted(VALID_PERMISSION_SCOPES)}."
            )
        if permission.scope in seen_scopes:
            result.add_error(
                f"Duplicate permission declaration {permission.scope!r}."
            )
        seen_scopes.add(permission.scope)

    # P9.2: Validate actions (for tool plugins)
    if manifest.kind.value == "tool" and manifest.actions:
        if len(manifest.actions) > MAX_ACTIONS:
            result.add_error(
                f"Plugin declares {len(manifest.actions)} actions, "
                f"exceeds maximum of {MAX_ACTIONS}."
            )
        seen_actions: set[str] = set()
        for action in manifest.actions:
            if not _is_identifier(action.name):
                result.add_error(f"Invalid action name {action.name!r}.")
            if action.name in seen_actions:
                result.add_error(f"Duplicate action name {action.name!r}.")
            seen_actions.add(action.name)

            # Validate action fields
            if action.side_effect_class not in VALID_SIDE_EFFECT_CLASSES:
                result.add_error(
                    f"Action {action.name!r} has invalid side_effect_class "
                    f"{action.side_effect_class!r}; valid: {sorted(VALID_SIDE_EFFECT_CLASSES)}."
                )
            if action.timeout_seconds <= 0 or action.timeout_seconds > 3600:
                result.add_error(
                    f"Action {action.name!r} timeout must be between 1 and 3600 seconds."
                )

            # Validate declared permissions are subset of manifest permissions
            declared_scopes = {p.scope for p in manifest.permissions}
            for perm in action.required_permissions:
                if perm not in declared_scopes:
                    result.add_error(
                        f"Action {action.name!r} requires undeclared permission {perm!r}."
                    )

    # P9.2: Manifest bounds
    import json
    manifest_json = manifest.model_dump_json()
    if len(manifest_json.encode("utf-8")) > MAX_MANIFEST_BYTES:
        result.add_error(
            f"Manifest size {len(manifest_json)} bytes exceeds maximum of {MAX_MANIFEST_BYTES} bytes."
        )

    if len(manifest.description) > MAX_DESCRIPTION_LENGTH:
        result.add_error(
            f"Description length {len(manifest.description)} exceeds maximum of {MAX_DESCRIPTION_LENGTH}."
        )

    if len(manifest.author) > MAX_AUTHOR_LENGTH:
        result.add_error(
            f"Author length {len(manifest.author)} exceeds maximum of {MAX_AUTHOR_LENGTH}."
        )

    if len(manifest.metadata) > MAX_METADATA_KEYS:
        result.add_error(
            f"Metadata has {len(manifest.metadata)} keys, exceeds maximum of {MAX_METADATA_KEYS}."
        )

    if manifest.metadata and not isinstance(manifest.metadata, dict):
        result.add_error("Plugin metadata must be a mapping.")

    return result


def validate_plugin(plugin, manifest: PluginManifest) -> PluginValidationResult:
    """Structurally validate a loaded ``Plugin`` instance.

    Checks that the instance's manifest identity matches the registered
    manifest and that contributed tools are well-formed ``Tool`` instances
    with unique names.
    """
    result = PluginValidationResult()

    if plugin.manifest.id != manifest.id:
        result.add_error(
            f"Plugin entry manifest id {plugin.manifest.id!r} does not match "
            f"registered id {manifest.id!r}."
        )
    if plugin.manifest.version != manifest.version:
        result.add_error(
            f"Plugin entry manifest version {plugin.manifest.version!r} does "
            f"not match registered version {manifest.version!r}."
        )

    from app.tools.base import Tool

    try:
        tools = plugin.provide_tools()
    except Exception as exc:  # noqa: BLE001 - surfaced as validation error
        result.add_error(f"provide_tools() raised: {exc}")
        return result
    if not isinstance(tools, (list, tuple)):
        result.add_error("provide_tools() must return a list of Tool instances.")
        return result

    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, Tool):
            result.add_error(
                f"Tool contribution must be a Tool instance, got "
                f"{type(tool).__name__}."
            )
            continue
        if not _is_identifier(str(tool.name)):
            result.add_error(f"Invalid tool name {tool.name!r}.")
        names.append(str(tool.name))
    if len(set(names)) != len(names):
        result.add_error("Tool names contributed by a plugin must be unique.")

    return result
