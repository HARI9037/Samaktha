from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import logging
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Any

from app.api.execute import router as execute_router
from app.api.health import router as health_router
from app.api.limits import RateLimiter, client_key, content_length
from app.api.metrics import HttpMetricsCollector, router as metrics_router
from app.api.metrics import provider_metrics_adapter, snapshot_adapter
from app.api.personality import router as personality_router
from app.config.settings import Settings, get_settings
from app.core.cap import ContextEngine
from app.core.contracts import ExecutionLocation
from app.conversation import ConversationStateManager
from app.core.gambit import Planner
from app.core.orchestrator import SamakthaOrchestrator
from app.core.telemetry import TelemetryRegistry
from app.providers import (
    GroqProvider,
    LocalProvider,
    MockProvider,
    OpenAIProvider,
    OpenRouterProvider,
    ProviderHealthChecker,
    ProviderInfo,
    ProviderManager,
    ProviderRegistry,
    ProviderSettings,
)
from app.memory.sqlite_store import SQLiteStore
from app.memory.manager import MemoryManager
from app.memory.repository import MemoryRepository
from app.memory.controller.facade import MemoryController
from app.memory.session_manager import SessionManager
from app.models import ModelInfo, ModelManager, ModelRegistry
from app.tools import ToolInfo, ToolManager, ToolRegistry
from app.tools.capability_registry import CapabilityRegistry as ProductCapabilityRegistry
from app.tools.models import CapabilityAvailability
from app.workflow import WorkflowEngine
from app.router import (
    CapabilityRegistry,
    ModelRouter,
    ProviderCapability,
    ProviderModelRegistration,
    RouterRegistry,
)
from app.runtime import (
    ProviderExecutor,
    RuntimeDispatcher,
    RuntimeEngine,
    RuntimeRegistry,
    ToolExecutor,
)
from app.core.execution_coordinator import ExecutionCoordinator
from app.runtime.checkpoint import CheckpointStore
from app.evidence import EvidenceStore, EvidenceStoreConfig, EvidenceInstrumentation
from app.security.input_scanner import InputSecurityScanner
from app.security.output_filter import OutputSecurityFilter
from app.security.security_metrics import SecurityMetricsCollector
from app.security.tool_guard import ToolGuard
from app.governance import GovernanceEngine
from app.voice.metrics import VoiceMetricsCollector

log = logging.getLogger(__name__)


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=_app_lifespan,
    )
    app.state.settings = settings

    http_metrics = HttpMetricsCollector()
    app.state.http_metrics = http_metrics
    app.state.rate_limiter = RateLimiter(settings.api_rate_limit_per_minute)
    telemetry = TelemetryRegistry()
    telemetry.register("http", http_metrics)
    app.state.telemetry = telemetry

    app.state.orchestrator = create_orchestrator(settings)
    app.state.execution_coordinator = app.state.orchestrator.execution_coordinator
    telemetry.register("security", snapshot_adapter(app.state.orchestrator.security_metrics))
    telemetry.register("streaming", snapshot_adapter(app.state.orchestrator.streaming_executor))
    # P2.8 — voice execution observability. Voice runs in the same process only
    # when a VoiceSession is started; this process-scoped collector reports the
    # live counters (zeros until a session exists) through /metrics.
    app.state.voice_metrics = VoiceMetricsCollector()
    telemetry.register("voice", app.state.voice_metrics)
    app.state.orchestrator.telemetry_registry = telemetry
    _register_system_telemetry(telemetry, app.state.orchestrator)

    @app.middleware("http")
    async def http_limits_middleware(request: Request, call_next):
        metrics = request.app.state.http_metrics
        limits_settings = request.app.state.settings
        request.state.request_id = request.headers.get("x-request-id") or str(uuid4())
        from app.core.logging import clear_request_id, set_request_id

        set_request_id(request.state.request_id)
        try:
            length = content_length(request)
            if (
                length is not None
                and limits_settings.api_max_request_bytes
                and length > limits_settings.api_max_request_bytes
            ):
                metrics.record_request_too_large()
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": {
                            "code": "request_too_large",
                            "message": (
                                f"Request body exceeds the "
                                f"{limits_settings.api_max_request_bytes}-byte limit"
                            ),
                            "request_id": request.state.request_id,
                        }
                    },
                )

            allowed, retry_after = request.app.state.rate_limiter.allow(client_key(request))
            if not allowed:
                metrics.record_rate_limited()
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": {
                            "code": "rate_limited",
                            "message": "Too many requests",
                            "request_id": request.state.request_id,
                        }
                    },
                    headers={"Retry-After": str(retry_after)},
                )

            metrics.record_request()
            return await call_next(request)
        finally:
            clear_request_id()

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        log.exception(
            "unhandled exception on %s %s (request_id=%s)",
            request.method,
            request.url.path,
            request_id,
        )
        metrics = getattr(request.app.state, "http_metrics", None)
        if metrics is not None:
            metrics.record_failed()
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "internal",
                    "message": "Internal server error",
                    "request_id": request_id,
                }
            },
        )

    app.include_router(health_router)
    app.include_router(execute_router)
    app.include_router(metrics_router)
    app.include_router(personality_router)
    return app


def _register_system_telemetry(telemetry: TelemetryRegistry, orchestrator: Any) -> None:
    """Register every subsystem's metric collector into the shared registry.

    P2.7 — all collectors record during real execution; registering them here
    exposes the live counters through the aggregated ``/metrics`` endpoint.
    Collectors are adapted lazily, so registration itself never executes work.
    """
    telemetry.register("runtime", snapshot_adapter(orchestrator.runtime))
    telemetry.register(
        "workers",
        snapshot_adapter(lambda: orchestrator.runtime.get_worker_metrics()),
    )
    telemetry.register("tool", snapshot_adapter(orchestrator.tool_manager))
    telemetry.register("memory", snapshot_adapter(orchestrator.memory_manager))
    telemetry.register("workflow", snapshot_adapter(orchestrator.workflow_engine))
    telemetry.register("orchestrator", snapshot_adapter(orchestrator))
    telemetry.register("router", snapshot_adapter(orchestrator.model_router))
    telemetry.register("provider", provider_metrics_adapter(orchestrator.provider_manager))
    telemetry.register("governance", snapshot_adapter(orchestrator.governance))


