from __future__ import annotations

from collections import defaultdict

from app.core.contracts.policy import AmbiguityCandidate, AmbiguityCheck


class AmbiguityResolver:
    """Detects unclear references and returns clarification requirements."""

    def check(
        self,
        reference: str | None,
        candidates: list[AmbiguityCandidate],
    ) -> AmbiguityCheck:
        if not reference or not reference.strip():
            return AmbiguityCheck(
                ambiguous=True,
                reason="Reference is missing or empty.",
                candidates=candidates,
            )

        normalized_reference = self._normalize(reference)
        exact_matches = [
            candidate
            for candidate in candidates
            if self._normalize(candidate.label) == normalized_reference
            or self._normalize(candidate.identifier) == normalized_reference
        ]
        if len(exact_matches) > 1:
            return AmbiguityCheck(
                ambiguous=True,
                reason="Multiple candidates match the same reference.",
                candidates=exact_matches,
            )

        grouped_labels = defaultdict(list)
        for candidate in candidates:
            grouped_labels[self._normalize(candidate.label)].append(candidate)

        duplicate_groups = [
            group
            for group in grouped_labels.values()
            if len(group) > 1 and self._normalize(group[0].label) == normalized_reference
        ]
        if duplicate_groups:
            return AmbiguityCheck(
                ambiguous=True,
                reason="Multiple candidates share the referenced name.",
                candidates=duplicate_groups[0],
            )

        partial_matches = [
            candidate
            for candidate in candidates
            if normalized_reference in self._normalize(candidate.label)
        ]
        if len(partial_matches) > 1:
            return AmbiguityCheck(
                ambiguous=True,
                reason="Reference matches multiple candidates.",
                candidates=partial_matches,
            )

        return AmbiguityCheck(ambiguous=False)

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.casefold().split())
