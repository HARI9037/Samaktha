# Phase 9 — Personality Engine: Architecture Specification

Status: **IMPLEMENTED (Phases 9.1–9.5) and INTEGRATED (Phase 10A).** This document
is the architecture specification; the deterministic vertical slice lives under
`app/personality/` and is wired into the production orchestrator.
Subsystem: Permanent first-class subsystem, co-equal to CAP, GAMBIT, Runtime, Memory.
Scope: Determines **HOW Samaktha behaves and communicates**. It never reasons, never plans, never governs, never selects models, never invokes tools.

---

## 1. System Overview

### 1.1 Position in the architecture

The Personality Engine sits **between GAMBIT and the Runtime / Model Router** in the execution pipeline. It is a deterministic, fully-local, read-only-against-memory subsystem that transforms a single request into a structured **Communication Directive** — a bounded, versioned bundle of behavioral parameters that downstream communication (the provider-bound request) must honor.

```
User
  │
  ▼
CAP (Context & Governance)        ── governance boundary (unchanged)
  │
  ▼
Memory Controller                 ── source of truth (unchanged)
  │
  ▼
GAMBIT (Planning Engine)          ── reasoning boundary (unchanged)
  │
  ▼
Personality Engine                ── NEW: communication boundary
  │
  ▼
Runtime / Model Router            ── execution + selection (unchanged)
  │
  ▼
LLM
  │
  ▼
Response
```

### 1.2 Architectural invariants (absolute, non-negotiable)

1. **Reasoning belongs to GAMBIT.** The Personality Engine never produces reasoning, never evaluates the correctness of a plan, never re-plans.
2. **Governance belongs to CAP.** The Personality Engine can never change, delay, or bypass a CAP decision. It may only *observe* risk/privacy to tune wording.
3. **Memory belongs to the Memory Controller.** The Personality Engine reads memory through a narrowed read-only port and **never writes to memory directly**.
4. **Planning belongs to GAMBIT.** The directive is attached to a plan's tasks as read-only metadata; it must not alter task sets, order, dependencies, or router requests.
5. **Execution belongs to Runtime, selection to the Router.** The directive is a communication parameter, never an execution or selection parameter.
6. **Determinism.** Given identical inputs, the engine produces a byte-identical directive (a `determinism_hash` is computed and verified). No LLM, no embeddings, no remote calls, no randomness.
7. **No private persistent state.** Every relationship-derived value is recomputed from Memory on demand. Ephemeral in-session state is allowed and bounded.

### 1.3 What the Personality Engine is not

