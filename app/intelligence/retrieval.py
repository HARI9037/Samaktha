from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.intelligence.confidence import ConfidenceDomains, ConfidenceSnapshot
from app.intelligence.context import ContextBundle, ContextEvidence
from app.memory.time_utils import normalize_datetime


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    evidence: tuple[ContextEvidence, ...]
    bundle: ContextBundle


@dataclass
class RetrievalEngine:
    memory_controller: Any
    session_manager: Any | None = None
    repository_index: Any | None = None
    code_index: Any | None = None

    def retrieve(self, query: str, *, session_id: str | None = None, top_k: int = 10) -> RetrievalResult:
        evidence = self._collect(query, session_id=session_id, top_k=top_k)
        bundle = self._bundle(query, evidence)
        return RetrievalResult(evidence=tuple(evidence), bundle=bundle)

    def assemble_context(self, query: str, *, session_id: str | None = None, top_k: int = 10) -> ContextBundle:
        return self.retrieve(query, session_id=session_id, top_k=top_k).bundle

    def _collect(self, query: str, *, session_id: str | None, top_k: int) -> list[ContextEvidence]:
        """Collect context evidence in strict priority order.

        Phase 20.2.1 priority tiers (metadata always before history):

        1. Current session metadata   (source=session_metadata, session_id match)
        2. Current session facts       (source=session, entries)
        3. Current session history     (source=session, history events)
        4. Previous session metadata   (source=session_metadata, other sessions)
        5. Previous session history    (source=session_history, other sessions)
        6. Long-term memory            (source=long_term)
        7. Skills / knowledge          (source=skill)
        8. Repository index            (source=repository)
        9. Code index                  (source=code)
        """
        items: list[ContextEvidence] = []
        cross_session = self._is_cross_session_query(query)
        mc = self.memory_controller
        if mc is not None:
            # Tiers 1–3: current session
            items.extend(self._from_session_metadata(session_id, query))
            items.extend(self._from_current_session(session_id, query))
            # Tier 4–5: previous sessions (via _from_session_history which
            # now also emits session_metadata evidence)
            items.extend(self._from_session(mc, query, session_id, top_k))
            items.extend(self._from_session_history(query, session_id, top_k, cross_session=cross_session))
            # Tiers 6–7: long-term memory then skills
            items.extend(self._from_long_term(mc, query, top_k))
            items.extend(self._from_skills(mc, query, top_k))
        # Tiers 8–9: repository and code indexes
        if self.repository_index is not None:
            items.extend(self._from_repository_index(query))
        if self.code_index is not None:
            items.extend(self._from_code_index(query))
        return self._rank_and_dedupe(items)[:top_k]

    def _from_session(self, mc: Any, query: str, session_id: str | None, top_k: int) -> list[ContextEvidence]:
        result: list[ContextEvidence] = []
        getter = getattr(mc.memory_manager, "get_recent_context", None)
        if not callable(getter):
            return result
        for item in getter(n=top_k, allow_private=True):
            if session_id and item.metadata.get("session_id") not in {None, session_id}:
                continue
            result.append(self._wrap(item.id, "session", item.content, item.metadata, "session memory"))
        return result

    def _from_session_metadata(self, session_id: str | None, query: str) -> list[ContextEvidence]:
        """Phase 20.2 — search the deterministic metadata index first.

        When ``session_id`` is None (cross-session query), scans all sessions.
        Answers "What tools did we use?", "What files were modified?", "What
        bugs were fixed?" directly from the structured metadata arrays without
        touching raw history.
        """
        result: list[ContextEvidence] = []
        manager = self.session_manager
        if manager is None:
            return result
        load_session = getattr(manager, "load_session", None)
        if not callable(load_session):
            return result

        # Determine sessions to scan
        if session_id:
            session_ids_to_scan = [session_id]
        else:
            # Cross-session query: scan all sessions
            list_sessions = getattr(manager, "list_sessions", None)
            if not callable(list_sessions):
                return result
            session_ids_to_scan = [
                getattr(meta, "session_id", None)
                for meta in list_sessions()
            ]
            session_ids_to_scan = [sid for sid in session_ids_to_scan if sid]

        index_fields: list[tuple[str, str]] = [
            ("tools_used", "tools used"),
            ("files_created", "files created"),
            ("files_modified", "files modified"),
            ("files_deleted", "files deleted"),
            ("bugs_fixed", "bugs fixed"),
            ("architecture_topics", "architecture topics"),
            ("milestones", "milestones"),
            ("repositories", "repositories"),
            ("runtime_errors", "runtime errors"),
            ("providers_used", "providers used"),
        ]

        q = query.lower()
        is_cross = session_id is None

        for sid in session_ids_to_scan:
            try:
                session = load_session(sid)
            except Exception:
                continue
            meta = getattr(session, "metadata", None)
            if meta is None:
                continue

            for field_name, label in index_fields:
                values = getattr(meta, field_name, []) or []
                if not values:
                    continue
                # Surface if cross-session OR query mentions this field/value
                matches = [v for v in values if q in v.lower() or v.lower() in q]
                field_hit = any(kw in q for kw in (field_name.replace("_", " "), label))
                if is_cross or matches or field_hit:
                    text = f"{label}: {', '.join(values)}"
                    result.append(self._wrap(
                        f"{sid}:meta:{field_name}",
                        "session_metadata",
                        text,
                        {
                            "session_id": sid,
                            "scope": "session",
                            "confidence": 1.0 if sid == session_id else 0.95,
                            "freshness": "active",
                            "provenance": f"session:{sid}:metadata:{field_name}",
                        },
                        f"session metadata — {label}",
                    ))
        return result

    def _from_session_history(self, query: str, session_id: str | None, top_k: int, *, cross_session: bool = False) -> list[ContextEvidence]:
        result: list[ContextEvidence] = []
        manager = self.session_manager
        if manager is None:
            return result
        list_sessions = getattr(manager, "list_sessions", None)
        load_session = getattr(manager, "load_session", None)
        if not callable(list_sessions) or not callable(load_session):
            return result
        for meta in list_sessions():
            sid = getattr(meta, "session_id", None)
            if not sid or sid == session_id:
                continue
            try:
                session = load_session(sid)
            except Exception:
                continue
            memory = getattr(session, "memory", None)
            entries = getattr(memory, "entries", [])
            history = getattr(memory, "history", [])
            metadata = getattr(session, "metadata", None)
            summary = getattr(metadata, "summary", "") if metadata is not None else ""
            topic_summary = list(getattr(metadata, "topic_summary", []) or [])

            # Phase 20.2 — synthesize cross-session answer from metadata arrays first
            if cross_session and metadata is not None:
                meta_fields: list[tuple[str, list[str]]] = [
                    ("tools_used", getattr(metadata, "tools_used", [])),
                    ("files_created", getattr(metadata, "files_created", [])),
                    ("files_modified", getattr(metadata, "files_modified", [])),
                    ("bugs_fixed", getattr(metadata, "bugs_fixed", [])),
                    ("architecture_topics", getattr(metadata, "architecture_topics", [])),
                    ("milestones", getattr(metadata, "milestones", [])),
                ]
                for field_name, values in meta_fields:
                    if values:
                        label = field_name.replace("_", " ")
                        result.append(self._wrap(
                            f"{sid}:meta:{field_name}",
                            "session_metadata",
                            f"{label}: {', '.join(values)}",
                            {
                                "session_id": sid,
                                "scope": "session",
                                "confidence": 0.95,
                                "freshness": "active",
                                "provenance": f"session:{sid}:metadata:{field_name}",
                            },
                            f"cross-session metadata — {label}",
                        ))

            if cross_session and summary:
                result.append(self._wrap(
                    f"{sid}:summary",
                    "session_summary",
                    summary,
                    {
                        "session_id": sid,
                        "scope": "session",
                        "confidence": 0.92,
                        "freshness": "active",
                        "provenance": f"session:{sid}:summary",
                    },
                    "cross-session summary",
                ))
            for topic in topic_summary[:3]:
                result.append(self._wrap(
                    f"{sid}:topic:{topic}",
                    "session_summary",
                    topic,
                    {
                        "session_id": sid,
                        "scope": "session",
                        "confidence": 0.8,
                        "freshness": "active",
                        "provenance": f"session:{sid}:topic:{topic}",
                    },
                    "session topic summary",
                ))

            archived_history = []
            if callable(getattr(manager, "load_archived_history", None)):
                archived_history = manager.load_archived_history(sid) or []

            # Phase 20.2 — also surface structured history events
            for is_archived, event_list in [(True, archived_history), (False, history)]:
                for event in event_list:
                    role = getattr(event, "role", "")
                    content = getattr(event, "content", "")
                    intent = getattr(event, "intent", "") or ""
                    tools = getattr(event, "tool_calls", []) or []
                    text = f"[{role}] {content}"
                    if tools:
                        text += f" (tools: {', '.join(tools)})"
                    event_id = getattr(event, "id", f"{sid}:hist:{getattr(event, 'timestamp', '')}") or f"{sid}:hist"
                    event_metadata = {
                        "session_id": sid,
                        "scope": "session",
                        "confidence": 0.7,
                        "freshness": "archived" if is_archived else "active",
                        "archive": is_archived,
                        "provenance": f"session:{sid}:history:{event_id}",
                    }
                    if cross_session or query.lower() in text.lower() or query.lower() in intent.lower():
                        result.append(self._wrap(f"{sid}:hist:{event_id}", "session_history", text, event_metadata, "cross-session history event"))

            for entry in entries:
                text = f"{getattr(entry, 'key', '')}: {getattr(entry, 'value', '')}"
                metadata = {
                    "session_id": sid,
                    "scope": "session",
                    "confidence": 0.65,
                    "freshness": "active",
                    "provenance": f"session:{sid}:{getattr(entry, 'key', '')}",
                }
                if cross_session or query.lower() in text.lower() or query.lower() in sid.lower() or (summary and query.lower() in summary.lower()):
                    result.append(self._wrap(f"{sid}:{getattr(entry, 'key', '')}", "session_history", text, metadata, "cross-session memory"))
        return result

    def _from_current_session(self, session_id: str | None, query: str) -> list[ContextEvidence]:
        result: list[ContextEvidence] = []
        manager = self.session_manager
        if manager is None or not session_id:
            return result
        load_session = getattr(manager, "load_session", None)
        if not callable(load_session):
            return result
        try:
            session = load_session(session_id)
        except Exception:
            return result
        memory = getattr(session, "memory", None)
        entries = getattr(memory, "entries", [])
        history = getattr(memory, "history", [])
        q = query.lower()

        for entry in entries:
            text = f"{getattr(entry, 'key', '')}: {getattr(entry, 'value', '')}"
            metadata = {
                "session_id": session_id,
                "scope": "session",
                "confidence": 1.0,
                "freshness": "active",
                "provenance": f"session:{session_id}:fact:{getattr(entry, 'key', '')}",
            }
            if q in text.lower() or q in session_id.lower():
                result.append(self._wrap(f"{session_id}:fact:{getattr(entry, 'key', '')}", "session", text, metadata, "current session fact"))

        # Phase 20.2.1 — surface structured history events for current session
        # Source is 'session_history' (not 'session') so tier ranking puts
        # facts above raw conversation events.
        archived_history = []
        if callable(getattr(manager, "load_archived_history", None)):
            archived_history = manager.load_archived_history(session_id) or []

        for is_archived, event_list in [(True, archived_history), (False, history)]:
            for event in sorted(event_list, key=lambda e: getattr(e, "turn_number", 0)):
                role = getattr(event, "role", "")
                content = getattr(event, "content", "")
                tools = getattr(event, "tool_calls", []) or []
                event_id = getattr(event, "id", "") or ""
                turn_num = getattr(event, "turn_number", 0)
                text = f"[{role}] {content}"
                if tools:
                    text += f" (tools: {', '.join(tools)})"
                metadata = {
                    "session_id": session_id,
                    "scope": "session",
                    "confidence": 0.95,
                    "freshness": "archived" if is_archived else "active",
                    "archive": is_archived,
                    "provenance": f"session:{session_id}:history:turn{turn_num}:{event_id}",
                    "turn_number": turn_num,
                }
                if q in text.lower() or q in session_id.lower():
                    result.append(self._wrap(
                        f"{session_id}:hist:{event_id}",
                        "session_history",
                        text,
                        metadata,
                        f"current session history (turn {turn_num})",
                    ))
        return result

    def _from_long_term(self, mc: Any, query: str, top_k: int) -> list[ContextEvidence]:
        result: list[ContextEvidence] = []
        search = getattr(mc, "search", None)
        if not callable(search):
            return result
        try:
            entries = search(query)
        except TypeError:
            entries = search(query=query)
        for item in entries[:top_k]:
            content = getattr(item, "content", getattr(item, "value", ""))
            result.append(self._wrap(getattr(item, "key", getattr(item, "id", content)), "long_term", str(content), getattr(item, "metadata", {}), "long-term memory"))
        return result

    def _from_skills(self, mc: Any, query: str, top_k: int) -> list[ContextEvidence]:
        result: list[ContextEvidence] = []
        finder = getattr(mc, "find_relevant_skills", None)
        if not callable(finder):
            return result
        for hit in finder(query)[:top_k]:
            skill = getattr(hit, "skill", hit)
            content = f"{skill.name}: {skill.description}"
            result.append(self._wrap(skill.skill_id, "skill", content, skill.metadata, "skill memory"))
        return result

    def _from_repository_index(self, query: str) -> list[ContextEvidence]:
        repo = getattr(self.repository_index, "summary", None) or self.repository_index
        items = []
        if isinstance(repo, dict):
            for key, value in repo.items():
                if query.lower() in str(key).lower() or query.lower() in str(value).lower():
                    items.append(self._wrap(f"repo:{key}", "repository", f"{key}: {value}", {}, "repository index"))
        return items

    def _from_code_index(self, query: str) -> list[ContextEvidence]:
        items = []
        idx = self.code_index
        if idx is None:
            return items
        symbols = getattr(idx, "symbols", {})
        for path, names in symbols.items():
            if query.lower() in str(path).lower() or any(query.lower() in n.lower() for n in names):
                items.append(self._wrap(f"code:{path}", "code", f"{path}: {', '.join(names)}", {}, "code index"))
        return items

    def _wrap(self, item_id: str, source: str, content: str, metadata: dict[str, Any], selected_reason: str) -> ContextEvidence:
        ts = metadata.get("created_at") or metadata.get("updated_at")
        return ContextEvidence(
            item_id=str(item_id),
            source=source,
            content=content,
            provenance=str(metadata.get("provenance", item_id)),
            confidence=float(metadata.get("confidence", 0.5)),
            freshness=str(metadata.get("freshness", "active")),
            scope=str(metadata.get("scope", metadata.get("session_id", "project"))),
            selected_reason=selected_reason,
            timestamp=normalize_datetime(ts),
        )

    def _rank_and_dedupe(self, evidence: list[ContextEvidence]) -> list[ContextEvidence]:
        """Sort by a fully deterministic key, then deduplicate by item_id.

        Phase 20.2.2 sort priority (all tiebreakers are deterministic):
        1. source_tier  — lower = higher priority (metadata before history)
        2. -confidence  — higher confidence first
        3. freshness    — active before stale before archived
        4. timestamp    — ISO string, lexicographic (newer = later in string)
        5. turn_number  — extracted from metadata field if present
        6. item_id      — stable string fallback; eliminates dict-ordering variance
        """
        seen: set[str] = set()
        unique: list[ContextEvidence] = []
        for item in sorted(
            evidence,
            key=lambda e: (
                self._source_tier(e.source),
                -e.confidence,
                self._freshness_rank(e.freshness),
                # Timestamp: use empty string if None so sort never fails.
                str(e.timestamp or ""),
                # turn_number stored in selected_reason as "turn N" if present.
                self._turn_rank(e.selected_reason),
                e.item_id,
            ),
        ):
            if item.item_id in seen:
                continue
            seen.add(item.item_id)
            unique.append(item)
        return unique

    @staticmethod
    def _turn_rank(selected_reason: str) -> int:
        """Extract turn number from selected_reason for deterministic ordering."""
        import re as _re
        m = _re.search(r"turn\s*(\d+)", selected_reason or "", _re.IGNORECASE)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _source_tier(source: str) -> int:
        """Return priority tier; lower number = higher priority.

        Enforces Phase 20.2.1 requirement #5:
            session_metadata > session_facts > session_history >
            long_term > skill > repository > code
        """
        tiers: dict[str, int] = {
            "session_metadata": 0,   # highest: deterministic, indexed metadata
            "session":          1,   # current session facts (entries)
            "session_summary":  2,   # session summary text
            "session_history":  3,   # raw conversation history events
            "long_term":        4,   # long-term memory store
            "skill":            5,   # skills/knowledge base
            "repository":       6,   # repository index
            "code":             7,   # code symbol index
        }
        return tiers.get(source, 8)

    @staticmethod
    def _scope_rank(scope: str) -> int:
        if scope == "session":
            return 3
        if scope == "project":
            return 2
        if scope == "workspace":
            return 1
        return 0

    @staticmethod
    def _freshness_rank(freshness: str) -> int:
        order = {"active": 0, "stale": 1, "archived": 2, "deleted": 3}
        return order.get(freshness, 1)

    def _bundle(self, query: str, evidence: list[ContextEvidence]) -> ContextBundle:
        domains = ConfidenceDomains(
            evidence=min((e.confidence for e in evidence), default=0.0),
            retrieval=min((e.confidence for e in evidence), default=0.0),
            reasoning=0.0,
            execution=0.0,
            memory=min((e.confidence for e in evidence), default=0.0),
            learning=0.0,
        )
        snapshot = ConfidenceSnapshot(domains=domains, rationale=tuple(e.selected_reason for e in evidence))
        return ContextBundle(
            query=query,
            evidence=tuple(evidence),
            citations=tuple(f"{e.source}:{e.item_id}" for e in evidence),
            provenance=tuple(e.provenance for e in evidence),
            confidence=snapshot.domains.retrieval,
            freshness=tuple(e.freshness for e in evidence),
            scope=evidence[0].scope if evidence else "unknown",
            memory_source=tuple(e.source for e in evidence),
        )

    @staticmethod
    def _is_cross_session_query(query: str) -> bool:
        normalized = query.lower()
        phrases = (
            "previous session",
            "previous conversation",
            "last session",
            "what did we discuss",
            "what were we working on",
            "continue where we left off",
            "continue previous conversation",
            "summarize previous session",
            "remind me what we discussed",
            "yesterday",
            "earlier conversation",
        )
        return any(phrase in normalized for phrase in phrases)
