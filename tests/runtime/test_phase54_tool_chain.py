"""Phase 5.4 tests — Tool Chain Executor.

Validates:
- Sequential execution and batch ordering based on depends_on
- Failure handling (stop on failure vs continue on failure)
- Retry behavior
- Result collection and metrics
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.contracts.tools import (
    ToolChain,
    ToolFailurePolicy,
    ToolStep,
)
from app.runtime.tool_chain import ToolChainExecutor
from app.tools.base import ToolResult


def _build_tool_manager(side_effects=None, return_value=None):
    manager = MagicMock()
    if side_effects:
        manager.execute_tool = AsyncMock(side_effect=side_effects)
    else:
        manager.execute_tool = AsyncMock(return_value=return_value or ToolResult(ok=True, data={"res": "ok"}))
    return manager


@pytest.mark.asyncio
async def test_tool_chain_sequential_execution():
    manager = _build_tool_manager()
    executor = ToolChainExecutor(tool_manager=manager)
    
    chain = ToolChain(
        chain_id="chain1",
        name="Test Chain",
        steps=[
            ToolStep(step_id="step1", tool_name="toolA"),
            ToolStep(step_id="step2", tool_name="toolB", depends_on=["step1"]),
            ToolStep(step_id="step3", tool_name="toolC", depends_on=["step1", "step2"]),
        ]
    )
    
    results = await executor.execute_chain(chain)
    
    assert len(results) == 3
    assert [r.step_id for r in results] == ["step1", "step2", "step3"]
    assert all(r.success for r in results)
    
    metrics = executor.get_metrics()
    assert metrics["chains_started"] == 1
    assert metrics["chains_completed"] == 1
    assert metrics["total_steps"] == 3


@pytest.mark.asyncio
async def test_tool_chain_cyclic_dependency_raises():
    manager = _build_tool_manager()
    executor = ToolChainExecutor(tool_manager=manager)
    
    chain = ToolChain(
        chain_id="chain_cycle",
        name="Cyclic",
        steps=[
            ToolStep(step_id="s1", tool_name="toolA", depends_on=["s2"]),
            ToolStep(step_id="s2", tool_name="toolB", depends_on=["s1"]),
        ]
    )
    
    with pytest.raises(RuntimeError, match="Cyclic dependency"):
        await executor.execute_chain(chain)


@pytest.mark.asyncio
async def test_tool_chain_stop_on_failure():
    manager = _build_tool_manager(side_effects=[
        ToolResult(ok=True, data={}),
        ToolResult(ok=False, error="Tool failed"),
        ToolResult(ok=True, data={}),
    ])
    executor = ToolChainExecutor(tool_manager=manager)
    
    chain = ToolChain(
        chain_id="fail_chain",
        name="Fail Chain",
        failure_policy=ToolFailurePolicy.STOP_ON_FAILURE,
        steps=[
            ToolStep(step_id="s1", tool_name="toolA"),
            ToolStep(step_id="s2", tool_name="toolB", depends_on=["s1"]),
            ToolStep(step_id="s3", tool_name="toolC", depends_on=["s2"]),
        ]
    )
    
    with pytest.raises(RuntimeError, match="STOP_ON_FAILURE is set"):
        await executor.execute_chain(chain)
        
    metrics = executor.get_metrics()
    assert metrics["chains_failed"] == 1
    assert metrics["total_steps"] == 2
    assert metrics["failed_steps"] == 1


@pytest.mark.asyncio
async def test_tool_chain_continue_on_failure():
    manager = _build_tool_manager(side_effects=[
        ToolResult(ok=True, data={}),
        ToolResult(ok=False, error="Tool failed"),
        ToolResult(ok=True, data={}),
    ])
    executor = ToolChainExecutor(tool_manager=manager)
    
    chain = ToolChain(
        chain_id="continue_chain",
        name="Continue Chain",
        failure_policy=ToolFailurePolicy.CONTINUE_ON_FAILURE,
        steps=[
            ToolStep(step_id="s1", tool_name="toolA"),
            ToolStep(step_id="s2", tool_name="toolB", depends_on=["s1"]),
            ToolStep(step_id="s3", tool_name="toolC", depends_on=["s2"]),
        ]
    )
    
    results = await executor.execute_chain(chain)
    
    assert len(results) == 3
    assert results[0].success is True
    assert results[1].success is False
    assert results[2].success is True


@pytest.mark.asyncio
async def test_tool_chain_retry_failed_step():
    manager = _build_tool_manager(side_effects=[
        ToolResult(ok=False, error="Temp fail"),
        ToolResult(ok=False, error="Temp fail"),
        ToolResult(ok=True, data={"recovered": True}),
    ])
    executor = ToolChainExecutor(tool_manager=manager)
    
    chain = ToolChain(
        chain_id="retry_chain",
        name="Retry Chain",
        failure_policy=ToolFailurePolicy.RETRY_FAILED_STEP,
        steps=[
            ToolStep(step_id="s1", tool_name="toolA"),
        ]
    )
    
    results = await executor.execute_chain(chain)
    
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].output == {"recovered": True}
    
    metrics = executor.get_metrics()
    assert metrics["retry_count"] == 2
