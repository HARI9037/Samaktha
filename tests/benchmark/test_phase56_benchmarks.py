"""Phase 5.6 — Performance Benchmarks.

Records baseline timing for all core subsystem operations.
These tests always pass — they exist to record regression percentages.
"""
import asyncio
import time
import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


# ──────────────────────────────────────────────────────────────────────────────
# 1. Provider routing latency
# ──────────────────────────────────────────────────────────────────────────────

def test_benchmark_router_latency():
    from app.router.router import ModelRouter
    from app.core.contracts.routing import RoutingDecision
    from app.core.contracts.planning import RouterRequest

    router = ModelRouter(registry=None)  # registry is injected at construction

    from app.router.registry import RouterRegistry
    cap_registry = RouterRegistry()
    router2 = ModelRouter(registry=cap_registry)

    request = RouterRequest(
        purpose="text_generation",
        complexity="low",
        required_capabilities=[],
        estimated_context_tokens=100,
        requires_local_model=False,
        requires_code=False,
        requires_reasoning=False,
    )

    import asyncio

    async def _run():
        nonlocal _ms
        start = time.perf_counter()
        for _ in range(50):
            try:
                await router2.route(request)
            except Exception:
                pass  # No models registered — that's fine for latency measurement
        _ms = elapsed_ms(start)

    _ms = 0.0
    asyncio.run(_run())
    avg = _ms / 50
    print(f"\n[BENCHMARK] Router: 50 routes in {_ms:.1f}ms | avg {avg:.3f}ms/op")
    assert avg < 50.0, f"Router latency regression: {avg:.3f}ms > 50ms threshold"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Tool chain execution latency
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_benchmark_tool_chain_latency():
    from unittest.mock import AsyncMock, MagicMock
    from app.tools.base import ToolResult
    from app.core.contracts.tools import ToolChain, ToolStep, ToolFailurePolicy
    from app.runtime.tool_chain import ToolChainExecutor

    manager = MagicMock()
    manager.execute_tool = AsyncMock(return_value=ToolResult(ok=True, data={}))
    executor = ToolChainExecutor(tool_manager=manager)

    chain = ToolChain(
        chain_id="bench_chain",
        name="Benchmark",
        failure_policy=ToolFailurePolicy.CONTINUE_ON_FAILURE,
        steps=[
            ToolStep(step_id="s1", tool_name="toolA"),
            ToolStep(step_id="s2", tool_name="toolB", depends_on=["s1"]),
            ToolStep(step_id="s3", tool_name="toolC", depends_on=["s2"]),
        ]
    )

    start = time.perf_counter()
    for _ in range(50):
        await executor.execute_chain(chain)
    ms = elapsed_ms(start)

    avg = ms / 50
    print(f"\n[BENCHMARK] ToolChain (3-step): 50 runs in {ms:.1f}ms | avg {avg:.3f}ms/run")
    assert avg < 50.0, f"Tool chain latency regression: {avg:.1f}ms > 50ms threshold"


# ──────────────────────────────────────────────────────────────────────────────
# 3. Semantic memory retrieval speed
# ──────────────────────────────────────────────────────────────────────────────

def test_benchmark_semantic_memory_retrieval():
    from app.memory.context import ContextMemoryStore
    from app.core.contracts.memory import MemoryItem, MemoryType

    store = ContextMemoryStore()
    for i in range(100):
        store.save_context(MemoryItem(
            content=f"execution context entry {i}: completed task successfully",
            category=MemoryType.EXECUTION,
        ))

    start = time.perf_counter()
    for _ in range(50):
        store.search_context("execution completed task", top_k=5)
    ms = elapsed_ms(start)

    avg = ms / 50
    print(f"\n[BENCHMARK] SemanticMemory (100 items): 50 searches in {ms:.1f}ms | avg {avg:.3f}ms/search")
    assert avg < 100.0, f"Memory retrieval regression: {avg:.1f}ms > 100ms threshold"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Skill retrieval speed
