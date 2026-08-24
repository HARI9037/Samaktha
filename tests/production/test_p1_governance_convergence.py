"""Exact-production regression coverage for P1 governance convergence."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

import app.agent.production as production_agent
import app.core.app as core_app
from app.config.settings import Settings
from app.core.contracts import (
    ApprovedRuntimeTask,
    ExecutionPlan,
    Goal,
    GoalComplexity,
    RouterRequest,
    RoutingDecision,
    RuntimeContext,
    StreamRequest,
)
from app.core.contracts.planning import PlanTask, TaskKind
from app.core.contracts.policy import (
    ApprovalDecision,
    ExecutionConstraints,
    ExecutionLocation,
    ExecutionPermit,
    PrivacyCategory,
    operation_digest,
)
from app.providers.config import ProviderSettings
from app.tools.base import ToolResult
from app.workflow.engine import WorkflowEngine
from tests.conftest import approved_task


@pytest.fixture
def production_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="groq",
        groq_api_key="production-regression-key",
        local_base_url="http://127.0.0.1:11434",
        local_model="local-test-model",
        mock_agent=True,
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    settings = Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "p1.db"),
        personality_state_path=str(tmp_path / "personality.json"),
    )
    return core_app.create_orchestrator(settings)


def _provider_plan(permit: ExecutionPermit) -> ExecutionPlan:
    router_request = RouterRequest(
        purpose="text_generation",
        complexity=GoalComplexity.LOW,
        estimated_context_tokens=20,
        requires_local_model=False,
        requires_code=False,
        requires_reasoning=False,
    )
    return ExecutionPlan(
        plan_id="p1-plan",
        goal=Goal(
            goal_id="p1-goal",
            raw_request="hello",
            summary="hello",
            complexity=GoalComplexity.LOW,
        ),
        tasks=[
            PlanTask(
                task_id="provider-task",
                title="Provider task",
                kind=TaskKind.EXECUTE_VIA_RUNTIME,
                description="Provider task",
                execution_action_type="text_generation",
                router_request=router_request,
                metadata={"permit": permit.model_dump()},
            )
        ],
        workflow=[],
        router_request=router_request,
    )


def test_interface_cannot_forge_allow_by_patching_pending_permit() -> None:
    issued = approved_task(
        task_id="provider-task",
        action_type="text_generation",
        inputs={"prompt": "hello"},
    ).permit
    assert issued is not None
    pending = ExecutionPermit.resolve_pending(
        issued,
        decision=ApprovalDecision.ASK_USER,
    )
    runtime_task = WorkflowEngine._workflow_tasks(
        _provider_plan(pending),
        {"provider-task": {"permit": {"decision": "allow"}}},
    )[0].runtime_task

    assert runtime_task.permit is not None
    assert runtime_task.permit.decision == ApprovalDecision.ASK_USER


@pytest.mark.asyncio
async def test_permit_for_operation_a_rejects_changed_payload(
    production_orchestrator,
) -> None:
    approved = approved_task(
        task_id="provider-task",
        action_type="text_generation",
        inputs={"prompt": "operation-a"},
        subject_id="principal-a",
    )
    assert approved.permit is not None
    task = ApprovedRuntimeTask(
        task_id="provider-task",
        title="Provider task",
        description="Provider task",
        action_type="text_generation",
        inputs={"prompt": "operation-b"},
        metadata={
            "required_permissions": [],
            "execution_constraints": approved.permit.constraints.model_dump(),
        },
        permit=approved.permit,
    )
    result = await production_orchestrator.runtime.run(
        RuntimeContext(request_id="p1-operation", user_id="principal-a"),
        task,
        RoutingDecision(
            provider_id="mock",
            model_id="mock-model",
            reasoning_summary="production regression",
            execution_constraints=approved.permit.constraints,
        ),
    )

    assert result.status.value == "failed"
    assert result.metadata["diagnostic"] == "permit_operation_mismatch"


@pytest.mark.asyncio
async def test_sensitive_router_request_rejects_preferred_cloud(
    production_orchestrator,
) -> None:
    decision = await production_orchestrator.model_router.route(
        RouterRequest(
            purpose="text_generation",
            complexity=GoalComplexity.LOW,
            estimated_context_tokens=20,
            requires_local_model=True,
            requires_code=False,
            requires_reasoning=False,
        )
    )

    assert decision.provider_id == "local"
    assert decision.model_id == "local-test-model"


def test_tui_uses_the_exact_production_runtime(
    production_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        production_agent,
        "create_orchestrator",
        lambda: production_orchestrator,
    )
    runtime = production_agent.ProductionAgentRuntime()

    assert runtime._orchestrator is production_orchestrator
    assert runtime._orchestrator._runtime is production_orchestrator.runtime


def _runtime_task(
    *,
    action_type: str = "text_generation",
    inputs: dict | None = None,
    tool: str | None = None,
    subject_id: str = "principal-a",
) -> ApprovedRuntimeTask:
    metadata = {"tool": tool} if tool else {}
    return approved_task(
        task_id="bound-task",
        action_type=action_type,
        inputs=inputs or {"prompt": "operation-a"},
        metadata=metadata,
        subject_id=subject_id,
    )


def _routing_for(task: ApprovedRuntimeTask) -> RoutingDecision:
    assert task.permit is not None
    return RoutingDecision(
        provider_id="mock",
        model_id="mock-model",
        reasoning_summary="P1 bound operation",
        execution_constraints=task.permit.constraints,
    )


def test_operation_digest_is_stable_but_argument_sensitive() -> None:
    first = operation_digest("tool", "shell", {"command": "echo a", "cwd": "C:/tmp"})
    reordered = operation_digest("tool", "shell", {"cwd": "C:/tmp", "command": "echo a"})
    changed = operation_digest("tool", "shell", {"command": "echo b", "cwd": "C:/tmp"})
    assert first == reordered
    assert first != changed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    [
        ("arguments", "permit_operation_mismatch"),
        ("target", "permit_operation_mismatch"),
        ("action", "permit_operation_mismatch"),
        ("principal", "permit_subject_mismatch"),
        ("tamper", "permit_integrity_invalid"),
        ("permissions", "permit_permissions_mismatch"),
        ("constraints", "permit_constraints_mismatch"),
    ],
)
async def test_runtime_rejects_every_bound_permit_mismatch_before_execution(
    production_orchestrator,
    mutation: str,
    diagnostic: str,
) -> None:
    original = _runtime_task()
    assert original.permit is not None
    task = original.model_copy(deep=True)
    context = RuntimeContext(request_id="request", user_id="principal-a")
    if mutation == "arguments":
        task.inputs["prompt"] = "operation-b"
    elif mutation == "target":
        task.action_type = "tool"
        task.metadata["tool"] = "filesystem"
    elif mutation == "action":
        task.action_type = "code_generation"
    elif mutation == "principal":
        context.user_id = "principal-b"
    else:
        if mutation == "tamper":
            task.permit = task.permit.model_copy(update={"policy_reference": "tampered"})
        elif mutation == "permissions":
            task.metadata["required_permissions"] = ["network"]
        else:
            task.metadata["execution_constraints"] = {
                "requires_local_model": True,
                "network_allowed": True,
                "privacy_category": "sensitive",
            }

    result = await production_orchestrator.runtime.run(
        context,
        task,
        _routing_for(original),
    )

    assert result.status.value == "failed"
    assert result.metadata["diagnostic"] == diagnostic


@pytest.mark.asyncio
async def test_permit_for_one_tool_cannot_authorize_another_tool(
    production_orchestrator,
) -> None:
    original = _runtime_task(
        action_type="tool",
        tool="filesystem",
        inputs={"action": "read", "path": "C:/safe/a.txt"},
    )
    changed = original.model_copy(deep=True)
    changed.metadata["tool"] = "shell"
    result = await production_orchestrator.runtime.run(
        RuntimeContext(request_id="request", user_id="principal-a"),
        changed,
        _routing_for(original),
    )
    assert result.metadata["diagnostic"] == "permit_operation_mismatch"


@pytest.mark.asyncio
async def test_expired_permit_is_rejected_before_execution(
    production_orchestrator,
) -> None:
    task = _runtime_task()
    assert task.permit is not None
    task.permit = ExecutionPermit.resolve_pending(
        task.permit,
        decision=ApprovalDecision.ALLOW,
        now=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    result = await production_orchestrator.runtime.run(
        RuntimeContext(request_id="request", user_id="principal-a"),
        task,
        _routing_for(task),
    )
    assert result.metadata["diagnostic"] == "permit_expired"


@pytest.mark.asyncio
async def test_router_constraints_must_match_permit_constraints(
    production_orchestrator,
) -> None:
    task = _runtime_task()
    routing = _routing_for(task).model_copy(
        update={
            "execution_constraints": ExecutionConstraints(
                requires_local_model=True,
                privacy_category=PrivacyCategory.SENSITIVE,
            )
        }
    )
    result = await production_orchestrator.runtime.run(
        RuntimeContext(request_id="request", user_id="principal-a"),
        task,
        routing,
    )
    assert result.metadata["diagnostic"] == "routing_constraints_mismatch"


@pytest.mark.asyncio
async def test_runtime_batch_validates_each_permit_independently(
    production_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = production_orchestrator.provider_manager.resolve_provider("mock")
    calls = 0

    async def execute(payload):
        nonlocal calls
        calls += 1
        return {"success": True, "response": payload.get("prompt", "")}

    monkeypatch.setattr(provider, "execute", execute)
    allowed = _runtime_task(subject_id="principal-a")
    denied = _runtime_task(subject_id="principal-a").model_copy(deep=True)
    denied.task_id = "changed-task-id"

    results = await production_orchestrator.runtime.run_batch(
        RuntimeContext(request_id="request", user_id="principal-a"),
        [(allowed, _routing_for(allowed)), (denied, _routing_for(denied))],
    )

    assert calls == 1
    assert [result.status.value for result in results] == ["completed", "failed"]
    assert results[1].metadata["diagnostic"] == "permit_action_mismatch"


async def _governed_tool_flow(
    production_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
    *,
    tool_id: str,
    request: str,
    decision: str,
):
    production_orchestrator.model_router._preferred_provider = "mock"
    tool = production_orchestrator.tool_manager.resolve_tool(tool_id)
    calls = 0

    async def safe_effect(arguments):
        nonlocal calls
        calls += 1
        if tool_id == "internet":
            return ToolResult(
                ok=True,
                data={"internet": True, "query": arguments.get("query"), "results": []},
            )
        return ToolResult(ok=True, data={"output": "safe command output"})

    monkeypatch.setattr(tool, "run", safe_effect)
    context = RuntimeContext(request_id=f"{tool_id}-initial", session_id=f"{tool_id}-session")
    state = await production_orchestrator.run_pipeline(request, context)
    governed_task = next(
        task for task in state.execution_plan.tasks
        if task.metadata.get("tool") == tool_id
    )
    assert state.workflow_state.status.value == "paused"

    resumed = await production_orchestrator.resume_pipeline(
        state,
        RuntimeContext(
            request_id=f"{tool_id}-resume",
            session_id=f"{tool_id}-session",
            metadata={"source": "test-interface"},
        ),
        governed_task.task_id,
        {
            "approval_decision": decision,
            "approval_reasons": [f"test {decision}"],
        },
    )
    return calls, resumed, governed_task


@pytest.mark.asyncio
async def test_approved_network_action_executes_exactly_once(
    production_orchestrator, monkeypatch,
) -> None:
    calls, state, task = await _governed_tool_flow(
        production_orchestrator,
        monkeypatch,
        tool_id="internet",
        request="search internet for current python version",
        decision="allow",
    )
    assert calls == 1
    assert state.runtime_result.status.value == "completed", (
        state.runtime_result.error,
        state.execution_report.errors,
        state.execution_report.results,
    )
    authorization = next(
        item for item in state.execution_report.metadata["authorizations"]
        if item["task_id"] == task.task_id
    )
    record = next(
        item
        for item in production_orchestrator.governance.records.list_records()
        if item.task_id == task.task_id
    )
    assert authorization["decision"] == record.decision == "allow"
    assert authorization["permit_id"] == record.permit_id
    assert authorization["operation_digest"] == record.operation_digest


@pytest.mark.asyncio
async def test_approved_execute_action_executes_exactly_once(
    production_orchestrator, monkeypatch,
) -> None:
    calls, state, _ = await _governed_tool_flow(
        production_orchestrator,
        monkeypatch,
        tool_id="shell",
        request="run command echo hello",
        decision="allow",
    )
    assert calls == 1
    assert state.runtime_result.status.value == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_id", "user_request"),
    [
        ("internet", "search internet for current python version"),
        ("shell", "run command echo hello"),
    ],
)
async def test_denied_network_and_execute_actions_execute_zero_times(
    production_orchestrator, monkeypatch, tool_id, user_request,
) -> None:
    calls, state, _ = await _governed_tool_flow(
        production_orchestrator,
        monkeypatch,
        tool_id=tool_id,
        request=user_request,
        decision="deny",
    )
    assert calls == 0
    assert state.runtime_result.status.value == "failed"


@pytest.mark.asyncio
async def test_interface_cannot_submit_an_executable_permit(
    production_orchestrator,
) -> None:
    production_orchestrator.model_router._preferred_provider = "mock"
    state = await production_orchestrator.run_pipeline(
        "run command echo hello",
        RuntimeContext(request_id="forge-initial", session_id="forge-session"),
    )
    task = next(
        task for task in state.execution_plan.tasks
        if task.metadata.get("tool") == "shell"
    )
    with pytest.raises(ValueError, match="approval decision"):
        await production_orchestrator.resume_pipeline(
            state,
            RuntimeContext(request_id="forge-resume", session_id="forge-session"),
            task.task_id,
            {"permit": {"decision": "allow"}},
        )


def _all_available(_provider_id):
    return SimpleNamespace(available=True)


@pytest.mark.asyncio
async def test_local_only_fallback_never_attempts_cloud(
    production_orchestrator, monkeypatch,
) -> None:
    manager = production_orchestrator.provider_manager
    monkeypatch.setattr(manager, "get_provider_status", _all_available)
    cloud_calls = 0

    async def local_failure(payload):
        return {"success": False, "finish_reason": "server_error", "model_id": payload["model_id"]}

    async def cloud_execution(payload):
        nonlocal cloud_calls
        cloud_calls += 1
        return {"success": True, "content": "policy escaped"}

    monkeypatch.setattr(manager.resolve_provider("local"), "execute", local_failure)
    monkeypatch.setattr(manager.resolve_provider("mock"), "execute", local_failure)
    for provider_id in ("openai", "groq", "openrouter"):
        monkeypatch.setattr(manager.resolve_provider(provider_id), "execute", cloud_execution)

    result = await manager.execute_provider(
        "local",
        {"prompt": "sensitive"},
        model_id="local-test-model",
        required_capabilities=["text_generation"],
        execution_constraints=ExecutionConstraints(
            requires_local_model=True,
            privacy_category=PrivacyCategory.SENSITIVE,
        ),
    )

    assert result["success"] is False
    assert cloud_calls == 0


@pytest.mark.asyncio
async def test_streaming_local_only_fallback_never_attempts_cloud(
    production_orchestrator, monkeypatch,
) -> None:
    manager = production_orchestrator.provider_manager
    monkeypatch.setattr(manager, "get_provider_status", _all_available)
    cloud_calls = 0

    async def local_stream(_payload):
        if False:
            yield ""
        raise RuntimeError("local failed")

    async def cloud_stream(_payload):
        nonlocal cloud_calls
        cloud_calls += 1
        yield "policy escaped"

    monkeypatch.setattr(manager.resolve_provider("local"), "execute_stream", local_stream)
    monkeypatch.setattr(manager.resolve_provider("mock"), "execute_stream", local_stream)
    for provider_id in ("openai", "groq", "openrouter"):
        monkeypatch.setattr(manager.resolve_provider(provider_id), "execute_stream", cloud_stream)

    request = StreamRequest(
        request_id="stream-local-only",
        provider_id="local",
        prompt="sensitive",
        capabilities=["text_generation"],
        execution_constraints=ExecutionConstraints(
            requires_local_model=True,
            privacy_category=PrivacyCategory.SENSITIVE,
        ),
        metadata={"model_id": "local-test-model"},
    )
    with pytest.raises(RuntimeError, match="local failed"):
        _ = [chunk async for chunk in manager.stream_provider(request)]
    assert cloud_calls == 0


@pytest.mark.asyncio
async def test_fallback_selects_provider_compatible_model(
    production_orchestrator, monkeypatch,
) -> None:
    manager = production_orchestrator.provider_manager
    monkeypatch.setattr(manager, "get_provider_status", _all_available)
    fallback_models: list[str] = []

    async def primary_failure(payload):
        return {"success": False, "finish_reason": "server_error", "model_id": payload["model_id"]}

    async def fallback_success(payload):
        fallback_models.append(payload["model_id"])
        return {"success": True, "content": "fallback", "model_id": payload["model_id"]}

    monkeypatch.setattr(manager.resolve_provider("mock"), "execute", primary_failure)
    monkeypatch.setattr(manager.resolve_provider("openai"), "execute", fallback_success)

    result = await manager.execute_provider(
        "mock",
        {"prompt": "hello"},
        model_id="mock-model",
        required_capabilities=["text_generation"],
        execution_constraints=ExecutionConstraints(),
    )

    assert result["success"] is True
    assert fallback_models == ["gpt-4o",]
    assert result["model_id"] == "gpt-4o"


def test_provider_execution_location_metadata_is_authoritative(
    production_orchestrator,
) -> None:
    infos = {
        info.provider_id: info.execution_location
        for info in production_orchestrator.provider_manager.list_providers()
    }
    assert infos["local"] == ExecutionLocation.LOCAL
    assert infos["mock"] == ExecutionLocation.LOCAL
    assert {infos[name] for name in ("openai", "groq", "openrouter")} == {
        ExecutionLocation.CLOUD
    }
