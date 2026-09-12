from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Iterable

from app.core.contracts.memory import MemorySearchEvidence, SessionRecallEvidence
from app.personality.models import MemoryVisibilitySummary, PersonalityEvaluation, VisibleMemory


@dataclass(frozen=True, slots=True)
class SynthesizedMemoryTopic:
    title: str
    bullets: tuple[str, ...]
    sessions: tuple[str, ...]
    confidence: float
    freshness: str
    evidence_count: int


class ConversationMemorySynthesizer:
    """Deterministic conversational synthesis over already-retrieved memories."""

    def synthesize(self, evaluation: PersonalityEvaluation, *, mode: str = "topics") -> str:
        memories = [memory for memory in evaluation.visible_memories if memory.content]
        if not memories:
            return ""
        topics = self._cluster(memories)
        if mode == "auto":
            mode = self._detect_mode(evaluation.message)
        if mode == "project":
            return self._project_summary(evaluation, topics)
        if mode == "timeline":
            return self._timeline_summary(memories)
        if mode == "bugs":
            return self._category_summary("bug", "Bug summary", memories, topics)
        if mode == "decisions":
            return self._category_summary("decision", "Architecture decisions", memories, topics)
        if mode == "milestones":
            return self._milestone_summary(topics)
        return self._topic_summary(evaluation, topics)

    def synthesize_search_evidence(
        self,
        evidence: MemorySearchEvidence,
        *,
        request: str = "",
    ) -> str:
        """Render only fields present in typed durable-memory evidence."""

        count = evidence.record_count
        if count == 0:
            return "I couldn't find a stored memory matching that request."
        noun = "record" if count == 1 else "records"
        lines = [
            f"A scoped durable-memory search returned {count} matching {noun}."
        ]
        expose_ids = bool(re.search(r"\b(?:id|ids|identifier|identifiers)\b", request.casefold()))
        for index, record in enumerate(evidence.records, start=1):
            facts = [record.memory_type]
            if record.created_at is not None:
                facts.append(self._timestamp_label(record.created_at, evidence.retrieved_at))
            label = f"{index}."
            if expose_ids:
                label += f" [{record.memory_id}]"
            lines.append(f"{label} {'; '.join(facts)}")
            lines.append(f"   {record.content}")
        return "\n".join(lines)

    def synthesize_session_evidence(
        self,
        evidence: SessionRecallEvidence,
    ) -> str:
        """Render a prior-session answer without inferred titles or topics."""

        if evidence.session_id is None:
            return "I couldn't find a previous stored session in the current scope."
        count = evidence.stored_message_count
        noun = "message" if count == 1 else "messages"
        timing = (
            self._timestamp_label(evidence.updated_at, evidence.retrieved_at)
            if evidence.updated_at is not None
            else "with no stored update timestamp"
        )
        availability = "only " if evidence.partial else ""
        lines = [
            f"I found the previous stored session, {timing}, with "
            f"{availability}{count} stored {noun}."
        ]
        for message in evidence.messages:
            role = message.role.capitalize() if message.role else "Message"
            if message.provenance == "generated_summary":
                role = f"{role} (generated summary)"
            timestamp = (
                f" ({message.created_at.isoformat()})"
                if message.created_at is not None else ""
            )
            lines.append(f"- {role}{timestamp}: {message.content}")
        if not evidence.messages:
            lines.append("No stored messages are available for that session.")
        return "\n".join(lines)

    @staticmethod
    def _timestamp_label(value: datetime, retrieved_at: datetime) -> str:
        """Return an exact timestamp plus deterministic relative age."""

        value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        retrieved_at = (
            retrieved_at
            if retrieved_at.tzinfo
            else retrieved_at.replace(tzinfo=timezone.utc)
        )
        delta = max(0, int((retrieved_at - value).total_seconds()))
        if delta < 60:
            relative = "less than a minute ago"
        elif delta < 3_600:
            amount = delta // 60
            relative = f"{amount} minute{'s' if amount != 1 else ''} ago"
        elif delta < 86_400:
            amount = delta // 3_600
            relative = f"{amount} hour{'s' if amount != 1 else ''} ago"
        else:
            amount = delta // 86_400
            relative = f"{amount} day{'s' if amount != 1 else ''} ago"
        return f"stored at {value.isoformat()} ({relative})"

    @staticmethod
    def _detect_mode(message: str) -> str:
        text = message.lower()
        if any(phrase in text for phrase in ("what happened yesterday", "yesterday", "last week", "this week", "today")):
            return "timeline"
        if any(phrase in text for phrase in ("what were we building", "project", "current progress")):
            return "project"
        if "bug" in text or "fix" in text:
            return "bugs"
        if "decision" in text:
            return "decisions"
        if "milestone" in text or "what did we achieve" in text:
            return "milestones"
        return "topics"

    def explain(self, evaluation: PersonalityEvaluation) -> str:
        memories = [m for m in evaluation.visible_memories if m.content]
        sessions = sorted({m.session_id for m in memories if m.session_id})
        confidence = max((m.confidence for m in memories), default=0.0)
        return "\n".join(
            [
                "Source sessions: " + (", ".join(sessions) if sessions else "unknown"),
                f"Retrieval confidence: {confidence:.2f}",
                f"Evidence count: {len(memories)}",
            ]
        )

    def _cluster(self, memories: list[VisibleMemory]) -> list[SynthesizedMemoryTopic]:
        buckets: dict[str, list[VisibleMemory]] = defaultdict(list)
        for memory in memories:
            buckets[self._topic_key(memory)].append(memory)
        topics: list[SynthesizedMemoryTopic] = []
        for key in sorted(buckets):
            group = buckets[key]
            sessions = tuple(sorted({m.session_id for m in group if m.session_id}))
            confidence = max((m.confidence for m in group), default=0.0)
            freshness = self._freshest(group)
            bullets = tuple(self._bullets_for(group))
            topics.append(
                SynthesizedMemoryTopic(
                    title=key,
                    bullets=bullets,
                    sessions=sessions,
                    confidence=confidence,
                    freshness=freshness,
                    evidence_count=len(group),
                )
            )
        topics.sort(key=lambda t: (-t.evidence_count, t.title))
        return topics

    @staticmethod
    def _topic_key(memory: VisibleMemory) -> str:
        content = memory.content.lower()
        for marker, label in (
            ("phase 20", "Phase 20 Conversational Intelligence"),
            ("phase 19", "Phase 19 Cognitive Planning"),
            ("phase 18", "Phase 18 Runtime Parallel Scheduler"),
            ("phase 17", "Phase 17 Intelligence Architecture"),
            ("scheduler", "Runtime Parallel Execution"),
            ("retrieval", "Memory Retrieval"),
            ("memory", "Conversational Memory"),
            ("governance", "Governance Architecture"),
            ("architecture", "Architecture"),
            ("bug", "Bug Fixes"),
            ("issue", "Bug Fixes"),
            ("decision", "Architecture Decisions"),
        ):
            if marker in content:
                return label
        return memory.content.split(".")[0][:60].strip() or "Other"

    @staticmethod
    def _bullets_for(group: list[VisibleMemory]) -> list[str]:
        seen: set[str] = set()
        bullets: list[str] = []
        for memory in sorted(group, key=lambda m: (m.session_id, m.memory_id)):
            text = memory.content.strip().rstrip(".")
            if text.lower() in seen:
                continue
            seen.add(text.lower())
            bullets.append(text)
        return bullets[:3]

    @staticmethod
    def _freshest(group: Iterable[VisibleMemory]) -> str:
        freshness_rank = {"active": 0, "recent": 0, "within_a_month": 1, "stale": 2, "archived": 3}
        best = min((freshness_rank.get(m.freshness, 1), m.freshness or "unknown") for m in group)
        return best[1]

    def _topic_summary(self, evaluation: PersonalityEvaluation, topics: list[SynthesizedMemoryTopic]) -> str:
        lines = ["Looking back across our recent work, here's the clearest summary:"]
        for topic in topics[:5]:
            lines.append(f"• {topic.title} ({topic.evidence_count} mentions)")
            for bullet in topic.bullets[:2]:
                lines.append(f"  - {bullet}")
        return "\n".join(lines)

    def _project_summary(self, evaluation: PersonalityEvaluation, topics: list[SynthesizedMemoryTopic]) -> str:
        project = evaluation.profile.name or "Project"
        lines = [f"Project: {project}", "Current progress:"]
        for topic in topics[:4]:
            lines.append(f"• {topic.title}")
        lines.append("Current focus: refining conversational memory and response quality.")
        return "\n".join(lines)

    def _timeline_summary(self, memories: list[VisibleMemory]) -> str:
        lines = ["Timeline:"]
        for memory in sorted(memories, key=lambda m: (m.session_id, m.memory_id), reverse=True)[:6]:
            lines.append(f"• {memory.content.strip()}")
        return "\n".join(lines)

    def _category_summary(self, keyword: str, heading: str, memories: list[VisibleMemory], topics: list[SynthesizedMemoryTopic]) -> str:
        filtered = [m for m in memories if keyword in m.content.lower()]
        lines = [heading + ":"]
        for memory in filtered[:5]:
            lines.append(f"• {memory.content.strip()}")
        if not filtered:
            lines.append("• No retrieved evidence for this category.")
        return "\n".join(lines)

    def _milestone_summary(self, topics: list[SynthesizedMemoryTopic]) -> str:
        lines = ["Recent milestones:"]
        for topic in topics[:5]:
            lines.append(f"• {topic.title}")
        return "\n".join(lines)
