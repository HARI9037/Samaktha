## Model Registry v0.1

Status: Implemented

Implemented modules:

- app/models/models.py
- app/models/registry.py
- app/models/manager.py
- app/models/__init__.py

### Description

Model Registry v0.1 introduces a dedicated metadata layer for AI models, separated from provider implementations and provider selection.

- ModelInfo describes model identity, owning provider, capability flags, scoring metadata, context window, and free-form metadata.
- ModelRegistry stores model metadata by model_id, supports lookup, listing, provider filtering, and duplicate overwrite.
- ModelManager delegates model registration, resolution, and listing to the registry.
- Application wiring registers foundation model metadata for mock, OpenAI, Groq, OpenRouter, and local model identities, then passes the manager into ModelRouter as an optional dependency.

### Current Limitations

- Routing behavior is unchanged.
- Provider selection is unchanged.
- Scores are not consumed by Router v0.2.
- No HTTP calls, streaming, embeddings, function calling, vision/audio execution, or dynamic discovery are introduced.

## Provider Status

Status: Implemented v1.0

Implemented modules:

- app/providers/base.py
- app/providers/config.py
- app/providers/cost.py
- app/providers/health.py
- app/providers/http_chat.py
- app/providers/models.py
- app/providers/registry.py
- app/providers/manager.py
- app/providers/metrics.py
- app/providers/mock.py
- app/providers/openai_provider.py
- app/providers/groq_provider.py
- app/providers/openrouter_provider.py
- app/providers/local_provider.py
- app/providers/selector.py
- app/providers/usage.py
- app/providers/__init__.py

### Description

Provider System v1.0 completes Phase 1 AI Infrastructure while preserving the existing Provider interface and ProviderManager entry point.

- **MockProvider** (`mock`): Deterministic test provider; unchanged from v0.1/v0.2.
- **OpenAIProvider** (`openai`): OpenAI-compatible cloud provider; returns normalized `ProviderResponse`; fails safely when API key is missing.
- **GroqProvider** (`groq`): Groq cloud provider; returns normalized `ProviderResponse`; fails safely when API key is missing.
- **OpenRouterProvider** (`openrouter`): OpenRouter cloud provider; returns normalized `ProviderResponse`; fails safely when API key is missing.
- **LocalProvider** (`local`): Local inference server provider (e.g. Ollama); fails safely when base URL is missing.
- **ProviderStatus**: Deterministic Pydantic health state for provider_id, enabled/configured/available flags, reachability, rate limiting, last check time, and last error.
- **ProviderHealthChecker**: Performs local configuration validation only and reports provider availability through `ProviderManager`.
- **ProviderSelectionEngine**: Deterministically selects a registered, enabled, configured provider from local metadata, required capabilities, optional preferred provider, and optional preferred model.
- **Live Providers**: OpenAI, Groq, and OpenRouter use `httpx` against official OpenAI-compatible chat completion endpoints. LocalProvider supports a configurable local endpoint. MockProvider remains deterministic for tests.
- **Streaming**: Providers expose optional `execute_stream()` without breaking existing `execute()`.
- **Fallback**: `ProviderManager.execute_provider(...)` attempts deterministic compatible provider fallback on unavailable, timeout, rate-limit, missing-key, and server-error failures without retrying the same provider twice.
- **Rate Limits**: HTTP 429 and provider-local rate-limit markers place providers into an in-memory cooldown for a configurable duration.
- **Usage and Cost**: `UsageTracker` records prompt/completion/total tokens and timestamps. `CostEstimator` applies a local configurable pricing table and attaches estimates to `ProviderResponse`.
- **Context Management**: Provider/model metadata includes maximum context, maximum output, streaming/tool/vision/reasoning support, and execution validates context before provider calls.
- **Normalization**: Provider responses normalize to `ProviderResponse` fields: success, content, provider_id, model_id, finish_reason, usage, cost, latency_ms, and metadata.
- **Metrics**: `ProviderManager` exposes per-provider runtime metrics for requests, successes, failures, average latency, average tokens, estimated spend, and last success/failure.

All cloud providers expose a normalized execution interface through `ProviderManager`. Provider execution uses configured HTTP endpoints only when explicitly invoked. Function calling, embeddings, vision, audio, tool calling, external billing, and network-backed health monitoring remain outside this milestone.

Provider Health System v0.1 adds provider availability inspection without changing Runtime, Router, Workflow, CAP, GAMBIT, Memory, Tools, or API behavior. Available means a provider is both enabled and configured. Unavailable means disabled or missing required configuration. Reachability and rate limit state are always reported as `False` in v0.1.

No external provider connectivity is performed in Provider Health System v0.1.

