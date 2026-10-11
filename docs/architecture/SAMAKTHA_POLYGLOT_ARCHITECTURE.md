# Samaktha — Polyglot Architecture & Technology Decision Study

**Scope:** Decision study only. No source code, tests, dependencies, or architecture were changed.
**Evidence base:** `SAMAKTHA_CURRENT_STATE_AUDIT.md`, `SAMAKTHA_VERIFICATION_BASELINE.md`, fresh repository inspection (this session), and targeted 2026 ecosystem research.
**Baseline under protection:** 3,151 passed / 0 failed / 0 errors / 0 skipped / 87 warnings, Python 3.14.5, pytest 9.1.1, exit 0.

> Method note (Rule 1): every recommendation starts from *responsibility → workload → constraints → bottleneck → ecosystem → security boundary → technology*, never from "language X is fast."

---

## 1. Executive Summary

Samaktha is a single-user, local-first, Windows-native agent with a deliberately strict control plane:

```
LLM proposes. GAMBIT plans. CAP authorizes. Runtime executes. Observer records. Memory persists.
```

The verified baseline (3,151 passing tests; measured bottlenecks; 14 permit predicates; quarantined bypass executors) shows that **the complexity of Samaktha sits in orchestration, policy, and LLM boundaries — not in compute hotspots.** The measured "hot" work (goal parsing at 2.9s for 20k chars, memory scans at ~150–195ms for 10k rows) is *algorithmic*, not language-limited, and is fixable with orders-of-magnitude headroom in Python.

The study therefore concludes:

| Decision | Verdict |
| --- | --- |
| Primary/keep language | **Python** — 61,401 LOC, the entire control plane, and the AI ecosystem all live here |
| New systems language | **Rust — one component only, Phase-Later:** a *Windows execution broker* (Job Objects, process-tree kill, restricted tokens, ACL/DACL) between the Runtime and the OS. It executes permits; it never decides them. |
| TypeScript/Node | **STUDY only.** Browser automation should be driven through the **Python** Playwright SDK first (avoids a second runtime in the bundle); Node is reserved for a future MCP-server/ecosystem role. |
| Native C/C++ | **Use existing native engines; author none.** (stdlib SQLite, PyMuPDF, Tesseract, llama.cpp/ONNX Runtime as external or wrapped engines.) |
| Plugins | **Wasm/Wasmtime — FUTURE (P3).** WASI 0.3 (June 2026) finally makes the component-model capability sandbox a credible Windows-local plugin boundary. Not justified today. |
| Database | **SQLite stays.** Move filtering into SQL, add FTS5 for token search, batch writes. No vector DB now (data too small; embedding latency floors retrieval). |
| IPC/contracts | **Typed JSON over stdio** for worker processes; MessagePack when payloads grow; named pipes only for a future persistent Rust broker; no gRPC. |
| First two engineering changes | **(1) Provider-identity fidelity (fail closed vs. mock fallback). (2) `goal_parser.py:186` regex rewrite + input bounds.** Both are Python fixes, both before any migration. |

**Headline finding:** nothing in Samaktha justifies a rewrite. One additive, contract-gated native component (Rust Windows execution broker) can be justified over time **for reliability and security-engineering value** (process-tree supervision, restricted tokens), not for raw speed. The two verified hotspots are regex/query-SQL problems with Python-side fixes that outperform any "rewrite in Rust" cost/benefit.

---

## 2. Current Architecture Baseline

### 2.1 Verified runtime flow

Source-confirmed in the Verification Baseline (Phases 2–7):

```
TUI / HTTP backend
   ↓
ExecutionCoordinator
   ↓
Orchestrator ── GAMBIT (plans) ── CAP (authorizes, signed permit)
   ↓
Runtime (governed surface)
   ├── ProviderExecutor   (engine.py:91,290,392 enforce_cap_permit)
   └── ToolExecutor       (tool-layer defense-in-depth)
   ↓
Providers / Tools
   ↓
Memory / persistence (SQLite) / external systems
```

- **CAP is the sole permit issuer** (`app/core/orchestrator/engine.py:543`); 14 permit predicates verified in `app/runtime/governance.py` (integrity, validity/expiry, principal/subject, session, workspace, action, operation, permissions, constraints, routing fidelity, approval state, mutation no-replay).
- **One governed execution surface.** The `RuntimeExecutionPool` runner hook is only ever wired to the gated `self.run` (`engine.py:549-556`); `app/core/app.py:1724` assigns the governed provider executor. `ToolChainExecutor`, `MultimodalExecutor`, `StreamingExecutor` are **quarantined fixtures** — zero imports in `app/` (re-verified this session).
- **AgentLoop v1** is single-step (`max_steps=1`, wired `app/core/orchestrator/engine.py:233-274`). CAP's banked-permit / no-replay guard (`engine.py:402-425`) is the mutation-replay defense.

### 2.2 Component inventory (re-established this session)

Repository state was re-inspected. Correcting the assumed paths: **`app/document/` does not exist** — document/OCR code lives in **`app/fileparsers/`** (`pdf_parsers.py`, `ocr_parser.py`, `ocr_worker.py`, `basic_office.py`, `factory.py`, `writer.py`). `app/governance/` exists (policy-adjacent modules) and `app/security/` exists (small). There is **no MCP code and no browser-automation code** (only keyword lists in classifiers/personality). Sizes in Python LOC:

| Component | Current path | Language | Current role | Production path? | ~Size (LOC) | Major dependencies |
| --- | --- | :-: | --- | :-: | --: | --- |
| App composition root | `app/core/app.py`, `app/agent/`, `app/developer/` | Python | wiring, session entry | YES | core 10,675 (whole dir); agent 523 | textual, fastapi |
| ExecutionCoordinator | `app/core/execution_coordinator.py` | Python | dispatch of user goals to orchestrator | YES | in core | — |
| Orchestrator / AgentLoop / context | `app/core/orchestrator/` (5 f), `app/core/agent_loop.py`, `app/core/context_builder.py` | Python | plan→act loop, context assembly | YES | 1,818 + agent_loop | pydantic |
| CAP | `app/core/cap/` (7 f), `app/core/contracts/` | Python | permit issuing, policy docs, approval | YES | 629 + contracts | pydantic |
| GAMBIT | `app/core/gambit/` (12 f) | Python | goal parsing, planning, decomposition | YES | 2,950 | regex, pydantic |
| Runtime | `app/runtime/` (24 f) | Python | governed execution surface, executor pool | YES | 3,628 | pydantic |
| Runtime parallel scheduler | `app/runtime_parallel/` (10 f) | Python | parallel tool scheduling | YES (used) | 422 | — |
| Providers | `app/providers/` (17 f) | Python | LLM + local voice/OCR provider abstraction | YES | 1,653 | openai/http; **groq & easyocr MISSING** |
| Router | `app/router/` (9 f) | Python | model/provider selection | YES | 604 | pydantic |
| Tools | `app/tools/` (39 f) | Python | filesystem, shell, network, windows, security | YES | 5,661 | httpx, socket |
| Memory | `app/memory/` (39 f) | Python | semantics, repository, manager | YES | 6,445 | stdlib sqlite3 |
| DB layer | `app/db/` (3 f) | Python | SQLite config/connections | YES | 227 | stdlib sqlite3 (**sqlalchemy MISSING**) |
| Security | `app/security/` (4 f) | Python | credential/key material | YES | 237 | cryptography |
| Governance | `app/governance/` (11 f) | Python | policy documents, enablement | YES | 1,273 | pydantic |
| Workflow | `app/workflow/` (6 f) | Python | workflow state machine | YES | 695 | pydantic |
| Document/OCR (≠ `app/document`) | `app/fileparsers/` (12 f) | Python | PDF, office, OCR workers | YES | 1,465 | pymupdf, tesseract subprocess, easyocr(opt./absent) |
| TUI | `app/tui/` (27 f) | Python | Textual front end | YES | 3,213 | textual |
| HTTP backend | `app/api/` (7 f) | Python | FastAPI surface | YES | 822 | fastapi, uvicorn |
| Windows layer | `app/windows/` (8 f) | Python (ctypes) | clipboard, files, window_state | YES | 359 | ctypes |
| Voice | `app/voice/` (17 f) | Python | STT/TTS via piper subprocess | YES | 2,091 | piper (external), audio |
| Internet fetcher | `app/internet/` (13 f) | Python | web fetch/tools w/ allow_localhost guard | YES | 2,504 | httpx, socket |
| Plugins | `app/plugins/` (18 f) | Python | registry, SDK scaffold, validation, isolation | **scaffold — no code-exec sandbox** | 2,821 | semver, pydantic |
| Communication | `app/communication/` (19 f) | Python | channels/notifications | PARTIAL | 1,757 | — |
| Evidence/audit | `app/evidence/` (5 f) | Python | evidence journaling | PARTIAL | 2,226 | — |
| Config/Setup | `app/config/`, `app/setup/` | Python | settings, wizard, validators | YES | 576 + 1,186 | pydantic |
| Models/Personality/Conversation | `app/models/`, `app/personality/`, `app/conversation/` | Python | schemas, persona, chat history | YES | 93 + 4,232 + 937 | pydantic |
| Shell glue | `app/shell/` (2 f) | Python | shell helpers | YES | 593 | — |

Total `app/`: ~61,401 Python LOC. All production code paths are Python; external native binaries are invoked as subprocesses (`tesseract`, `piper`, `where.exe`, taskkill) — the POSIX-process-broker shape already exists.

