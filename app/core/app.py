from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import logging
import os
from typing import Any

from app.api.execute import router as execute_router
from app.api.health import router as health_router
from app.api.limits import RateLimiter, client_key, content_length
from app.api.metrics import HttpMetricsCollector, router as metrics_router
from app.api.metrics import provider_metrics_adapter, snapshot_adapter
from app.api.personality import router as personality_router
from app.config.settings import Settings, get_settings
from app.core.cap import ContextEngine
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
from app.runtime.streaming import StreamingExecutor
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
    try:
        yield
    finally:
        if scheduler is not None:
            await scheduler.stop()


def create_orchestrator(settings: Settings | None = None) -> SamakthaOrchestrator:
    # Provider credentials are optional at composition time: the application
    # and /health must remain reachable without keys. Missing provider
    # configuration is a clean execution-time error, enforced by the
    # orchestrator before any provider/tool execution (see
    # SamakthaOrchestrator._ensure_provider_available).
    settings = settings or get_settings()
    provider_settings = ProviderSettings()

    provider_registry = ProviderRegistry()
    health_checker = ProviderHealthChecker(provider_settings)
    if provider_settings.mock_allowed():
        provider_registry.register(
            provider_id="mock",
            provider=MockProvider(),
            info=ProviderInfo(
                provider_id="mock",
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
            capabilities=["text_generation"],
            models=[provider_settings.groq_model],
            supported_models=["llama-3.3-70b-versatile"],
            metadata={"maximum_context": 128000, "maximum_output": provider_settings.max_output_tokens, "supports_streaming": True, "supports_tools": False, "supports_vision": False, "supports_reasoning": True},
        ),
    )
    provider_registry.register(
        provider_id="openrouter",
        provider=OpenRouterProvider(provider_settings),
        info=ProviderInfo(
            provider_id="openrouter",
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
            model_id="llama-3.3-70b-versatile",
            provider_id="groq",
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
            model_id="local-default",
            provider_id="local",
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
    session_manager = SessionManager(memory_controller=memory_controller)
    # Phase 11.4 — one shared short-lived conversation state per process so
    # the orchestrator and the shell command router see the same session state.
    conversation_state_manager = ConversationStateManager()

    from app.tools import FileSystemTool, MemoryTool, PDFTool, WindowsTool, ImageTool, ResolverTool, DocumentTool
    from app.tools.shell import ShellTool
    from app.tools.clipboard import ClipboardTool
    from app.tools.notification import NotificationTool
    from app.internet import BraveSearchProvider, InternetTool
    tool_registry = ToolRegistry()
    tool_registry.register(
        tool_id="resolver",
        tool=ResolverTool(registry=tool_registry),
        info=ToolInfo(
            tool_id="resolver",
            description="Dynamically routes resource tasks to specific format tools.",
            capabilities=["read", "list", "search", "move", "copy", "delete", "rename"],
        ),
    )
    tool_registry.register(
        tool_id="filesystem",
        tool=FileSystemTool(),        # No sandbox — allows absolute paths from planner
        info=ToolInfo(
            tool_id="filesystem",
            description=(
                "Local filesystem operations: exists, read, write, list, search, copy, move, delete, mkdir. "
                "write/write_file supports .txt, .md, .markdown, .html, .htm, .csv (UTF-8 text), .docx (Word), "
                ".xlsx (Excel), and .pdf (PyMuPDF). When an explicit absolute path is supplied by the user, "
                "preserve it exactly. Relative write paths resolve against the default output directory (Desktop)."
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
        ),
    )
    tool_registry.register(
        tool_id="windows",
        tool=WindowsTool(),
        info=ToolInfo(
            tool_id="windows",
            description="Windows OS operations: list processes, clipboard, terminal commands",
            capabilities=["processes", "clipboard_get", "clipboard_set", "terminal"],
        ),
    )
    # Phase 12 — governed internet intelligence. The provider reads
    # SAMAKTHA_BRAVE_API_KEY from the environment; when absent the tool reports
    # a graceful configuration error rather than crashing the pipeline.
    internet_tool = InternetTool(
        provider=BraveSearchProvider(api_key=os.environ.get("SAMAKTHA_BRAVE_API_KEY"))
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
            permissions=["write"],
            approval_required=False,
            supported_actions=["send"],
            policy=notification_tool.policy,
        ),
    )
    # Phase 14 — personal productivity tools
    from app.tools.reminder import ReminderTool
    from app.tools.notes import NotesTool
    from app.tools.tasks import TasksTool
    from app.tools.contacts import ContactsTool
    from app.tools.calendar import CalendarTool
    reminder_tool = ReminderTool(db_path=db_path)

    async def _reminder_notification_callback(reminder):
        result = await notification_tool.run(
            {
                "title": f"Reminder: {reminder.title}",
                "message": reminder.description or reminder.title,
            }
        )
        if not result.ok:
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
            description="Personal reminder management with scheduling, notifications, and voice support",
            capabilities=[c.value for c in reminder_tool.capabilities if hasattr(c, "value")] or ["reminder_create", "reminder_list", "reminder_cancel", "reminder_update", "reminder_snooze"],
            version="1.0.0",
            input_schema=reminder_tool.input_schema,
            category="personal",
            permissions=["read", "write"],
            approval_required=False,
            supported_actions=["create", "list", "cancel", "update", "snooze", "complete"],
            policy=reminder_tool.policy,
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
        ),
    )
    # Phase 15 — communication tools
    from app.communication.email_tool import EmailTool
    from app.communication.message_tool import MessageTool
    email_tool = EmailTool()
    tool_registry.register(
        tool_id="email",
        tool=email_tool,
        info=ToolInfo(
            tool_id="email",
            description="Email communication with compose, draft, send, reply, forward, read, search, and attachments",
            capabilities=[c.value for c in email_tool.capabilities if hasattr(c, "value")] or ["email_compose", "email_draft", "email_send", "email_reply", "email_forward", "email_read", "email_search", "email_list_folders", "email_attachments"],
            version="1.0.0",
            input_schema=email_tool.input_schema,
            category="communication",
            permissions=["read", "write", "network"],
            approval_required=True,
            supported_actions=["compose", "draft", "send", "reply", "forward", "read", "search", "list_folders"],
            policy=email_tool.policy,
        ),
    )
    message_tool = MessageTool()
    tool_registry.register(
        tool_id="message",
        tool=message_tool,
        info=ToolInfo(
            tool_id="message",
            description="Messaging communication with send, reply, history, draft, and search",
            capabilities=[c.value for c in message_tool.capabilities if hasattr(c, "value")] or ["message_send", "message_reply", "message_history", "message_draft", "message_search", "message_attachments"],
            version="1.0.0",
            input_schema=message_tool.input_schema,
            category="communication",
            permissions=["read", "write", "network"],
            approval_required=True,
            supported_actions=["send", "reply", "history", "draft", "search"],
            policy=message_tool.policy,
        ),
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
    runtime_registry.register("provider", ProviderExecutor(provider_manager, governance=governance))
    runtime_registry.register("tool", ToolExecutor(tool_manager, tool_guard=tool_guard, governance=governance))
    runtime = RuntimeEngine(RuntimeDispatcher(runtime_registry))

    router_registrations: list[ProviderModelRegistration] = []
    if provider_settings.mock_allowed():
        router_registrations.append(
            ProviderModelRegistration(
                provider_id="mock", model_id="mock-model", capabilities=["text_generation"]),
        )
    router_registrations.extend([
        ProviderModelRegistration(
            provider_id="openai", model_id=provider_settings.openai_model, capabilities=["text_generation"]),
        ProviderModelRegistration(
            provider_id="groq", model_id=provider_settings.groq_model, capabilities=["text_generation"]),
        ProviderModelRegistration(
            provider_id="openrouter", model_id=provider_settings.openrouter_model, capabilities=["text_generation"]),
        ProviderModelRegistration(
            provider_id="local", model_id=provider_settings.local_model or "unknown", capabilities=["text_generation"]),
    ])
    router_registry = RouterRegistry(router_registrations)
    capability_registry = CapabilityRegistry()
    if provider_settings.mock_allowed():
        capability_registry.register(ProviderCapability(
            provider_id="mock",
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

    orchestrator = SamakthaOrchestrator(
        context_engine=ContextEngine(memory_reader=memory_manager),
        planner=Planner(memory_manager=memory_manager),
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
    )
    # Expose existing runtime streaming as a connection point for frontends;
    # this does not alter the orchestrator's synchronous workflow path.
    orchestrator.streaming_executor = StreamingExecutor(provider_manager)
    orchestrator.provider_settings = provider_settings
    orchestrator.provider_manager = provider_manager
    orchestrator.provider_registry = provider_registry
    orchestrator.model_manager = model_manager
    orchestrator.health_checker = health_checker
    orchestrator.tool_registry = tool_registry
    orchestrator.internet_tool = internet_tool
    orchestrator.memory_manager = memory_manager
    orchestrator.memory_controller = memory_controller
    orchestrator.session_manager = session_manager
    orchestrator.conversation_state_manager = conversation_state_manager
    orchestrator.security_metrics = security_metrics
    orchestrator.input_scanner = input_scanner
    orchestrator.output_filter = output_filter
    orchestrator.tool_guard = tool_guard
    orchestrator.reminder_scheduler = reminder_scheduler
    # P2.7 — telemetry accessors (public handles to subsystem collectors).
    orchestrator.runtime = runtime
    orchestrator.workflow_engine = workflow_engine
    orchestrator.model_router = model_router
    orchestrator.tool_manager = tool_manager
    orchestrator.governance = governance
    return orchestrator
