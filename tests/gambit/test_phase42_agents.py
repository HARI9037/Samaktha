import pytest
from uuid import uuid4

from app.core.contracts.agents import AgentCapability, AgentDefinition, AgentRole, AgentTask
from app.core.contracts.planning import TaskKind, GoalComplexity
from app.core.gambit.agents import AgentRegistry
from app.core.gambit.agent_planner import AgentPlanner


def test_agent_contracts_validation():
    cap = AgentCapability(name="cap1", description="desc", supported_task_types=[TaskKind.PLAN])
    assert cap.confidence == 1.0
    
    agent = AgentDefinition(
        agent_id="test-agent",
        name="Test Agent",
        role=AgentRole.PLANNER,
        capabilities=[cap]
    )
    assert agent.total_confidence == 1.0
    assert agent.supports_task_type(TaskKind.PLAN)
    assert not agent.supports_task_type(TaskKind.EXECUTE_VIA_RUNTIME)
    
    task = AgentTask(agent_id="test-agent", objective="do a plan", kind=TaskKind.PLAN)
    pt = task.to_plan_task()
    assert pt.metadata["agent_id"] == "test-agent"
    assert pt.kind == TaskKind.PLAN


def test_agent_registry_deterministic_ranking():
    registry = AgentRegistry()
    registry.register(AgentDefinition(
        agent_id="a-agent", name="A", role=AgentRole.PLANNER, 
        capabilities=[AgentCapability(name="c", description="c", supported_task_types=[TaskKind.PLAN], confidence=0.8)]
    ))
    registry.register(AgentDefinition(
        agent_id="b-agent", name="B", role=AgentRole.PLANNER, 
        capabilities=[AgentCapability(name="c", description="c", supported_task_types=[TaskKind.PLAN], confidence=0.9)]
    ))
    registry.register(AgentDefinition(
        agent_id="c-agent", name="C", role=AgentRole.PLANNER, 
        capabilities=[AgentCapability(name="c", description="c", supported_task_types=[TaskKind.PLAN], confidence=0.9)]
    ))

    # Highest confidence wins. If tied, alphabetical agent_id wins.
    # B has 0.9, C has 0.9. "b-agent" < "c-agent".
    best = registry.find_best_agent(TaskKind.PLAN)
    assert best.agent_id == "b-agent"
    
    # Check fallback / role lookup
    role_best = registry.find_agent_for_role(AgentRole.PLANNER)
    assert role_best.agent_id == "b-agent"


def test_agent_planner_produces_agent_plan():
    planner = AgentPlanner()
    agent_plan = planner.create_agent_plan("design a complex workflow system")
    
    # Complex goal should have PLAN, VERIFY, REFLECT, EXECUTE
    assert len(agent_plan.agent_tasks) > 2
    assert agent_plan.goal.complexity in [GoalComplexity.MEDIUM, GoalComplexity.HIGH]
    
    # Make sure agent roles are correct
    tasks_with_roles = [t.metadata.get("agent_role") for t in agent_plan.agent_tasks]
    assert AgentRole.PLANNER in tasks_with_roles


def test_agent_planner_produces_execution_plan():
    planner = AgentPlanner()
    exec_plan = planner.plan_with_agents("design a complex workflow system")
    
    # Should be regular plan tasks now
    assert len(exec_plan.tasks) > 2
    for t in exec_plan.tasks:
        assert "agent_id" in t.metadata
        assert t.origin == "agent_planner"
    
    # Workflow should be populated
    assert len(exec_plan.workflow) == len(exec_plan.tasks)


def test_no_architecture_violation_in_gambit():
    import sys
    
    # Unload to trace fresh
    modules_to_unload = [m for m in sys.modules if m.startswith('app.core.gambit.agent')]
    for m in modules_to_unload:
        del sys.modules[m]
        
    import app.core.gambit.agents
    import app.core.gambit.agent_planner
    
    for m in sys.modules:
        if m.startswith('app.core.gambit.agent'):
            assert 'runtime' not in m.lower(), "GAMBIT agents should not import Runtime"
            assert 'tool' not in m.lower(), "GAMBIT agents should not import Tools"
            assert 'provider' not in m.lower(), "GAMBIT agents should not import Providers"