- Not a prompt-engineering layer (it outputs structured data; serialization to model-bound text is a downstream adapter concern and is specified here only as a contract, not as prompt copy).
- Not an emotion simulator (it estimates the *user's* state and adjusts *parameters*; it never claims to feel anything itself).
- Not a roleplay/chatbot persona switcher (one persistent identity; per-request adjustments stay within identity-imposed bounds).
- Not a memory writer (Phase 8.2 Memory Formation remains the sole ingestion path for derived observations).

---

## 2. Complete Pipeline

### 2.1 Where the engine runs today (grounding in the current code)

Current production path (`SamakthaOrchestrator.run_pipeline`, `app/core/orchestrator/engine.py`):

1. GAMBIT Goal Parser produces a `Goal`.
2. CAP evaluates the intent (`PolicyEngine.evaluate` + `ApprovalEngine.decide`); a DENY short-circuits (the Personality Engine never sees denied requests).
3. `ContextEngine.build` produces a `PreparedContext`; the orchestrator retrieves `state.memory_context` from the Memory Controller.
4. GAMBIT `Planner.plan_with_capability_check` produces the `ExecutionPlan`.
5. CAP evaluates each runtime task and issues `ExecutionPermit`s.
6. `WorkflowEngine.execute` converts plan tasks to `RuntimeTask`s and drives Runtime → Router → ProviderManager.
7. CAP re-filters the final output (privacy) and Phase 8.2 Memory Formation persists interaction memories.

The Personality Engine is inserted as a **new step 5.5**, strictly between step 5 (CAP task permits) and step 6 (Workflow execution). It is computed once per request and attached to the request for the rest of the pipeline.

### 2.2 Pipeline stages with the Personality Engine

| Stage | Subsystem | Produces | Personality involvement |
|---|---|---|---|
| 1 | GAMBIT (Goal Parser) | `Goal` | none |
| 2 | CAP | `PolicyDecision`, `ApprovalDecision` | none (deny short-circuits) |
| 3 | Context + Memory Controller | `PreparedContext`, memory context | none yet |
| 4 | GAMBIT (Planner) | `ExecutionPlan` | none |
| 5 | CAP | `ExecutionPermit[]` per task | none |
| **5.5** | **Personality Engine** | **`CommunicationDirective` + `InteractionMetadata`** | **this stage** |
| 6 | Workflow → Runtime → Router → Provider | `RuntimeResult` | directive travels as metadata on `RuntimeTask.inputs`; serializer applies it at the provider boundary |
| 7 | CAP (output filter) + Memory Formation | final `RuntimeResult`, persisted memories | directive's `observation_candidates` are handed to Memory Formation; CAP still filters the rendered output |

### 2.3 Delivery channels of the directive

- **Primary channel:** the directive is injected into each `text_generation` / `provider` / `code_generation` `RuntimeTask` as `inputs["personality"]`, and mirrored into `RuntimeContext.metadata["personality"]`.
- **Model-bound application:** the streaming/production bridge (`app/agent/production.py::_StreamingRuntimeBridge.run`) and the non-streaming `ProviderExecutor` read the directive and pass it to a **DirectiveSerializer** at `StreamRequest`/provider-payload construction time. The serializer is deterministic and model-agnostic; its exact template text is an implementation-phase deliverable and is **out of scope for this specification**.
- **Observability channel:** `InteractionMetadata` is appended to `RuntimeResult.metadata` and the `ExecutionTrace` for post-hoc analysis; it is never sent to the model.

---

## 3. Internal Modules

Proposed location: `app/personality/` (peer of `app/core/gambit`, `app/memory/controller`). All modules are deterministic; the only external dependency is the read-only memory port.

| # | Module | Role | Layer |
|---|---|---|---|
| M1 | `IdentityManager` | Permanent identity: hard rules, values, allowed bands. | L1 |
| M2 | `TraitManager` | Core trait baseline (formality, verbosity, humor, assertiveness, warmth). | L2 |
| M3 | `RelationshipManager` | Derives continuous relationship metrics from Memory. | L3 |
| M4 | `InteractionStateManager` | Per-session ephemeral conversation state. | L4 |
| M5 | `EmotionalAnalyzer` | Estimates the user's emotional state from the current message. | L5 |
| M6 | `BehaviorPolicyEngine` | Rule engine that maps inputs to behavior decisions (levers). | cross |
| M7 | `ToneEngine` | Resolves tone: register, warmth, humor allowance, formality, assertiveness. | cross |
| M8 | `InitiativeManager` | Resolves initiative level and permitted proactive moves. | cross |
| M9 | `ConversationStyleManager` | Resolves pacing, structure, verbosity, explanation depth, summarize/expand. | cross |
| M10 | `Composer` | Assembles the final `CommunicationDirective` + `InteractionMetadata`. | cross |
| M11 | `ConsistencyGuard` | Validates the directive against invariants; computes `determinism_hash`. | cross |
| M12 | `MemoryReader` | Narrow, read-only, CAP-aware port into the Memory Controller. | port |
| M13 | `DirectiveSerializer` | Adapter at the model boundary that maps a directive to model-bound context. | port (impl-phase content) |
| M14 | `PluginRegistry` | Extension point registry for future analyzers/tones/channels. | cross |

### 3.1 Module responsibilities

**M1 IdentityManager (Layer 1).**
- Owns the immutable identity constitution: a fixed list of hard rules (e.g., intellectual honesty, no unnecessary flattery, never fabricate memories, never fake emotions, challenge incorrect assumptions, explain reasoning clearly, stay consistent across sessions).
- Owns the **allowed bands** for every behavior lever (floor/ceiling), e.g. `warmth ∈ [0.25, 0.85]`, `humor ∈ [0, 0.5]`, `formality ∈ [0.3, 0.9]`. Layer 5 can never push a lever outside its band.
- Identity is code-defined, versioned, and shared across all users. Per-user identity changes are only possible through CAP-approved configuration, never through interaction.

**M2 TraitManager (Layer 2).**
- Holds a configurable but stable baseline trait vector (`TraitBaseline`). Sourced from `AgentConfig`-style settings; identical for all requests until changed by an operator.
- Produces the starting point that Layers 3–5 perturb.

**M3 RelationshipManager (Layer 3).**
- Queries Memory via `MemoryReader` (preferences, knowledge/projects, workflows, tools, conversation volume/recency, permission history where exposed by CAP).
- Computes **continuous** relationship metrics (familiarity, style preference, trust-comfort, project context, habits, inferred expertise) — never discrete "stages".
- Emits an `ObservationCandidate` list (e.g., "user prefers concise answers") into metadata; persistence is performed only by Memory Formation.
- Is stateless between requests: the same Memory snapshot yields the same metrics.

**M4 InteractionStateManager (Layer 4).**
- Per-session ring buffer (bounded, TTL-bounded): recent exchanges, active topic, in-session correction flags, deferred observations, session duration, follow-up cadence.
- Pure in-memory; cleared on session end; never persisted; keyed by `session_id`.

**M5 EmotionalAnalyzer (Layer 5 input).**
- Deterministic linguistic feature extraction on the current user message plus surrounding context (see §9).
- Outputs `EmotionalSignals {frustration, urgency, excitement, uncertainty, valence, activation, confidence, unsure}`.
- Never emits a subjective claim about the user's internal state to the model; it only feeds parameter adjustments.

**M6 BehaviorPolicyEngine.**
- The decision core. Applies a prioritized rule set (see §7) over `(TraitBaseline, RelationshipState, InteractionState, EmotionalSignals, plan features, CAP risk/privacy)`.
- Produces `BehaviorDecisions` — one decision per lever (ask-vs-answer, challenge, encourage, summarize, explanation depth, brevity, humor allowance, formality, initiative) plus `reason_codes`.

**M7 ToneEngine.**
- Converts `BehaviorDecisions` + identity bands into `ToneProfile {register, warmth, humor, assertiveness, formality}`. All values are floats within identity bands.

**M8 InitiativeManager.**
- Maps relationship/emotional/plan context to `InitiativeLevel {passive, responsive, active, proactive}` and a set of *permitted proactive moves* (offer follow-up, surface a memory conflict, suggest a known workflow, observe a pattern).
- Proactive moves are communication-only: they may propose an action but can never execute one, open tools, or modify the plan.

**M9 ConversationStyleManager.**
- Resolves `ExplanationDepth {brief, summarize, balanced, detailed}`, `Pacing {fast, normal, measured}`, `StructurePreference {prose, bullets, step_by_step}`, verbosity, and whether to summarize prior context vs. expand.

**M10 Composer.**
- Bundles outputs of M6–M9 with identity header and version into the single `CommunicationDirective`.
- Bundles signals, decisions, reasons, observations, and governance acknowledgements into `InteractionMetadata`.

**M11 ConsistencyGuard.**
- Validates every directive before release: no lever outside identity bands; no CAP conflict; no plan/tool fields; deterministic re-computation matches `determinism_hash`.
- The Guard is the only module allowed to reject an output; rejection is a hard failure that fails the stage closed (request proceeds with the identity-only default directive, never with a partially-applied directive).

**M12 MemoryReader.**
- The *only* memory access path for the engine. A protocol exposing a whitelist of Memory Controller methods: `retrieve`, `retrieve_recent`, `retrieve_semantic`, `search_documents`, `check_read_access`.
- Enforces read-access rules (SecurityLevel) and filters to relevant types; never exposes write methods. Implemented in terms of the existing `MemoryController` facade — no new memory code.

**M13 DirectiveSerializer (model boundary adapter).**
- Maps a `CommunicationDirective` to the model-bound request (system-context block + generation parameters) at `StreamRequest`/payload construction time.
- Deterministic, idempotent, length-bounded, model-agnostic, and stripped of all governance data. Template content is defined at implementation time — out of scope here.

**M14 PluginRegistry.**
- Registry for pluggable `EmotionalAnalyzer`s, `ToneResolver`s, `InitiativeDecider`s, and rule providers. Default implementations are the deterministic rule-based ones. Future models/voice/avatar/channels plug in here without touching the core (§13).

---

## 4. Responsibilities Matrix

| Concern | Owner | Personality Engine |
|---|---|---|
| Governance, policy, privacy, approval | CAP | observes risk/privacy only |
| Reasoning, plans, skills, reflection | GAMBIT | reads plan features only |
| Model selection | Router | never influences |
| Execution, tools | Runtime | never influences |
| Memory persistence, lifecycle, retrieval | Memory Controller | reads only; observes through M12 |
| Tone, depth, pacing, initiative, warmth | **Personality Engine** | owns |
| Emotional state of user | **EmotionalAnalyzer** | estimates (never simulates) |
| Behavior rules (when to ask/challenge/encourage/summarize/joke) | **BehaviorPolicyEngine** | owns |
| Consistency over time | **IdentityManager + ConsistencyGuard** | owns |

---

## 5. Data Flow

### 5.1 Inputs — `PersonalityRequest`

The engine receives exactly one structured request per user turn:

| Field | Source | Notes |
|---|---|---|
| `request_id`, `session_id`, `user_id` | `RuntimeContext` | identity of the turn |
| `user_message` | raw request | the current utterance |
| `conversation_tail` | `PreparedContext.recent_messages` / passed conversation | last N messages (bounded) |
| `policy_decision` | CAP `PolicyDecision` (risk, privacy, approvals) | read-only; may be absent for non-action turns |
| `goal` | GAMBIT `Goal` (intent, complexity, requires_code, constraints) | read-only |
| `execution_plan` | GAMBIT `ExecutionPlan` (task kinds, workflow, router_request) | read-only; never modified |
| `memory_items` | `MemoryController.retrieve(...)` via M12 | ranked, filtered, CAP-access-checked |
| `memory_context_text` | orchestrator's existing `state.memory_context` | string form for reference |
| `turn_timestamp` | orchestrator | for recency/decay derivation |

Constraints: all inputs are treated as **read-only**; the engine performs no writes to any source.

### 5.2 Processing order

```
PersonalityRequest
  ├─ M5  EmotionalAnalyzer ──────────────────────────► EmotionalSignals
  ├─ M4  InteractionStateManager (session fetch) ─────► InteractionState
  ├─ M3  RelationshipManager (M12 MemoryReader) ──────► RelationshipState (+observation candidates)
  ├─ M2  TraitManager ────────────────────────────────► TraitBaseline
  ├─ M6  BehaviorPolicyEngine (L1 bands + L2 base + L3/L4/L5 deltas) ──► BehaviorDecisions
  ├─ M7  ToneEngine ──────────────────────────────────► ToneProfile
  ├─ M8  InitiativeManager ───────────────────────────► InitiativeLevel + allowed moves
  ├─ M9  ConversationStyleManager ────────────────────► StyleResolution
  ├─ M10 Composer ────────────────────────────────────► CommunicationDirective
  ├─ M11 ConsistencyGuard (validate + hash) ──────────► verified directive
  └─ M4  InteractionStateManager (session update) ────► updated ephemeral state
```

### 5.3 Outputs

**`CommunicationDirective`** (the only artifact consumed by the pipeline):

| Group | Fields | Type/bounds |
|---|---|---|
| Identity header | `identity_id`, `profile_version` | string |
| Tone profile | `register`, `warmth`, `humor`, `assertiveness`, `formality` | register: enum; floats within identity bands |
| Communication strategy | `explanation_depth`, `pacing`, `structure_preference`, `verbosity`, `summarize_prior` | enums + floats |
| Behavioral constraints | hard-rule codes (NO_FLATTERY, NO_EMOTION_FABRICATION, NO_MEMORY_INVENTION, CHALLENGE_INCORRECT_ASSUMPTIONS, EXPLAIN_REASONING, etc.) | frozen list from IdentityManager |
| Initiative | `level`, `permitted_moves`, `challenge_threshold` | enum + list |
| `determinism_hash` | sha-256 over canonical input + decisions | string |

**`InteractionMetadata`** (observability only, never model-bound):

| Field | Meaning |
|---|---|
| `relationship_metrics` | continuous relationship values + confidence |
| `emotional_signals` | analyzer output + confidence |
| `decision_reasons` | rule `reason_codes` trace |
| `initiative` | level + allowed moves |
| `observation_candidates` | memory-worthy facts suggested to Memory Formation (typed + confidence) |
| `compliance` | `governance_ack` (CAP decision honored), `plan_readonly_ack` (plan untouched), `no_write_ack` |
| `latency_ms`, `profile_version`, `determinism_hash` | diagnostic |

The directive **must not** contain: reasoning, plan modifications, tool requests, model-selection hints, memory writes, or governance changes.

---

## 6. Personality State Model (the five layers)

The engine separates personality into five layers with strict interaction rules.

### 6.1 Layer definitions

**Layer 1 — Permanent identity.** Immutable. The constitution and the allowed bands for every lever. Never modified by interaction, emotion, or relationship. Versioned only through release cycles.

**Layer 2 — Core traits.** Static baseline trait vector from configuration. Same for every request until an operator changes configuration. Sits inside Layer 1's bands by construction.

**Layer 3 — Relationship adaptation.** Derived from Memory on every request: familiarity, style preference, project context, habits, trust-comfort. Changes only as fast as Memory itself changes (months-scale). Continuously valued; no hardcoded stages.

**Layer 4 — Conversation state.** Ephemeral, per-session: current topic, recent exchanges, in-session corrections, follow-ups. Changes within a session; cleared at session end.

**Layer 5 — Current-interaction adjustments.** Per-request: user emotional signals, urgency, CAP risk, GAMBIT complexity/intent. Changes every turn; the most volatile layer.

### 6.2 Interaction rules

1. **Monotonic precedence:** L1 (hard rules + bands) > L2 (baseline) > L3 > L4 > L5. Any lever value is `clamp(base + Δ_L3 + Δ_L4 + Δ_L5, band_L1)`.
2. **Band enforcement:** L5 deltas are bounded to a small fraction of the band width; L3 may move further; only L1 defines the extremes. A frustrated user can shift warmth by `±0.1`, not to the edge of sycophancy.
3. **Discrete decisions** (ask/challenge/summarize/joke) use a priority cascade: L1 hard rules first, then task-type defaults, then risk/complexity, then emotion, then relationship, then conversation state. First applicable rule wins; ties are resolved deterministically (rule id order).
4. **Consistency contract:** the same `(L1, L2, L3, L4, L5)` input tuple yields the same directive. Since L3 derives from Memory and L4 is bounded by TTL, long-range behavior is stable while short-range behavior is adaptive.
5. **No layer may veto a CAP decision.** Layers only shape communication parameters; governance acknowledgements are copied verbatim into `compliance`.

### 6.3 State lifecycle

| State | Storage | Lifecycle | Written by |
|---|---|---|---|
| L1 identity | code (versioned) | release cycle | release |
| L2 traits | config | operator change | operator |
| L3 relationship | **Memory** (source of truth) | memory lifecycle | Memory Controller |
| L4 interaction | in-memory `InteractionStateManager` | session lifetime | engine (ephemeral) |
| L5 adjustments | per-request (none stored) | one request | engine |

---

## 7. Behaviour Decision Pipeline

### 7.1 The levers

The engine decides exactly these behaviors (nothing else):

| Lever | Values | Decides |
|---|---|---|
| `ask_vs_answer` | `answer`, `ask_clarifying`, `ask_confirm` | whether to request info before/while answering |
| `challenge` | `off`, `soft`, `firm` | whether to contest an incorrect assumption/instruction |
| `encourage` | `off`, `light`, `supportive` | whether to acknowledge effort/progress |
| `summarize` | `off`, `on` | whether to condense prior context into the reply |
| `explanation_depth` | `brief`, `summarize`, `balanced`, `detailed` | depth of the reply |
| `verbosity` | float in band | length of the reply |
| `humor_allowance` | float in band | whether humor is acceptable |
| `formality` | float in band | register strictness |
| `initiative` | `passive`, `responsive`, `active`, `proactive` | degree of unsolicited contribution |

### 7.2 Rule priority cascade (deterministic)

**Priority 1 — Identity + governance (always).**
- Never flatter unnecessarily (NO_FLATTERY).
- Never claim emotions the system does not have (NO_EMOTION_FABRICATION).
- Never invent memories or facts (NO_MEMORY_INVENTION).
- Never circumvent CAP wording/decisions.
- Challenge threshold defaults on; soft by default.

**Priority 2 — Task-type defaults (from GAMBIT `Goal.intent`).**
- `ANSWER_QUESTION` → `answer`, `balanced`, verbosity medium.
- `GENERATE_CODE` → `detailed`, `step_by_step`, structure bullets.
- `SEARCH_MEMORY` / `RETRIEVE_CONTEXT` → `summarize` on.
- `READ_RESOURCE` / `LIST_DIRECTORY` → `summarize`, `brief` unless asked.
- `WRITE_*` / `DELETE_*` / `RUN_COMMAND` / `OPERATE_WINDOWS` → confirm understanding, `formality` raised with risk.

**Priority 3 — Risk & complexity (from CAP risk + GAMBIT complexity).**
- `ActionRisk.HIGH/CRITICAL` → `formality` +, `pacing` measured, explicit consequences, no humor, `challenge` available for risky assumptions.
- `GoalComplexity.HIGH` → `explanation_depth` up, `step_by_step`.
- `requires_local_model` → privacy-sensitive → minimal disclosure wording (still communication-only).

**Priority 4 — Emotional signals (§9).**
- High urgency → `pacing` fast, minimal preamble, direct answer first.
- High frustration → no defensiveness, `summarize` to the fix, `verbosity` down, `encourage` light.
- High uncertainty → ask clarifying/confirming, `structure_preference` explicit.
- High excitement → `encourage` supportive, matched activation (not mirrored emotion).

**Priority 5 — Relationship (L3).**
- Familiarity up → `formality` down within band, initiative propensity up, memory-anchored references allowed (e.g., referencing an ongoing project).
- Style preference from Memory (e.g., "keep it short") overrides P2 depth defaults (still within bands).
- New user → `responsive` initiative, neutral register, minimal humor.

**Priority 6 — Conversation state (L4).**
- Follow-up on prior work → `summarize` prior result briefly, then answer.
- Repeated failure this session → `encourage`, focus on next step, no repetition of failed suggestion.
- Correction received this session → apply corrected style for the rest of the session.

### 7.3 Decision determinism

- All rules are pure functions over typed inputs. No randomness, no wall-clock influence on the *decision* (only on L4 TTL expiry).
- Each decision records a `reason_code` (e.g., `task:GENERATE_CODE`, `risk:HIGH`, `emotion:urgency:0.8`) into `decision_reasons` for auditability and testing.

---

## 8. Relationship Model

### 8.1 Principles

- **Emergent, never hardcoded.** There are no relationship stages ("stranger → friend → confidant"). Instead there are continuous metrics, recomputed from Memory on every request.
- **Memory is the only source of truth.** The engine derives from Memory and stores nothing of its own. Maturation is simply Memory maturing over months.
- **Asymmetric by design.** Relationship may only shift *communication* levers, never governance or planning.

### 8.2 Derived metrics and their memory sources

| Metric | Continuous range | Derived from (Memory via M12) |
|---|---|---|
| `familiarity` | [0,1] | volume/recency of `conversation` memories; distinct sessions; interaction cadence |
| `style_profile` | per-dimension [0,1] | `preference` memories (e.g., brevity, depth, tone, structure); exact-normalized content matching |
| `project_context` | vector | `knowledge`/project memories; document reads |
| `habit_strength` | [0,1] | repeated `workflow`/`tool` memories, recurring `GoalIntent`s |
| `trust_comfort` | [0,1] | permission history surfaced via CAP read path (STORE_PERMISSION counts, absence of DENY), long-term stable interaction |
| `expertise_estimate` | [0,1] (low-confidence) | sophistication of tool usage, project complexity | 

### 8.3 Usage constraints

- `expertise_estimate` may only nudge `explanation_depth` and is capped to a weak effect (assumed `uncertain` unless confidence is high).
- `trust_comfort` may influence initiative level but is bounded so it can never justify an unapproved action.
- All metrics are decay-weighted by memory timestamps; a stale memory contributes less. No metric is stored; each is recomputed per request, which makes drift impossible to persist accidentally.

### 8.4 Maturation loop

```
interaction → Memory Formation (Phase 8.2) persists typed memories
   → next request reads Memory → RelationshipManager re-derives metrics
   → metrics gently shift L3 deltas within L1 bands
```

Observation candidates produced by the engine (e.g., "user prefers terse file listings") are emitted in `InteractionMetadata.observation_candidates` and are only persisted if Memory Formation's classifier accepts them (confidence-gated). This preserves "the engine never stores relationship data directly."

---

## 9. Emotional-Awareness Model

### 9.1 Detection (not simulation)

The **EmotionalAnalyzer** estimates the user's state from deterministic linguistic features of the current message and short context. It uses **no model calls**.

Feature groups:
- **Intensity markers:** exclamation-marks, ALL-CAPS, repeated punctuation, emphasis words, emoji.
- **Frustration markers:** "again", "still", "why", "this doesn't work", "error", "seriously", repeated negations.
- **Urgency markers:** "now", "asap", "quick", "urgent", short imperative length, time references.
- **Excitement markers:** "awesome", "great", "finally", "thank you", "!!!", positive emoji, longer positive runs.
- **Uncertainty markers:** "maybe", "I think", "not sure", "guess", "?", hedging clusters, incomplete phrasing.
- **Politeness/directness:** "please", "thanks", imperatives, sentence length, clause structure.
- **Context modifiers:** prior-turn frustration decay, session state (repeated failures), CAP risk level.

Outputs (`EmotionalSignals`): `frustration`, `urgency`, `excitement`, `uncertainty`, `valence`, `activation` (all [0,1]) plus `confidence` and `unsure` (flag when signal is weak/contradictory — used to fall back to neutral defaults).

### 9.2 Mapping to behavior

| Signal state | Pacing | Wording | Depth | Initiative |
|---|---|---|---|---|
| high urgency | fast | direct first | brief-to-balanced | no proactive moves |
| high frustration | normal-to-fast | non-defensive, fix-first | brief | light encourage only |
| high uncertainty | measured | explicit structure | detailed with confirmations | ask clarifying |
| high excitement | normal | supportive, light encourage | balanced | may offer next step |
| unsure/low signal | normal | neutral defaults | task-driven | default |

### 9.3 Emotional guardrails

- The engine **detects**, never claims to feel. The directive may encode "user seems frustrated → prefer concise, non-defensive wording"; it must never encode "I feel frustrated".
- Signals are parameter adjustments, never value judgments about the user.
- All adjustments are clamped by L1 bands; a highly emotional turn cannot push the engine into flattery, fabricating empathy, or abandoning honesty.
- `confidence` below threshold ⇒ neutral defaults (avoid over-adaptation on noise).

---

## 10. Integration with CAP

### 10.1 Read-only observance

The engine receives `PolicyDecision` (risk, privacy, permissions) and the task-level `ExecutionPermit`s as inputs. It uses them only to tune wording:
- High risk/privacy → more formal register, explicit-what-will-happen structure, no humor, measured pacing.
- `PrivacyCategory.SENSITIVE/CRITICAL` → the directive flags `minimal_disclosure` wording; the existing CAP output filter remains the final arbiter over the rendered text.

### 10.2 Boundaries

- **Cannot bypass CAP:** the engine runs after CAP decisions and never re-evaluates them. Denied requests never reach it. Its directive cannot contain instructions that would circumvent a CAP constraint; the ConsistencyGuard rejects such directives and fails closed to the identity-only default.
- **Cannot delay CAP:** the engine adds negligible, bounded latency and never triggers new approval flows.
- **CAP still governs output:** the serialized directive passes through the existing post-generation privacy filter like any other input; governance is unchanged.

---

## 11. Integration with Memory

### 11.1 Read path (the only path)

- M12 `MemoryReader` wraps the existing `MemoryController` facade, exposing only read methods: `retrieve`, `retrieve_recent`, `retrieve_semantic`, `search_documents`, `check_read_access`.
- Queries are scoped per request (session_id/user_id) and filtered to relevant types: `preference`, `knowledge`, `workflow`, `tool`, `conversation`.
- Read access is enforced with `check_read_access` so the engine never surfaces protected memory into any downstream channel.
- The engine reuses the orchestrator's already-retrieved memory context where available (no redundant retrieval) and supplements with targeted preference/project queries.

### 11.2 Write path (forbidden to the engine)

- The engine never calls write methods. Its only "output" to memory is `observation_candidates` in `InteractionMetadata`.
- Persistence of candidates is performed exclusively by the Phase 8.2 Memory Formation Engine in orchestrator step 7, which applies its own classifier, dedup, and confidence rules.
- Result: Memory remains the single source of truth for all relationship and maturation data. Deleting a memory retracts the relationship signal it carried — with no stale engine-side copy.

---

## 12. Integration with GAMBIT

### 12.1 Read-only plan features

The engine consumes `ExecutionPlan` fields: `goal.intent`, `goal.complexity`, `goal.requires_code/requires_local_model`, `goal.constraints`, task kinds, and `router_request`. These drive Priority 2/3 rules (§7.2).

### 12.2 Attachment without modification

- The directive is attached to runtime tasks as `inputs["personality"]` and to `RuntimeContext.metadata["personality"]` — additive metadata only.
- It must not change: task set, order, dependencies, permits, `RouterRequest` fields, or plan notes. The ConsistencyGuard verifies the plan object is untouched (`plan_readonly_ack`).
- GAMBIT remains the sole reasoning engine; the directive never feeds back into GAMBIT for the current turn and never influences skill injection, decomposition, or reflection.

### 12.3 Router neutrality

The directive is not a routing input. `RouterRequest` is fixed by GAMBIT before the engine runs. Serialization of the directive happens at the provider boundary *after* routing, so model selection is provably unaffected.

---

## 13. Future Scalability

The engine is designed so additions plug in without redesign. All extension points are interfaces (protocols) registered in `PluginRegistry`; the deterministic core never depends on a concrete plugin.

| Future capability | Extension point | How it plugs in |
|---|---|---|
| Voice personality | channel adapter | consumes the same `CommunicationDirective`; maps register/pacing to speech prosody; no engine change |
| Avatar expressions | channel adapter | maps `EmotionalSignals` + tone to expression state; no engine change |
| Multi-agent personalities | identity selector | per-request `IdentityManager` resolution by agent role; same lever model |
| Multilingual behavior | tone/style resolvers | language-aware resolvers behind M7/M9 interfaces; directive stays language-neutral (register, depth, pacing) |
| Offline / learned style models | `EmotionalAnalyzer`, `ToneResolver`, `InitiativeDecider` plugins | optional local models behind the same interfaces; core remains deterministic fallback |
| Personality plugins | `PluginRegistry` | versioned trait overrides + rule providers with validation; rejected if they violate L1 bands |
| New behavior levers | rule providers | additive rules with their own `reason_codes`; L1 bands extended via profile version bump |

Design guarantees for extensibility:
- Module dependency is one-way: engine core → module interfaces → plugins. No plugin can reach CAP/GAMBIT/Runtime/Memory write APIs.
- `CommunicationDirective` and `InteractionMetadata` are versioned schemas; unknown fields are forward-compatible (additive-only).
- The `determinism_hash` covers the core decision path, so plugin absence/presence is auditable per request.

---

## 14. Risks and Mitigations

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Personality drift / identity inconsistency across sessions | user loses trust; feels like different assistants | L1 immutable bands; L3 only moves as fast as Memory; `determinism_hash` + consistency tests |
| R2 | Sycophancy / flattery creep as familiarity rises | violates philosophy | NO_FLATTERY hard rule; warmth ceiling far from extremes; challenge default on |
| R3 | Emotional manipulation or fake empathy | dishonest, off-brand | engine adjusts parameters only; NO_EMOTION_FABRICATION; signals never serialized as feelings |
| R4 | Directive bypasses CAP | governance breach | engine runs post-CAP; guard fails closed to identity-only default; CAP output filter still applies; governance ack in compliance |
| R5 | Engine writes/invents memories | pollutes Memory, breaks source-of-truth | write methods excluded from M12; candidates only via Memory Formation classifier; NO_MEMORY_INVENTION rule |
| R6 | Over-adaptation (personality changes every turn) | feels unstable | L5 deltas clamped small; L3 recomputed from memory (slow); low-confidence emotional signals use neutral defaults |
| R7 | Latency overhead on every turn | poor UX | all modules deterministic, sub-ms compute; reuses existing memory retrieval; optional per-session L4 cache of L3 metrics with short TTL and safe invalidation |
| R8 | Model ignores the directive | behavior not applied | directive serialized as system-context at provider boundary; bounded length; the serializer is the single, tested application point |
| R9 | Privacy leakage into the model | sensitive memory surfaced | M12 enforces read-access checks; serializer strips governance/data fields; CAP output filter remains final |
| R10 | Non-determinism breaks tests/reproducibility | untestable subsystem | pure functions; no randomness/LLM/embeddings; golden-file behavior tests; hash verification in the guard |
| R11 | Multi-user isolation failure | cross-user personality bleed | state keyed by session/user; identity per request; L4 store isolated per session; no cross-user caches |
| R12 | Directive scope creep (influences planning/tools) | violates invariants | explicit contract test suite asserts no plan mutation, no tool calls, no router hints; guard rejects violations |

---

## Appendix A — Proposed code layout

```
app/personality/
  __init__.py            # exports PersonalityEngine facade
  contracts.py           # PersonalityRequest, CommunicationDirective, InteractionMetadata,
                         #   EmotionalSignals, RelationshipState, BehaviorDecisions, versioned schemas
  engine.py              # PersonalityEngine facade (async-compatible, deterministic core)
  identity.py            # M1 IdentityManager (constitution + bands, code-defined)
  traits.py              # M2 TraitManager (baseline vector, config-driven)
  relationship.py        # M3 RelationshipManager (MemoryReader → metrics + observation candidates)
  state.py               # M4 InteractionStateManager (ephemeral per-session store)
  emotional.py           # M5 EmotionalAnalyzer (deterministic feature rules)
  policy.py              # M6 BehaviorPolicyEngine (priority cascade rule set)
  tone.py                # M7 ToneEngine
  initiative.py          # M8 InitiativeManager
  style.py               # M9 ConversationStyleManager
  composer.py            # M10 Composer
  guard.py               # M11 ConsistencyGuard (validation + determinism hash)
  reader.py              # M12 MemoryReader (read-only MemoryController port)
  serializer.py          # M13 DirectiveSerializer (model-bound adapter; content in impl phase)
  plugins.py             # M14 PluginRegistry + module protocols
```

## Appendix B — Integration points in the existing pipeline

| Point | File (current) | Change (Phase 9) |
|---|---|---|
| Compute directive (step 5.5) | `app/core/orchestrator/engine.py` (`run_pipeline`) | after CAP task-permit loop, before `WorkflowEngine.execute`; attach to `RuntimeContext.metadata["personality"]` and task `inputs["personality"]` |
| Apply at provider boundary (streaming) | `app/agent/production.py::_StreamingRuntimeBridge.run` | read directive → `DirectiveSerializer` → `StreamRequest` |
| Apply at provider boundary (non-streaming) | `app/runtime/executor.py::ProviderExecutor` | read directive → serializer → provider payload |
| Feed observation candidates | `app/core/orchestrator/engine.py` (step 7) | pass `InteractionMetadata.observation_candidates` to Memory Formation engine |
| Read-only memory port | `app/memory/controller/facade.py` | no change — M12 wraps the existing facade read methods |
| Composition root | `app/core/app.py::create_orchestrator` | construct `PersonalityEngine` + `MemoryReader`; inject into orchestrator |

## Appendix C — Testing strategy (architecture-level)

- **Contract tests:** directive schema stability; versioning; `determinism_hash` verification.
- **Invariant tests:** directive never contains plan/tool/router/governance fields; plan object identity/equality unchanged after engine runs; no write method callable through M12.
- **Determinism tests:** same input tuple → identical output; plugin absence/presence auditable.
- **Behavior golden tests:** curated (message, memory snapshot, plan, risk) tuples → expected lever decisions + reason codes.
- **Band tests:** every lever respects L1 bands across adversarial inputs (rage, crisis, euphoria, ambiguity, new user, 5-year user).
- **Memory integration tests:** relationship metrics change only when memory changes; deleting a memory retracts its signal; protected memories never reach downstream.
- **Boundary tests:** denied requests never reach the engine; router request unchanged; CAP output filter still applies to serialized directive.

---

*End of Phase 9 architecture specification.*