@asynccontextmanager
async def _app_lifespan(app: FastAPI):
    """Start the reminder scheduler on startup and stop it gracefully on
    shutdown (P1.2)."""
    scheduler = getattr(app.state.orchestrator, "reminder_scheduler", None)
    if scheduler is not None:
        await scheduler.start()
    coordinator = getattr(app.state, "execution_coordinator", None)
    if coordinator is not None:
        await coordinator.recover_pending()
    try:
        yield
    finally:
        if scheduler is not None:
            await scheduler.stop()


def _harden_private_file_permissions(path: Path) -> None:
    """Restrict a security-state file to this user, SYSTEM, and admins.

    ``mode=0o600`` is sufficient on POSIX.  Windows ignores those creation
    mode bits for DACL purposes, so install an explicit protected DACL rather
    than inheriting potentially writable permissions from the parent folder.
    """
    if sys.platform != "win32":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        return

    import ctypes
    from ctypes import wintypes

    token_query = 0x0008
    token_user = 1
    dacl_security_information = 0x00000004
    protected_dacl_security_information = 0x80000000
    sddl_revision_1 = 1

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("User", SidAndAttributes)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_uint, wintypes.LPVOID,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertSidToStringSidW.argtypes = [
        wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.SetFileSecurityW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPVOID,
    ]
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, token_user, None, 0, ctypes.byref(required)
        )
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token, token_user, buffer, required, ctypes.byref(required)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        sid_text_pointer = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            user.User.Sid, ctypes.byref(sid_text_pointer)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sid_text = sid_text_pointer.value
        finally:
            kernel32.LocalFree(sid_text_pointer)
    finally:
        kernel32.CloseHandle(token)

    # Protected DACL: full access for the current identity, LocalSystem, and
    # built-in administrators.  No inherited or broad Users/Everyone ACEs.
    sddl = f"D:P(A;;FA;;;{sid_text})(A;;FA;;;SY)(A;;FA;;;BA)"
    security_descriptor = wintypes.LPVOID()
    descriptor_size = wintypes.DWORD()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, sddl_revision_1, ctypes.byref(security_descriptor),
        ctypes.byref(descriptor_size),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not advapi32.SetFileSecurityW(
            str(path),
            dacl_security_information | protected_dacl_security_information,
            security_descriptor,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.LocalFree(security_descriptor)


def _load_or_create_signing_key(path: Path) -> bytes:
    """Atomically create or load the per-installation authorization key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as key_file:
            key_file.write(secrets.token_bytes(32))
            key_file.flush()
            os.fsync(key_file.fileno())
    key = path.read_bytes()
    if len(key) < 32:
        raise ValueError("ExecutionPermit signing key must contain at least 32 bytes.")
    _harden_private_file_permissions(path)
    try:
        # Installed config roots are created inside the current user's profile
        # and can be protected as a directory too. Source/test workspaces may
        # be owned by a different managed identity; the key file DACL above is
        # still mandatory and already prevents read/write access.
        _harden_private_file_permissions(path.parent)
    except PermissionError:
        log.warning(
            "Could not replace inherited ACL on signing-key parent directory %s",
            path.parent,
        )
    return key


def create_orchestrator(settings: Settings | None = None) -> SamakthaOrchestrator:
    # Provider credentials are optional at composition time: the application
    # and /health must remain reachable without keys. Missing provider
    # configuration is a clean execution-time error, enforced by the
    # orchestrator before any provider/tool execution (see
    # SamakthaOrchestrator._ensure_provider_available).
    settings = settings or get_settings()
    from app.core.contracts.policy import configure_permit_signing_key

    signing_key_path = Path(settings.permit_signing_key_path)
    signing_key = _load_or_create_signing_key(signing_key_path)
    configure_permit_signing_key(signing_key)
    provider_settings = ProviderSettings()

    provider_registry = ProviderRegistry()
    health_checker = ProviderHealthChecker(provider_settings)
    if provider_settings.mock_allowed():
        provider_registry.register(
            provider_id="mock",
            provider=MockProvider(),
            info=ProviderInfo(
                provider_id="mock",
                execution_location=ExecutionLocation.LOCAL,
                capabilities=["text_generation"],
                models=["mock-model"],
                supported_models=["mock-model"],
                metadata={"maximum_context": 4096, "maximum_output": 1024, "supports_streaming": False, "supports_tools": False, "supports_vision": False, "supports_reasoning": False},
            ),
        )
    provider_registry.register(
        provider_id="openai",
        provider=OpenAIProvider(provider_settings),
        info=ProviderInfo(
            provider_id="openai",
            execution_location=ExecutionLocation.CLOUD,
            capabilities=["text_generation"],
            models=[provider_settings.openai_model],
            supported_models=["gpt-4o", "gpt-4o-mini"],
            metadata={"maximum_context": 128000, "maximum_output": provider_settings.max_output_tokens, "supports_streaming": True, "supports_tools": True, "supports_vision": True, "supports_reasoning": True},
        ),
    )
    provider_registry.register(
        provider_id="groq",
        provider=GroqProvider(provider_settings),
        info=ProviderInfo(
            provider_id="groq",
            execution_location=ExecutionLocation.CLOUD,
            capabilities=["text_generation"],
            models=[provider_settings.groq_model],
            supported_models=[provider_settings.groq_model, "llama-3.3-70b-versatile"],
            metadata={"maximum_context": 128000, "maximum_output": provider_settings.max_output_tokens, "supports_streaming": True, "supports_tools": False, "supports_vision": False, "supports_reasoning": True},
        ),
    )
    provider_registry.register(
        provider_id="openrouter",
        provider=OpenRouterProvider(provider_settings),
        info=ProviderInfo(
            provider_id="openrouter",
            execution_location=ExecutionLocation.CLOUD,
            capabilities=["text_generation"],
            models=[provider_settings.openrouter_model],
            supported_models=["openai/gpt-oss-120b"],
            metadata={"maximum_context": 128000, "maximum_output": provider_settings.max_output_tokens, "supports_streaming": True, "supports_tools": True, "supports_vision": False, "supports_reasoning": True},
        ),
    )
    provider_registry.register(
        provider_id="local",
        provider=LocalProvider(provider_settings),
        info=ProviderInfo(
            provider_id="local",
            execution_location=ExecutionLocation.LOCAL,
            capabilities=["text_generation"],
            models=[provider_settings.local_model or "unknown"],
            supported_models=(
                [provider_settings.local_model]
                if provider_settings.local_model
                else []
            ),
            metadata={"maximum_context": 4096, "maximum_output": provider_settings.max_output_tokens, "supports_streaming": True, "supports_tools": False, "supports_vision": False, "supports_reasoning": False},
        ),
    )
    provider_manager = ProviderManager(
        provider_registry,
        provider_settings,
        health_checker=health_checker,
    )

    model_registry = ModelRegistry()
    mock_models: list[ModelInfo] = []
    if provider_settings.mock_allowed():
        mock_models = [
            ModelInfo(
                model_id="mock-model",
                provider_id="mock",
                execution_location=ExecutionLocation.LOCAL,
                display_name="Mock Model",
                context_window=4096,
                supports_tools=False,
                supports_streaming=False,
                supports_images=False,
                supports_audio=False,
                reasoning_score=3,
                coding_score=3,
                speed_score=10,
                cost_score=10,
                privacy_score=8,
            ),
        ]
    for model in mock_models + [
        ModelInfo(
            model_id="gpt-4o-mini",
            provider_id="openai",
            execution_location=ExecutionLocation.CLOUD,
            display_name="GPT-4o mini",
            context_window=128000,
            supports_tools=False,
            supports_streaming=False,
            supports_images=False,
            supports_audio=False,
            reasoning_score=8,
            coding_score=8,
            speed_score=7,
            cost_score=7,
            privacy_score=3,
        ),
        ModelInfo(
            model_id=provider_settings.groq_model,
            provider_id="groq",
            execution_location=ExecutionLocation.CLOUD,
            display_name="GPT OSS 120B (Groq)",
            context_window=128000,
            supports_tools=False,
            supports_streaming=True,
            supports_images=False,
            supports_audio=False,
            reasoning_score=9,
            coding_score=8,
            speed_score=10,
            cost_score=9,
            privacy_score=4,
        ),
        ModelInfo(
            model_id="llama-3.3-70b-versatile",
            provider_id="groq",
            execution_location=ExecutionLocation.CLOUD,
            display_name="Llama 3.3 70B Versatile",
            context_window=128000,
            supports_tools=False,
            supports_streaming=False,
            supports_images=False,
            supports_audio=False,
            reasoning_score=8,
            coding_score=8,
            speed_score=10,
            cost_score=9,
            privacy_score=4,
        ),
        ModelInfo(
            model_id="openai/gpt-oss-120b",
            provider_id="openrouter",
            execution_location=ExecutionLocation.CLOUD,
            display_name="GPT OSS 120B",
            context_window=128000,
            supports_tools=False,
            supports_streaming=False,
            supports_images=False,
            supports_audio=False,
            reasoning_score=8,
            coding_score=8,
            speed_score=5,
            cost_score=6,
            privacy_score=4,
        ),
        ModelInfo(
            model_id=provider_settings.local_model or "local-default",
            provider_id="local",
            execution_location=ExecutionLocation.LOCAL,
            display_name="Local Default",
            context_window=4096,
            supports_tools=False,
            supports_streaming=False,
            supports_images=False,
            supports_audio=False,
            reasoning_score=6,
            coding_score=6,
            speed_score=5,
            cost_score=10,
            privacy_score=10,
        ),
    ]:
        model_registry.register(model)
    model_manager = ModelManager(model_registry)

    # SQLite path is configured once (settings.sqlite_url); no hardcoded DB
    # locations remain in production composition.
    from app.config.settings import resolve_sqlite_path

    db_path = resolve_sqlite_path(settings.sqlite_url)
    db_dir = os.path.dirname(db_path) or "."
    os.makedirs(db_dir, exist_ok=True)
    sqlite_store = SQLiteStore(db_path=db_path)
    repository = MemoryRepository(store=sqlite_store)
    memory_manager = MemoryManager(repository=repository)
    memory_controller = MemoryController(memory_manager)
    session_manager = SessionManager(
        base_dir=settings.session_storage_path,
        memory_controller=memory_controller,
    )
    # Phase 11.4 — one shared short-lived conversation state per process so
    # the orchestrator and the shell command router see the same session state.
    conversation_state_manager = ConversationStateManager()

    from app.tools import FileSystemTool, MemoryTool, PDFTool, WindowsTool, ImageTool, ResolverTool, DocumentTool
    from app.tools.shell import ShellTool
    from app.tools.clipboard import ClipboardTool
    from app.tools.notification import NotificationTool
    from app.internet import BraveSearchProvider, InternetTool
    tool_registry = ToolRegistry()
    from app.tools.security import (
        FileSystemSecurityPolicy,
        ShellSecurityPolicy,
        ProcessSecurityPolicy,
        NetworkSecurityPolicy,
        ToolSecurityEnforcer,
    )
    filesystem_policy = FileSystemSecurityPolicy.build(
        allowed_roots=settings.filesystem_allowed_roots,
        default_root=settings.filesystem_default_root,
        protected_paths=settings.filesystem_protected_paths,
        max_read_bytes=settings.filesystem_max_read_bytes,
        max_write_bytes=settings.filesystem_max_write_bytes,
        max_directory_entries=settings.filesystem_max_directory_entries,
        max_recursion_depth=settings.filesystem_max_recursion_depth,
        max_files_per_operation=settings.filesystem_max_files_per_operation,
        max_path_length=settings.filesystem_max_path_length,
    )
    shell_policy = ShellSecurityPolicy.build(
        allowed_executables=settings.shell_allowed_executables,
        allowed_roots=settings.shell_allowed_roots,
        default_root=settings.shell_default_root,
        max_stdout_bytes=settings.shell_max_stdout_bytes,
        max_stderr_bytes=settings.shell_max_stderr_bytes,
        max_runtime_seconds=settings.shell_max_runtime_seconds,
    )
    process_policy = ProcessSecurityPolicy.build(
        max_process_list_entries=settings.process_max_list_entries,
        max_clipboard_bytes=settings.process_max_clipboard_bytes,
        allow_clipboard_write=settings.process_allow_clipboard_write,
        allow_terminal=settings.process_allow_terminal,
    )
    network_policy = NetworkSecurityPolicy.build(
        allowed_schemes=settings.network_allowed_schemes,
        allowed_hosts=settings.network_allowed_hosts,
        blocked_hosts=settings.network_blocked_hosts,
        allow_private_addresses=settings.network_allow_private_addresses,
        allow_localhost=settings.network_allow_localhost,
        max_redirects=settings.network_max_redirects,
        max_response_bytes=settings.network_max_response_bytes,
        request_timeout_seconds=settings.network_request_timeout_seconds,
        allowed_ports=settings.network_allowed_ports,
        sensitive_header_allowlist=settings.network_sensitive_header_allowlist,
    )
    tool_security_enforcer = ToolSecurityEnforcer(
        filesystem=filesystem_policy,
        shell=shell_policy,
        process=process_policy,
        network=network_policy,
    )
    filesystem_tool = FileSystemTool(security_policy=filesystem_policy)
    tool_registry.register(
        tool_id="resolver",
        tool=ResolverTool(registry=tool_registry),
        info=ToolInfo(
            tool_id="resolver",
            description="Dynamically routes resource tasks to specific format tools.",
            capabilities=["read", "write", "list", "search", "move", "copy", "delete", "rename"],
            supported_actions=["read", "write", "list", "search", "move", "copy", "delete", "rename"],
            permissions=["read", "write", "delete"],
            product_domain="filesystem",
            execution_mode=CapabilityAvailability.PRODUCTION_READY,
            side_effect_actions=["write", "move", "copy", "delete", "rename"],
            evidence_requirements={
                "write": "positive_written_bytes",
                "move": "source_and_destination",
                "copy": "source_and_destination",
                "delete": "deleted_target",
                "rename": "source_and_destination",
            },
            natural_language_intents=[
                "read_resource", "write_resource", "list_directory", "search_resource",
                "delete_resource", "move_resource", "copy_resource", "rename_resource",
            ],
            advertised=True,
        ),
    )
    tool_registry.register(
        tool_id="filesystem",
        tool=filesystem_tool,
        info=ToolInfo(
            tool_id="filesystem",
            description=(
                "Local filesystem operations: exists, read, write, list, search, copy, move, delete, mkdir. "
                "write/write_file supports .txt, .md, .markdown, .html, .htm, .csv (UTF-8 text), .docx (Word), "
                ".xlsx (Excel), and .pdf (PyMuPDF). When an explicit absolute path is supplied by the user, "
                "accept it only inside an approved filesystem root. Relative paths resolve against the configured workspace."
            ),
            capabilities=["exists", "read", "read_file", "write", "write_file", "list", "list_directory", "search", "copy", "move", "delete", "mkdir"],
        ),
    )
    tool_registry.register(
        tool_id="document",
        tool=DocumentTool(),
        info=ToolInfo(
            tool_id="document",
            description="Extract text, tables, images, and metadata from documents (PDF, DOCX, PPTX, XLSX, TXT, MD, HTML) using IBM Docling",
            capabilities=["read_document", "summarize_document", "extract_text", "extract_tables", "extract_metadata"],
            supported_actions=["read_document", "summarize_document", "extract_text", "extract_tables", "extract_metadata"],
            permissions=["read"],
            product_domain="document",
            execution_mode=CapabilityAvailability.INTERNAL_ONLY,
        ),
    )
    tool_registry.register(
        tool_id="pdf",
        tool=PDFTool(),
        info=ToolInfo(
            tool_id="pdf",
            description="Extract text, metadata, and page count from PDF documents",
            capabilities=["extract_text", "read_pdf", "page_count", "metadata", "tables"],
        ),
    )
    tool_registry.register(
        tool_id="image",
        tool=ImageTool(),
        info=ToolInfo(
            tool_id="image",
            description="Analyze image contents and extract metadata",
            capabilities=["analyze", "read_image", "metadata"],
        ),
    )
    memory_tool = MemoryTool(
        memory_manager=memory_manager,
        memory_controller=memory_controller,
        session_manager=session_manager,
    )
    tool_registry.register(
        tool_id="memory",
        tool=memory_tool,
        info=ToolInfo(
            tool_id="memory",
            description="Search, retrieve, and delete conversation and skill memories",
            capabilities=["search", "retrieve", "delete", "delete_type", "delete_all", "delete_session"],
            supported_actions=["search", "retrieve", "delete", "delete_type", "delete_all", "delete_session"],
            permissions=["read", "delete"],
            product_domain="memory",
            execution_mode=CapabilityAvailability.LOCAL_ONLY,
            side_effect_actions=["delete", "delete_type", "delete_all", "delete_session"],
            evidence_requirements={"delete": "positive_deleted_count", "delete_type": "positive_deleted_count", "delete_all": "positive_deleted_count", "delete_session": "deleted_session"},
            natural_language_intents=["search_memory", "delete_memory"],
            advertised=True,
        ),
    )
    tool_registry.register(
        tool_id="windows",
        tool=WindowsTool(),
        info=ToolInfo(
            tool_id="windows",
            description="Windows OS operations: list processes, clipboard, terminal commands",
            capabilities=["processes", "clipboard_get", "clipboard_set", "terminal"],
            supported_actions=["processes", "clipboard_get", "clipboard_set", "terminal"],
            permissions=["read", "write", "execute"],
            product_domain="windows",
            execution_mode=CapabilityAvailability.LOCAL_ONLY,
            side_effect_actions=["clipboard_set", "terminal"],
            evidence_requirements={"clipboard_set": "written_true", "terminal": "runtime_tool_success"},
            natural_language_intents=["operate_windows"],
            advertised=True,
        ),
    )
    # Phase 12 — governed internet intelligence. The provider reads
    # SAMAKTHA_BRAVE_API_KEY from the environment; when absent the tool reports
    # a graceful configuration error rather than crashing the pipeline.
    internet_tool = InternetTool(
        provider=BraveSearchProvider(api_key=os.environ.get("SAMAKTHA_BRAVE_API_KEY")),
        allow_private_addresses=settings.network_allow_private_addresses,
        allow_localhost=settings.network_allow_localhost,
        max_redirects=settings.network_max_redirects,
        max_response_bytes=settings.network_max_response_bytes,
        sensitive_header_allowlist=tuple(settings.network_sensitive_header_allowlist),
    )
    tool_registry.register(
        tool_id="internet",
        tool=internet_tool,
        info=ToolInfo(
            tool_id="internet",
            description="Governed internet search, news, content fetch, and suggestions",
            capabilities=["search", "news", "fetch", "suggest"],
            category="internet",
            permissions=["network"],
            approval_required=True,
            supported_actions=["search", "news", "fetch", "suggest"],
            product_domain="internet",
            execution_mode=CapabilityAvailability.PRODUCTION_READY,
            natural_language_intents=["search_internet"],
            advertised=True,
        ),
    )
    # Phase 13 — native core tools. Each declares its category, permissions
    # and policy so CAP can govern them and the dispatcher can enforce
    # timeouts/retries without app-specific orchestration logic.
    shell_tool = ShellTool()
    tool_registry.register(
        tool_id="shell",
        tool=shell_tool,
        info=ToolInfo(
            tool_id="shell",
            description="Execute an approved shell command with a hard denylist and timeout",
            capabilities=[c.value for c in shell_tool.capabilities if hasattr(c, "value")] or ["shell_exec", "run", "command", "terminal", "shell"],
            version="1.0.0",
            input_schema=shell_tool.input_schema,
            category="system",
            permissions=["execute"],
            approval_required=True,
            supported_actions=["run"],
            policy=shell_tool.policy,
            product_domain="shell",
            execution_mode=CapabilityAvailability.PRODUCTION_READY,
            side_effect_actions=["run"],
            evidence_requirements={"run": "runtime_tool_success"},
            natural_language_intents=["run_command"],
            advertised=True,
        ),
    )
    clipboard_tool = ClipboardTool()
    tool_registry.register(
        tool_id="clipboard",
        tool=clipboard_tool,
        info=ToolInfo(
            tool_id="clipboard",
            description="Read or write the system clipboard",
            capabilities=[c.value for c in clipboard_tool.capabilities if hasattr(c, "value")] or ["clipboard_read", "clipboard_write", "read", "write"],
            version="1.0.0",
            input_schema=clipboard_tool.input_schema,
            category="system",
            permissions=["read", "write"],
            approval_required=False,
            supported_actions=["read", "write"],
            policy=clipboard_tool.policy,
            product_domain="clipboard",
            execution_mode=CapabilityAvailability.LOCAL_ONLY,
            side_effect_actions=["write"],
            evidence_requirements={"write": "written_true"},
            natural_language_intents=["clipboard"],
            advertised=True,
        ),
    )
    notification_tool = NotificationTool()
    tool_registry.register(
        tool_id="notification",
        tool=notification_tool,
        info=ToolInfo(
            tool_id="notification",
            description="Send a local desktop notification",
            capabilities=[c.value for c in notification_tool.capabilities if hasattr(c, "value")] or ["notify", "send", "notification"],
            version="1.0.0",
            input_schema=notification_tool.input_schema,
            category="system",
            # Product planning treats a user-requested notification as a
            # governed local write.  The transient backend itself remains a
            # permissionless sink so an already-authorized persisted reminder
            # can be revalidated and dispatched with a fresh bound permit.
            permissions=["write"],
            approval_required=False,
            supported_actions=["send"],
            policy=notification_tool.policy,
            product_domain="notification",
            execution_mode=CapabilityAvailability.LOCAL_ONLY,
            side_effect_actions=["send"],
            evidence_requirements={"send": "sent_true"},
            natural_language_intents=["send_notification"],
            advertised=True,
        ),
    )
    # Phase 14 — personal productivity tools
    from app.tools.reminder import ReminderTool
    from app.tools.notes import NotesTool
    from app.tools.tasks import TasksTool
    from app.tools.contacts import ContactsTool
    from app.tools.calendar import CalendarTool
    reminder_tool = ReminderTool(db_path=db_path, integrity_key=signing_key)

    async def _reminder_notification_callback(reminder):
        """Re-authorize and dispatch a persisted reminder through Runtime."""
        from time import perf_counter
        from uuid import uuid4

        from app.core.contracts import ApprovedRuntimeTask, RoutingDecision, RuntimeContext
        from app.core.contracts.policy import (
            ApprovalDecision,
            ApprovalRequest,
            PlannedAction,
            authorization_payload,
            authorization_target,
        )

        arguments = {
            "title": f"Reminder: {reminder.title}",
            "message": reminder.description or reminder.title,
        }
        execution_id = f"reminder-{reminder.id}-{uuid4().hex}"
        task_id = f"{execution_id}-notification"
        target = authorization_target("tool", "notification")
        policy_action = PlannedAction(
            action_id=task_id,
            action_type="notification",
            description="Fire a scheduled local reminder notification.",
            target=target,
            payload=authorization_payload("tool", arguments),
        )
        operation = policy_action.model_copy(update={"action_type": "tool"})
        policy = orchestrator._policy_engine.evaluate(policy_action)
        permit = await orchestrator._approval_engine.authorize(
            ApprovalRequest(action=policy_action, operation=operation, policy=policy),
            subject_id=reminder.principal_id,
            session_id=reminder.session_id,
            workspace_id=reminder.workspace_id,
        )
        if permit.decision != ApprovalDecision.ALLOW:
            log.warning(
                "ReminderScheduler: current policy denied notification %s (%s)",
                reminder.id,
                permit.decision.value,
            )
            return
        task = ApprovedRuntimeTask(
            task_id=task_id,
            title="Scheduled reminder notification",
            description=policy_action.description,
            action_type="tool",
            inputs=arguments,
            metadata={
                "tool": "notification",
                "required_permissions": [
                    scope.value for scope in permit.required_permissions
                ],
                "execution_constraints": permit.constraints.model_dump(),
                "side_effect_class": "non_idempotent_mutation",
            },
            permit=permit,
        )
        context = RuntimeContext(
            request_id=execution_id,
            user_id=reminder.principal_id,
            session_id=reminder.session_id,
            workspace_id=reminder.workspace_id,
            metadata={"source": "reminder_scheduler"},
        )
        routing = RoutingDecision(
            provider_id="",
            model_id="",
            reasoning_summary="Scheduled local notification through canonical Runtime.",
            execution_constraints=permit.constraints,
        )
        started = perf_counter()
        if evidence_instrumentation is not None:
            evidence_instrumentation.tool_started(
                execution_id,
                reminder.principal_id,
                reminder.session_id,
                task_id,
                "notification",
                "send",
                action_id=task_id,
            )
        result = await runtime.run(context, task, routing)
        if evidence_instrumentation is not None:
            if result.status.value == "completed":
                evidence_instrumentation.tool_completed(
                    execution_id,
                    reminder.principal_id,
                    reminder.session_id,
                    task_id,
                    "notification",
                    "send",
                    duration_ms=int((perf_counter() - started) * 1000),
                    action_id=task_id,
                    side_effect_class="non_idempotent_mutation",
                )
            else:
                evidence_instrumentation.tool_failed(
                    execution_id,
                    reminder.principal_id,
                    reminder.session_id,
                    task_id,
                    "notification",
                    "send",
                    error=result.error or "Scheduled notification failed.",
                    duration_ms=int((perf_counter() - started) * 1000),
                    action_id=task_id,
                )
        if result.status.value != "completed":
            log.warning(
                "ReminderScheduler: notification callback failed: %s", result.error
            )

    reminder_scheduler = reminder_tool.scheduler
    reminder_scheduler.register_callback(_reminder_notification_callback)
    tool_registry.register(
        tool_id="reminder",
        tool=reminder_tool,
        info=ToolInfo(
            tool_id="reminder",
            description="Local reminder records whose due notifications are re-authorized through canonical Runtime",
            capabilities=[c.value for c in reminder_tool.capabilities if hasattr(c, "value")] or ["reminder_create", "reminder_list", "reminder_cancel", "reminder_update", "reminder_snooze"],
            version="1.0.0",
            input_schema=reminder_tool.input_schema,
            category="personal",
            permissions=["read", "write"],
            approval_required=False,
            supported_actions=["create", "list", "cancel", "update", "snooze", "complete"],
            policy=reminder_tool.policy,
            product_domain="reminder",
            execution_mode=CapabilityAvailability.LOCAL_ONLY,
            side_effect_actions=["create", "cancel", "update", "snooze", "complete"],
            evidence_requirements={"create": "reminder_record", "cancel": "mutation_message", "update": "reminder_record", "snooze": "reminder_record", "complete": "reminder_record"},
            natural_language_intents=["manage_reminder"],
            advertised=True,
        ),
    )
    notes_tool = NotesTool(db_path=db_path)
    tool_registry.register(
        tool_id="notes",
        tool=notes_tool,
        info=ToolInfo(
            tool_id="notes",
            description="Markdown notes with CRUD, search, voice dictation, and memory indexing",
            capabilities=[c.value for c in notes_tool.capabilities if hasattr(c, "value")] or ["note_create", "note_read", "note_update", "note_delete", "note_search", "note_list"],
            version="1.0.0",
            input_schema=notes_tool.input_schema,
            category="personal",
            permissions=["read", "write"],
            approval_required=False,
            supported_actions=["create", "read", "update", "delete", "search", "list"],
            policy=notes_tool.policy,
            product_domain="note",
            execution_mode=CapabilityAvailability.LOCAL_ONLY,
            side_effect_actions=["create", "update", "delete"],
            evidence_requirements={"create": "note_record", "update": "note_record", "delete": "mutation_message"},
            natural_language_intents=["manage_note"],
            advertised=True,
        ),
    )
    tasks_tool = TasksTool(db_path=db_path)
    tool_registry.register(
        tool_id="tasks",
        tool=tasks_tool,
        info=ToolInfo(
            tool_id="tasks",
            description="Task management with priority, status, due dates, dependencies, and reminder integration",
            capabilities=[c.value for c in tasks_tool.capabilities if hasattr(c, "value")] or ["task_create", "task_read", "task_update", "task_delete", "task_list", "task_filter", "task_complete"],
            version="1.0.0",
            input_schema=tasks_tool.input_schema,
            category="personal",
            permissions=["read", "write"],
            approval_required=False,
            supported_actions=["create", "read", "update", "delete", "list", "filter", "complete"],
            policy=tasks_tool.policy,
            product_domain="task",
            execution_mode=CapabilityAvailability.LOCAL_ONLY,
            side_effect_actions=["create", "update", "delete", "complete"],
            evidence_requirements={"create": "task_record", "update": "task_record", "delete": "mutation_message", "complete": "task_record"},
            natural_language_intents=["manage_task"],
            advertised=True,
        ),
    )
    contacts_tool = ContactsTool(db_path=db_path)
    tool_registry.register(
        tool_id="contacts",
        tool=contacts_tool,
        info=ToolInfo(
            tool_id="contacts",
            description="Contact management with CRUD, search, tags, vCard import/export, and voice support",
            capabilities=[c.value for c in contacts_tool.capabilities if hasattr(c, "value")] or ["contact_create", "contact_read", "contact_update", "contact_delete", "contact_search", "contact_list", "contact_lookup", "contact_import", "contact_export"],
            version="1.0.0",
            input_schema=contacts_tool.input_schema,
            category="personal",
            permissions=["read", "write"],
            approval_required=False,
            supported_actions=["create", "read", "update", "delete", "search", "list", "lookup", "import", "export"],
            policy=contacts_tool.policy,
            product_domain="contact",
            execution_mode=CapabilityAvailability.LOCAL_ONLY,
            side_effect_actions=["create", "update", "delete", "import"],
            evidence_requirements={"create": "contact_record", "update": "contact_record", "delete": "mutation_message", "import": "contact_record"},
            natural_language_intents=["search_contact", "manage_contact"],
            advertised=True,
        ),
    )
    calendar_tool = CalendarTool(db_path=db_path)
    tool_registry.register(
        tool_id="calendar",
        tool=calendar_tool,
        info=ToolInfo(
            tool_id="calendar",
            description="Local-first calendar with events, conflict detection, recurrence, agenda, and voice support",
            capabilities=[c.value for c in calendar_tool.capabilities if hasattr(c, "value")] or ["event_create", "event_read", "event_update", "event_delete", "event_agenda", "event_conflicts", "event_list", "event_recurring"],
            version="1.0.0",
            input_schema=calendar_tool.input_schema,
            category="personal",
            permissions=["read", "write"],
            approval_required=False,
            supported_actions=["create", "read", "update", "delete", "agenda", "conflicts", "list", "recurring"],
            policy=calendar_tool.policy,
            product_domain="calendar",
            execution_mode=CapabilityAvailability.LOCAL_ONLY,
            side_effect_actions=["create", "update", "delete"],
            evidence_requirements={"create": "event_record", "update": "event_record", "delete": "mutation_message"},
            natural_language_intents=["manage_calendar"],
            advertised=True,
        ),
    )
    # Phase 15 — communication tools
    from app.integrations.registry import IntegrationRegistry
    from app.integrations.credentials import CredentialResolver
    from app.integrations.email_smtp import SMTPIntegrationProvider

    integration_registry = IntegrationRegistry()
    smtp_provider = SMTPIntegrationProvider(CredentialResolver.get_smtp_credentials())
    integration_registry.register("smtp", smtp_provider)

    from app.communication.email_tool import EmailTool
    from app.communication.message_tool import MessageTool

    email_tool = EmailTool(integration_provider=smtp_provider)

    email_execution_mode = (
        CapabilityAvailability.PRODUCTION_READY
        if smtp_provider.is_configured()
        else CapabilityAvailability.SIMULATED
    )

    email_description = (
        "Send real emails via SMTP provider"
        if smtp_provider.is_configured()
        else "Local email drafting and simulation only; no external email delivery provider is connected"
    )

    tool_registry.register(
        tool_id="email",
        tool=email_tool,
        info=ToolInfo(
            tool_id="email",
            description=email_description,
            capabilities=[c.value for c in email_tool.capabilities if hasattr(c, "value")] or ["email_compose", "email_draft", "email_send", "email_reply", "email_forward", "email_read", "email_search", "email_list_folders", "email_attachments"],
            version="1.0.0",
            input_schema=email_tool.input_schema,
            category="communication",
            permissions=["read", "write", "network"],
            approval_required=True,
            supported_actions=["compose", "draft", "send", "reply", "forward", "read", "search", "list_folders"],
            policy=email_tool.policy,
            product_domain="email",
            execution_mode=email_execution_mode,
            side_effect_actions=["send", "reply", "forward"],
            evidence_requirements={"compose": "draft_state", "draft": "draft_state", "send": "simulation_state" if not smtp_provider.is_configured() else "provider_accepted", "reply": "simulation_state", "forward": "simulation_state"},
            natural_language_intents=["send_email", "read_email", "reply_email", "forward_email"],
            advertised=True,
        ),
    )
    message_tool = MessageTool()
    tool_registry.register(
        tool_id="message",
        tool=message_tool,
        info=ToolInfo(
            tool_id="message",
            description="Local message drafting and simulation only; no external messaging provider is connected",
            capabilities=[c.value for c in message_tool.capabilities if hasattr(c, "value")] or ["message_send", "message_reply", "message_history", "message_draft", "message_search", "message_attachments"],
            version="1.0.0",
            input_schema=message_tool.input_schema,
            category="communication",
            permissions=["read", "write"],
            approval_required=True,
            supported_actions=["send", "reply", "history", "draft", "search"],
            policy=message_tool.policy,
            product_domain="message",
            execution_mode=CapabilityAvailability.SIMULATED,
            side_effect_actions=["send", "reply"],
            evidence_requirements={"draft": "draft_state", "send": "simulation_state", "reply": "simulation_state"},
            natural_language_intents=["send_message", "read_messages", "search_messages"],
            advertised=True,
        ),
    )
    product_capability_registry = ProductCapabilityRegistry.from_tool_registry(
        tool_registry
    )
    tool_manager = ToolManager(tool_registry)

    # P0.2 — one security control plane per process: the input scanner gates
    # every request at the pipeline entry, the output filter redacts leaked
    # credentials from every response, and the tool guard gates every tool
    # execution. All three share a single metrics collector.
    security_metrics = SecurityMetricsCollector()
    input_scanner = InputSecurityScanner()
    output_filter = OutputSecurityFilter(metrics=security_metrics)
    tool_guard = ToolGuard(tool_manager=tool_manager, metrics=security_metrics)

    runtime_registry = RuntimeRegistry()
    governance = GovernanceEngine()
    provider_executor = ProviderExecutor(provider_manager, governance=governance)
    runtime_registry.register("provider", provider_executor)
    runtime_registry.register(
        "tool",
        ToolExecutor(
            tool_manager,
            tool_guard=tool_guard,
            governance=governance,
            tool_security=tool_security_enforcer,
        ),
    )
    from app.runtime.reliability import RetryPolicy
    retry_policy = RetryPolicy(
        max_attempts=settings.runtime_max_retry_attempts,
        initial_delay_s=settings.runtime_retry_initial_delay_seconds,
        max_delay_s=settings.runtime_retry_max_delay_seconds,
    )
    from app.runtime.reliability import SideEffectClass

    def tool_reliability(task):
        tool_id = task.metadata.get("tool") if task.action_type == "tool" else None
        info = tool_manager.get_tool_info(tool_id) if tool_id else None
        if info is None:
            return SideEffectClass.NON_IDEMPOTENT_MUTATION
        action = str(task.inputs.get("action", ""))
        if action not in set(info.side_effect_actions):
            return SideEffectClass.READ_ONLY
        if info.policy is not None and info.policy.idempotent_mutation:
            return SideEffectClass.IDEMPOTENT_MUTATION
        return SideEffectClass.NON_IDEMPOTENT_MUTATION

    runtime = RuntimeEngine(
        RuntimeDispatcher(runtime_registry),
        max_parallelism=settings.max_runtime_tasks,
        retry_policy=retry_policy,
        tool_reliability_resolver=tool_reliability,
        tool_security=tool_security_enforcer,
    )

    router_registrations: list[ProviderModelRegistration] = []
    if provider_settings.mock_allowed():
        router_registrations.append(
            ProviderModelRegistration(
                provider_id="mock", model_id="mock-model", capabilities=["text_generation"], execution_location=ExecutionLocation.LOCAL),
        )
    router_registrations.extend([
        ProviderModelRegistration(
            provider_id="openai", model_id=provider_settings.openai_model, capabilities=["text_generation"], execution_location=ExecutionLocation.CLOUD),
        ProviderModelRegistration(
            provider_id="groq", model_id=provider_settings.groq_model, capabilities=["text_generation"], execution_location=ExecutionLocation.CLOUD),
        ProviderModelRegistration(
            provider_id="openrouter", model_id=provider_settings.openrouter_model, capabilities=["text_generation"], execution_location=ExecutionLocation.CLOUD),
        ProviderModelRegistration(
            provider_id="local", model_id=provider_settings.local_model or "unknown", capabilities=["text_generation"], execution_location=ExecutionLocation.LOCAL),
    ])
    router_registry = RouterRegistry(router_registrations)
    capability_registry = CapabilityRegistry()
    if provider_settings.mock_allowed():
        capability_registry.register(ProviderCapability(
            provider_id="mock",
            execution_location=ExecutionLocation.LOCAL,
            model_id="mock-model",
            capabilities=["text_generation"],
            reasoning_score=3,
            coding_score=3,
            speed_score=10,
            privacy_score=8,
            cost_score=10,
            context_window=4096,
            maximum_output=1024,
            latency_ms=1.0,
        ))
    capability_registry.register(ProviderCapability(
        provider_id="openai",
        execution_location=ExecutionLocation.CLOUD,
        model_id=provider_settings.openai_model,
        capabilities=["text_generation", "code_generation"],
        reasoning_score=8,
        coding_score=8,
        speed_score=7,
        privacy_score=3,
        cost_score=7,
        context_window=128000,
        maximum_output=provider_settings.max_output_tokens,
        input_cost_per_1k=0.00015,
        output_cost_per_1k=0.0006,
    ))
    capability_registry.register(ProviderCapability(
        provider_id="groq",
        execution_location=ExecutionLocation.CLOUD,
        model_id=provider_settings.groq_model,
        capabilities=["text_generation", "code_generation"],
        reasoning_score=9,
        coding_score=8,
        speed_score=10,
        privacy_score=4,
        cost_score=9,
        context_window=128000,
        maximum_output=provider_settings.max_output_tokens,
        latency_ms=20.0,
    ))
    capability_registry.register(ProviderCapability(
        provider_id="openrouter",
        execution_location=ExecutionLocation.CLOUD,
        model_id=provider_settings.openrouter_model,
        capabilities=["text_generation", "code_generation"],
        reasoning_score=8,
        coding_score=8,
        speed_score=5,
        privacy_score=4,
        cost_score=6,
        context_window=128000,
        maximum_output=provider_settings.max_output_tokens,
        latency_ms=30.0,
    ))
    capability_registry.register(ProviderCapability(
        provider_id="local",
        execution_location=ExecutionLocation.LOCAL,
        model_id=provider_settings.local_model or "unknown",
        capabilities=["text_generation"],
        reasoning_score=6,
        coding_score=6,
        speed_score=5,
        privacy_score=10,
        cost_score=10,
        context_window=4096,
        maximum_output=provider_settings.max_output_tokens,
        latency_ms=50.0,
    ))
    model_router = ModelRouter(
        router_registry,
        capability_registry,
        model_manager=model_manager,
        health_checker=health_checker,
        preferred_provider=provider_settings.default_provider,
    )

    workflow_engine = WorkflowEngine()

    # P2.8 — personality lifecycle wired into the production orchestrator. The
    # registry catalogs personalities, the manager owns the active selection,
    # and persistence re-activates the last chosen profile across restarts.
    from app.personality import (
        PersonalityLifecycleManager,
        PersonalityPersistence,
        default_personality_registry,
    )

    personality_registry = default_personality_registry()
    personality_manager = PersonalityLifecycleManager(
        personality_registry,
        default_profile_id=settings.personality_profile,
        persistence=PersonalityPersistence(settings.personality_state_path),
    )
    from app.personality.response_formatter import ResponseFormatter

    orchestrator = SamakthaOrchestrator(
        context_engine=ContextEngine(memory_reader=memory_manager),
        planner=Planner(
            memory_manager=memory_manager,
            capability_registry=product_capability_registry,
        ),
        router=model_router,
        runtime=runtime,
        workflow_engine=workflow_engine,
        memory_manager=memory_manager,
        memory_controller=memory_controller,
        session_manager=session_manager,
        conversation_state_manager=conversation_state_manager,
        security_scanner=input_scanner,
        security_output_filter=output_filter,
        personality_registry=personality_registry,
        personality_manager=personality_manager,
        response_formatter=ResponseFormatter(
            capability_registry=product_capability_registry
        ),
    )
    # Streaming telemetry comes from the canonical Runtime ProviderExecutor.
    # The legacy StreamingExecutor remains a disconnected library helper.
    orchestrator.streaming_executor = provider_executor
    orchestrator.provider_settings = provider_settings
    orchestrator.provider_manager = provider_manager
    orchestrator.provider_registry = provider_registry
    orchestrator.model_manager = model_manager
    orchestrator.health_checker = health_checker
    orchestrator.tool_registry = tool_registry
    orchestrator.product_capability_registry = product_capability_registry
    orchestrator.internet_tool = internet_tool
    orchestrator.memory_manager = memory_manager
    orchestrator.memory_controller = memory_controller
    orchestrator.session_manager = session_manager
    orchestrator.conversation_state_manager = conversation_state_manager
    orchestrator.security_metrics = security_metrics
    orchestrator.input_scanner = input_scanner
    orchestrator.output_filter = output_filter
    orchestrator.tool_guard = tool_guard
    orchestrator.tool_security_enforcer = tool_security_enforcer
    orchestrator.reminder_scheduler = reminder_scheduler
    # P2.7 — telemetry accessors (public handles to subsystem collectors).
    orchestrator.runtime = runtime
    orchestrator.workflow_engine = workflow_engine
    orchestrator.model_router = model_router
    orchestrator.tool_manager = tool_manager
    orchestrator.governance = governance
    checkpoint_location = settings.checkpoint_location
    if checkpoint_location == "data/checkpoints" and db_path != "data/memory.db":
        checkpoint_location = os.path.join(db_dir, "checkpoints")
    checkpoint_store = (
        CheckpointStore(
            checkpoint_location,
            integrity_key=signing_key,
            integrity_index_path=signing_key_path.with_name(
                "checkpoint_integrity.json"
            ),
            secure_file=_harden_private_file_permissions,
        )
        if settings.checkpoint_enabled else None
    )
    orchestrator.checkpoint_store = checkpoint_store

    # P8 — Durable execution evidence store
    evidence_store = None
    evidence_instrumentation = None
    if settings.evidence_enabled:
        evidence_config = EvidenceStoreConfig(
            db_path=settings.evidence_db_path,
            enabled=settings.evidence_enabled,
            retention_days=settings.evidence_retention_days,
            max_events_per_execution=settings.evidence_max_events_per_execution,
            max_payload_bytes=settings.evidence_max_payload_bytes,
        )
        evidence_store = EvidenceStore(evidence_config)
        evidence_instrumentation = EvidenceInstrumentation(evidence_store)
    orchestrator.evidence_store = evidence_store
    orchestrator.evidence_instrumentation = evidence_instrumentation

    # P12-D07 — production owns one plugin lifecycle manager bound to the
    # canonical registries.  Discovery is metadata-only; plugins remain
    # disabled until an explicit operator action enables and loads them.
    from app.plugins import PluginActivityTracker, PluginManager

    plugin_activity = PluginActivityTracker()
    plugin_manager = PluginManager(
        tool_registry=tool_registry,
        capability_registry=product_capability_registry,
        data_dir=os.path.join(settings.plugin_dir, ".data"),
        activity=plugin_activity,
        evidence_instrumentation=evidence_instrumentation,
        require_explicit_enable=True,
    )
    if os.path.isdir(settings.plugin_dir):
        plugin_manager.discover(settings.plugin_dir)
    orchestrator.plugin_manager = plugin_manager
    orchestrator.plugin_activity = plugin_activity

    orchestrator.execution_coordinator = ExecutionCoordinator(
        orchestrator,
        checkpoint_store=checkpoint_store,
        evidence_instrumentation=evidence_instrumentation,
        execution_timeout_s=settings.execution_timeout_seconds,
        max_active_executions=settings.max_active_executions,
        max_pending_executions=settings.max_pending_executions,
        max_retained_executions=settings.max_retained_executions,
    )
    return orchestrator
