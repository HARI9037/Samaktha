"""Phase 3.3 / 3.5 — Persistent Skill Memory Store.

Implements deterministic storage, retrieval, and lifecycle management for
learned skills. No embeddings, no vector databases, no autonomous execution.

Phase 3.5 adds:
- SkillLifecycleState awareness in queries
- record_skill_use / record_skill_success / record_skill_failure
- deprecate_skill / archive_skill
- merge_duplicate_skills (deterministic)
- run_lifecycle_maintenance (decay stale skills)
- list_deprecated_skills / list_archived_skills
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.core.contracts.learning import SkillConfidence
from app.core.contracts.skills import SkillLifecycleState, SkillRecord, SkillSearchResult
from app.memory.skill_metrics import SkillMetricsCollector

# ---------------------------------------------------------------------------
# Constants for lifecycle maintenance thresholds
# ---------------------------------------------------------------------------

#: Number of days without use before confidence decay is applied.
STALE_DAYS_THRESHOLD = 30


class SkillMemoryStore:
    """Deterministic, exact/substring matching store for learned skills."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillRecord] = {}
        self._metrics = SkillMetricsCollector()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> dict:
        """Expose current skill metrics."""
        active = sum(1 for s in self._skills.values() if s.is_active)
        deprecated = sum(1 for s in self._skills.values() if s.is_deprecated)
        archived = sum(1 for s in self._skills.values() if s.is_archived)
        return self._metrics.get_metrics(
            current_count=len(self._skills),
            active_count=active,
            deprecated_count=deprecated,
            archived_count=archived,
        )

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def save_skill(self, skill: SkillRecord) -> None:
        """Save a new skill or merge with an existing duplicate."""
        existing = self._find_duplicate(skill)
        if existing:
            self._merge_duplicate(existing, skill)
            self._metrics.record_duplicate_merge()
        else:
            self._skills[skill.skill_id] = skill
            self._metrics.record_saved()

    def update_skill(self, skill: SkillRecord) -> None:
        """Update an existing skill."""
        if skill.skill_id in self._skills:
            skill.updated_at = datetime.utcnow()
            self._skills[skill.skill_id] = skill
            self._metrics.record_updated()

    def delete_skill(self, skill_id: str) -> None:
        """Permanently delete a skill by ID (prefer archive instead)."""
        if skill_id in self._skills:
            del self._skills[skill_id]

    def get_skill(self, skill_id: str) -> Optional[SkillRecord]:
        """Retrieve a skill by exact ID."""
        return self._skills.get(skill_id)

    def list_skills(self) -> list[SkillRecord]:
        """List all stored skills regardless of lifecycle state."""
        return list(self._skills.values())

    def list_active_skills(self) -> list[SkillRecord]:
        """List only ACTIVE skills."""
        return [s for s in self._skills.values() if s.is_active]

    def list_deprecated_skills(self) -> list[SkillRecord]:
        """List only DEPRECATED skills."""
        return [s for s in self._skills.values() if s.is_deprecated]

    def list_archived_skills(self) -> list[SkillRecord]:
        """List only ARCHIVED skills."""
        return [s for s in self._skills.values() if s.is_archived]

    # ------------------------------------------------------------------
    # Lifecycle Statistics
    # ------------------------------------------------------------------

    def record_skill_use(self, skill_id: str) -> None:
        """Increment usage_count and update last_used_at for a skill."""
        skill = self._skills.get(skill_id)
        if skill and skill.is_active:
            skill.usage_count += 1
            skill.last_used_at = datetime.utcnow()
            skill.updated_at = datetime.utcnow()

    def record_skill_success(self, skill_id: str) -> None:
        """Increment success_count and recompute success_rate."""
        skill = self._skills.get(skill_id)
        if skill:
            skill.success_count += 1
            skill.recompute_success_rate()
            skill.updated_at = datetime.utcnow()

    def record_skill_failure(self, skill_id: str) -> None:
        """Increment failure_count and recompute success_rate."""
        skill = self._skills.get(skill_id)
        if skill:
            skill.failure_count += 1
            skill.recompute_success_rate()
            skill.updated_at = datetime.utcnow()
            # Auto-deprecate if success rate drops below 30% with enough data
            total = skill.success_count + skill.failure_count
            if total >= 5 and skill.success_rate < 0.30:
                self.deprecate_skill(skill_id, reason="auto: success rate below threshold")

    # ------------------------------------------------------------------
    # Deprecation & Archival
    # ------------------------------------------------------------------

    def deprecate_skill(self, skill_id: str, reason: str = "") -> None:
        """Mark a skill as DEPRECATED."""
        skill = self._skills.get(skill_id)
        if skill and not skill.is_archived:
            skill.lifecycle_state = SkillLifecycleState.DEPRECATED
            skill.updated_at = datetime.utcnow()
            if reason:
                skill.metadata["deprecation_reason"] = reason

    def archive_skill(self, skill_id: str) -> None:
        """Archive a skill so it is never retrieved or injected, but remains stored."""
        skill = self._skills.get(skill_id)
        if skill:
            skill.lifecycle_state = SkillLifecycleState.ARCHIVED
            skill.updated_at = datetime.utcnow()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def run_lifecycle_maintenance(
        self, stale_days: int = STALE_DAYS_THRESHOLD
    ) -> dict[str, int]:
        """Apply deterministic decay and deprecation rules.

        Rules:
        - If an ACTIVE skill has never been used AND is older than stale_days,
          decay its confidence one level.
        - If confidence reaches LOW after decay, mark as DEPRECATED.
        - If a DEPRECATED skill has LOW confidence, mark it for potential archive.

        Returns counts of skills affected.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(days=stale_days)

        decayed = 0
        deprecated = 0

        confidence_order = [SkillConfidence.HIGH, SkillConfidence.MEDIUM, SkillConfidence.LOW]

        for skill in list(self._skills.values()):
            if not skill.is_active:
                continue

            is_stale = skill.last_used_at is None and skill.created_at < cutoff
            if not is_stale:
                continue

            current_idx = confidence_order.index(skill.confidence)
            if current_idx < len(confidence_order) - 1:
                # Decay one level
                skill.confidence = confidence_order[current_idx + 1]
                skill.updated_at = now
                self._metrics.record_decayed()
                decayed += 1

            if skill.confidence == SkillConfidence.LOW:
                self.deprecate_skill(skill.skill_id, reason="auto: confidence decayed to LOW")
                deprecated += 1

        return {"decayed": decayed, "deprecated": deprecated}

    def merge_duplicate_skills(self, primary_id: str, duplicate_id: str) -> bool:
        """Explicitly merge duplicate_id into primary_id and remove duplicate.

        Merges: statistics, tags, lessons; keeps primary's creation date and
        the higher confidence; removes the duplicate entry.
        """
        primary = self._skills.get(primary_id)
        duplicate = self._skills.get(duplicate_id)
        if not primary or not duplicate or primary_id == duplicate_id:
            return False

        # Merge counts
        primary.success_count += duplicate.success_count
        primary.failure_count += duplicate.failure_count
        primary.usage_count += duplicate.usage_count
        primary.recompute_success_rate()

        # Keep best confidence
        confidence_order = [SkillConfidence.HIGH, SkillConfidence.MEDIUM, SkillConfidence.LOW]
        if confidence_order.index(duplicate.confidence) < confidence_order.index(primary.confidence):
            primary.confidence = duplicate.confidence

        # Merge tags deterministically (preserve order, drop dupes)
        combined_tags = list(dict.fromkeys(primary.tags + duplicate.tags))
        primary.tags = combined_tags

        # Keep oldest creation date
        if duplicate.created_at < primary.created_at:
            primary.created_at = duplicate.created_at

        primary.updated_at = datetime.utcnow()

        # Remove duplicate
        del self._skills[duplicate_id]
        self._metrics.record_merged()
        return True

    # ------------------------------------------------------------------
    # Search APIs
    # ------------------------------------------------------------------

    def search_by_name(self, query: str) -> list[SkillSearchResult]:
        """Search ACTIVE skills by substring match in name or description."""
        query_lower = query.lower()
        results: list[SkillSearchResult] = []
        for skill in self._skills.values():
            if not skill.is_active:
                continue
            score = 0.0
            if query_lower in skill.name.lower():
                score += 1.0
            if query_lower in skill.description.lower():
                score += 0.5
            if score > 0:
                results.append(SkillSearchResult(skill=skill, score=score))
        return sorted(results, key=lambda x: x.score, reverse=True)

    def search_by_tag(self, tag: str) -> list[SkillSearchResult]:
        """Find ACTIVE skills containing the exact tag."""
        tag_lower = tag.lower()
        results: list[SkillSearchResult] = []
        for skill in self._skills.values():
            if not skill.is_active:
                continue
            if any(t.lower() == tag_lower for t in skill.tags):
                results.append(SkillSearchResult(skill=skill, score=1.0))
        return results

    def search_by_category(self, category: str) -> list[SkillSearchResult]:
        """Find ACTIVE skills by exact category match."""
        cat_lower = category.lower()
        results: list[SkillSearchResult] = []
        for skill in self._skills.values():
            if not skill.is_active:
                continue
            if skill.category.lower() == cat_lower:
                results.append(SkillSearchResult(skill=skill, score=1.0))
        return results

    def find_relevant_skills(
        self,
        goal: str,
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> list[SkillSearchResult]:
        """Deterministically rank and filter ACTIVE skills based on relevance."""
        goal_lower = goal.lower()
        cat_lower = category.lower() if category else None
        tag_set = {t.lower() for t in (tags or [])}

        results: list[SkillSearchResult] = []
        for skill in self._skills.values():
            # Only ACTIVE skills are considered for planning
            if not skill.is_active:
                self._metrics.record_planner_rejection()
                continue

            score = 0.0

            # 1. Goal match
            if goal_lower in skill.name.lower():
                score += 2.0
            elif skill.name.lower() in goal_lower:
                score += 1.0
            if goal_lower in skill.description.lower():
                score += 1.0

            # 2. Category match
            if cat_lower and skill.category.lower() == cat_lower:
                score += 3.0
            elif not cat_lower:
                score += 0.5

            # 3. Tags match
            skill_tags = {t.lower() for t in skill.tags}
            overlap = len(tag_set & skill_tags)
            score += overlap * 1.5

            # 4. Usage and success boost
            usage_boost = min(skill.usage_count * 0.1, 1.0)
            score += usage_boost

            total_runs = skill.success_count + skill.failure_count
            if total_runs > 0:
                score += skill.success_rate * 2.0
            else:
                score += 1.0

            # 5. Confidence boost
            if skill.confidence == SkillConfidence.HIGH:
                score += 1.5
            elif skill.confidence == SkillConfidence.MEDIUM:
                score += 0.5

            if score > 0:
                results.append(SkillSearchResult(skill=skill, score=score))

        return sorted(results, key=lambda x: (-x.score, x.skill.usage_count, x.skill.skill_id))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_duplicate(self, new_skill: SkillRecord) -> Optional[SkillRecord]:
        """Determine if a skill with an identical signature already exists."""
        for skill in self._skills.values():
            if (skill.name.lower() == new_skill.name.lower()
                    and skill.category.lower() == new_skill.category.lower()):
                return skill
        return None

    def _merge_duplicate(self, existing: SkillRecord, new_skill: SkillRecord) -> None:
        """Merge a new observation into an existing skill record."""
        existing.usage_count += 1
        existing.updated_at = datetime.utcnow()
        combined_tags = list(dict.fromkeys(existing.tags + new_skill.tags))
        existing.tags = combined_tags
        existing.success_count += new_skill.success_count
        existing.failure_count += new_skill.failure_count
        existing.recompute_success_rate()



