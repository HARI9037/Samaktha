from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.gambit import Planner
from app.intelligence import (
    AdaptivePlanningPolicy,
    ExplainabilityEngine,
    FailurePatternLibrary,
    IntelligenceManager,
    PlanOptimizer,
    PlanningContext,
)
from app.intelligence.context import ContextBundle, ContextEvidence
from app.intelligence.graph import KnowledgeGraphBuilder
from app.intelligence.learning import LearningEngine
from app.intelligence.manager import IntelligenceManager
from app.intelligence.reflection import ReflectionEngine
from app.intelligence.retrieval import RetrievalEngine
from app.memory.controller.facade import MemoryController
from app.memory.manager import MemoryManager
from app.memory.session_manager import SessionManager


def _manager(tmp_path: Path) -> IntelligenceManager:
    sessions = SessionManager(base_dir=tmp_path, clock=lambda: "2026-08-03T10:00:00+00:00")
    controller = MemoryController(MemoryManager())
    controller.write_knowledge("env var REQUIRED=1", source="system", tags=["build"])
    return IntelligenceManager(
        retrieval_engine=RetrievalEngine(controller, session_manager=sessions),
        reflection_engine=ReflectionEngine(),
        learning_engine=LearningEngine(),
        memory_controller=controller,
    )


def test_context_bundle_is_evidence_only():
    bundle = ContextBundle(
        query="build",
        evidence=(
            ContextEvidence(
                item_id="1",
                source="long_term",
                content="run build",
                provenance="mem:1",
                confidence=0.8,
                freshness="active",
                scope="project",
                selected_reason="matched",
            ),
        ),
        citations=("long_term:1",),
        provenance=("mem:1",),
        confidence=0.8,
        freshness=("active",),
        scope="project",
        memory_source=("long_term",),
    )
    assert bundle.evidence[0].content == "run build"
    assert bundle.evidence[0].source == "long_term"


def test_retrieval_informed_planning_uses_context(tmp_path):
    manager = _manager(tmp_path)
    context = manager.build_planning_context("how do I build the repo?", session_id="s1")
    planner = Planner(memory_manager=MemoryManager())
    plan = asyncio.run(planner.plan_with_capability_check("how do I build the repo?", planning_context=context))
    assert plan.status.name == "OK"
    assert any("retrieved" in reason.lower() for reason in plan.plan.planner_reasoning)


def test_reflection_informed_planning_records_failure_patterns():
    library = FailurePatternLibrary()
    library.register("timeout", ["pytest timeout"], "Increase timeout", 0.9)
    context = PlanningContext(
        query="pytest timeout",
        bundle=ContextBundle(
            query="pytest timeout",
            evidence=tuple(),
            citations=tuple(),
            provenance=tuple(),
            confidence=0.0,
            freshness=tuple(),
            scope="unknown",
            memory_source=tuple(),
        ),
        failure_patterns=library.consult("pytest timeout"),
    )
    assert context.failure_patterns


def test_plan_optimizer_removes_duplicate_tasks():
    class Dummy:
        def __init__(self, kind, description):
            self.kind = kind
            self.description = description

    tasks = [Dummy(type("K", (), {"value": "x"})(), "same"), Dummy(type("K", (), {"value": "x"})(), "same"), Dummy(type("K", (), {"value": "y"})(), "other")]
    optimized = PlanOptimizer().optimize(tasks, None)
    assert len(optimized) == 2


def test_explainability_references_evidence():
    engine = ExplainabilityEngine()
    context = PlanningContext(
        query="demo",
        bundle=ContextBundle(
            query="demo",
            evidence=(
                ContextEvidence(
                    item_id="1",
                    source="session",
                    content="demo evidence",
                    provenance="session:1",
                    confidence=0.9,
                    freshness="active",
                    scope="session",
                    selected_reason="matched session memory",
                ),
            ),
            citations=("session:1",),
            provenance=("session:1",),
            confidence=0.9,
            freshness=("active",),
            scope="session",
            memory_source=("session",),
        ),
        explanations=("matched session memory",),
    )
    plan = type("Plan", (), {"used_skill_names": ["Context Synthesis"], "planner_reasoning": ["Injected 1 relevant skills from memory."]})()
    reasons = engine.explain_plan(plan, context)
    assert any("evidence" in reason.lower() for reason in reasons)


def test_confidence_routing_is_deterministic(tmp_path):
    manager = _manager(tmp_path)
    context = manager.build_planning_context("debug dependency resolution", session_id="s1")
    policy = AdaptivePlanningPolicy()
    assert policy.choose(context) in {"default", "broad-retrieval", "broaden-retrieval", "simple-plan"}
    assert policy.choose(context) == policy.choose(context)


def test_cross_session_retrieval_excludes_session_history(tmp_path):
    sessions = SessionManager(base_dir=tmp_path, clock=lambda: "2026-08-03T10:00:00+00:00")
    s1 = sessions.create_session(session_id="s1")
    sessions.add_memory_entry(s1.session_id, "pattern", "pytest timeout", "fact")
    controller = MemoryController(MemoryManager())
    retrieval = RetrievalEngine(controller, session_manager=sessions)
    bundle = retrieval.assemble_context("pytest timeout", session_id="s2")
    assert not any(ev.source == "session_history" for ev in bundle.evidence)


def test_knowledge_graph_expands_lightweight_relationships():
    graph = KnowledgeGraphBuilder().build(project="proj", repositories=["repo"], files=["file.py"])
    assert graph.neighbors("proj") == ("repo",)
