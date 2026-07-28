"""Security and Privacy Layer Contracts.

Defines deterministic structures for security policies and decisions.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SecurityLevel(str, Enum):
    """Classification of security risk or requirement."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SecurityPolicy(BaseModel):
    """A deterministic security rule."""
    policy_id: str
    name: str
    description: str
    level: SecurityLevel = SecurityLevel.MEDIUM
    enabled: bool = True


class SecurityDecision(BaseModel):
    """The outcome of a security validation."""
    allowed: bool
    reason: Optional[str] = None
    policy_id: Optional[str] = None
    security_level: SecurityLevel = SecurityLevel.LOW
