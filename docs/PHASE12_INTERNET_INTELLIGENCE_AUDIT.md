# Phase 12 — Internet Intelligence Audit — Final Report

Date: 2026-08-02

Scope: Governance-controlled internet access as a first-class capability. The
LLM never searches directly; it reasons only over cached → ranked → verified
results. No changes were committed; this report is the phase deliverable.

Explicitly excluded from Phase 12: Gmail, WhatsApp, calendar, GitHub, terminal,
Tool Registry, marketplace, plugins, RAG/embeddings, knowledge router, learning,
multi-agent.

---

## 1. Architecture

```
USER QUERY
   ↓
GoalParser._is_internet_intent            app/core/gambit/goal_parser.py
   → SEARCH_INTERNET (deterministic signals, memory queries excluded)
   ↓
TaskDecomposer SEARCH_INTERNET branch     app/core/gambit/task_decomposer.py
   UNDERSTAND → tool:internet(search) → EXECUTE_VIA_RUNTIME(text_generation) → REFLECT
   ↓
CapabilityRegistry domain "internet"       app/tools/capability_registry.py
   ↓
CAP PolicyEngine                          app/core/cap/policy_engine.py
   INTERNET_ACTIONS → PermissionScope.NETWORK → HIGH risk, approval required
   ↓
ApprovalEngine.decide → ExecutionPermit   injected into task.metadata
   ↓
Orchestrator injects _cap_permit          app/core/orchestrator/engine.py
   ↓
Workflow → Runtime → Dispatcher "internet"→"tool" → InternetTool.run
   ↓
SearchPolicy gates                        app/internet/policy.py
   enabled / category allowlist / query length / fetch+suggest toggles
   ↓
SearchCache.get (TTL 300s web / 60s news) app/internet/cache.py
   ↓ (miss)
SearchProvider (Brave adapter / injected) app/internet/provider.py, brave.py
   ↓
ResultRanker (6-axis, deterministic)      app/internet/ranker.py
   relevance*5 + authority*3 + freshness*1.5 + completeness*1 + language*0.5
   duplicate collapse keyed (normalized-title, domain)
   ↓
SearchVerifier (agreement/conflict)       app/internet/verifier.py
   HIGH ≥2 sources + authority≥0.7 + fresh; LOW on conflict/single; UNKNOWN empty
   ↓
SearchCache.put (stamped response)
   ↓
ContextBuilder [INTERNET SEARCH RESULTS] block → system prompt cite-as-[n]
   ↓
LLM reasons over verified results only
   ↓
ResponseFormatter "Sources:" block        app/personality/response_formatter.py
   ↓
MemoryFormationEngine transient gate      app/memory/formation/engine.py
   internet_sourced ∧ ¬explicit_memory → no persistence
```

The pipeline is provider-agnostic (any `SearchProvider` adapter) and fully
deterministic from query normalization → cache key → ranking → verification.

## 2. Sub-phase coverage

- **12.1** InternetTool facade in `app/internet/tool.py` — actions
  search/news/suggest/fetch, CAP governance, never raises (every SearchError →
  graceful ToolResult).
- **12.2** Brave adapter `app/internet/brave.py` — web/news endpoints,
  `X-Subscription-Token`, retries w/ backoff (429/5xx), typed errors
  (auth/rate-limit/timeout/HTTP), provider-agnostic normalization.
- **12.3** CAP governance — `INTERNET_ACTIONS` → `PermissionScope.NETWORK` →
  HIGH risk + approval required; tool refuses without `_cap_permit` and on
  `deny`.
- **12.4** GAMBIT intent detection — deterministic phrases/verbs/freshness
  markers, memory-search exclusion, positioned before filesystem search.
- **12.5** Deterministic ranking — 6-axis score, dedup, cap, no-URL drop.
- **12.6** Content retrieval — httpx, http/https only, 15 s timeout, 2 MB cap,
  HTML boilerplate stripping, markdown/PDF extraction, redirect-scheme guard.
- **12.7** Multi-source verification — title clustering, domain-authority
  weighting, conflict detection, per-result confidence stamping.
- **12.8** Source attribution — `sources` on tool output → ContextBuilder
  citation rules → ResponseFormatter `Sources:` block.
- **12.9** SearchCache — TTL cache, normalized keys, category namespacing.
- **12.10** Transient memory — internet-sourced interactions are never
  auto-persisted unless the user explicitly requested remembering.
- **12.11** Reliability — no exceptions escape the tool; live-network tests
  are skippable; all behavior tested offline (FakeProvider + httpx
  MockTransport).
- **12.12** Provider-abstraction verification — `SearchProvider` ABC; both
  `InternetTool` and `BraveSearchProvider` accept injected
  `httpx.AsyncBaseTransport`; Brave key from `SAMAKTHA_BRAVE_API_KEY` env.
- **12.13** Regression tests — `tests/phase12/` (94 tests).
- **12.14** Production audit — this report.

## 3. Execution trace (E2E)

```
request: "what is the latest python version"
  goal        → SEARCH_INTERNET
  plan        → [understand | tool:internet(search) | text_generation | reflect]
  cap         → task_policy: NETWORK, approval_required=True
  approval    → ALLOW (pre-seeded InMemoryPermissionStore in test; user prompt in prod)
  permit      → task.metadata["permit"] = {"decision": "allow", ...}
  _cap_permit → "allow" injected into tool args
  internet    → tool.run → cache miss → FakeProvider.search
                → rank (docs.python.org 1st) → verify (2 sources agree, fresh → HIGH)
                → cache put → ToolResult{internet: True, sources: [...], verification: {...}}
  llm         → provider "mock" → output
  formatter   → appends "Sources:\n- … — https://docs.python.org/3.13/"
  memory      → _used_internet=True → formation SKIPPED (transient gate)
  result      → completed, content contains "Sources:" + docs.python.org URL
```

