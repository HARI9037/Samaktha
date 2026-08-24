"""P0 production-composition and direct-execution architecture guards.

These tests intentionally describe the architecture that is wired today.  An
allowlisted bypass is not an endorsement: it is a visible migration boundary
that must be reviewed before the allowlist is changed.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections import Counter, deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import FunctionType, MethodType, ModuleType
from typing import Any

import pytest

import app.core.app as core_app
from app.communication.manager import CommunicationManager
from app.config.settings import Settings
from app.core.gambit.agent_planner import AgentPlanner
from app.core.gambit.planner import Planner
from app.providers.config import ProviderSettings
from app.runtime.checkpoint import CheckpointStore
from app.runtime.executor import ProviderExecutor, ToolExecutor
from app.runtime.multimodal import MultimodalExecutor
from app.runtime.recovery import RecoveryManager
from app.runtime.tool_chain import ToolChainExecutor


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPOSITORY_ROOT / "app"

CANONICAL_PRODUCTION = "CANONICAL PRODUCTION"
SAFE_INTERNAL = "SAFE INTERNAL"
POTENTIAL_BYPASS = "POTENTIAL BYPASS"
SHOULD_REMAIN_DISCONNECTED = "SHOULD REMAIN DISCONNECTED"
NEEDS_FUTURE_MIGRATION = "NEEDS FUTURE MIGRATION"
TRANSITIONAL = "TRANSITIONAL"
CANONICAL_RUNTIME_INTERNAL = "CANONICAL RUNTIME INTERNAL"


@dataclass(frozen=True, order=True)
class CallSite:
    module: str
    scope: str
    receiver: str
    method: str


@dataclass(frozen=True)
class AllowedCall:
    classification: str
    reason: str
    count: int = 1


@dataclass(frozen=True)
class FrozenSubsystem:
    component_type: type[Any]
    classification: str
    reason: str


# P0.3 classifications.  These types may exist and have focused unit tests,
# but create_orchestrator() must not instantiate them unless a later phase
# explicitly migrates one into the canonical path.
FROZEN_SUBSYSTEMS = {
    "AgentPlanner": FrozenSubsystem(
        AgentPlanner,
        SHOULD_REMAIN_DISCONNECTED,
        "The canonical GAMBIT planner is Planner; multi-agent planning stays disconnected.",
    ),
    "MultimodalExecutor": FrozenSubsystem(
        MultimodalExecutor,
        POTENTIAL_BYPASS,
        "It calls ProviderManager directly and has not been migrated to Runtime permits.",
    ),
    "ToolChainExecutor": FrozenSubsystem(
        ToolChainExecutor,
        POTENTIAL_BYPASS,
        "It calls ToolManager directly and has not been migrated to Runtime permits.",
    ),
    "CommunicationManager": FrozenSubsystem(
        CommunicationManager,
        SHOULD_REMAIN_DISCONNECTED,
        "Production registers local email/message tools, not CommunicationManager delivery.",
    ),
    "RecoveryManager": FrozenSubsystem(
        RecoveryManager,
        TRANSITIONAL,
        "Runtime accepts this transitional dependency, but composition supplies None.",
    ),
}


# Non-frozen execution infrastructure.  runtime_parallel was reverified as a
# live RuntimeEngine.run_batch dependency, not as an isolated future library.
EXECUTION_COMPONENT_CLASSIFICATIONS = {
    "runtime_parallel": CANONICAL_RUNTIME_INTERNAL,
    "provider_adapters": SAFE_INTERNAL,
    "tool_dispatcher": SAFE_INTERNAL,
    "StreamingExecutor": POTENTIAL_BYPASS,
    "ToolManager.execute_tool": POTENTIAL_BYPASS,
    "CheckpointStore": CANONICAL_RUNTIME_INTERNAL,
    "PluginManager": "CANONICAL LIFECYCLE ONLY",
    "PluginToolAdapter": CANONICAL_RUNTIME_INTERNAL,
}


# ProviderManager entry points.  ProviderExecutor is canonical.  Streaming and
# multimodal callers are recorded exceptions, not alternate canonical paths.
ALLOWED_PROVIDER_MANAGER_CALLS = {
    CallSite(
        "app.runtime.executor",
        "ProviderExecutor.execute",
        "self._provider_manager",
        "execute_provider",
    ): AllowedCall(
        CANONICAL_PRODUCTION,
        "Runtime's ProviderExecutor is the governed provider execution boundary.",
    ),
    CallSite(
        "app.runtime.executor",
        "ProviderExecutor.execute",
        "self._provider_manager",
        "stream_provider",
    ): AllowedCall(
        CANONICAL_PRODUCTION,
        "Runtime's ProviderExecutor performs governed token streaming after permit validation.",
    ),
    CallSite(
        "app.runtime.multimodal",
        "MultimodalExecutor.execute",
        "self._provider_manager",
        "execute_provider",
    ): AllowedCall(
        POTENTIAL_BYPASS,
        "Disconnected future executor; must enter canonical Runtime before activation.",
    ),
    CallSite(
        "app.runtime.streaming",
        "StreamingExecutor.stream_execute",
        "self._provider_manager",
        "stream_provider",
    ): AllowedCall(
        POTENTIAL_BYPASS,
        "Disconnected streaming helper; direct manager use prevents user-facing activation.",
    ),
}


# Calls from ProviderManager into concrete providers, and calls inside concrete
# provider adapters, are valid low-level implementation details.  No interface,
# orchestrator, planner, or workflow module is allowed in this inventory.
ALLOWED_PROVIDER_ADAPTER_CALLS = {
    CallSite(
        "app.providers.manager",
        "ProviderManager.stream_provider",
        "provider",
        "execute_stream",
    ): AllowedCall(SAFE_INTERNAL, "ProviderManager invokes the selected streaming adapter."),
    CallSite(
        "app.providers.manager",
        "ProviderManager.execute_provider",
        "provider",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "ProviderManager invokes the selected provider adapter."),
    CallSite(
        "app.providers.manager",
        "ProviderManager.execute_provider_stream",
        "provider",
        "execute_stream",
    ): AllowedCall(SAFE_INTERNAL, "Legacy manager streaming API invokes an adapter."),
    CallSite(
        "app.providers.base",
        "BaseProvider.execute_stream",
        "self",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "Base adapter implements non-streaming fallback."),
    CallSite(
        "app.providers.local_provider",
        "LocalProvider.execute_stream",
        "self",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "Local adapter chunks its normalized response."),
    CallSite(
        "app.providers.http_chat",
        "OpenAICompatibleChatClient.execute_stream",
        "self",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "HTTP adapter falls back to its own execute method."),
    CallSite(
        "app.providers.openai_provider",
        "OpenAIProvider.execute",
        "self._client",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "Provider adapter delegates to the shared HTTP client."),
    CallSite(
        "app.providers.openai_provider",
        "OpenAIProvider.execute_stream",
        "self._client",
        "execute_stream",
    ): AllowedCall(SAFE_INTERNAL, "Provider adapter delegates streaming to the HTTP client."),
    CallSite(
        "app.providers.groq_provider",
        "GroqProvider.execute",
        "self._client",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "Provider adapter delegates to the shared HTTP client."),
    CallSite(
        "app.providers.groq_provider",
        "GroqProvider.execute_stream",
        "self._client",
        "execute_stream",
    ): AllowedCall(SAFE_INTERNAL, "Provider adapter delegates streaming to the HTTP client."),
    CallSite(
        "app.providers.openrouter_provider",
        "OpenRouterProvider.execute",
        "self._client",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "Provider adapter delegates to the shared HTTP client."),
    CallSite(
        "app.providers.openrouter_provider",
        "OpenRouterProvider.execute_stream",
        "self._client",
        "execute_stream",
    ): AllowedCall(SAFE_INTERNAL, "Provider adapter delegates streaming to the HTTP client."),
    # P10 — Canonical External Integration Provider calls from Tools.
    # Tools execute through ToolExecutor (canonical runtime path) and may invoke
    # integration providers (SMTP, Calendar, Contacts) as part of their execution.
    CallSite(
        "app.communication.email_tool",
        "EmailTool._send",
        "self._provider",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "EmailTool invokes SMTP integration provider for real delivery."),
    CallSite(
        "app.tools.calendar",
        "CalendarTool._create_event",
        "self._provider",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "CalendarTool invokes Calendar integration provider for attendee sync."),
    CallSite(
        "app.tools.calendar",
        "CalendarTool._update_event",
        "self._provider",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "CalendarTool invokes Calendar integration provider for attendee update."),
    CallSite(
        "app.tools.contacts",
        "ContactsTool._create_contact",
        "self._provider",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "ContactsTool invokes Contacts integration provider for contact sync."),
    CallSite(
        "app.tools.contacts",
        "ContactsTool._update_contact",
        "self._provider",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "ContactsTool invokes Contacts integration provider for contact update."),
    CallSite(
        "app.tools.contacts",
        "ContactsTool._delete_contact",
        "self._provider",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "ContactsTool invokes Contacts integration provider for contact deletion."),
}


ALLOWED_STREAMING_EXECUTOR_CALLS = {
    CallSite(
        "app.runtime.streaming",
        "StreamingExecutor.collect_stream",
        "self",
        "stream_execute",
    ): AllowedCall(SAFE_INTERNAL, "StreamingExecutor's batch helper reuses its single-call API."),
}


ALLOWED_TOOL_MANAGER_CALLS = {
    CallSite(
        "app.runtime.executor",
        "ToolExecutor.execute",
        "self._tool_manager",
        "execute_tool_with_context",
    ): AllowedCall(
        CANONICAL_PRODUCTION,
        "Runtime's ToolExecutor supplies permission and cancellation context.",
    ),
    CallSite(
        "app.runtime.executor",
        "ToolExecutor.execute",
        "self._tool_manager",
        "execute_tool",
    ): AllowedCall(
        CANONICAL_PRODUCTION,
        "Compatibility fallback for ToolManager-like implementations without context support.",
    ),
    CallSite(
        "app.runtime.tool_chain",
        "ToolChainExecutor._execute_step_with_retry",
        "self._tool_manager",
        "execute_tool",
    ): AllowedCall(
        POTENTIAL_BYPASS,
        "Disconnected future system; direct manager use prevents production activation.",
    ),
    CallSite(
        "app.tools.manager",
        "ToolManager.execute_many",
        "self._dispatcher",
        "execute_many",
    ): AllowedCall(SAFE_INTERNAL, "ToolManager delegates its parallel internal API."),
    CallSite(
        "app.tools.manager",
        "ToolManager.execute_ordered",
        "self._dispatcher",
        "execute_ordered",
    ): AllowedCall(SAFE_INTERNAL, "ToolManager delegates its ordered internal API."),
    CallSite(
        "app.tools.framework.dispatcher",
        "ToolDispatcher.execute_ordered",
        "self",
        "execute_many",
    ): AllowedCall(SAFE_INTERNAL, "ToolDispatcher reuses its own parallel primitive."),
}


# ToolDispatcher is the ToolManager implementation engine.  Construction and
# direct dispatcher calls must stay in ToolManager (plus dispatcher self-use).
ALLOWED_TOOL_DISPATCHER_CALLS = {
    CallSite(
        "app.tools.manager",
        "ToolManager.execute_tool",
        "self._dispatcher",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "ToolManager delegates its legacy single-call API."),
    CallSite(
        "app.tools.manager",
        "ToolManager.execute_tool_with_context",
        "self._dispatcher",
        "execute",
    ): AllowedCall(SAFE_INTERNAL, "ToolManager delegates its context-aware API."),
    CallSite(
        "app.tools.manager",
        "ToolManager.execute_many",
        "self._dispatcher",
        "execute_many",
    ): AllowedCall(SAFE_INTERNAL, "ToolManager delegates its parallel internal API."),
    CallSite(
        "app.tools.manager",
        "ToolManager.execute_ordered",
        "self._dispatcher",
        "execute_ordered",
    ): AllowedCall(SAFE_INTERNAL, "ToolManager delegates its ordered internal API."),
}


# Direct Tool.run calls below ToolManager.  The reminder callback is the one
# current production exception: it is deliberately marked as a bypass so it
# cannot be mistaken for canonical governed tool execution.
ALLOWED_DIRECT_TOOL_RUN_CALLS = {
    CallSite(
        "app.plugins.tool_adapter",
        "PluginToolAdapter.run",
        "self._tool",
        "run",
    ): AllowedCall(
        SAFE_INTERNAL,
        "The adapter is reached only through ToolExecutor/ToolManager and delegates to the plugin handler while tracking lifecycle activity.",
    ),
    CallSite(
        "app.tools.framework.dispatcher",
        "ToolDispatcher._run_with_policy",
        "tool",
        "run",
    ): AllowedCall(
        SAFE_INTERNAL,
        "ToolDispatcher performs the final registered tool invocation.",
        count=2,
    ),
    CallSite(
        "app.tools.resolver_layer",
        "ResolverTool.run",
        "tool",
        "run",
    ): AllowedCall(SAFE_INTERNAL, "Resolver delegates within an already-approved tool request."),
    CallSite(
        "app.tools.filesystem",
        "FileSystemTool._read",
        "self._document_tool",
        "run",
    ): AllowedCall(
        SAFE_INTERNAL,
        "Filesystem delegates document parsing only after P7A scope and size validation.",
    ),
}


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(REPOSITORY_ROOT).with_suffix("").parts)


def _expression_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _expression_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _expression_name(node.func)
    return "<dynamic>"


class _CallCollector(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.classes: list[str] = []
        self.functions: list[str] = []
        self.calls: list[CallSite] = []

    @property
    def scope(self) -> str:
        return ".".join([*self.classes, *self.functions]) or "<module>"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
        self.generic_visit(node)
        self.classes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            self.calls.append(
                CallSite(
                    module=self.module,
                    scope=self.scope,
                    receiver=_expression_name(node.func.value),
                    method=node.func.attr,
                )
            )
        self.generic_visit(node)


@lru_cache(maxsize=1)
def _application_calls() -> tuple[CallSite, ...]:
    calls: list[CallSite] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        collector = _CallCollector(_module_name(path))
        collector.visit(tree)
        calls.extend(collector.calls)
    return tuple(calls)


def _expected_counter(allowlist: dict[CallSite, AllowedCall]) -> Counter[CallSite]:
    return Counter({site: allowed.count for site, allowed in allowlist.items()})


def _assert_allowlist(actual: list[CallSite], allowlist: dict[CallSite, AllowedCall]) -> None:
    actual_counter = Counter(actual)
    expected_counter = _expected_counter(allowlist)
    unexpected = actual_counter - expected_counter
    missing = expected_counter - actual_counter
    assert not unexpected and not missing, (
        f"Unexpected direct execution calls: {list(unexpected.elements())}; "
        f"missing allowlisted calls: {list(missing.elements())}"
    )


def _walk_composition(root: Any) -> list[tuple[str, Any]]:
    """Walk objects owned by the composition without following modules/types."""
    queue: deque[tuple[str, Any]] = deque([("orchestrator", root)])
    visited: set[int] = set()
    discovered: list[tuple[str, Any]] = []
    scalar_types = (str, bytes, int, float, bool, type(None), Path)

    while queue:
        path, value = queue.popleft()
        if isinstance(value, scalar_types) or isinstance(value, (ModuleType, type)):
            continue
        identity = id(value)
        if identity in visited:
            continue
        visited.add(identity)
        discovered.append((path, value))

        if isinstance(value, dict):
            queue.extend((f"{path}[{key!r}]", child) for key, child in value.items())
            continue
        if isinstance(value, (list, tuple, set, frozenset, deque)):
            queue.extend((f"{path}[{index}]", child) for index, child in enumerate(value))
            continue
        if isinstance(value, MethodType):
            queue.append((f"{path}.__self__", value.__self__))
            continue
        if isinstance(value, FunctionType):
            for name, cell in zip(value.__code__.co_freevars, value.__closure__ or ()):
                try:
                    queue.append((f"{path}.<closure:{name}>", cell.cell_contents))
                except ValueError:
                    pass
            continue
        try:
            attributes = vars(value)
        except TypeError:
            continue
        queue.extend((f"{path}.{name}", child) for name, child in attributes.items())

    return discovered


@pytest.fixture
def production_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build the real production graph with isolated persistence/config paths."""
    monkeypatch.delenv("MOCK_AGENT", raising=False)
    monkeypatch.setattr(
        core_app,
        "ProviderSettings",
        lambda: ProviderSettings(
            _env_file=None,
            groq_api_key="architecture-test-key",
        ),
    )
    settings = Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "architecture.db"),
        personality_state_path=str(tmp_path / "personality.json"),
    )
    return core_app.create_orchestrator(settings)