---

## 3. Workload Classification

Classified from actual code paths and the baseline:

| Component | Workload class(es) |
| --- | --- |
| GAMBIT goal parser | `CPU_BOUND` (pathological regex), otherwise `CPU-light`; `LLM_LATENCY_BOUND` downstream |
| GAMBIT planner / decomposition | `LLM_LATENCY_BOUND`, `AI_ECOSYSTEM`, CPU-light |
| CAP generation + verification | `SECURITY_CRITICAL`, CPU-light; **must stay in-process, single authority** |
| AgentLoop / ExecutionCoordinator | `LLM_LATENCY_BOUND`, `CONCURRENCY_BOUND` (waits on model calls) |
| Runtime engine / pool | `CONCURRENCY_BOUND`, `SECURITY_CRITICAL` (governed surface) |
| Runtime parallel scheduler | `CONCURRENCY_BOUND`, `CPU_BOUND` (fan-out of tool calls) |
| Provider adapters / Router | `NETWORK_BOUND`, `LLM_LATENCY_BOUND`, `AI_ECOSYSTEM` |
| Memory repository + search | `DATABASE_BOUND`, `MEMORY_BOUND` (full-table scan + Python filter today) |
| SQLite layer | `DATABASE_BOUND`, `IO_BOUND` (connect-per-op / commit-per-entry today) |
| Artifact state (memory) | `DATABASE_BOUND` |
| Document parser (PDF/office) | `CPU_BOUND` (PyMuPDF), `IO_BOUND` |
| OCR | `CPU_BOUND` (tesseract subprocess; easyocr absent), `MEMORY_BOUND` if torch-backed |
| Filesystem executor | `IO_BOUND`, `WINDOWS_NATIVE`, `SECURITY_CRITICAL` |
| Shell executor | `IO_BOUND`, `WINDOWS_NATIVE`, `SECURITY_CRITICAL`, subprocess-heavy |
| Network executor / internet fetcher | `NETWORK_BOUND`, `SECURITY_CRITICAL` (SSRF guards) |
| Windows layer (clipboard/files/state) | `WINDOWS_NATIVE`, `IO_BOUND` (ctypes surface today) |
| Browser automation | **absent today**; when added: `BROWSER_ECOSYSTEM`, `NETWORK_BOUND`, `IO_BOUND` |
| MCP adapter | **absent today**; when added: `PLUGIN_BOUND`, `IO_BOUND`, `SECURITY_CRITICAL` boundary |
| TUI | `IO_BOUND`/event loop, `BROWSER_ECOSYSTEM`-na |
| HTTP backend | `NETWORK_BOUND`, `CONCURRENCY_BOUND` |
| Voice (TTS/STT) | `IO_BOUND`, `CPU_BOUND` (piper subprocess) |
| Packaging | `PACKAGING_BOUND` |
| Plugins | `PLUGIN_BOUND`, `SECURITY_CRITICAL` (future sandbox) |

**Implication:** the only `CPU_BOUND` hotspots are algorithmic (goal regex, memory scan) or already subprocess-isolated (OCR/TTS). There is no throughput-critical compute loop inside the Python runtime that would be transformed by a faster systems language.

---

## 4. Performance Findings (verified, measured)

All figures are from the Verification Baseline (Phases 4–6), re-measured or source-confirmed this session.

### P0 — Goal parser (quadratic regex)
- Site: `app/core/gambit/goal_parser.py:186` — `re.search(r"([a-zA-Z]:[\\/][^\s'\"]+|/?[^\s'\"]+\.[a-zA-Z0-9]+)", request)`, unanchored.
- Measurements: 2,000 chars → 43.5 ms; 20,000 chars → 2,877 ms; 35,000 chars → 5,742 ms. ~420 ms per search on an 8K dotless input. No length guard exists before this call (the `[:240]`/`[:8]` caps at lines 933/940 are downstream in a different method).

### P1 — Memory search (full-table scan + Python filtering)
- Measurements: 100 rows → ~2.6 ms; 1,000 rows → ~11.9 ms; 10,000 rows → ~145–195 ms. Growth is superlinear at the tail (10× rows ≈ 13–16× time) — consistent with Python-side post-filtering of a full SQLite scan.

### P1 — Memory insertion (connect-per-operation / commit-per-entry)
- ~10 ms per inserted entry; seeding 100,000 rows exceeded 120 s. `delete_memory_by_type` silently caps behavior at the 1,000 most-recent items.

### P2 — Blocking work in async paths
- SQLite calls, PyMuPDF parsing, and OCR/document work execute synchronously inside asyncio paths.

### Event-loop baseline (Phase 5)
- Required for context: baseline event-loop timings (e.g., ~0.15–0.2 ms/drain) recorded in the baseline report; no event-loop starvation hotspot beyond the blocking-call finding.

### Other
- `app/core/gambit/goal_parser.py:933-940` truncates small fields but not the parser's primary input; all parser regexes are module-level compiled (no per-call `re.compile`).

---

## 5. Security Findings Relevant to Migration

### HIGH — Provider fallback fidelity (G1 binding)
`requires_local_model=True` (a sensitive, local-only request) empirically **fell back to the mock provider** and returned a fabricated success (`provider_id: 'mock'`, `"Mock provider response"`). Source: router excludes mock, but the provider manager's fallback path synthesizes mock; governance never sees the provider that actually executed. The permit / actual-executor identity can diverge. This is a *control-plane* defect — **no language change fixes it**, and it must be closed before any polyglot component is introduced (native code cannot be allowed to carry an alternate authorization path).

### Defenses present (verified, to preserve)
- CAP is the sole permit issuer; 14 predicates verified; `enforce_cap_permit` at `engine.py:91,290,392`.
- Mutation/replay guard `engine.py:402-425`.
- Quarantined bypass executors (`ToolChainExecutor`, `MultimodalExecutor`, `StreamingExecutor`) — zero imports in `app/`.
- Network/SSRF guards (`allow_localhost: bool = False` defaults; IP resolve + loopback check in `app/internet/fetcher.py`, `app/tools/security.py`).

### Migration-relevant principle
Any new worker (Rust broker, Node/browser worker, Wasm plugin, MCP server) is admissible **only** as an *executor of a constitutional permit*, and must report back the actual identity of what executed so the Observer can reconcile it against the permit (same pattern as the mutation-replay guard). No technology in this study may become an alternate authorization mechanism (Rule 2).

---

## 6. Repository / Framework Research

Review performed against the 2026 state of each project (source-of-truth inspection + current documentation). The purpose is **architecture comparison**, not adoption.

