"""P12.5 — Provider/Tool Failure, Timeout, Retry/Fallback Stress Tests.

Tests provider degradation matrix, retry bounds, fallback behavior,
and timeout/cancellation semantics under stress.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.core.app import create_orchestrator
from app.config.settings import Settings
from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult
from app.core.contracts.planning import TaskStatus
from app.runtime.reliability import (
    FailureType,
    OperationOutcome,
    RetryPolicy,
    SideEffectClass,
    classify_failure,
)
from app.runtime.engine import RuntimeEngine
from app.runtime.dispatcher import RuntimeDispatcher
from app.runtime.registry import RuntimeRegistry
from app.tools.base import ToolResult
from app.tools.manager import ToolManager
from app.tools.models import ToolInfo
from app.tools.registry import ToolRegistry
from app.tools.filesystem import FileSystemTool
from app.providers.config import ProviderSettings
from app.providers.health import ProviderHealthChecker
from app.providers.manager import ProviderManager
from app.providers.registry import ProviderRegistry
from tests.conftest import approved_task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def orchestrator(tmp_path):
    """Create a production orchestrator with isolated persistence and mock provider."""
    settings = Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "stress.db"),
        personality_state_path=str(tmp_path / "personality.json"),
        checkpoint_location=str(tmp_path / "checkpoints"),
        groq_api_key="test-key",
        runtime_max_retry_attempts=3,
        runtime_retry_initial_delay_seconds=0.01,
        runtime_retry_max_delay_seconds=0.05,
    )
    import app.core.app as core_app
    original_provider_settings = core_app.ProviderSettings

    def mock_provider_settings(*args, **kwargs):
        kwargs.setdefault("mock_agent", True)
        kwargs.setdefault("default_provider", "mock")
        return original_provider_settings(*args, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(core_app, "ProviderSettings", mock_provider_settings)

    try:
        return create_orchestrator(settings)
    finally:
        monkeypatch.undo()


@pytest.fixture
def runtime(orchestrator):
    """Extract the runtime engine from the orchestrator."""
    return orchestrator.runtime


# ---------------------------------------------------------------------------
# Failure Classification Tests
# ---------------------------------------------------------------------------

def test_failure_classification_explicit():
    """Failure classification must be explicit and deterministic."""
    assert classify_failure("429 rate limited") == FailureType.RATE_LIMITED
    assert classify_failure("rate limit exceeded") == FailureType.RATE_LIMITED
    assert classify_failure("timeout") == FailureType.PROVIDER_TIMEOUT
    assert classify_failure("connection timeout") == FailureType.PROVIDER_TIMEOUT
    assert classify_failure("invalid request") == FailureType.INVALID_REQUEST
    assert classify_failure("bad request") == FailureType.INVALID_REQUEST
    assert classify_failure("permit expired") == FailureType.PERMIT_EXPIRED
    assert classify_failure("connection reset") == FailureType.CONNECTION_ERROR
    assert classify_failure("connection refused") == FailureType.CONNECTION_ERROR
    assert classify_failure("auth failed") == FailureType.PROVIDER_AUTH_FAILED
    assert classify_failure("unauthorized") == FailureType.AUTHORIZATION_DENIED
    assert classify_failure("model not found") == FailureType.MODEL_UNAVAILABLE
    assert classify_failure("model unavailable") == FailureType.MODEL_UNAVAILABLE
    assert classify_failure("cancelled") == FailureType.CANCELLED
    assert classify_failure("unknown error") == FailureType.UNKNOWN_FAILURE


def test_retry_policy_respects_side_effect_class():
    """Retry policy must respect side effect class."""
    policy = RetryPolicy(max_attempts=3)

    # READ_ONLY and IDEMPOTENT_MUTATION may safely retry transient failures.
    for side_effect in (SideEffectClass.READ_ONLY, SideEffectClass.IDEMPOTENT_MUTATION):
        assert policy.allows(
            FailureType.CONNECTION_ERROR,
            attempt=1,
            side_effect=side_effect,
            outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
        )

    # NON_IDEMPOTENT_MUTATION may only be retried while nothing happened.
    assert policy.allows(
        FailureType.CONNECTION_ERROR,
        attempt=1,
        side_effect=SideEffectClass.NON_IDEMPOTENT_MUTATION,
        outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
    )
    # Once an effect started, a retry could duplicate it - never allowed.
    assert not policy.allows(
        FailureType.CONNECTION_ERROR,
        attempt=1,
        side_effect=SideEffectClass.NON_IDEMPOTENT_MUTATION,
        outcome=OperationOutcome.STARTED,
    )
    assert not policy.allows(
        FailureType.CONNECTION_ERROR,
        attempt=1,
        side_effect=SideEffectClass.NON_IDEMPOTENT_MUTATION,
        outcome=OperationOutcome.FAILED_AFTER_EFFECT_UNKNOWN,
    )


def test_retry_policy_rejects_non_retryable():
    """Non-retryable failures must be rejected regardless of side effect."""
    policy = RetryPolicy(max_attempts=3)

    for failure in (
        FailureType.INVALID_REQUEST,
        FailureType.CANCELLED,
        FailureType.AUTHORIZATION_DENIED,
        FailureType.PERMIT_EXPIRED,
        FailureType.MODEL_UNAVAILABLE,
    ):
        for side_effect in (
            SideEffectClass.READ_ONLY,
            SideEffectClass.IDEMPOTENT_MUTATION,
            SideEffectClass.NON_IDEMPOTENT_MUTATION,
        ):
            assert not policy.allows(
                failure,
                attempt=1,
                side_effect=side_effect,
                outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
            )


def test_retry_policy_respects_max_attempts():
    """Retry policy must respect max_attempts limit."""
    policy = RetryPolicy(max_attempts=2)

    # First attempt failed - one retry remains within budget.
    assert policy.allows(
        FailureType.CONNECTION_ERROR,
        attempt=1,
        side_effect=SideEffectClass.READ_ONLY,
        outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
    )
    # The retry budget is exhausted at max_attempts.
    assert not policy.allows(
        FailureType.CONNECTION_ERROR,
        attempt=2,
        side_effect=SideEffectClass.READ_ONLY,
        outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
    )


def test_retry_policy_is_bounded_by_attempts():
    """Allowance must stop once the attempt budget is exhausted."""
    policy = RetryPolicy(max_attempts=5)

    granted = 0
    attempt = 1
    while policy.allows(
        FailureType.RATE_LIMITED,
        attempt=attempt,
        side_effect=SideEffectClass.READ_ONLY,
        outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
    ):
        granted += 1
        attempt += 1

    assert granted == 4  # attempts 1..4 allowed, 5 rejected


def test_delay_for_retry_is_exponential_and_capped():
    """Backoff delays must grow exponentially but never exceed max_delay_s."""
    policy = RetryPolicy(
        max_attempts=6,
        initial_delay_s=0.01,
        max_delay_s=0.05,
    )

    delays = [policy.delay_for_retry(n) for n in range(1, 6)]
    assert delays[0] == pytest.approx(0.01)
    assert all(later >= earlier for earlier, later in zip(delays, delays[1:]))
    assert max(delays) <= 0.05


# ---------------------------------------------------------------------------
# Provider Transient Failure Tests
# ---------------------------------------------------------------------------

class SequenceExecutor:
    """Mock executor that fails N times then succeeds."""

    def __init__(self, failures: list[str]):
        self.failures = list(failures)
        self.calls = 0

    async def execute(self, context, task, routing):
        self.calls += 1
        if self.failures:
            error = self.failures.pop(0)
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=error,
            )
        return RuntimeResult(
            task_id=task.task_id,
            status=TaskStatus.COMPLETED,
            output={"ok": True},
        )


def _runtime(executor, *, attempts=3, sleeper=None):
    """Create a runtime engine backed by a custom executor and retry policy."""
    registry = RuntimeRegistry()
    registry.register("provider", executor)
    registry.register("tool", executor)
    return RuntimeEngine(
        RuntimeDispatcher(registry),
        retry_policy=RetryPolicy(
            max_attempts=attempts,
            initial_delay_s=0.01,
            max_delay_s=0.05,
        ),
        sleeper=sleeper,
    )


@pytest.mark.asyncio
async def test_transient_provider_failure_retries_bounded():
    """Transient provider failures must retry up to max_attempts."""
    delays = []

    async def sleep(delay):
        delays.append(delay)

    executor = SequenceExecutor(["connection reset", "503 server error", "still unavailable"])
    rt = _runtime(executor, attempts=3, sleeper=sleep)

    result = await rt.run(
        RuntimeContext(request_id="retry-1"),
        approved_task(task_id="provider-1", action_type="text_generation", subject_id="retry-1"),
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
    )

    assert result.status == TaskStatus.FAILED
    assert executor.calls == 3  # Initial + 2 retries = 3 total
    assert result.metadata["retry_count"] == 2
    assert delays == [pytest.approx(0.01), pytest.approx(0.02)]  # Backoff delays


@pytest.mark.asyncio
async def test_transient_provider_failure_succeeds_on_retry():
    """Transient failure that recovers should succeed."""
    executor = SequenceExecutor(["connection reset", "503 server error"])
    rt = _runtime(executor, attempts=3)

    result = await rt.run(
        RuntimeContext(request_id="retry-success"),
        approved_task(task_id="provider-recover", action_type="text_generation", subject_id="retry-success"),
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
    )

    assert result.status == TaskStatus.COMPLETED
    assert executor.calls == 3  # Initial + 2 retries = success on 3rd


@pytest.mark.asyncio
async def test_rate_limit_failure_retries_bounded():
    """Rate limit failures must respect retry bounds."""
    executor = SequenceExecutor(["429 rate limited"] * 3)
    rt = _runtime(executor, attempts=3)

    result = await rt.run(
        RuntimeContext(request_id="rate-limit"),
        approved_task(task_id="rate-limit", action_type="text_generation", subject_id="rate-limit"),
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
    )

    assert result.status == TaskStatus.FAILED
    assert executor.calls == 3


# ---------------------------------------------------------------------------
# Non-Retryable Failure Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auth_failure_not_retried():
    """Authentication failures must not be retried."""
    executor = SequenceExecutor(["auth failed"])
    rt = _runtime(executor, attempts=3)

    result = await rt.run(
        RuntimeContext(request_id="auth-fail"),
        approved_task(task_id="auth", action_type="text_generation", subject_id="auth-fail"),
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
    )

    assert result.status == TaskStatus.FAILED
    assert executor.calls == 1  # No retries


@pytest.mark.asyncio
async def test_invalid_request_not_retried():
    """Invalid request must not be retried."""
    executor = SequenceExecutor(["invalid request"])
    rt = _runtime(executor, attempts=3)

    result = await rt.run(
        RuntimeContext(request_id="invalid-req"),
        approved_task(task_id="invalid", action_type="text_generation", subject_id="invalid-req"),
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
    )

    assert result.status == TaskStatus.FAILED
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_cancelled_not_retried():
    """Cancelled executions must not be retried."""
    executor = SequenceExecutor(["cancelled"])
    rt = _runtime(executor, attempts=3)

    result = await rt.run(
        RuntimeContext(request_id="cancelled", metadata={"cancel_requested": True}),
        approved_task(task_id="cancelled", action_type="text_generation", subject_id="cancelled"),
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
    )

    assert result.status == TaskStatus.FAILED
    assert executor.calls == 1


# ---------------------------------------------------------------------------
# Bounded Retry Behavior Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_attempts_bounded_under_persistent_failure():
    """Persistent transient failure must stop at max_attempts without runaway loops."""
    delays = []

    async def sleep(delay):
        delays.append(delay)

    executor = SequenceExecutor(["connection reset"] * 20)
    rt = _runtime(executor, attempts=4, sleeper=sleep)

    start = time.perf_counter()
    result = await asyncio.wait_for(
        rt.run(
            RuntimeContext(request_id="bounded"),
            approved_task(task_id="bounded", action_type="text_generation", subject_id="bounded"),
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
        ),
        timeout=2.0,
    )
    elapsed = time.perf_counter() - start

    assert result.status == TaskStatus.FAILED
    assert executor.calls == 4  # Never more than max_attempts
    assert len(delays) == 3  # One backoff between each pair of attempts
    assert elapsed < 1.0


# ---------------------------------------------------------------------------
# Cancellation Stops Retries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_stops_future_retries():
    """Cancellation must stop future retry attempts."""

    class CancellableExecutor:
        def __init__(self):
            self.calls = 0
            self.cancel_event = asyncio.Event()

        async def execute(self, context, task, routing):
            self.calls += 1
            if self.calls == 1:
                await self.cancel_event.wait()  # Wait for cancel signal
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error="cancelled",
            )

    executor = CancellableExecutor()
    rt = _runtime(executor, attempts=3)

    task = approved_task(task_id="cancel-test", action_type="text_generation", subject_id="cancel-test")
    ctx = RuntimeContext(request_id="cancel-test")

    exec_task = asyncio.create_task(
        rt.run(
            ctx,
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
        )
    )

    # Wait for the first call to block, then request cancellation.
    await asyncio.sleep(0.05)
    ctx.metadata["cancel_requested"] = True
    executor.cancel_event.set()

    result = await asyncio.wait_for(exec_task, timeout=1.0)

    # Should have been cancelled, not retried.
    assert result.status in {TaskStatus.FAILED, TaskStatus.CANCELLED}
    assert executor.calls <= 2  # Initial attempt + maybe one retry before cancel


# ---------------------------------------------------------------------------
# Fallback Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_configuration_available():
    """Provider settings expose fallback configuration used by selection."""
    settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        groq_api_key="test-key",
    )

    manager = ProviderManager(ProviderRegistry(), settings=settings)

    assert settings.fallback_enabled is True  # Enabled by default
    assert manager.resolve_provider("missing-provider") is None


@pytest.mark.asyncio
async def test_all_fallbacks_exhausted_state_truthful():
    """When all fallbacks exhausted, state must be truthful."""
    executor = SequenceExecutor(["auth failed", "connection reset", "503 server error"])
    rt = _runtime(executor, attempts=3)

    result = await rt.run(
        RuntimeContext(request_id="exhausted"),
        approved_task(task_id="exhausted", action_type="text_generation", subject_id="exhausted"),
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
    )

    assert result.status == TaskStatus.FAILED
    assert result.error  # Truthful error surfaced, never a fake success
    assert result.metadata["failure_type"] == FailureType.PROVIDER_AUTH_FAILED.value


# ---------------------------------------------------------------------------
# Tool Stress Tests
# ---------------------------------------------------------------------------

class FailingTool:
    """Tool that fails with specific error types before succeeding."""

    def __init__(self, name, fail_type="transient", fail_count=2):
        self._name = name
        self.fail_type = fail_type
        self.fail_count = fail_count
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def run(self, arguments):
        self.calls += 1
        if self.calls <= self.fail_count:
            if self.fail_type == "transient":
                return ToolResult(ok=False, error="connection reset")
            elif self.fail_type == "timeout":
                return ToolResult(ok=False, error="timeout")
            elif self.fail_type == "security":
                return ToolResult(ok=False, error="security denied")
            elif self.fail_type == "invalid":
                return ToolResult(ok=False, error="invalid arguments")
        return ToolResult(ok=True, data={"result": "success"})


def _tool_manager(tool) -> ToolManager:
    registry = ToolRegistry()
    registry.register(
        tool.name,
        tool,
        ToolInfo(tool_id=tool.name, description=f"stress tool {tool.name}"),
    )
    return ToolManager(registry)


@pytest.mark.asyncio
async def test_tool_security_denial_non_retryable(orchestrator):
    """Tool security denial must not be retried."""
    policy = orchestrator.runtime._retry_policy
    for side_effect in (
        SideEffectClass.READ_ONLY,
        SideEffectClass.IDEMPOTENT_MUTATION,
        SideEffectClass.NON_IDEMPOTENT_MUTATION,
    ):
        assert not policy.allows(
            FailureType.AUTHORIZATION_DENIED,
            attempt=1,
            side_effect=side_effect,
            outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
        )


@pytest.mark.asyncio
async def test_tool_timeout_surfaces_error_without_retry(orchestrator):
    """Tool timeout must surface an explicit error rather than hang or spin."""
    tool = FailingTool("slow-tool", fail_type="timeout", fail_count=5)
    manager = _tool_manager(tool)

    result = await manager.execute_tool("slow-tool", {"action": "execute"})

    assert result.ok is False
    assert "timeout" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_filesystem_limit_boundaries_under_concurrency(orchestrator):
    """Filesystem limits must hold under concurrent access."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        fs_tool = FileSystemTool(root_dir=tmpdir)
        root = fs_tool.security_policy.default_root

        # Write a file at the size limit (limit itself is allowed).
        large_content = "x" * 2_000_000  # 2MB - at limit
        result = await fs_tool.run(
            {"action": "write", "path": str(root / "test.txt"), "content": large_content}
        )
        assert result.ok is True

        # Try to write over limit.
        over_limit = "x" * 2_000_001
        result = await fs_tool.run(
            {"action": "write", "path": str(root / "test2.txt"), "content": over_limit}
        )
        assert result.ok is False
        message = (result.error or "").lower()
        assert "size" in message or "limit" in message

        # Under concurrency, limits must still hold (each write under limit).
        tasks = [
            fs_tool.run(
                {
                    "action": "write",
                    "path": str(root / f"concurrent_{i}.txt"),
                    "content": "x" * 1_000_000,
                }
            )
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful = [r for r in results if not isinstance(r, Exception) and r.ok]
        assert len(successful) == 5


# ---------------------------------------------------------------------------
# Provider Retry Matrix Verification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("failure_type,should_retry", [
    (FailureType.TRANSIENT_PROVIDER_FAILURE, True),
    (FailureType.PROVIDER_TIMEOUT, True),
    (FailureType.PROVIDER_UNAVAILABLE, True),
    (FailureType.RATE_LIMITED, True),
    (FailureType.CONNECTION_ERROR, True),
    (FailureType.INVALID_REQUEST, False),
    (FailureType.AUTHORIZATION_DENIED, False),
    (FailureType.PERMIT_EXPIRED, False),
    (FailureType.MODEL_UNAVAILABLE, False),
    (FailureType.CANCELLED, False),
    (FailureType.UNKNOWN_FAILURE, False),
])
def test_provider_retry_matrix(failure_type, should_retry):
    """Verify complete provider retry matrix."""
    policy = RetryPolicy(max_attempts=3)
    result = policy.allows(
        failure_type,
        attempt=1,
        side_effect=SideEffectClass.READ_ONLY,
        outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
    )
    assert result == should_retry, (
        f"Failure {failure_type}: expected retry={should_retry}, got {result}"
    )


