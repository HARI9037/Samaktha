"""P2.3 — Versioned Capability Contracts.

Versioned, machine-readable capability contracts for tools, providers,
skills and personalities, with structural compatibility validation,
breaking-change detection, semantic-versioning discipline, a versioned
contract registry and a migration strategy. Builds on the P2.1 plugin
specification (``PluginKind``) and semver engine; system tools and plugin
contributions are compared through one mechanism.
"""

from app.capabilities.builders import (
    contract_for_personality,
    contract_for_provider,
    contract_for_skill,
    contract_for_tool,
)
from app.capabilities.compat import (
    ContractError,
    breaking_changes,
    compare_contracts,
    is_compatible,
    is_semver_compatible,
)
from app.capabilities.migration import (
    MigrationPlan,
    is_consumer_compatible,
    plan_migration,
    upgrade_path,
)
from app.capabilities.models import (
    CapabilityContract,
    ContractChange,
    ContractChangeKind,
    ContractComparison,
    ContractParameter,
)
from app.capabilities.registry import ContractRegistry
from app.capabilities.versioning import (
    compatible_range,
    recommended_bump,
    version_respects_bump,
)

__all__ = [
    "CapabilityContract",
    "ContractChange",
    "ContractChangeKind",
    "ContractComparison",
    "ContractError",
    "ContractParameter",
    "ContractRegistry",
    "MigrationPlan",
    "breaking_changes",
    "compare_contracts",
    "compatible_range",
    "contract_for_personality",
    "contract_for_provider",
    "contract_for_skill",
    "contract_for_tool",
    "is_compatible",
    "is_consumer_compatible",
    "is_semver_compatible",
    "plan_migration",
    "recommended_bump",
    "upgrade_path",
    "version_respects_bump",
]