| Repository | Language | Relevant Samaktha subsystem | Concept worth adopting | Why |
| --- | --- | --- | --- | --- |
| `openai/codex` (codex-rs) | Rust (rewritten from TS in ~1yr) | Runtime + sandboxing | **Harness/executor separation** (control plane vs compute plane); sandbox *policy mapped onto OS primitives* (Seatbelt/macOS, Landlock+bubblewrap/Linux, **restricted tokens + DACL/Windows**) out of a single policy enum | Direct validation of Samaktha's CAP→Runtime split and of the "single policy, native enforcement" idea below for Windows |
| `xai-org/grok-build` | Rust | AgentLoop, Observer, approval | **Plan→approve→execute loop**; ACP (JSON-RPC) streaming protocol for tool_calls/thought/plan events; subagents with independent context; **CLI+SKILLS vs MCP token economics** | Samaktha's AgentLoop v2 should emit streamed, typed lifecycle events (Observer contract), and skills-style commanding is cheaper in tokens than MCP schema-dumps |
| `block/goose` (community) | Rust harness + SDKs | Runtime, plugin boundary | Extensible tool/extension model with explicit permission prompts | Confirms permission-prompts-as-first-class fit CAP's approval model |
| `OpenHands/software-agent-sdk` | Python/TS | AgentLoop | Agent SDK as a library API, not a CLI | Concept compatible with Samaktha's `agent_loop.py`; none needed now |
| `langchain-ai/langgraph` | Python | Checkpointing/recovery | **Explicit graph state + serializable checkpoints + resume** | Samaktha has checkpoint/recovery gaps; adopt the *state-serialization concept*, not the framework |
| `pydantic/pydantic-ai` | Python | Tools/Observation | Typed tool results + DI (dependency-injected tool context) | Samaktha already uses pydantic; typed tool results are exactly the Observation contract |
| `0xPlaygrounds/rig` | Rust | AgentLoop (future), contracts | **Sans-IO, serializable `AgentRun` state machine** + hook stack + provider-agnostic traits | The strongest model for a *deterministic, replayable* AgentLoop v2 that keeps CAP on the critical path |
| `modelcontextprotocol/*` | Python/TS/Rust(Unofficial) | tool adapter / plugin boundary | MCP v2 (spec 2026-07-28) as an *external-tools ecosystem protocol with schema-validated tools*; stdio transport standard | Samaktha should talk to MCP servers as CAP-wrapped tools; never let MCP become its policy layer |
| `microsoft/playwright` (+ `playwright-mcp`) | TS (+ official Python SDK) | Browser automation | Snapshot/accessibility-tree automation; **MCP server vs CLI+skills token trade (≈114k vs ≈27k tokens/task, directional)**; Python SDK is first-party | Supports: dev first browser driver in **Python Playwright**; Node/TS only if MCP-browser ecosystem access becomes the requirement |
| `tauri-apps/tauri` | Rust core, web UI | future desktop UI | Tiny single-binary desktop shell using webview for UI | Reference for a *future* native shell around Samaktha; not needed while Textual TUI + FastAPI covers the UI |
| `bytecodealliance/wasmtime` | Rust | plugin sandbox | **WASI 0.3 (June 2026): async in the Component Model ABI; capability-based fs/CLI/sockets with cap-std** | Validation that Wasm is a *future* (not now) capability-plugins boundary |
| `ggerganov/llama.cpp` | C/C++ | local inference | GGML/GGUF quantized execution; `llama-server` binary; no mandatory GPU libs | Best external-engine default for CPU / iGPU Windows local inference |
| `microsoft/onnxruntime` (+ GenAI) | C/C++ | local inference, embeddings | Cross-backend (CPU/DirectML/CUDA) execution with a Python API | The "wrap existing native, don't author" exemplar for embedders |
| `lancedb/lancedb` | Rust | memory/vector retrieval | Columnar + vector store with embedding-aware search | Evidence that a Rust storage layer is *available* if ever justified; **not justified at current scale** |
| `qdrant/qdrant` | Rust | vector retrieval | Local + gRPC vector search | Same: premature at this dataset size; revisit at ≫1M rows |
| `tokio-rs/tokio` | Rust | (future Rust broker internals) | Async runtime + process/Job-Object supervision primitives | Dependency of a future broker; irrelevant now |
| `astral-sh/uv` | Rust | build/dev toolchain | Universal Python tooling (resolve→run→build) | **Adopt now as the dev-tool toolchain backbone** |
| `astral-sh/ruff` | Rust | lint/format | Lin`t + format, PyPI-wide adoption speed | **Adopt now** |
| `nextest-rs/nextest` | Rust | test runner | Parallel test executor | **Only when Rust components exist** |
| `mozilla/sccache` | Rust | build cache | Shared compilation cache (C/C++/Rust) | **Only when native compilation enters the build** |

### Additional relevant to Samaktha
- **OS-level sandbox mapping (codex `sandboxing/manager.rs`)** — a *single policy enum → per-OS enforcement primitive* (Windows: restricted tokens + DACLs) is exactly the model a future "Rust execution broker" should implement on Windows.
- **MCP v2 (2026-07-28)** is a major protocol rework (era negotiation, no forced `initialize`, `server/discover`). Python and TS SDKs are both current and stable-first-line; the Python SDK is MIT, requires 3.10+, and is single-package (`mcp>=2.2.0`, ~4.4 MB sdist) — cheap to adopt.

---

## 7. Python Decision

**Primary language. KEEP.**

Evidence and reasoning (Samaktha-specific):
- **Where the complexity lives.** The 61.4k LOC is orchestration + policy + LLM boundaries + persistence — the domains Python's ecosystem and developer velocity serve best. AI ecosystem score is unmatched (all provider SDKs, LangChain/Pydantic-AI/GAMBIT-style planning all Python-first).
- **Verified bottlenecks are not Python's fault.** Goal parser (regex algorithm), memory scan (SQL + Python post-filter), insert (SQLite usage pattern). Each has a Python-side fix (Sections 12, 24) that removes 99% of the measured cost. A Rust port of a regex or a SQLite call pattern would add nothing the fix doesn't.
- **Control-plane invariants** (CAP, permit, replay guard) are correctness-critical and are **cheaper to keep correct in a garbage-collected, duck-typed, test-covered codebase** with 3,151 passing tests already encoding the semantics. Rewriting the authorization boundary in Rust would *move* the risk, not remove it.
- **Startup/packaging** are tolerable at this scale (91,905 exe `samaktha.exe`; launch verified ~0.5s-class). Python 3.14.5 is the interpreter; `requires-python >= 3.12` (3.12 compat NOT VERIFIED — a gap to close by CI, see §16).
- **Concurrency** is adequate if placement is fixed (§12): asyncio for I/O, thread/process pools for CPU/SQLite-blocking work. No measured event-loop bottleneck beyond the blocking-call finding.

**Decision:** Python remains the language of the control plane, orchestration, all tools, TUI/HTTP, memory semantics. Cost of reversing: effectively none (it stays). Risk: none.

---

## 8. Rust Decision

**One component, Phase-Later: a Windows execution broker. Everything else: KEEP PYTHON / STUDY.**

### The measured facts
- No benchmark evidence shows any Python hotspot that Rust would meaningfully change (the two P0/P1 hotspots are regex/query fixes). Memory scan at 10k rows (~150–195 ms) is a *search-algorithm* cost: SQL-side fixes get it to single-digit ms in Python with zero native code.
- Therefore Rust is **not** justified by performance. It is justified, **later**, by two *systems-security* arguments specific to Windows:
  1. **Process-tree supervision** — reliable tree-kill and lifecycle that Python only fakes with `taskkill /T` (`app/tools/shell.py:245`). Windows **Job Objects** (kill-on-close, memory/CPU limits) have no robust Python binding in the bundle today; a small Rust shim gets Job Objects, restricted tokens, and robust `CreateProcess` semantics without dragging legacy wrapper dependencies in.
  2. **The "execution broker" shape** (below) matches codex's validated single-policy-→-OS-primitive model and keeps CAP authoritative.

### Proposed conceptual relationship (evaluate; do not build now)
```
CAP (Python) ──Signature──▶ ExecutionPermit ──▶ Runtime (Python) ──permits√──▶ Rust execution broker ──▶ Windows
```
The broker **executes policy-approved actions and enforces OS-level limits; it does not decide whether an action is allowed.** It speaks a typed JSON contract (§19), returns structured `ExecutionResult`, and the Observer reconciles reported identity against the permit. This mirrors the codex `exec-server` executor pattern and the current `app/shell/`/`app/tools/windows.py` subprocess boundary.

### Explicit Rust decision matrix (candidates evaluated)

| Candidate | Why Python insufficient today | Benefit | Cost / risk | Benchmark? | Now? | Class |
| --- | --- | --- | --- | --- | :-: | :-: |
| Goal parser | Not insufficient — regex rewrite fixes it | ~3ms at any input | 0 (Python) | YES (P0) | **No** | KEEP PYTHON |
| Memory storage/search | Not insufficient — SQL/FTS fixes it | — | 0 (Python) | YES (P1) | **No** | KEEP PYTHON |
| SQLite layer | Not insufficient — SQLite is C | — | — | YES (P1) | **No** | KEEP PYTHON |
| Windows execution broker | ctypes surface is thin; Job Objects/restricted-token/robust-tree-kill lack first-party API; taskkill-only today | Reliable tree-kill, resource limits, restricted tokens, clean ACL/DACL | +1 native binary in bundle (~5–20 MB static); cross-language contract needed first; security review | **No perf benchmark — justified on reliability/security, not speed** | **Later** | **MOVE LATER (P1)** |
| Wasmtime plugin host | — | — | — | — | **Later/Future** | STUDY/FUTURE |

**Decision:** MOVE LATER (priority P1) only for the Windows execution broker, gated on the Stage-3 cross-language contract and the Stage-1/2 security fixes. Everything else stays Python. Cross-language complexity is low (one stdio subprocess boundary). Migration risk: low — it is additive (new binary behind Runtime), never a modification of CAP/permit semantics.

---

## 9. TypeScript/Node Decision

**STUDY only. No Node runtime in the bundle now.**

Where Node/TS *could* matter for Samaktha: browser automation (Playwright is a TS-native project) and the MCP ecosystem (whose reference SDK is TS, though the Python SDK is equal-first-line).

Why **not now**:
- **Packaging cost (evidence).** The current bundle is a PyInstaller ONEDIR (`samaktha.exe`) measured to **92,356,783 bytes** with no installer (Inno Setup missing). Injecting a Node runtime + `@playwright/*` + browsers is ~60–150+ MB of additional payload and a second runtime to patch — unacceptable without a demonstrated user need. Browser automation **does not currently exist** in the codebase (zero code).
- **The Python Playwright SDK is first-party and full-featured** (navigation, snapshots, multi-browser, tracing). A Python driver keeps a single runtime, single signing story, and the same subprocess boundary Samaktha already uses for tesseract/piper.

If and when Samaktha adds browser automation, the **driver is Python Playwright**; the *contract* below is language-agnostic and CAP-gated:

```
GAMBIT ──▶ BrowserAction ──▶ CAP (permit) ──▶ Worker (Python Playwright) ──▶ Browser
                                          └──▶ ExecutionResult ──▶ Observation
```

When Node/TS *would* be the right call (Phase-Later/STUDY, P2):
- Samaktha exposing **Samaktha tools to other agent hosts** as an MCP *server* where the ecosystem strongly prefers TS hosts — or Samaktha consuming `browser-use`-class agents whose best packaging is npx. Both are optional extensions, not core.
- Per the Playwright team's own analysis, MCP-style tool schemas cost ~4× the tokens of CLI+skills per browser task (≈114k vs ≈27k, directional) — so Samaktha should prefer a **CLI/skills-style action set** for its own browser tool, and reserve MCP for interop.

**Decision:** no Node now. Browser worker = STUDY (P2) behind the CAP contract using the Python driver. Node = STUDY if MCP-server/browser-use ecosystem access becomes a product requirement. Adding Node as a general "web-facing" runtime is **not justified** for the TUI/HTTP/desktop surface Samaktha has.

---

## 10. C/C++ / Native Decision

**Use existing native libraries and binary engines; author essentially nothing.**

| Workload | Recommendation | Form |
| --- | --- | --- |
| PDF/document parse | PyMuPDF (existing C++ binding) | **wrap existing native** — keep |
| OCR | Tesseract subprocess (`app/fileparsers/ocr_parser.py`) today; EasyOCR absent (torch, heavy) | **run external binary** — keep; EasyOCR only if a product need for heavy OCR emerges, and then **not bundled** |
| SQLite persistence | stdlib SQLite (C) | keep |
| Local inference (CPU/iGPU) | llama.cpp (`llama-server` as an external provider process) or ONNX Runtime (GenAI) via its Python API | **run external engine / wrap existing native** |
| Embeddings | ONNX Runtime or a small GGUF embedder via llama.cpp — *only if* vector retrieval becomes justified | **wrap existing native**; do not author |
| Windows Job Objects / restricted tokens | (Phase-Later) Rust broker using `windows-rs` | **author a thin Rust shim** — the single authored native component (§8) |
| GPU matrix ops | CUDA/DirectML — via llama.cpp/ONNX backends only, **never bundled** | external |

Rule: prefer mature native implementations ("write ourselves" only for the ~1k-line Rust broker). Native libraries that are already in the process (SQLite, PyMuPDF) receive no new authored code. GPU libraries (CUDA/cuDNN/DirectML) are distribution-hostile (hundreds of MB) and are deliberately kept **out of the bundle** by using the external-engine model (§21).

---

## 11. WebAssembly Decision

**Plugin sandbox boundary — FUTURE (P3). Not justified now.**

- Current plugin surface (`app/plugins/`) is a **Python SDK scaffold** (registry, semver, validation, tool_adapter, isolation) with **no code-execution sandbox**. Plugins today are in-process Python — a capability concern, not a solved isolation story.
- Ecosystem maturity 2026 (evidence): **WASI 0.3 ratified 2026-06-11** with native async in the Component Model ABI; Wasmtime 46 ships WASI 0.3 + component-model-async by default; cap-std-based capability fs/cli/sockets exist. This is a step-change from the "sandwich problem" WASI 0.2 era: composable async + capability grants now work.
- **Samaktha applicability:** a future *plugin* = Wasm component with **capabilities explicitly granted by a CAP-issued permit envelope** (filesystem roots, sockets, clock, random) — matching the `Plugin → Wasm → capability grant → Samaktha` model. This keeps CAP as the grant source and Wasm as the enforcement tech.
- Why not now: (a) no plugin-execution requirement is evidenced (SDK is scaffold-grade); (b) adding a Wasmtime host adds 30–40 MB to a 92 MB bundle and a second native surface to audit; (c) Python plugins remain the fast path for trusted local work.

| Classification | Justification |
| --- | --- |
| NOW | No |
| LATER | Unlikely — no in-protocol need until plugin execution is a requirement |
| FUTURE | **Yes** — Wasm plugin capability sandbox, behind CAP grants (§23 Stage 9) |
| NOT JUSTIFIED | wasmCloud (distributed, over-scoped), WASI as a *replacement* for the Python runtime |

---

## 12. Storage / Database Decision

**SQLite stays. Move filtering into SQL, batch writes, add FTS5 for token search. No vector DB. No Rust storage layer.**

Evaluated candidates against measured data (`~2.6ms@100 rows → ~12ms@1k → ~145–195ms@10k`; `~10ms/insert`; 100k-seed >120s):

| Candidate | Verdict | Evidence-based reason |
| --- | :-: | --- |
| SQLite SQL indexing + SQL-side filtering | **OPTIMIZE (does now)** | The scan+Python-post-filter pattern is the measured cost. Indexed WHERE/`LIKE` (with `COLLATE NOCASE`) pushes filtering to C. At 10k rows this is the difference between ~150ms and ~1–5ms. |
| SQLite FTS5 | **ADD (P1)** | Samaktha memory search is mostly *token/substring* search; FTS5 with trigram or token tables gives indexed substring matching with negligible FTS cost at this size. Faster than a naive LIKE for token queries, and free of new dependencies. |
| Bulk transactions / connection reuse | **OPTIMIZE (P1)** | Measured ~10ms/insert is connect-per-operation + commit-per-entry. A single writer connection (WAL) + batched transactions removes the constant factor that made the 100k seed >120s. |
| Async DB access (aiosqlite / dedicated writer thread) | **OPTIMIZE (P2)** | Fixes the blocking-in-asyncio finding without C or a new engine. Single-writer + thread-pool readers is sufficient for 10k–100k rows. |
| APSW | POSSIBLE | Lower-level, robust SQLite binding; **unnecessary** while stdlib `sqlite3` is adequate — only if edge-case SQLite control is needed later. |
| Vector retrieval (LanceDB, Qdrant) | **NOT NOW** | Dataset is ≤100k rows; retrieval latency floor is *embedding generation* (network or CPU model call = tens–hundreds of ms), which swamps the ~200ms scan. Vector search adds distribution weight (Rust binaries) and dependency complexity for zero user-perceived gain at this scale. Revisit at ≫1M rows or if semantic-search becomes a product feature. |
| DuckDB | NOT JUSTIFIED | Analytical OLAP engine; not the workload (point reads/writes, small dataset). |
| Rust storage layer | **NOT JUSTIFIED** | The table shows the cost is in *query/shape*, not engine. SQLite is already C; replacing it trades verified behavior for risk. No benchmark supports it. |

**Decision:** persist SQLite; move search into SQL; FTS5 for token search; batched single-writer paradigm; aiosqlite/thread placement. Vector retrieval premature. This is the P1 memory fix and belongs in Stage 2 (§23), Python-only.

---

## 13. Browser / MCP Decision

### Browser
- **Driver now:** Python Playwright SDK (first-party) behind the CAP contract in §9 — a Python *worker process*, same subprocess shape as today's tesseract/piper calls, same Runtime gating.
- **Token economics:** prefer **CLI/skills-style** compact action sets for Samaktha's own browser tool (directional evidence ≈ 4× token saving vs MCP schema/snapshot loads). Reserve MCP-style persistent-session automation for interop.
- **When Node?** Only when Samaktha must interoperate with Node-packaged browser/MCP ecosystems (npx-hosted servers such as `@playwright/mcp`) *as a client* — STUDY (P2), node runtime kept external (not bundled) if possible.

### MCP
- **Placement:** MCP is a **tool adapter / external-capability ecosystem protocol**, never governance.
- **Boundary (adopt design now, integrate later):**
```
MCP tool ──▶ Adapter ──▶ Samaktha ActionContract ──▶ CAP (permit) ──▶ Executor ──▶ Observation (reconcile)
```
- **Direction:** Samaktha as an **MCP client** (external servers become CAP-wrapped tools) is the primary, low-risk direction — same exhaustive tool schema validation, stdio transport standard, Python SDK stable-line (`mcp>=2.2.0`, 2026-07-28 spec, era negotiation). Samaktha as an **MCP server** (expose its governed tools to other AI hosts) is a *later* product decision and must route through the same permit path — MCP's own auth/approval notions are transport-level, not policy.
- **Do not adopt:** MCP as a policy/approval substitute; MCP sampling/elicitation as a bypass of CAP; a server adopted without wrapping its every tool call in an ActionContract.

---

## 14. Local Inference Decision

Router + provider abstraction already exists. Guidance per evidence:

| Runtime | Verdict for Samaktha | Windows/CPU/iGPU notes |
| --- | :-: | --- |
| llama.cpp (`llama-server`) | **Provider — external process (preferred)** | GGUF quantization; runs CPU and iGPU (Vulkan/DirectML flavors) with no mandatory CUDA. Treat as a provider Samaktha starts/stops like any other model provider. |
| ONNX Runtime / GenAI | **Provider/wrapped native — embedder if needed** | Cross-backend (CPU/DirectML). Use for a *small embedding model* if vector retrieval is later justified; Python API, no bundle bloat if the runtime stays external-ish (onnxruntime DLL can be bundled if ever required — it is self-contained). |
| llama-cpp-python | POSSIBLE (embedded option) | Convenient single-wheel embedding of GGUF in-process; heavier bundle; prefer external server unless latency demands in-process. |
| Ollama | Provider — external (OK) | Convenient multi-model manager; still an external daemon, same boundary as llama-server. |
| vLLM | NOT JUSTIFIED (local) | Multi-GPU service-grade; wrong shape for single-user Windows. |
| MLX | NOT APPLICABLE | Apple-Silicon only. |
| TensorRT | NOT JUSTIFIED | NVIDIA-only server-grade; iGPU-focused DirectML path preferred. |

**Principle:** the Router selects local/native/remote through the existing provider abstraction regardless of engine. Do **not embed** a model engine now; do not bundle GPU libraries (§21). A "native inference" optimization stage (§23 Stage 10) should only *add* engines behind the provider interface; the interface itself is already the abstraction.

---

## 15. Cross-Language IPC / Contract Decision

**Default: typed JSON over stdio for worker processes; MessagePack when payloads grow; named pipes only for a persistent Rust broker later; no gRPC.**

Because Samaktha is Windows-native, local-first, single-user:

| Boundary | Recommendation | Why (Samaktha-specific) |
| --- | :-: | --- |
| Python ↔ worker subprocess (tesseract, piper, future Python-Playwright browser worker) | JSON-RPC-style typed JSON over **stdio**, one request/response framing + stderr for logs | Already the pattern today (`create_subprocess_exec`); zero new dependencies; trivially auditable; fails loudly. Add a schema (JSON Schema or pydantic-generated both sides) so the *contract*, not an ad-hoc dict, is versioned. |
| Python ↔ Rust execution broker (Phase-Later) | **Named pipe** (Windows) or stdio for a short-lived broker | Windows-native, no TCP surface to defend, supports the Job-Object-per-grant model. MessagePack frames reduce size for binary-ish payloads (file ACL blobs) — optional and cheap. C ABI/PyO3 also viable but couples safety-critical code into the Python process (loses fault isolation) — prefer a separate process. |
| Python ↔ Node (if ever) | stdio JSON, same framing | Node workers are subprocesses like any other; they must not get a privileged boundary. |
| Python ↔ native inference (llama.cpp/ONNX) | HTTP/OpenAI-compatible (llama-server) or existing provider SDK | Providers already speak HTTP; do not invent IPC for engines that have a protocol. |
| Python ↔ Wasm (FUTURE) | Wasmtime host inside the Rust broker OR external `wasmtime`/`jco` process | Capability linking via WIT; joins the same permit→execute→reconcile path. |

**Explicitly avoid:** gRPC/Tonic (a distributed RPC is overkill and adds ~big codegen/tooling weight for one host), Unix sockets (Windows-native = named pipes), long-lived TCP listeners (unnecessary attack surface). C ABI / PyO3 / maturin: **STUDY** only if an embedded-in-process native module is ever justified (none is today).

---

## 16. Developer Toolchain / Build-Speed Decision

Goal: **faster to build and iterate**, specifically for a 61.4k-LOC Python codebase with a 518s full suite and a 92 MB PyInstaller artifact.

| Tool | Verdict | Samaktha benefit (evidence-based) |
| --- | :-: | --- |
| `uv` | **Adopt/keep as the toolchain backbone** | Locked deps, fast installs, `uv run`, script environments, no pip bootstrapping; replaces ad-hoc venv assembly (`.venv` today). |
| `Ruff` (lint+format) | **Adopt** | Single fast linter/formatter; if not already in CI, add as a pre-commit + CI gate. |
| `ty` (Astral, Mypy-compatible) | **Adopt** | Fast, correct type checking for the pydantic-heavy control plane; aligns with 3.14 typing. |
| `pytest-xdist` | **Adopt (investigate isolation first)** | 3,151 tests / 518 s currently sequential (`.basetemp` per-run). Distributed workers could cut wall-clock ~2–3×; must confirm the suite's DB-state isolation (memory fixtures) before enabling `-n auto`. |
| `pytest` + filtered fast feedback targets | Adopt | Keep the proven `-q --basetemp` flow; add a `FAST` marker/segment so dev loop bypasses the 518s full run. |
| `cargo-nextest` | **Later** | Only when Rust lands; replace `cargo test` for its per-test file separation. |
| `sccache` | **Later** | Only when native compilation (Rust broker) lands; shares compile artifact cache across CI/editors. |
| `cargo check`/incremental builds | Later | Keep Rust crate count tiny (1 binary crate) so incremental builds stay ~seconds. |
| pnpm / TS tooling | Not now | No Node in the bundle (Section 9); avoid second toolchain until Node is justified. |
| PyInstaller build caching | Adopt | The ONEDIR build is a slow tail of CI; cache the site-packages staging + use `--clean` sparingly; a `.spec`-driven reproducible build already exists. |

**Recommended toolchain (concrete):** `uv` + `Ruff` + `ty` + `pytest` (+`pytest-xdist` fenced behind suite-isolation validation) now; `cargo-nextest` + `sccache` only on arrival of the Rust broker. Inno Setup (`iscc`) to be added to close the installer gap (Stage 5/6 packaging), which also fixes the currently NOT-buildable installer.

---

## 17. Packaging / Distribution Decision

Current: PyInstaller ONEDIR (`dist\samaktha\samaktha.exe`, measured **92,356,783 bytes**, launches `samaktha 0.5.0`, exit 0) + `samaktha.iss` (Inno) **not buildable** (no `iscc`). Version 0.5.0 consistent across manifests; `samaktha-plugin` entry point advertised, not packaged.

Impact of introducing runtimes (evidence-driven):

| Addition | Δ bundle size (est.) | Δ signing/maintenance | Verdict |
| --- | --: | --- | :-: |
| Rust broker (static, 1 binary) | +5–20 MB | +1 PE to sign; static vs CRT | **Acceptable later** — the only polyglot addition that doesn't wreck distribution |
| Node.js runtime + Playwright + browsers | +60–150 MB | +1 runtime patch surface + browser payloads | **Not now** — choose Python driver (§9) |
| Wasmtime host | +30–40 MB | +1 native surface to audit | **Only at plugin FUTURE stage** |
| ONNX Runtime (if bundled) | +40–80 MB | +DLL set | Avoid by external-engine/`llama-server` model (§14) |
| GPU libs (CUDA/cuDNN/DirectML) | hundreds of MB | licensing + size | **Never bundled**; external engines |
| Third Python runtime | — | — | Reject — one interpreter |

**Decision:** keep ONEDIR + Inno as the distribution model; the bundle stays Python-only now; only a small static Rust broker is an acceptable future addition. GPU/model weights and external engines remain *outside* the bundle (installed, not shipped) — this is what keeps distribution cost of local inference near zero. Installing the Inno step closes the current build gap. Polyglot is deliberately bounded so packaging cost does not grow by a runtime × 3.

---

## 18. Component-by-Component Technology Matrix

Every cell answered: `YES` / `NO` / `POSSIBLE` / `STUDY ONLY`. Recommendations derive from the workload classification (§3) and measured findings (§4), not from generic performance claims.

| Samaktha component | Current impl | Keep Python | Rust | TS/Node | C/C++ | Wasm | External/native tool | Recommendation | Priority |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: | --- | :-: |
| CAP policy | Python | YES | NO | NO | NO | NO | NO | KEEP Python (single authority, in-process) | P0 |
| CAP approval | Python | YES | NO | NO | NO | NO | NO | KEEP Python | P0 |
| Permit generation / signing | Python | YES | NO | NO | NO | NO | NO | KEEP Python (cryptography) | P0 |
| Permit verification | Python | YES | POSSIBLE | NO | NO | POSSIBLE | NO | KEEP Python; handler pattern | P0 |
| GAMBIT goal parser | Python | YES | NO | NO | NO | NO | NO | KEEP Python + **regex rewrite & input bounds (first perf fix)** | P0 |
| GAMBIT planner / task decomposition | Python | YES | NO | NO | NO | NO | NO | KEEP Python (LLM-latency-bound, ecosystem) | P0 |
| AgentLoop (v1; v2 design) | Python | YES | NO | NO | NO | NO | NO | KEEP Python; v2 above Runtime, under CAP/GAMBIT | P0 |
| Observer | Python | YES | NO | NO | NO | NO | NO | KEEP Python; adopt streamed typed lifecycle events (grok ACP model) | P1 |
| ExecutionCoordinator | Python | YES | NO | NO | NO | NO | NO | KEEP Python | P0 |
| Runtime engine (governed surface) | Python | YES | NO | NO | NO | NO | NO | KEEP Python (must stay CAP-gated) | P0 |
| Runtime parallel scheduler | Python | YES | POSSIBLE | NO | NO | NO | NO | KEEP Python; process-pool placement for CPU tools | P1 |
| ProviderManager | Python | YES | NO | NO | NO | NO | NO | KEEP Python + **identity-fidelity fix (first security fix)** | P0 |
| Router | Python | YES | NO | NO | NO | NO | NO | KEEP Python (abstraction stays) | P0 |
| Provider adapters | Python | YES | NO | NO | NO | NO | STUDY ONLY | KEEP Python; add llama.cpp/ONNX as providers | P1 |
| ContextBuilder | Python | YES | NO | NO | NO | NO | NO | KEEP Python | P0 |
| Memory semantics | Python | YES | NO | NO | NO | NO | NO | KEEP Python (semantics stay) | P0 |
| Memory repository/search | Python | YES | POSSIBLE | NO | NO | NO | NO | OPTIMIZE: SQL-filter + FTS5 + batch writes (Python) | P1 |
| SQLite layer | Python (stdlib sqlite3) | YES | NO | NO | YES (already C) | NO | NO | KEEP SQLite; aiosqlite/thread placement | P1 |
| Artifact state | Python/SQLite | YES | NO | NO | NO | NO | NO | KEEP | P2 |
| Document parser (PDF/office) | Python/PyMuPDF | YES | NO | NO | YES (existing lib) | NO | NO | KEEP Python driver; native already inside via PyMuPDF; move off async loop | P2 |
| OCR | Python/tesseract | YES | NO | NO | NO | NO | YES (tesseract) | KEEP subprocess model; easyocr(optional, not bundled) in own process | P2 |
| Filesystem executor | Python | YES | POSSIBLE | NO | NO | NO | NO | KEEP Python now; broker candidate for ACL/restricted ops later | P1 |
| Shell executor | Python | YES | POSSIBLE | NO | NO | NO | NO | KEEP Python now; **broker's process-tree/Job-Object value later** | P1 |
| Network executor / web fetch | Python | YES | NO | NO | NO | NO | NO | KEEP Python (httpx/SSRF guards intact) | P1 |
| Windows integration (clipboard/state/files) | Python ctypes | YES | POSSIBLE | NO | NO | NO | NO | KEEP ctypes now; **move to Rust broker later (windows-rs)** | P2 |
| Browser automation | (absent) | YES | NO | STUDY ONLY | NO | NO | YES (Playwright driver) | **Add via Python Playwright worker behind CAP contract** | P2 |
| MCP adapter | (absent) | YES | NO | STUDY ONLY | NO | NO | YES (MCP servers) | **Add client adapter; MCP tool→ActionContract→CAP** | P2 |
| Event bus | Python | YES | NO | NO | NO | NO | NO | KEEP Python | P2 |
| Checkpoint/recovery | Python | YES | NO | NO | NO | NO | NO | KEEP Python; adopt serializable-state concept (langgraph/rig) | P1 |
| Logging / diagnostics | Python | YES | NO | NO | NO | NO | NO | KEEP Python (diagnostics.py surface) | P2 |
| TUI | Python (textual) | YES | NO | NO (future-desktop STUDY ONLY) | NO | NO | NO | KEEP Python Textual; Tauri-style native shell only if a desktop UI becomes a goal | P2 |
| HTTP backend | Python (FastAPI/uvicorn) | YES | NO | NO | NO | NO | NO | KEEP Python | P1 |
| Packaging (PyInstaller + Inno) | Python | YES | POSSIBLE (static broker) | NO | NO | NO | NO | KEEP ONEDIR + Inno; add `iscc`; only Rust broker enters bundle later | P1 |
| Installer | (missing) | YES | NO | NO | NO | NO | NO | ADD Inno Setup build (closes verified gap) | P2 |
| Plugin system | Python scaffold | YES | NO | NO | NO | STUDY ONLY | NO | KEEP SDK scaffold; sandbox = **Wasm FUTURE** | P3 |
| Local inference | providers | YES (interface) | NO | NO | YES (existing engines) | NO | YES (llama.cpp/ONNX) | External engines as providers; nothing embedded/bundled | P2 |
| Future sandbox (Job Objects/AppContainer) | (none) | NO | YES | NO | NO | STUDY ONLY | NO | **Rust broker (Phase-Later) is the vehicle** | P1 |

---

## 19. Do-Not-Rewrite Invariants

| Item | Category |
| --- | --- |
| CAP authorization semantics (sole issuer, signed permits) | **CONCEPT MUST REMAIN** |
| ExecutionPermit shape (banked, replay-guarded) | **CONCEPT MUST REMAIN** |
| Deterministic authorization boundary (&ldquo;no effect without a permit&rdquo;) | **CONCEPT MUST REMAIN** |
| GAMBIT planning responsibility (proposal/plan only) | **CONCEPT MUST REMAIN** |
| AgentLoop state contracts (`max_steps` semantics, governance convergence) | **CONCEPT MUST REMAIN** |
| Observation contract (record reality; reconcile with the permit) | **CONCEPT MUST REMAIN** |
| Runtime as the single execution surface | **CONCEPT MUST REMAIN** |
| Memory ownership boundaries (control semantics stay in Python) | **CONCEPT MUST REMAIN** |
| Router abstraction (provider-agnostic selection) | **CONCEPT MUST REMAIN** |
| Architecture-freeze invariants (test `p1_governance_convergence` & siblings) | **CONCEPT MUST REMAIN** |
| Single-user, local-first, Windows-native model | **CONCEPT MUST REMAIN** |
| CAP Python implementation | IMPLEMENTATION MAY CHANGE (later, and only behind the same semantics) |
| GAMBIT goal parser implementation | IMPLEMENTATION MAY CHANGE (regex/schema fix — part of Stage 2) |
| Memory repository/SQL | IMPLEMENTATION MAY CHANGE (SQL/FTS/batch — Stage 2) |
| Runner/executor internals | IMPLEMENTATION MAY CHANGE (placement — Stage 4) |
| Windows ops via broker | IMPLEMENTATION MAY ADD (Stage 6) |

---

## 20. Migration Priority Matrix

| Priority | Component | Action | Trigger/evidence |
| :-: | --- | --- | --- |
| P0 | Provider fallback fidelity | FIX (Python, fail-closed identity match) | Verified HIGH security finding |
| P0 | Goal parser `goal_parser.py:186` | FIX (Python, regex + input bounds) | Verified P0, 2.9–5.7s at 20–35k chars |
| P1 | Memory search | OPTIMIZE (SQL filter + FTS5) | Verified P1, ~150–195ms @10k |
| P1 | Memory insert | OPTIMIZE (single writer, batched txn) | Verified P1, ~10ms/entry, 100k>120s |
| P1 | Blocking SQLite/OCR/PDF in async | OPTIMIZE (placement: aiosqlite/writer thread; process pools) | Verified P2 |
| P1 | Windows execution broker (Rust) | MIGRATE LATER (Stage 6) | Reliability/security not perf; needs contract first |
| P1 | Checkpoint/recovery serialization | OPTIMIZE (Python state model) | Gap in AgentLoop matrix |
| P2 | Browser worker (Python Playwright) | STUDY/ADD (Stage 7) | No browser code today |
| P2 | MCP client adapter | ADD (Stage 7/8), MCP tool→Creative CAP contract | MCP v2 stable; adoption is cheap |
| P2 | Installer (Inno `iscc`) | ADD (Stage 5/6) | Verified NOT-buildable gap |
| P3 | Wasm plugin sandbox | FUTURE (Stage 10) | WASI 0.3 ratified 2026; no exec-sandbox need yet |

---

## 21. Staged Migration Roadmap

Stage numbering is calibrated to the evidence: the first two engineering changes (§24) are stages 1–2.

### Stage 0 — Verified baseline
- **Why:** 3,151 passing tests, measured hotspots, enumerated predicates. Immutable starting point.
- **Dependencies:** none.
- **Risk:** none.
- **Rollback:** n/a.
- **Tests required:** the existing suite stays green.
- **Invariants at risk:** none.
- **Success criteria:** baseline reproducible (documented commands).

### Stage 1 — Security gap closure (Problem A)
- **Why:** closing the mock-fallback fidelity hole before any polyglot surface exists (native code must never carry an alternate authorization path).
- **Dependencies:** none.
- **Risk:** low; scope is ProviderManager/Router resolution order.
- **Rollback:** revert the resolution change; provider fallback code is small.
- **Tests:** new regression for `requires_local_model=True` fallback; permit↔executor identity reconciliation test; existing 3,151 must pass.
- **Invariants at risk:** none if implemented as "fail closed on resolution"; watch `.env`/config-driven routers.
- **Success criteria:** no sensitive request can execute as a provider other than the permit-bound provider; fallback = explicit error.

### Stage 2 — Algorithmic / performance fixes (Problem B + P1 memory)
- **Why:** measurable, Python-only, orders-of-magnitude wins (goal parser 2.9s→~ms at 20k; memory scan ~150ms→~ms; inserts ~10ms/entry→batched).
- **Dependencies:** none.
- **Risk:** low–medium (goal parser is invoked per request; replay all GAMBIT tests).
- **Rollback:** keep the old regex behind a flag for one release if parser tokenization changes surface behavior.
- **Tests:** parser property tests (path/URL/quoted/Windows-path/dotless), fuzz inputs 0–64k chars; memory scale benchmarks 1k/10k/100k rows.
- **Invariants at risk:** GAMBIT extraction semantics (must not change which paths are recognized).
- **Success criteria:** 20k-char goal parses <50ms; 10k-search <10ms; 100k-seed no longer bounded by per-entry commits.

### Stage 3 — Stable cross-language contracts (design doc + schema, no code)
- **Why:** any future native/browser/MCP worker must speak one typed framing (§15). No migration happens before this.
- **Dependencies:** Stage 1/2 (semantics frozen).
- **Risk:** none (documentation/contract shell only).
- **Rollback:** n/a (no runtime code).
- **Tests:** schema-conformance tests for the contract envelope (JSON Schema + pydantic both sides).
- **Invariants at risk:** none.
- **Success criteria:** `ExecutionPermitEnvelope` + `ExecutionResult` + `ObservationEnvelope` schema v1 with versioned fields; RPC frame spec (JSON / optional MessagePack).

### Stage 4 — Async placement fixes
- **Why:** P2 finding (blocking SQLite/OCR/PDF in async paths).
- **Dependencies:** none.
- **Risk:** low; mechanical asyncio placement.
- **Rollback:** per-call offload is additive.
- **Tests:** event-loop responsiveness tests (baseline Phase 5 numbers as regression floor).
- **Invariants at risk:** runtime ordering (parallel scheduler).
- **Success criteria:** no synchronous SQLite/parse/OCR in the event loop; loop wake latency returns to baseline.

### Stage 5 — First native component decision gate
- **Why:** re-evaluate Rust broker (Stage 6) against realized benefits of Stages 1–4; if Python fixes removed the pain, the broker can be deprioritized.
- **Dependencies:** Stages 1–4.
- **Risk:** none.
- **Success criteria:** evidence snapshot: costs re-benchmarked post-fix; decision to proceed/deprioritize the broker recorded.

### Stage 6 — Rust Windows execution broker (first polyglot component)
- **Why:** false only-then: reliable Job-Object tree-kill, restricted-token/ACL operations, clean `CreateProcess`; **executes permits, never decides them** (§8).
- **Dependencies:** Stage 3 contracts, Stage 1 security fix.
- **Risk:** medium — new binary, new signing element, new audit surface. Mitigate: subprocess isolation (broker is a separate process; Python keeps CAP).
- **Rollback:** broker is additive behind Runtime; disable by config and fall back to current Python subprocess path (today's behavior).
- **Tests:** broker conformance against contract schema; permit-replay tests; kill-tree resource-limit tests; existing suite unchanged.
- **Invariants at risk:** none if the broker refuses un-permitted actions and reports actual identity.
- **Success criteria:** shell/filesystem executor can opt into the broker; `taskkill /T` path is replaced for opted-in calls; process-tree kill + Job Object limits verified.

### Stage 7 — Browser worker (Python Playwright, behind CAP)
- **Why:** product gap (no browser automation); Python-first to protect bundle size.
- **Dependencies:** Stage 3 contract for the worker.
- **Risk:** low; worker is a subprocess like tesseract.
- **Tests:** synthetic browser actions through CAP permits; network allow-listing honored.
- **Invariants at risk:** browser worker must not bypass CAP (contract-verified).
- **Success criteria:** `BrowserAction` permits flow end-to-end; Observation records actual page state.

### Stage 8 — MCP client adapter
- **Why:** external-capability ecosystem with low integration cost (§13).
- **Dependencies:** Stage 3 contract; Python MCP SDK.
- **Risk:** low.
- **Tests:** MCP tool→ActionContract→CAP wiring; schema validation of server tools.
- **Invariants at risk:** MCP never policy-authoritative.
- **Success criteria:** first-party MCP tool(s) usable as permits-bound tools; audit log of every call.

### Stage 9 — Wasm plugin capability sandbox (FUTURE classification)
- **Why:** plugin code isolation at capability granularity, CAP-issued grants (WASI 0.3 component model).
- **Dependencies:** Stage 3 contract; Wasmtime host (via broker or external).
- **Risk:** high (new host surface, model weight in bundle).
- **Rollback:** keep Python plugin mode default; Wasm is opt-in.
- **Tests:** capability-misuse matrix (fs/socket/clock denied-by-default).
- **Invariants at risk:** plugin capability grants must come only from CAP.
- **Success criteria:** untrusted plugin demonstrates denied fs/network without host compromise.

### Stage 10 — Native inference optimization (only if product demands)
- **Why:** only addresses a real local-inference product; engines stay providers.
- **Dependencies:** Router abstraction (already present).
- **Risk:** low if external-engine model (no GPU bundling).
- **Success criteria:** selectable llama.cpp/ONNX providers; no GPU libs in bundle.

---

## 22. Target Architecture

Derived from the findings, not from a template. The control plane stays Python and mono-authority; polyglot points are *guarded leaf executors*.

```
                         USER (TUI / HTTP backend)
                                   │
                                   ▼
                         ExecutionCoordinator
                                   │
                       ┌───────────┴───────────┐
                       │   CAP  (Python)       │  sole permit issuer
                       │   policy + approval   │
                       └───────────┬───────────┘
                                   │ signed ExecutionPermit (banked, replay-guarded)
                                   ▼
                       ┌───────────────────────┐
                       │   GAMBIT (Python)     │  goal → plan (LLM_LATENCY_BOUND)
                       └───────────┬───────────┘
                                   ▼
                       ┌───────────────────────┐
                       │  AgentLoop v2 (Python)│  above Runtime, under GAMBIT/CAP
                       │  ordered + observed   │  serializable state, streamed events
                       └───────────┬───────────┘
                                   ▼ governed action + permit
                       ┌───────────────────────┐
                       │  Runtime (Python)     │  THE single execution surface
                       └───────┬───────┬───────┘
                               │       │
          Python tool executors│       │ permitted leaf workers (same envelope)
                               ▼       └───────────────────────────────────┐
                  ┌─────────────────────┐                       ┌──────────▼─────────┐
                  │ Tools / fileparsers │                       │ Leaf workers (later)│
                  │ providers / TUI/API │                       │ • Python-Playwright │
                  │ memory (SQLite+FTS) │                       │   browser worker    │
                  └────────┬────────────┘                       │ • Rust OS broker    │
                           │                                    │ • MCP adapter       │
                           ▼                                    │ • Wasm plugin (fut.)│
                  Provider abstraction                          └──────────┬─────────┘
                  llama.cpp · ONNX · Ollama · remote (all as providers)     │
                           │                                                │
                           └────────────────────────┬───────────────────────┘
                                                    ▼
                                           Observation (records actual
                                           executing identity; reconcile
                                           against permit — stage-1 invariant)
                                                    ▼
                                            State / Memory / Evidence
```

Decisions encoded:
- **One authority, many guarded leaves.** CAP stays the only issuer; every leaf (including Rust broker, browser worker, MCP adapter, Wasm plugin) executes a permit and reports the true identity of what ran.
- **No second policy engine.** The Rust broker, if built, is a Job-Object/ACL executor behind Runtime, not a decider.
- **AgentLoop v2 runs above the Runtime and under GAMBIT/CAP** — i.e., in the Python orchestration layer, operating on CAP-processed results. It adopts *concepts* (serializable state, typed lifecycle events, plan→approve) from rig/codex/grok-build without importing their runtimes.

---

## 23. Risks and Rollback Strategy

| Risk | Likelihood | Impact | Mitigation | Rollback |
| --- | :-: | :-: | --- | --- |
| Goal-parser fix changes recognized-path surface | Med | Med | Property tests on path/URL/Windows-path cases; feature-flag old regex | Revert single-function diff |
| Memory SQL/FTS behavior change | Med | Med | Keep scan as fallback path; migration at read/write layer | Back-compat SQL flag |
| Provider fail-closed breaks a working auto-fallback flow | Med | Low | Only fail closed for sensitive (`requires_local_model=True`) classes; log clearly | Toggle + config |
| Rust broker introduces an auditable native surface | Low–Med | Med | Subprocess isolation; contract schema; broker refuses un-permitted ops; sign PE | Disable via config → Python subprocess fallback (today's path) |
| Browser/MCP workers exceed bundle budget | Med | Med | Python-first decisions (§17); Node/Wasmtime kept out of bundle until justified | Don't ship them; feature-gated |
| Adding a second runtime (Node) by accident of ecosystem pressure | Med | Med | Explicit gate: Node only behind a separate product requirement (§9) | Do not bundle; keep external |
| Test suite regression (3,151) during Stages 1–2 | Low | High | Stages 1–2 are additive & Python-only; full suite must stay green per stage | Revert the specific fix |
| MCP server becomes de-facto authority | Low | High | Rule 2 + §13 boundary; every MCP call is an ActionContract→CAP→Executor wrapper | Disable MCP adapter |
| Bundling GPU/model libs | Low | High | External-engine model (§14/§17); never ship CUDA/weights in the bundle | Remove from spec |

**Overarching strategy:** every stage is additive, ideally feature-flagged, revertible to the prior state, and gated on the untouched 3,151-test baseline. No stage mutates CAP, permit semantics, or the architecture-freeze invariants.

---

## 24. Final Recommendation

1. **Do not rewrite Samaktha.** It is not a speed problem; it is a control-plane + algorithmic-shape problem.
2. **Land the two Python fixes first** — (A) provider-identity fail-closed fidelity; (B) goal-parser regex rewrite + input bounds — before any polyglot work. Both are small, high-value, and preserve the 3,151-test baseline.
3. **Make Python the permanent primary language** — the entire control plane (CAP/GAMBIT/AgentLoop/Observer/Memory semantics/Router), TUI, HTTP, providers, and tools remain Python.
4. **Put memory on SQL** — SQL-side filtering + FTS5 + batched single-writer; no vector DB, no Rust storage layer (not justified by measured data).
5. **Adopt the dev toolchain** — `uv` + `Ruff` + `ty` + `pytest-xdist` (fenced on isolation) for a faster build/lint/type/test loop.
6. **Gate one future native component** — the Rust Windows execution broker (Job Objects, restricted tokens, ACL) MIGRATE LATER behind the Stage-3 signed contract; it executes permits, never decides them.
7. **Add browser + MCP as CAP-gated Python-leaf workers later** — Python Playwright driver first (bundle economics), MCP as a client adapter around ActionContracts.
8. **Keep Wasm a FUTURE (P3)** plugin capability sandbox; be ready for WASI 0.3 maturity on the roadmap, not the critical path.

---

## Required Final Summary Table

| Samaktha Component   | Today          | Target Technology               | Action                   | Priority |
| -------------------- | -------------- | ------------------------------- | ------------------------ | -------- |
| CAP policy           | Python         | Python                          | KEEP                     | P0       |
| CAP approval         | Python         | Python                          | KEEP                     | P0       |
| ExecutionPermit/predicate verification | Python | Python                          | KEEP                     | P0       |
| GAMBIT goal parser   | Python (regex) | Python (fixed regex + input bounds) | FIX/Python            | P0       |
| GAMBIT planner       | Python         | Python                          | KEEP                     | P0       |
| AgentLoop            | Python         | Python                          | KEEP (v2 design above Runtime) | P0   |
| Observer             | Python         | Python                          | KEEP (streamed typed events)     | P1 |
| ExecutionCoordinator | Python         | Python                          | KEEP                     | P0       |
| Runtime engine       | Python         | Python                          | KEEP                     | P0       |
| Runtime parallel scheduler | Python    | Python (process-pool placement) | OPTIMIZE                | P1       |
| ProviderManager      | Python         | Python                          | FIX (identity fail-closed) | P0     |
| Router               | Python         | Python                          | KEEP                     | P0       |
| Provider adapters    | Python         | Python (+ llama.cpp/ONNX providers) | KEEP/ADD              | P1       |
| ContextBuilder       | Python         | Python                          | KEEP                     | P0       |
| Memory semantics     | Python         | Python                          | KEEP                     | P0       |
| Memory search        | Python full-scan | SQLite SQL-filter + FTS5     | OPTIMIZE                 | P1       |
| Memory insert        | connect/commit-per-entry | SQLite single-writer + batch | OPTIMIZE               | P1       |
| SQLite layer         | Python stdlib   | Python stdlib (aiosqlite/writer thread) | OPTIMIZE            | P1       |
| Artifact state       | SQLite         | SQLite                          | KEEP                     | P2       |
| Document parser      | Python/PyMuPDF  | Python driver + PyMuPDF (fixed placement) | OPTIMIZE         | P2 |
| OCR                  | tesseract subprocess | tesseract subprocess (easyocr optional, own process) | KEEP   | P2 |
| Filesystem executor  | Python         | Python now; Rust broker later   | KEEP → MIGRATE LATER     | P1       |
| Shell executor       | Python/taskkill | Python now; Rust Job-Object broker later | KEEP → MIGRATE LATER | P1 |
| Network executor     | Python         | Python (SSRF guards intact)     | KEEP                     | P1       |
| Windows integration  | Python ctypes  | Python now; windows-rs via broker later | KEEP → MIGRATE LATER | P2 |
| Browser              | (absent)       | Python Playwright worker (CAP-gated); Node STUDY | ADD (Python)      | P2 |
| MCP adapter          | (absent)       | Python client adapter (ActionContract→CAP) | ADD                 | P2 |
| Event bus            | Python         | Python                          | KEEP                     | P2       |
| Checkpoint/recovery  | Python         | Python (serializable state model) | OPTIMIZE               | P1       |
| Logging / diagnostics| Python         | Python                          | KEEP                     | P2       |
| TUI                  | Python (textual) | Python (textual)               | KEEP                     | P2       |
| HTTP backend         | Python (FastAPI) | Python (FastAPI)               | KEEP                     | P1       |
| Packaging            | PyInstaller ONEDIR | PyInstaller ONEDIR + Inno     | KEEP (add iscc; only Rust broker enters later) | P1 |
| Installer            | (missing)       | Inno Setup                       | ADD                      | P2       |
| Plugin system        | Python SDK scaffold | Python SDK; Wasm sandbox FUTURE | KEEP → FUTURE          | P3       |
| Local inference      | providers       | external engines as providers (llama.cpp/ONNX/Ollama) | ADD/STUDY          | P2 |
| Future sandbox       | (none)          | Job Objects / restricted tokens via Rust broker | MIGRATE LATER       | P1 |

---

# Samaktha — Final Technology Decision

**PRIMARY LANGUAGE:**
Python — the control plane (CAP, GAMBIT, AgentLoop, Observer, Router), TUI, HTTP backend, providers, tools, and memory semantics stay Python because the complexity is orchestration/policy/LLM-boundary work and both verified hotspots are Python-fixable.

**SYSTEMS LANGUAGE:**
Rust — exactly one component, Phase-Later: a Windows **execution broker** (Job Objects, process-tree kill, restricted tokens, ACL/DACL) that *executes* permits and never decides them. Justified by reliability/security value on Windows, not by speed; no benchmark supports a broader Rust port.

**BROWSER / ECOSYSTEM LANGUAGE:**
Python first (Playwright Python SDK as a CAP-gated worker). TypeScript/Node reserved as STUDY for optional MCP-ecosystem exposure; not admitted to the bundle on packaging-cost evidence.

**NATIVE COMPUTE:**
Wrap existing native engines, author none: stdlib SQLite, PyMuPDF, Tesseract, llama.cpp (external `llama-server`), ONNX Runtime (embedder). Never bundle GPU/model binaries in the installer.

**PLUGIN SANDBOX:**
Wasmtime/WASI component model (WASI 0.3, 2026) — **FUTURE (P3)**, capability grants issued only through CAP; keep the Python plugin SDK as today.

**DATABASE:**
SQLite — moved from Python-side filtering to SQL-indexed/FTS5 search with a single-writer, batched-transaction paradigm via aiosqlite/writer-thread placement. No vector DB or DuckDB now; revisit vector only at ≫1M rows or if semantic search becomes a feature.

**IPC / CONTRACT:**
Typed JSON over stdio (JSON-RPC-style framed envelopes + JSON Schema) for all worker processes; MessagePack for large payloads; named pipes if/when a persistent Rust broker exists. No gRPC, no TCP surface, no C-ABI coupling of safety-critical code into the Python process.

**DEVELOPER TOOLCHAIN:**
`uv` (backbone) + `Ruff` (lint/format) + `ty` (types) + `pytest` with `pytest-xdist` once suite isolation is validated; `cargo-nextest` + `sccache` only when the Rust broker lands; Inno `iscc` to close the installer gap.

**KEEP IN PYTHON:**
CAP policy/approval/permit lifecycle · GAMBIT planning + (fixed) goal parser · AgentLoop v2 design · Observer · ExecutionCoordinator · Runtime engine · Router · ProviderManager (post-fix) · provider adapters · ContextBuilder · Memory semantics · event bus · checkpoint/recovery · logging/diagnostics · TUI · HTTP backend · packaging harness · MCP client adapter.

**MOVE TO RUST:**
Windows execution broker only (Job Objects / restricted-token / ACL execution surface), Phase-Later (Stage 6), gated on the Stage-3 typed contract and the Stage-1 security fix. Nothing else — no goal parser, no memory, no SQLite, no router.

**USE TYPESCRIPT / NODE:**
Nothing now. STUDY: browser-automation ecosystem (Playwright/npx-hosted), optional MCP-server exposure of Samaktha tools. Node stays out of the bundle unless a separate product requirement emerges.

**USE NATIVE C/C++:**
Do not author. Use existing mature native libraries/binary engines (SQLite, PyMuPDF, Tesseract, llama.cpp, ONNX Runtime) and the future Rust broker's `windows-rs` for OS primitives.

**USE WASM:**
FUTURE plugin capability sandbox (Wasmtime/WASI 0.3 + Component Model), capability grants from CAP; not a replacement for the Python runtime; wasmCloud not justified.

**USE EXISTING EXTERNAL TOOLS:**
Tesseract (OCR), piper (voice), `llama-server`/Ollama (local inference), `where.exe`/taskkill (today's process supervision until the broker), future MCP server binaries (as CAP-wrapped tools).

**DO NOT REWRITE:**
CAP authorization semantics · ExecutionPermit (banked/replay-guarded) · deterministic authorization boundary · GAMBIT planning responsibility · AgentLoop state contracts · Observation contract · Runtime as the single execution surface · Memory ownership boundaries · Router abstraction · architecture-freeze invariants · single-user local-first Windows-native model.

**FIRST SECURITY FIX:**
Provider-identity fidelity: provider resolution must precede authorization, `requires_local_model=True` fails closed on local-unavailable instead of mock-falling-back, and the Observer must reconcile the actually-executing provider identity against the permit (mirroring the replay-guard pattern at `engine.py:402-425`).

**FIRST PERFORMANCE FIX:**
`goal_parser.py:186` — replace the unanchored greedy path regex (anchored/tokenized parsing) and enforce input-length bounds at the parser entry; target <50 ms at arbitrary sizes (measured: 43 ms @2K chars → 2,877 ms @20K → 5,742 ms @35K today).

**FIRST POLYGLOT COMPONENT:**
None now. When justified (Stage 6, Phase-Later), the Rust Windows execution broker — the first/only native component, added behind the Stage-3 signed contract and additively behind the Runtime.

**AGENTLOOP V2 SHOULD RUN ABOVE:**
The Runtime and under GAMBIT/CAP — that is, in the Python orchestration layer, consuming CAP-approved execution results, adopting serializable-state/typed-event concepts from rig/codex/grok-build without importing any runtime wholesale.

**TARGET ARCHITECTURE:**
Python mono-authority control plane: `TUI/HTTP → ExecutionCoordinator → CAP (signed permit) → GAMBIT → AgentLoop → Runtime (single governed surface)` → permitted leaf executors (Python tools · future Rust OS broker · future Python-Playwright browser · future MCP adapter · future Wasm plugin) → Observation (reconcile actual identity) → State/Memory. See §22.

**OVERALL CONFIDENCE:**
HIGH on keep-Python core and SQLite-first storage (measured algorithmic fixes; unchanged governance invariants). MEDIUM-HIGH on the Phase-Later Rust broker (no performance benchmark — justified on Windows reliability/security engineering; low migration risk since it is additive). MEDIUM on browser/Node timing (depends on unformed product requirements). LOW on Wasm timing (FUTURE by design; ecosystem maturing, WASI 0.3 ratified 2026).

---

## Change Control

```text
SOURCE CODE CHANGED:
NO

TEST CODE CHANGED:
NO

PRODUCTION DEPENDENCIES ADDED:
NO

ARCHITECTURE CHANGED:
NO

DOCUMENTS CREATED:
docs/architecture/SAMAKTHA_POLYGLOT_ARCHITECTURE.md
```

The 3,151-test baseline is untouched. Repository `git status` this session shows only the pre-existing modifications/untracked files from before this study, plus the new document.

Verified against the two prior evidence reports; where repository state differed from the task's assumed paths (e.g., `app/document/` does not exist, `app/fileparsers/` is the document/OCR location; no MCP/browser code exists), the discrepancy was noted explicitly and the current truth was established from source.