## 4. Design decisions

1. **Dedup keyed (normalized-title, domain).** Identical headlines from
   different domains are independent corroborating sources and must survive
   ranking — otherwise the verifier could never find cross-source agreement.
   Same-title/same-domain entries collapse to the best-scoring representative
   (deterministic first-seen on tie).
2. **Action ↔ category split.** Actions (`search/news/fetch/suggest`) are what
   the facade accepts; categories (`web/news`) are what providers/cache use.
   `search` maps to `web`.
3. **Verification never fabricates certainty.** Empty → UNKNOWN, single source
   → LOW, conflict without an authoritative majority → LOW, stale agreement →
   MEDIUM.
4. **Transient-by-default memory.** Internet content is volatile and
   uncorroborated; only `explicit_memory=True` persists it.
5. **Governance before execution.** The tool refuses to run without the CAP
   permit the orchestrator injects; the LLM can never bypass it.

## 5. Files modified

Application code (NEW — `app/internet/`, 1582 lines):

- `app/internet/models.py` — SearchConfidence, SearchResult, SearchResponse,
  SourceMetadata, VerificationReport, FetchResult, SearchError hierarchy.
- `app/internet/provider.py` — SearchProvider ABC (is_configured, search, news,
  suggestions, health).
- `app/internet/cache.py` — SearchCache (TTL, normalized keys, namespacing).
- `app/internet/policy.py` — SearchPolicy (immutable governance ruleset).
- `app/internet/ranker.py` — ResultRanker (deterministic 6-axis scoring).
- `app/internet/verifier.py` — SearchVerifier (agreement/conflict analysis).
- `app/internet/fetcher.py` — ContentFetcher (HTTPS retrieval + extraction).
- `app/internet/brave.py` — BraveSearchProvider (web/news, retries, typing).
- `app/internet/tool.py` — InternetTool facade.
- `app/internet/__init__.py` — public exports.

Integration edits:

- `app/core/contracts/planning.py` — `SEARCH_INTERNET` in GoalIntent.
- `app/core/gambit/goal_parser.py` — `_is_internet_intent` (before filesystem
  search; memory exclusion) + capability-domain mapping.
- `app/core/gambit/task_decomposer.py` — SEARCH_INTERNET plan branch.
- `app/tools/capability_registry.py` — internet domain entry.
- `app/core/cap/policy_engine.py` — INTERNET_ACTIONS → NETWORK.
- `app/runtime/dispatcher.py` — `"internet": "tool"`.
- `app/core/context_builder.py` — `[INTERNET SEARCH RESULTS]` block +
  citation system-prompt rules.
- `app/core/orchestrator/engine.py` — permit injection, `_internet_sources`,
  `_used_internet`, formatter `sources=` path, memory metadata.
- `app/memory/formation/engine.py` — transient gate.
- `app/personality/response_formatter.py` — `sources` kwarg + `_append_sources`.
- `app/core/app.py` — InternetTool registration with env key.

Test code (NEW):

- `tests/phase12/` — 10 modules, 94 tests.

## 6. Performance & security analysis

- **Performance:** per-query provider call only on cache miss; rank/verify are
  pure O(n·m) token ops on ≤5 results; fetched content capped at 12 000 chars;
  hard 2 MB wire cap and 15 s timeout bound the worst case.
- **Security:** http/https scheme guard + redirect-scheme re-check (no
  `file://` or downgrade); query-length cap; content-type allowlist; UA
  branding; user-content that reaches the LLM is verification-stamped and
  attribution-bound; no secrets in code — API key read from env only.
- **Governance:** network egress is a HIGH-risk NETWORK action requiring CAP
  approval; the tool hard-refuses missing/denied permits; `enabled=False`
  disables egress entirely.

## 7. Test report

| Module | Tests |
|--------|-------|
| test_models.py | 8 |
| test_cache.py | 7 |
| test_policy.py | 5 |
| test_ranker.py | 8 |
| test_verifier.py | 7 |
| test_fetcher.py | 7 |
| test_brave_provider.py | 11 |
| test_internet_tool.py | 14 |
| test_gambit_integration.py | 24 |
| test_orchestrator_integration.py | 3 |
| **Total** | **94** |

Pre-new-test baselines (regression check): gambit/tools/runtime/personality/
memory 487 passed; orchestrator/phase10/conversation/contracts/security 153
passed. Post-integration sanity: internet intent correctly detected for
"latest/python/web/news" phrases; memory/PDF/code queries unchanged vs the
pre-Phase-12 parser (verified against `git show HEAD:...goal_parser.py`).

## 8. Final test results

- Phase 12 suite: **94 passed**.
- Full suite: **1286 passed, 0 failed** (169.6 s) — 1192 pre-existing +
  94 new, no regressions.

## 9. Production-stability confirmation

- Internet access is governance-gated end-to-end and provider-agnostic.
- Every provider error is a graceful ToolResult; no exception escapes.
- LLM output is always attribution-bound and never invents sources.
- Internet-sourced content is transient in memory unless explicitly requested.
- Live-network tests are skippable; CI behavior is fully offline.
- No git commit made, per phase policy.

## 10. Recommendation log

1. **Commit.** Phase 11–12 work remains uncommitted; commit after review.
2. **Approval UX:** production approval flow already resumes via
   `resume_pipeline`; consider surfacing the NETWORK permit prompt to the TUI
   with a "remember this site" option.
3. **Optional hardening:** wire `app/security/tool_guard.py` to the internet
   domain so a future non-CAP path still cannot egress ungoverned.
