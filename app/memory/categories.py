from app.core.contracts.memory import MemoryDomainCategory
from app.core.contracts.policy import PrivacyCategory


def normalize_category(raw: str) -> PrivacyCategory | MemoryDomainCategory:
    """Map stored category strings to contract-safe category labels."""
    try:
        return PrivacyCategory(raw)
    except ValueError:
        pass
    try:
        return MemoryDomainCategory(raw)
    except ValueError:
        return PrivacyCategory.INTERNAL


def normalize_category_for_storage(category: str) -> str:
    """Normalize caller-provided category strings before persistence."""
    resolved = normalize_category(category)
    return resolved.value
