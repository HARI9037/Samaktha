"""P0.2 — security controls are active runtime controls, not dead code.

Verifies the production wiring:
- create_orchestrator() composes input scanner + output filter + tool guard
  and wires the tool guard into the runtime's ToolExecutor.
- Malicious/dangerous inputs are rejected at the pipeline entry (API and
  orchestrator paths) before any provider or tool execution.
- The output filter redacts leaked credentials from user-facing results.
- Tool guard denials stop execution and are observable/auditable.
"""
import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.core.app import create_app, create_orchestrator
from app.core.contracts import RoutingDecision, RuntimeContext
from app.core.contracts.planning import TaskStatus
from app.runtime import ToolExecutor
from app.security.output_filter import OutputSecurityFilter
from app.security.tool_guard import ToolGuard
from app.tools import ToolInfo, ToolManager, ToolRegistry
from app.tools.base import Tool, ToolResult
from tests.conftest import approved_task


def test_production_composition_wires_security_controls():
    orchestrator = create_orchestrator()

    assert orchestrator.input_scanner is not None
    assert isinstance(orchestrator.output_filter, OutputSecurityFilter)
    assert isinstance(orchestrator.tool_guard, ToolGuard)
    assert orchestrator.security_metrics is not None


def test_production_tool_executor_has_tool_guard():
    orchestrator = create_orchestrator()
    executors = orchestrator._runtime._dispatcher._registry._executors
    tool_executor = executors["tool"]
    assert isinstance(tool_executor, ToolExecutor)
    assert isinstance(tool_executor._tool_guard, ToolGuard)


@pytest.mark.asyncio
async def test_orchestrator_rejects_path_traversal_input():
    orchestrator = create_orchestrator()
    result = await orchestrator.run(
        request="list ../../etc/passwd",
        runtime_context=RuntimeContext(request_id="req-security"),
    )
    assert result.status == TaskStatus.FAILED
    assert result.metadata.get("security_blocked") is True
    assert "Path traversal" in result.metadata.get("security_reason", "")


@pytest.mark.asyncio
async def test_orchestrator_rejects_dangerous_command_input():
    orchestrator = create_orchestrator()
    result = await orchestrator.run(
        request="run rm -rf /var/log",
        runtime_context=RuntimeContext(request_id="req-security"),
    )
    assert result.status == TaskStatus.FAILED
    assert result.metadata.get("security_blocked") is True
    assert "Dangerous command" in result.metadata.get("security_reason", "")


@pytest.mark.asyncio
async def test_orchestrator_rejects_credential_input():
    orchestrator = create_orchestrator()
    result = await orchestrator.run(
        request="set api_key=super_secret_value",
        runtime_context=RuntimeContext(request_id="req-security"),
    )
    assert result.status == TaskStatus.FAILED
    assert result.metadata.get("security_blocked") is True
    assert "Credential leakage" in result.metadata.get("security_reason", "")


def test_api_blocks_malicious_input():
    app = create_app(Settings())
    client = TestClient(app)

    response = client.post("/execute", json={"message": "run rm -rf /"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["response"] is None
    assert "Dangerous command" in (body["error"] or "")


def test_output_filter_redacts_result_credentials():
    from app.core.contracts.runtime import RuntimeResult
    from app.core.orchestrator.pipeline import PipelineState

    orchestrator = create_orchestrator()
    state = PipelineState(request="safe")
    state.runtime_result = RuntimeResult(
        task_id="t1",
        status=TaskStatus.COMPLETED,
        output={
            "content": "Connected with api_key='sk_live_12345'",
            "metadata": {"user": "admin", "token": "abc123"},
        },
        error="debug api_key=x-secret",
    )

    orchestrator._apply_output_security(state)

    output = state.runtime_result.output
    assert "sk_live_12345" not in output["content"]
    assert "[REDACTED]" in output["content"]
    assert output["metadata"]["token"] == "[REDACTED]"
    assert "x-secret" not in state.runtime_result.error
    assert "[REDACTED]" in state.runtime_result.error


class _RecordingTool(Tool):
    def __init__(self) -> None:
        self.invoked = []

    @property
    def name(self) -> str:
        return "filesystem"

    async def run(self, arguments: dict) -> ToolResult:
        self.invoked.append(arguments)
        return ToolResult(ok=True, data={"result": "done"})


@pytest.mark.asyncio
async def test_tool_guard_denies_arguments_and_does_not_run_tool():
    tool = _RecordingTool()
    registry = ToolRegistry()
    registry.register("filesystem", tool, ToolInfo(tool_id="filesystem", description="fs"))
    manager = ToolManager(registry)
    executor = ToolExecutor(manager, tool_guard=ToolGuard(tool_manager=manager))

    result = await executor.execute(
        RuntimeContext(request_id="req"),
        approved_task(
            task_id="t1",
            action_type="tool",
            metadata={"tool": "filesystem"},
            inputs={"action": "write_file", "path": "test.txt", "content": "rm -rf /var/log"},
        ),
        RoutingDecision(provider_id="", model_id="", reasoning_summary="tool"),
    )

    assert result.status == TaskStatus.FAILED
    assert result.metadata.get("security_blocked") is True
    assert "Dangerous command" in result.metadata.get("security_reason", "")
    assert tool.invoked == []