@pytest.mark.parametrize("side_effect,outcome,should_retry", [
    (SideEffectClass.READ_ONLY, OperationOutcome.FAILED_BEFORE_EFFECT, True),
    (SideEffectClass.IDEMPOTENT_MUTATION, OperationOutcome.FAILED_BEFORE_EFFECT, True),
    (SideEffectClass.NON_IDEMPOTENT_MUTATION, OperationOutcome.NOT_STARTED, True),
    (SideEffectClass.NON_IDEMPOTENT_MUTATION, OperationOutcome.FAILED_BEFORE_EFFECT, True),
    (SideEffectClass.NON_IDEMPOTENT_MUTATION, OperationOutcome.STARTED, False),
    (SideEffectClass.NON_IDEMPOTENT_MUTATION, OperationOutcome.FAILED_AFTER_EFFECT_UNKNOWN, False),
])
def test_side_effect_retry_matrix(side_effect, outcome, should_retry):
    """Non-idempotent mutations are retried only when nothing happened yet."""
    policy = RetryPolicy(max_attempts=3)
    result = policy.allows(
        FailureType.CONNECTION_ERROR,
        attempt=1,
        side_effect=side_effect,
        outcome=outcome,
    )
    assert result == should_retry, (
        f"Side effect {side_effect}/{outcome}: expected retry={should_retry}, got {result}"
    )


