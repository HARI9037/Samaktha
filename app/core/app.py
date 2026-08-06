from fastapi import FastAPI

from app.api.execute import router as execute_router
from app.api.health import router as health_router
from app.config.settings import Settings
from app.core.cap import ContextEngine
from app.conversation import ConversationStateManager
from app.core.gambit import Planner
from app.core.orchestrator import SamakthaOrchestrator
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
import os


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
    )
    app.state.orchestrator = create_orchestrator()
    app.include_router(health_router)
    app.include_router(execute_router)
    return app


def create_orchestrator() -> SamakthaOrchestrator:
    provider_settings = ProviderSettings()
    # Phase 11.2 — production startup fails loudly instead of silently
    # degrading to a development provider.
    provider_settings.validate_startup()
    provider_settings.validate_production()

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

    # Ensure data directory exists for SQLite
    os.makedirs('data', exist_ok=True)
    sqlite_store = SQLiteStore(db_path='data/memory.db')
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
    reminder_tool = ReminderTool()
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
    notes_tool = NotesTool()
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
    tasks_tool = TasksTool()
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
    contacts_tool = ContactsTool()
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
    calendar_tool = CalendarTool()
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

    runtime_registry = RuntimeRegistry()
    runtime_registry.register("provider", ProviderExecutor(provider_manager))
    runtime_registry.register("tool", ToolExecutor(tool_manager))
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

    orchestrator = SamakthaOrchestrator(
        context_engine=ContextEngine(memory_reader=memory_manager),
        planner=Planner(memory_manager=memory_manager),
        router=model_router,
        runtime=runtime,
        workflow_engine=WorkflowEngine(),
        memory_manager=memory_manager,
        memory_controller=memory_controller,
        session_manager=session_manager,
        conversation_state_manager=conversation_state_manager,
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
    return orchestrator
