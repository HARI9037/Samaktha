"""CAP Engine trust-layer components for Samaktha Core."""

from app.core.cap.ambiguity_resolver import AmbiguityResolver
from app.core.cap.approval_engine import ApprovalEngine
from app.core.cap.context_engine import ContextEngine
from app.core.cap.permission_store import InMemoryPermissionStore
from app.core.cap.policy_engine import PolicyEngine
from app.core.cap.privacy_classifier import PrivacyClassifier

__all__ = [
    "AmbiguityResolver",
    "ApprovalEngine",
    "ContextEngine",
    "InMemoryPermissionStore",
    "PolicyEngine",
    "PrivacyClassifier",
]
