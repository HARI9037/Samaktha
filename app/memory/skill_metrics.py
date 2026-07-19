"""Phase 3.3 / 3.5 — Skill Memory Metrics.

Tracks deterministic operations performed by the SkillMemoryStore.

Phase 3.5 adds lifecycle-specific counters.
"""
from __future__ import annotations

from typing import TypedDict


class SkillMetricsSnapshot(TypedDict):
    """Snapshot of current skill memory metrics."""

    # Phase 3.3 fields
    skills_saved: int
    skills_updated: int
    skills_rejected: int
    duplicate_merges: int
    current_skill_count: int
    # Phase 3.5 lifecycle fields
    active_skills: int
    deprecated_skills: int
    archived_skills: int
    merged_skills: int
    decayed_skills: int
    planner_rejections: int


class SkillMetricsCollector:
    """Collects and reports metrics for skill memory operations."""

    def __init__(self) -> None:
        # Phase 3.3
        self._skills_saved = 0
        self._skills_updated = 0
        self._skills_rejected = 0
        self._duplicate_merges = 0
        # Phase 3.5
        self._merged_skills = 0
        self._decayed_skills = 0
        self._planner_rejections = 0

    def record_saved(self) -> None:
        self._skills_saved += 1

    def record_updated(self) -> None:
        self._skills_updated += 1

    def record_rejected(self) -> None:
        self._skills_rejected += 1

    def record_duplicate_merge(self) -> None:
        self._duplicate_merges += 1

    def record_merged(self) -> None:
        self._merged_skills += 1

    def record_decayed(self) -> None:
        self._decayed_skills += 1

    def record_planner_rejection(self) -> None:
        self._planner_rejections += 1

    def get_metrics(
        self,
        current_count: int,
        active_count: int,
        deprecated_count: int,
        archived_count: int,
    ) -> SkillMetricsSnapshot:
        """Return a full snapshot of current metrics."""
        return {
            "skills_saved": self._skills_saved,
            "skills_updated": self._skills_updated,
            "skills_rejected": self._skills_rejected,
            "duplicate_merges": self._duplicate_merges,
            "current_skill_count": current_count,
            "active_skills": active_count,
            "deprecated_skills": deprecated_count,
            "archived_skills": archived_count,
            "merged_skills": self._merged_skills,
            "decayed_skills": self._decayed_skills,
            "planner_rejections": self._planner_rejections,
        }