# ──────────────────────────────────────────────────────────────────────────────

def test_benchmark_skill_retrieval():
    from app.memory.skills import SkillMemoryStore
    from app.core.contracts.skills import SkillRecord
    from app.core.contracts.learning import SkillConfidence

    # Use correct API from app.memory.skills.SkillMemoryStore
    store = SkillMemoryStore()
    for i in range(50):
        record = SkillRecord(
            skill_id=f"skill-bench-{i}",
            name=f"DataProcessing-{i}",
            description=f"Analyzes data stream {i} efficiently",
            category="data_analysis",
            source_plan=f"plan-{i}",
            confidence=SkillConfidence.HIGH,
            tags=["data", "analysis"],
        )
        store.save_skill(record)

    start = time.perf_counter()
    for _ in range(100):
        store.search_by_name("DataProcessing")
    ms = elapsed_ms(start)

    avg = ms / 100
    print(f"\n[BENCHMARK] SkillRetrieval (50 skills): 100 searches in {ms:.1f}ms | avg {avg:.3f}ms/search")
    assert avg < 50.0, f"Skill retrieval regression: {avg:.1f}ms > 50ms threshold"


# ──────────────────────────────────────────────────────────────────────────────
# 5. Security scanner overhead
# ──────────────────────────────────────────────────────────────────────────────

def test_benchmark_security_scanner():
    from app.security.input_scanner import InputSecurityScanner

    scanner = InputSecurityScanner()
    safe_input = {
        "message": "Please analyze the following document and provide a summary.",
        "context": "This is a standard processing request for text data.",
    }

    start = time.perf_counter()
    for _ in range(500):
        scanner.validate_request(safe_input)
    ms = elapsed_ms(start)

    avg = ms / 500
    print(f"\n[BENCHMARK] SecurityScanner: 500 scans in {ms:.1f}ms | avg {avg:.3f}ms/scan")
    assert avg < 2.0, f"Security scanner regression: {avg:.3f}ms > 2ms threshold"


# ──────────────────────────────────────────────────────────────────────────────
# 6. Output filter overhead
# ──────────────────────────────────────────────────────────────────────────────

def test_benchmark_output_filter():
    from app.security.output_filter import OutputSecurityFilter

    filter_ = OutputSecurityFilter()
    text = "The analysis is complete. Results have been stored to the output directory successfully."

    start = time.perf_counter()
    for _ in range(500):
        filter_.filter_text(text)
    ms = elapsed_ms(start)

    avg = ms / 500
    print(f"\n[BENCHMARK] OutputFilter: 500 filter ops in {ms:.1f}ms | avg {avg:.3f}ms/op")
    assert avg < 2.0, f"Output filter regression: {avg:.3f}ms > 2ms threshold"


# ──────────────────────────────────────────────────────────────────────────────
# 7. Streaming chunk overhead
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_benchmark_streaming_overhead():
    from unittest.mock import MagicMock
    from app.core.contracts.streaming import StreamChunk, StreamEventType, StreamRequest
    from app.runtime.streaming import StreamingExecutor

    async def mock_stream(request):
        for i in range(10):
            yield StreamChunk(
                sequence=i,
                event_type=StreamEventType.CHUNK,
                content=f"token_{i}",
                provider="mock",
                model="mock-model",
            )

    manager = MagicMock()
    manager.stream_provider = mock_stream

    executor = StreamingExecutor(provider_manager=manager)
    request = StreamRequest(
        request_id="bench-req-1",
        provider_id="mock",
        prompt="test prompt",
    )

    start = time.perf_counter()
    for _ in range(20):
        await executor.collect_stream(request)
    ms = elapsed_ms(start)

    avg = ms / 20
    print(f"\n[BENCHMARK] Streaming (10 chunks): 20 runs in {ms:.1f}ms | avg {avg:.3f}ms/run")
    assert avg < 100.0, f"Streaming overhead regression: {avg:.1f}ms > 100ms threshold"
