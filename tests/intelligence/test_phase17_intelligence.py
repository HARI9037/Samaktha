from __future__ import annotations

from datetime import datetime, timezone

from app.core.contracts.memory import MemoryItem, MemoryType
from app.core.contracts.skills import SkillRecord
from app.memory.controller.facade import MemoryController
from app.memory.manager import MemoryManager
from app.memory.session_manager import SessionManager
from app.intelligence import (
    ConfidenceDomains,
    ContextBundle,
    GraphEdge,
    GraphNode,
    IntelligenceManager,
    KnowledgeGraphBuilder,
    LearningEngine,
    MemoryLifecycleState,
    ReflectionEngine,
    RetrievalEngine,
    SkillRunner,
)


def _make_memory_controller() -> MemoryController:
    return MemoryController(MemoryManager())


def _make_skill(skill_id: str, name: str, description: str, source_plan: str = "plan-1") -> SkillRecord:
    return SkillRecord(
        skill_id=skill_id,
        name=name,
        description=description,
        category="general",
        confidence="high",
        source_plan=source_plan,
        source_tasks=["task-1"],
        tags=["test"],
    )


def test_context_bundle_is_immutable():
    bundle = ContextBundle(
        query="q",
        evidence=tuple(),
        citations=tuple(),
        provenance=tuple(),
        confidence=0.0,
        freshness=tuple(),
        scope="unknown",
        memory_source=tuple(),
    )
    try:
        bundle.query = "other"  # type: ignore[misc]
        mutated = False
    except Exception:
        mutated = True
    assert mutated


def test_retrieval_engine_cross_session_ranking(tmp_path):
    session_manager = SessionManager(base_dir=tmp_path, clock=lambda: "2026-08-03T10:00:00+00:00")
    session_a = session_manager.create_session(session_id="session-a")
    session_manager.add_memory_entry(session_a.session_id, "topic", "shared project detail", "fact")
    session_b = session_manager.create_session(session_id="session-b")
    session_manager.add_memory_entry(session_b.session_id, "topic", "other detail", "fact")
    controller = _make_memory_controller()
    controller.write_knowledge("project detail", source="system", tags=["project"])
    skill = _make_skill("skill-1", "Project Skill", "shared project detail")
    controller.memory_manager.save_skill(skill)
    engine = RetrievalEngine(controller, session_manager=session_manager)
    result = engine.retrieve("shared project detail", session_id="session-a", top_k=10)
    assert result.bundle.evidence
    assert result.bundle.evidence[0].source in {"session", "session_history", "long_term", "skill"}
    assert any(ev.source in {"session", "session_history"} for ev in result.bundle.evidence)
    assert any(ev.selected_reason for ev in result.bundle.evidence)


def test_retrieval_engine_preserves_provenance_and_confidence(tmp_path):
    session_manager = SessionManager(base_dir=tmp_path, clock=lambda: "2026-08-03T10:00:00+00:00")
    session = session_manager.create_session(session_id="session-a")
    session_manager.add_memory_entry(session.session_id, "shared", "shared project detail", "fact")
    controller = _make_memory_controller()
    engine = RetrievalEngine(controller, session_manager=session_manager)
    bundle = engine.assemble_context("shared project detail", session_id="session-a")
    assert bundle.provenance
    assert bundle.confidence >= 0.0
    assert bundle.memory_source
    assert bundle.freshness


def test_intelligence_manager_orchestrates_without_planning():
    controller = _make_memory_controller()
    retrieval = RetrievalEngine(controller)
    reflection = ReflectionEngine()
    learning = LearningEngine()
    manager = IntelligenceManager(retrieval, reflection, learning)
    bundle = manager.retrieve("nothing here")
    assert isinstance(bundle, ContextBundle)
    report = type("Report", (), {"success": True, "completed_tasks": 1, "failed_tasks": 0, "results": ["task-1"], "errors": [], "metadata": {"goal": "test"}})()
    reflection_summary = manager.reflect(report)
    proposals = manager.learn(reflection_summary)
    assert proposals
    assert proposals[0].lifecycle_state == MemoryLifecycleState.VALIDATED


def test_reflection_and_learning_are_deterministic():
    reflection = ReflectionEngine()
    report = type("Report", (), {"success": True, "completed_tasks": 2, "failed_tasks": 0, "results": ["a"], "errors": [], "metadata": {"goal": "demo"}})()
    first = reflection.reflect(report)
    second = reflection.reflect(report)
    assert first == second
    learning = LearningEngine()
    assert learning.propose(first) == learning.propose(second)


def test_knowledge_graph_builder_and_edges():
    graph = KnowledgeGraphBuilder().build(project="proj", repositories=["repo"], files=["file.py"])
    assert any(node.kind == "Project" for node in graph.nodes)
    assert any(edge.relation == "contains" for edge in graph.edges)


def test_confidence_domains_are_independent():
    domains = ConfidenceDomains(evidence=0.9, retrieval=0.8, reasoning=0.7, execution=0.6, memory=0.5, learning=0.4)
    assert domains.evidence != domains.learning


def test_skill_runner_load_validate_and_expand():
    runner = SkillRunner()
    plan = runner.load_approved_skill({"skill_id": "s1", "trigger": "/repo", "steps": ["step1", "step2"], "constraints": ["cap"]})
    assert runner.validate_trigger(plan, "/repo")
    assert runner.verify_constraints(plan, {"violations": []})
    assert runner.expand(plan) == ("step1", "step2")