Provider Selection Engine v0.1 adds deterministic provider selection through `ProviderManager.select_provider(...)`. It uses registered `ProviderInfo` metadata, local provider health status, required capabilities, and optional provider/model preferences. `ProviderInfo.supported_models` records metadata about model support without changing execution behavior.

Retries, Redis-backed state, external health monitoring, router scoring changes, workflow changes, CAP changes, GAMBIT changes, memory changes, and tool changes are intentionally outside Provider System v1.0.

### Configuration

Environment variables (prefix `SAMAKTHA_`):

- `OPENAI_ENABLED` (default: `true`)
- `GROQ_ENABLED` (default: `true`)
- `OPENROUTER_ENABLED` (default: `true`)
- `LOCAL_ENABLED` (default: `true`)
- `MOCK_ENABLED` (default: `true`)
- `REQUEST_TIMEOUT_SECONDS` (default: `30.0`)
- `MAX_RETRIES` (default: `0`)
- `COOLDOWN_SECONDS` (default: `60`)
- `STREAM_ENABLED` (default: `true`)
- `COST_ENABLED` (default: `true`)
- `USAGE_ENABLED` (default: `true`)
- `FALLBACK_ENABLED` (default: `true`)
- `DEFAULT_MODEL` (default: `mock-model`)
- `MAX_OUTPUT_TOKENS` (default: `1024`)
- `GROQ_API_KEY`, `GROQ_MODEL` (default: `llama-3.3-70b-versatile`)
- `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (default: `openai/gpt-oss-120b`), `OPENROUTER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
- Existing OpenAI, local, and default provider settings remain unchanged.

## Memory Status

Status: Implemented v0.2

Implemented modules:

- app/memory/base.py
- app/memory/models.py
- app/memory/store.py
- app/memory/manager.py
- app/memory/sqlite_store.py
- app/memory/repository.py
- app/memory/search.py
- app/memory/__init__.py
- app/core/contracts/memory.py

default public interface:

- Memory.read(key: str) -> Any | None
- Memory.write(key: str, value: Any) -> None
- Memory.delete(key: str) -> None
- Memory.search(query: str, category: Optional[str]) -> List[MemoryRecord]

### Description

MemorySystem v0.2 upgrades the cognitive memory layer from in-memory only to persistent SQLite-backed storage, while preserving strict contract-based boundaries.

- SQLiteStore: Manages the SQLite database connection, ensures existence and schema creation, and provides basic store/retrieve/delete for MemoryEntry objects.
- MemoryRepository: Encapsulates all direct database operations, provides model-to-row and row-to-model conversion, and offers save/get/delete/list_all/search abstractions.
- MemoryManager: Uses the repository, implements both Memory and MemoryReader interfaces, and exposes persistent read/write/delete/search. Accepts either a `MemoryRepository` (v0.2) or an `InMemoryStore` (v0.1 compatibility) at construction time. Category strings are normalized internally: privacy labels map to `PrivacyCategory`, and domain labels (`project`, `conversation`, `preference`, `workflow`) map to `MemoryDomainCategory` without changing callers.
- Search: Deterministic keyword/category search on keys and values, with category filtering.
- CAP compatibility: CAP and other systems use the abstract MemoryReader protocol, and remain unaware of the memory backend; all memory reads (including for context-building) transparently use persistent storage.

Limitations:
- Still single-process safe only — no cross-process locking.
- No vector, semantic, or AI memory; search is deterministic and substring/keyword based.
- Memory schema and contracts must be updated before adding new memory features or advanced privacy controls.

## Workflow Engine v0.1

Status: Implemented

Implemented modules:

- app/workflow/__init__.py
- app/workflow/engine.py
- app/workflow/models.py
- app/workflow/state.py

### Description

Workflow Engine v0.1 is a deterministic sequential executor that runs an existing ExecutionPlan step by step. It sits between GAMBIT and Runtime, resolves routing through the existing Router, and invokes the existing Runtime interface without changing provider or tool execution behavior.

- Sequential execution only.
- No autonomous loop.
- No retries.
- No scheduling.
- No background workers.
- No parallel execution.

### Failure Handling

- Execution stops immediately on the first failed step.
- Partial progress is preserved in the returned workflow state and outputs.
- The failed step index and error message are recorded for inspection.

### Execution State

- WorkflowState tracks workflow_id, status, current_step, total_steps, completed_steps, failed_step, started_at, finished_at, results, and errors.
- WorkflowResult returns the final success flag, the workflow state, collected outputs, and collected errors.

### Current Limitations

- Workflow Engine v0.1 does not replan, retry, or recover from failure.
- It depends on the existing Router and Runtime contracts and does not alter their behavior.
- It executes tasks sequentially and does not group or parallelize steps.
