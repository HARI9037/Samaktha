from fastapi import FastAPI

from app.api.execute import router as execute_router
from app.api.health import router as health_router
from app.config.settings import Settings
from app.core.cap import ContextEngine
from app.core.gambit import Planner
from app.core.orchestrator import SamakthaOrchestrator
from app.providers import (
    GroqProvider,
    LocalProvider,
    MockProvider,
    OpenAIProvider,
    OpenRouterProvider,
    ProviderInfo,
    ProviderManager,
    ProviderRegistry,
    ProviderSettings,
)
from app.memory.sqlite_store import SQLiteStore
from app.memory.manager import MemoryManager
from app.memory.repository import MemoryRepository
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
    provider_registry = ProviderRegistry()
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
    provider_manager = ProviderManager(provider_registry, provider_settings)

    model_registry = ModelRegistry()
    for model in [
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

    from app.tools import FileSystemTool, MemoryTool, PDFTool, WindowsTool, ImageTool, ResolverTool, DocumentTool
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
            description="Local filesystem operations: exists, read, write, list, search, copy, move, delete, mkdir",
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
    memory_tool = MemoryTool(memory_manager=memory_manager)
    tool_registry.register(
        tool_id="memory",
        tool=memory_tool,
        info=ToolInfo(
            tool_id="memory",
            description="Search and retrieve conversation and skill memories",
            capabilities=["search", "retrieve"],
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
    tool_manager = ToolManager(tool_registry)

    runtime_registry = RuntimeRegistry()
    runtime_registry.register("provider", ProviderExecutor(provider_manager))
    runtime_registry.register("tool", ToolExecutor(tool_manager))
    runtime = RuntimeEngine(RuntimeDispatcher(runtime_registry))

    router_registry = RouterRegistry([
        ProviderModelRegistration(
            provider_id="mock", model_id="mock-model", capabilities=["text_generation"]),
        ProviderModelRegistration(
            provider_id="openai", model_id=provider_settings.openai_model, capabilities=["text_generation"]),
        ProviderModelRegistration(
            provider_id="groq", model_id=provider_settings.groq_model, capabilities=["text_generation"]),
        ProviderModelRegistration(
            provider_id="local", model_id=provider_settings.local_model or "unknown", capabilities=["text_generation"]),
    ])
    capability_registry = CapabilityRegistry()
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
        preferred_provider=provider_settings.default_provider,
    )

    orchestrator = SamakthaOrchestrator(
        context_engine=ContextEngine(memory_reader=memory_manager),
        planner=Planner(),
        router=model_router,
        runtime=runtime,
        workflow_engine=WorkflowEngine(),
    )
    # Expose existing runtime streaming as a connection point for frontends;
    # this does not alter the orchestrator's synchronous workflow path.
    orchestrator.streaming_executor = StreamingExecutor(provider_manager)
    orchestrator.provider_settings = provider_settings
    return orchestrator
