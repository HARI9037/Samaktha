"""Phase 8.2 — Memory Formation Engine.

Runs automatically after every completed interaction and determines whether
anything is worth remembering — the user never needs to say "remember this".

Flow (deterministic, entirely local):

    User message + Assistant response
        ↓
    Memory Formation Engine
        ↓
    Memory Classification (MemoryClassifier)
        ↓
    Importance / confidence assignment
        ↓
    Duplicate / conflict detection
        ↓
    MemoryController.write_xxx(...)
        ↓
    SQLite (via MemoryManager)

The engine reuses the existing MemoryController and its sub-systems
(Writer, PreferenceResolver, Consolidator, LifecycleManager, MetadataManager,
Cache, SecurityManager).  It never replaces them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4

from app.memory.controller.facade import MemoryController
from app.memory.formation.classifier import Classification, MemoryClassifier

log = logging.getLogger(__name__)


@dataclass
class MemoryFormationResult:
    """Outcome of one formation decision for a single memory candidate."""

    memory_type: str
    stored: bool
    item_id: str | None
    duplicate_of: str | None
    content: str
    reason: str
    tags: list[str] = field(default_factory=list)


_CANDIDATE_ID = "__memory_formation_candidate__"


class MemoryFormationEngine:
    """Deterministic engine that forms memories from completed interactions.

    Responsibilities:
        1. Persist every conversation turn (user message, assistant response,
           timestamp, session, metadata) as a conversation memory.
        2. Inspect the user message and the assistant response and classify
           typed memories (preference, project, workflow, tool, knowledge).
        3. Assign importance / confidence / category / retention.
        4. Detect duplicates via the existing Consolidator and update the
           canonical memory instead of creating a duplicate.
        5. Persist typed memories through MemoryController.write_*().

    The engine never raises: any failure is logged and swallowed so that
    autonomous memory formation can never break the agent response.
    """

    def __init__(
        self,
        memory_controller: MemoryController,
        classifier: MemoryClassifier | None = None,
        session_manager: Any | None = None,
    ) -> None:
        self._controller = memory_controller
        self._memory_manager = getattr(memory_controller, "memory_manager", None)
        self._classifier = classifier or MemoryClassifier()
        self._session_manager = session_manager
        self._formed = 0
        self._skipped = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def formed_count(self) -> int:
        """Number of typed memories formed since engine creation."""
        return self._formed

    @property
    def skipped_count(self) -> int:
        """Number of candidates skipped as noise / duplicates."""
        return self._skipped

    def ingest(
        self,
        user_message: str,
        assistant_response: str = "",
        session_id: str | None = None,
        conversation_id: str | None = None,
        metadata: dict | None = None,
        persist_conversation: bool = True,
        execution_report: Any | None = None,
        workflow_result: Any | None = None,
        approval_result: Any | None = None,
        runtime_summary: str | None = None,
    ) -> list[MemoryFormationResult]:
        """Analyze one completed interaction and persist what is worth remembering.

        Parameters
        ----------
        user_message:
            The user's message for this interaction.
        assistant_response:
            The assistant's generated response for this interaction.
        session_id / conversation_id:
            Session and conversation identifiers attached to every stored item.
        metadata:
            Optional extra metadata (e.g. workflow outputs) — informational only.
        persist_conversation:
            When True (default) every turn is stored as a conversation memory.
        execution_report / workflow_result / approval_result / runtime_summary:
            Strongly typed runtime artifacts used strictly by SessionBuilder.

        Returns
        -------
        list[MemoryFormationResult] — one entry per formation decision.
        """
        results: list[MemoryFormationResult] = []
        if self._controller is None:
            return results

        user_message = (user_message or "").strip()
        assistant_response = (assistant_response or "").strip()
        metadata = metadata or {}

        # Phase 12.10 — internet-sourced interactions are TRANSIENT. Unless the
        # user explicitly asked to remember the content (``explicit_memory``),
        # neither the conversation turn nor any typed memory derived from an
        # internet lookup may be auto-persisted. The interaction stays in the
        # short-lived session working memory only.
        if metadata.get("internet_sourced") and not metadata.get("explicit_memory"):
            log.info(
                "MemoryFormationEngine: skipping persistence — "
                "internet-sourced interaction is transient"
            )
            return results

        # 1. Every conversation turn persists automatically.
        if persist_conversation:
            results.append(
                self._write_conversation(
                    user_message, assistant_response, session_id, conversation_id, metadata
                )
            )

        # 1b. Session Intelligence Phase 20.2 — Form structured session history
        if self._session_manager and session_id:
            try:
                from app.memory.formation.session_builder import SessionBuilder

                # Load session first so we can read the current turn counter.
                session = self._session_manager.load_session(session_id)
                base_turn = session.memory.next_turn_number

                logical_id = None
                timestamp = None
                if execution_report is not None:
                    if hasattr(execution_report, "plan_id"):
                        logical_id = str(execution_report.plan_id)
                    if hasattr(execution_report, "started_at") and execution_report.started_at:
                        if hasattr(execution_report.started_at, "isoformat"):
                            timestamp = execution_report.started_at.isoformat()
                        else:
                            timestamp = str(execution_report.started_at)

                entries = SessionBuilder.build_history_entries(
                    user_message=user_message,
                    assistant_response=assistant_response,
                    execution_report=execution_report,
                    workflow_result=workflow_result,
                    approval_result=approval_result,
                    runtime_summary=runtime_summary,
                    base_turn_number=base_turn,
                    logical_id=logical_id,
                    timestamp=timestamp,
                )

                # update_metadata mutates a copy of session.metadata in-place
                # and returns it; pass as positional new_metadata.
                new_metadata = SessionBuilder.update_metadata(
                    metadata=session.metadata,
                    history_entries=entries,
                    execution_report=execution_report,
                    workflow_result=workflow_result,
                )

                if hasattr(self._session_manager, "update_metadata"):
                    self._session_manager.update_metadata(session_id, new_metadata)

                if hasattr(self._session_manager, "append_history"):
                    for entry in entries:
                        # append_history will re-stamp turn_number with its
                        # own counter, which is authoritative.
                        self._session_manager.append_history(session_id, entry)

            except Exception:
                log.warning("MemoryFormationEngine: SessionBuilder failed", exc_info=True)

        # 2. Classify the interaction into typed memories.
        try:
            classification = self._classifier.classify(user_message, assistant_response)
        except Exception:
            log.warning("MemoryFormationEngine: classification failed", exc_info=True)
            classification = None

        # 3. Write the typed memory (dedup-aware).
        if classification is not None:
            result = self._write_typed(classification, session_id, assistant_response, metadata)
            if result is not None:
                results.append(result)
                if result.stored:
                    self._formed += 1
                else:
                    self._skipped += 1

        return results

    # ------------------------------------------------------------------
    # Conversation persistence
    # ------------------------------------------------------------------

    def _write_conversation(
        self,
        user_message: str,
        assistant_response: str,
        session_id: str | None,
        conversation_id: str | None,
        metadata: dict,
    ) -> MemoryFormationResult:
        content = f"User: {user_message}\nAssistant: {assistant_response}"
        tags = ["auto-saved", "conversation"]
        try:
            item = self._controller.write_conversation(
                content=content,
                session_id=session_id,
                conversation_id=conversation_id,
                tags=tags,
                importance_kind="conversation",
            )
            return MemoryFormationResult(
                memory_type="conversation",
                stored=True,
                item_id=getattr(item, "id", None),
                duplicate_of=None,
                content=content,
                reason="conversation turn",
                tags=tags,
            )
        except Exception as exc:
            log.warning("MemoryFormationEngine: conversation write failed: %s", exc)
            return MemoryFormationResult(
                memory_type="conversation",
                stored=False,
                item_id=None,
                duplicate_of=None,
                content=content,
                reason=f"write failed: {exc}",
                tags=tags,
            )

    # ------------------------------------------------------------------
    # Typed memory writes
    # ------------------------------------------------------------------

    def _write_typed(
        self,
        classification: Classification,
        session_id: str | None,
        assistant_response: str,
        metadata: dict,
    ) -> MemoryFormationResult | None:
        memory_type = classification.memory_type
        tags = classification.tags

        # Project memories are stored as knowledge (no dedicated project
        # writer exists) — dedup against the stored memory type.
        dedup_type = "knowledge" if memory_type == "project" else memory_type

        # Preference writes already resolve conflicts via PreferenceResolver.
        # Every other typed memory is deduped against existing items first.
        if memory_type != "preference":
            duplicate, score = self._find_duplicate(classification.content, dedup_type)
            if duplicate is not None:
                self._reinforce_canonical(duplicate)
                log.debug(
                    "MemoryFormationEngine: skipped %s — duplicate of %s (score=%.2f)",
                    memory_type, getattr(duplicate, "id", "?"), score,
                )
                return MemoryFormationResult(
                    memory_type=memory_type,
                    stored=False,
                    item_id=None,
                    duplicate_of=getattr(duplicate, "id", None),
                    content=classification.content,
                    reason=f"duplicate of existing {memory_type} memory",
                    tags=tags,
                )

        try:
            item = self._store_typed(classification, session_id, metadata)
            if item is None:
                return None

            confidence = self._classifier.confirm(classification, assistant_response)
            self._apply_confidence(item, confidence)

            log.info(
                "MemoryFormationEngine: stored %s memory %s (importance=%.2f, confidence=%.2f)",
                memory_type, getattr(item, "id", "?"),
                (item.metadata or {}).get("importance", 0.0),
                (item.metadata or {}).get("confidence", 1.0),
            )
            return MemoryFormationResult(
                memory_type=memory_type,
                stored=True,
                item_id=getattr(item, "id", None),
                duplicate_of=None,
                content=classification.content,
                reason=f"detected {memory_type} ({classification.reason})",
                tags=tags,
            )
        except Exception as exc:
            log.warning("MemoryFormationEngine: %s write failed: %s", memory_type, exc)
            return MemoryFormationResult(
                memory_type=memory_type,
                stored=False,
                item_id=None,
                duplicate_of=None,
                content=classification.content,
                reason=f"write failed: {exc}",
                tags=tags,
            )

    def _store_typed(
        self,
        classification: Classification,
        session_id: str | None,
        metadata: dict,
    ):
        """Dispatch to the matching MemoryController.write_* method."""
        memory_type = classification.memory_type
        if memory_type == "preference":
            return self._controller.write_preference(
                classification.content, session_id=session_id, tags=classification.tags
            )
        if memory_type == "project":
            # No dedicated project writer exists; project facts are long-term
            # knowledge tagged as a project (kept inside the typed KNOWLEDGE
            # memory type so no generic memory is ever created).
            return self._controller.write_knowledge(
                classification.content,
                source="project",
                tags=classification.tags,
                importance_kind=classification.importance_kind,
            )
        if memory_type == "workflow":
            return self._controller.write_workflow(
                classification.content,
                workflow_id=f"wf-{uuid4().hex[:12]}",
                session_id=session_id,
                tags=classification.tags,
                success=True,
            )
        if memory_type == "tool":
            return self._controller.write_tool(
                classification.content,
                tool_name=classification.entity or "tool",
                session_id=session_id,
                tags=classification.tags,
            )
        if memory_type == "knowledge":
            return self._controller.write_knowledge(
                classification.content,
                source="conversation",
                tags=classification.tags,
                importance_kind=classification.importance_kind,
            )
        if memory_type == "system":
            return self._controller.write_system(
                classification.content, tags=classification.tags
            )
        log.debug("MemoryFormationEngine: unknown memory type %r", memory_type)
        return None

    # ------------------------------------------------------------------
    # Duplicate detection & canonical reinforcement
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_content(text: str) -> str:
        """Lowercase, strip punctuation, collapse whitespace (dedup key)."""
        import re as _re
        return _re.sub(r"\s+", " ", _re.sub(r"[^\w\s]", " ", text.lower())).strip()

    def _find_duplicate(
        self,
        content: str,
        memory_type: str,
        threshold: float = 0.75,
    ) -> tuple[object | None, float]:
        """Return (existing_item, score) when content duplicates a stored item."""
        if not self._memory_manager:
            return None, 0.0

        existing = [
            item
            for item in self._memory_manager.get_recent_context(n=500)
            if (item.metadata or {}).get("memory_type") == memory_type
        ]
        if not existing:
            return None, 0.0

        # Exact-normalized match: identical content is always a duplicate,
        # independent of the fuzzy similarity threshold.
        normalized = self._normalize_content(content)
        if normalized:
            for item in existing:
                if self._normalize_content(str(getattr(item, "content", "") or "")) == normalized:
                    return item, 1.0

        candidate = SimpleNamespace(
            id=_CANDIDATE_ID,
            content=content,
            metadata={"memory_type": memory_type, "tags": []},
        )
        try:
            pairs = self._controller.find_duplicates(
                [candidate] + existing, threshold=threshold
            )
        except Exception:
            log.warning("MemoryFormationEngine: duplicate check failed", exc_info=True)
            return None, 0.0

        for a, b, score in pairs:
            if getattr(a, "id", None) == _CANDIDATE_ID and getattr(b, "id", None) != _CANDIDATE_ID:
                return b, score
            if getattr(b, "id", None) == _CANDIDATE_ID and getattr(a, "id", None) != _CANDIDATE_ID:
                return a, score
        return None, 0.0

    def _reinforce_canonical(self, duplicate) -> None:
        """Bump importance/access on the canonical memory instead of duplicating."""
        try:
            item_id = getattr(duplicate, "id", None)
            if not item_id or not self._memory_manager:
                return
            self._controller.promote_memory(item_id)
            self._controller.update_accessed(duplicate)
            # LifecycleManager.promote_memory mutates the in-memory item but
            # does not persist; update_memory persists the reinforcement.
            self._memory_manager.update_memory(duplicate)
        except Exception:
            log.debug("MemoryFormationEngine: reinforce canonical failed", exc_info=True)

    # ------------------------------------------------------------------
    # Confidence / retention assignment
    # ------------------------------------------------------------------

    def _apply_confidence(self, item, confidence: float) -> None:
        """Record the assigned confidence on the stored item's metadata."""
        if item is None or not self._memory_manager:
            return
        meta = getattr(item, "metadata", None)
        if not isinstance(meta, dict):
            return
        confidence = round(min(max(float(confidence), 0.0), 1.0), 4)
        current = meta.get("confidence", 1.0)
        if abs(float(current) - confidence) < 0.001:
            return
        meta["confidence"] = confidence
        try:
            self._memory_manager.update_memory(item)
        except Exception:
            log.debug("MemoryFormationEngine: confidence persist failed", exc_info=True)


# Re-export helpers so callers never import the classifier package directly.
__all__ = [
    "Classification",
    "MemoryClassifier",
    "MemoryFormationEngine",
    "MemoryFormationResult",
]