# ---------------------------------------------------------------------------
# Tool Concurrency Safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_concurrency_does_not_bypass_security(orchestrator):
    """Concurrent tool execution must not bypass security denials."""
    tool = FailingTool("secure-tool", fail_type="security", fail_count=100)
    manager = _tool_manager(tool)

    results = await asyncio.gather(*[
        manager.execute_tool("secure-tool", {"action": "execute"})
        for _ in range(5)
    ], return_exceptions=True)

    for r in results:
        assert isinstance(r, ToolResult)
        assert r.ok is False
        message = (r.error or "").lower()
        assert "security" in message or "denied" in message


# ---------------------------------------------------------------------------
# Retry Backoff Verification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_backoff_respected():
    """Retry backoff timing must be respected and strictly increasing."""
    delays = []

    async def sleep(delay):
        delays.append(delay)

    executor = SequenceExecutor(["connection reset", "connection reset"])
    rt = _runtime(executor, attempts=3, sleeper=sleep)

    result = await rt.run(
        RuntimeContext(request_id="backoff-test"),
        approved_task(task_id="backoff", action_type="text_generation", subject_id="backoff-test"),
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
    )

    assert result.status == TaskStatus.COMPLETED
    assert len(delays) == 2
    assert delays[0] >= 0.01  # Initial delay
    assert delays[1] > delays[0]  # Backoff must increase


# ---------------------------------------------------------------------------
# Provider Health Under Load
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_health_check_under_concurrency(orchestrator):
    """Provider health checks must work under concurrent load."""
    settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        groq_api_key="test-key",
    )
    checker = ProviderHealthChecker(settings)

    async def probe(index):
        # Thread-safe synchronous probes driven concurrently.
        available = checker.is_available("mock")
        status = checker.get_status("mock")
        return index, available, status

    results = await asyncio.gather(*[probe(i) for i in range(10)])

    assert len(results) == 10
    assert all(available is True for _, available, _ in results)


# ---------------------------------------------------------------------------
# Rate Limit Retry Bounds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limit_retry_respects_bounds():
    """Rate limit retries must stay within max_attempts and finish promptly."""
    policy = RetryPolicy(max_attempts=5)
    start = time.perf_counter()

    attempts = 0
    while attempts < 100 and policy.allows(
        FailureType.RATE_LIMITED,
        attempt=attempts + 1,
        side_effect=SideEffectClass.READ_ONLY,
        outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
    ):
        attempts += 1
        await asyncio.sleep(0)  # Yield without real delay

    elapsed = time.perf_counter() - start
    assert elapsed < 0.5
    assert attempts == 4  # Bounded by max_attempts, never unbounded