def test_create_orchestrator_preserves_frozen_subsystems(production_orchestrator) -> None:
    graph = _walk_composition(production_orchestrator)
    frozen_types = tuple(item.component_type for item in FROZEN_SUBSYSTEMS.values())
    activated = [
        (path, type(value).__name__)
        for path, value in graph
        if isinstance(value, frozen_types)
    ]

    assert activated == []
    assert type(production_orchestrator._planner) is Planner
    assert production_orchestrator.runtime._checkpoint_store is None
    assert production_orchestrator.runtime._recovery_manager is None
    assert isinstance(production_orchestrator.checkpoint_store, CheckpointStore)
    assert (
        production_orchestrator.execution_coordinator._checkpoint_store
        is production_orchestrator.checkpoint_store
    )

    # The graph walk proves attachment/activation.  This AST check also catches
    # a constructor that is invoked and discarded during composition.
    tree = ast.parse(inspect.getsource(core_app.create_orchestrator))
    constructors = {
        _expression_name(node.func).split(".")[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert constructors.isdisjoint(FROZEN_SUBSYSTEMS)


def test_p6_checkpoint_recovery_cannot_dispatch_execution(production_orchestrator) -> None:
    """Recovery state enters through the coordinator and cannot execute work."""
    checkpoint_source = inspect.getsource(CheckpointStore)
    assert "execute_provider" not in checkpoint_source
    assert "execute_tool" not in checkpoint_source
    assert ".run(" not in checkpoint_source


def test_create_orchestrator_preserves_canonical_runtime_executors(
    production_orchestrator,
) -> None:
    runtime = production_orchestrator.runtime
    executors = runtime._dispatcher._registry._executors

    assert runtime is production_orchestrator._runtime
    assert set(executors) == {"provider", "tool"}
    assert type(executors["provider"]) is ProviderExecutor
    assert type(executors["tool"]) is ToolExecutor
    assert executors["provider"]._provider_manager is production_orchestrator.provider_manager
    assert executors["tool"]._tool_manager is production_orchestrator.tool_manager
    assert production_orchestrator.streaming_executor is executors["provider"]
    assert not any(
        isinstance(value, __import__("app.runtime.streaming", fromlist=["StreamingExecutor"]).StreamingExecutor)
        for _path, value in _walk_composition(production_orchestrator)
    )


def test_provider_manager_direct_callers_are_allowlisted() -> None:
    manager_methods = {"execute_provider", "stream_provider", "execute_provider_stream"}
    actual = [call for call in _application_calls() if call.method in manager_methods]
    _assert_allowlist(actual, ALLOWED_PROVIDER_MANAGER_CALLS)


def test_provider_adapter_execution_callers_are_allowlisted() -> None:
    actual = [
        call
        for call in _application_calls()
        if call.method in {"execute", "execute_stream"}
        and (
            call.module.startswith("app.providers.")
            and call.receiver in {"self", "self._client", "provider"}
            or call.receiver.rsplit(".", 1)[-1] in {"provider", "_provider"}
        )
    ]
    _assert_allowlist(actual, ALLOWED_PROVIDER_ADAPTER_CALLS)


def test_streaming_executor_callers_are_allowlisted() -> None:
    actual = [call for call in _application_calls() if call.method == "stream_execute"]
    _assert_allowlist(actual, ALLOWED_STREAMING_EXECUTOR_CALLS)


def test_tool_manager_direct_callers_are_allowlisted() -> None:
    manager_methods = {
        "execute_tool",
        "execute_tool_with_context",
        "execute_many",
        "execute_ordered",
    }
    actual = [call for call in _application_calls() if call.method in manager_methods]
    _assert_allowlist(actual, ALLOWED_TOOL_MANAGER_CALLS)


def test_tool_dispatcher_callers_are_allowlisted() -> None:
    dispatcher_methods = {"execute", "execute_many", "execute_ordered"}
    actual = [
        call
        for call in _application_calls()
        if call.method in dispatcher_methods
        and "dispatcher" in call.receiver.rsplit(".", 1)[-1].lower()
    ]
    _assert_allowlist(actual, ALLOWED_TOOL_DISPATCHER_CALLS)

    dispatcher_importers: set[str] = set()
    constructor_callers: set[str] = set()
    for path in sorted(APP_ROOT.rglob("*.py")):
        module = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "ToolDispatcher" for alias in node.names
            ):
                dispatcher_importers.add(module)
            if (
                isinstance(node, ast.Call)
                and _expression_name(node.func).split(".")[-1] == "ToolDispatcher"
            ):
                constructor_callers.add(module)

    assert dispatcher_importers == {"app.tools.framework.__init__", "app.tools.manager"}
    assert constructor_callers == {"app.tools.manager"}


def test_direct_tool_run_callers_are_allowlisted() -> None:
    actual = [
        call
        for call in _application_calls()
        if call.method == "run"
        and (
            call.receiver.rsplit(".", 1)[-1] == "tool"
            or call.receiver.rsplit(".", 1)[-1].endswith("_tool")
        )
    ]
    _assert_allowlist(actual, ALLOWED_DIRECT_TOOL_RUN_CALLS)


def test_transitional_runtime_classification_matches_reachable_batch_path() -> None:
    """runtime_parallel is canonical for run_batch, not an isolated library."""
    assert EXECUTION_COMPONENT_CLASSIFICATIONS["runtime_parallel"] == (
        CANONICAL_RUNTIME_INTERNAL
    )
    workflow_calls = [
        call
        for call in _application_calls()
        if call.module == "app.workflow.engine" and call.method == "run_batch"
    ]
    assert workflow_calls == [
        CallSite(
            "app.workflow.engine",
            "WorkflowEngine.execute",
            "runtime",
            "run_batch",
        )
    ]

    from app.runtime.engine import RuntimeEngine

    run_batch_tree = ast.parse(textwrap.dedent(inspect.getsource(RuntimeEngine.run_batch)))
    constructors = {
        _expression_name(node.func).split(".")[-1]
        for node in ast.walk(run_batch_tree)
        if isinstance(node, ast.Call)
    }
    assert {
        "RuntimeScheduler",
        "WorkerManager",
        "DependencyResolver",
        "ResultAggregator",
        "FailureRecoveryEngine",
        "ResourceAllocator",
    } <= constructors


def test_allowlisted_exceptions_remain_explicitly_noncanonical() -> None:
    all_allowlists = (
        ALLOWED_PROVIDER_MANAGER_CALLS,
        ALLOWED_PROVIDER_ADAPTER_CALLS,
        ALLOWED_STREAMING_EXECUTOR_CALLS,
        ALLOWED_TOOL_MANAGER_CALLS,
        ALLOWED_TOOL_DISPATCHER_CALLS,
        ALLOWED_DIRECT_TOOL_RUN_CALLS,
    )
    classifications = {
        allowed.classification
        for allowlist in all_allowlists
        for allowed in allowlist.values()
    }
    assert classifications == {CANONICAL_PRODUCTION, SAFE_INTERNAL, POTENTIAL_BYPASS}
    assert not any(
        site.module.startswith(("app.agent.", "app.api.", "app.tui."))
        for site in ALLOWED_STREAMING_EXECUTOR_CALLS
    )
