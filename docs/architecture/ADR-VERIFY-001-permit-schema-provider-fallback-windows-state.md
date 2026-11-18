# ADR-VERIFY-001 — Permit Schema Evolution, Provider Fallback Identity, and Windows Security-State Coverage

- **Status:** PROPOSED (decision study / audit record — no production, test, or configuration code changed)
- **Date:** 2026-10-11
- **Area(s):** CAP/Runtime authorization boundary; provider routing fallback; Windows local security state
- **Scope:** Source-and-test verification only. This ADR does not authorize implementation.
- **Canonical rule applied:** empirical evidence from source and executable tests supersedes every pre-existing audit claim. Prior reports (`SAMAKTHA_VERIFICATION_BASELINE.md`, `SAMAKTHA_POLYGLOT_ARCHITECTURE.md`, `SAMAKTHA_CURRENT_STATE_AUDIT.md`) are treated as **hypotheses** and re-verified here.

---

## 1. Executive Summary

Three verification questions were asked of the current `main` tree
(`5cf87a1` — "Architecture Polyglot"):

1. **Can `ExecutionPermit` evolve without invalidating existing signed/checkpointed permits?**
   → **No clean path exists.** There is no permit schema-version field and no
   stored-permit migration contract. Any field add/remove/rename/enum-or-default
   change alters the HMAC because the signature is computed over the *entire*
   `model_dump()` (defaults included). Unknown/removed fields raise
   `ValidationError` (`extra="forbid"`). Behavior is **fail-closed**, but the
   failure is unclassified and produces no migration or operator diagnostic.

2. **Can a sensitive (`requires_local_model=True`) request be executed by a provider other than the CAP-bound one?**
   → **Yes.** The Router excludes mock, but `ProviderManager` does not. An
   independent probe (this session) reproduced a `SENSITIVE` local-only request
   being answered by the **mock** provider (`provider_id: "mock"`,
   `content: "mock-content"`), with cloud correctly excluded. Governance
   (`enforce_provider`) validates only the **routed** provider id and is never
   re-run on the fallback provider. A second fidelity defect: the **streaming**
   result records `routing.provider_id` (e.g. `local`) while the tokens were
   produced by the fallback provider (e.g. `mock`).

3. **Is Windows security state consistently hardened and independently verified?**
   → **Partially.** The permit-signing key is hardened with a protected DACL and
   validated by a live `icacls` test. `checkpoint_integrity.json` is hardened on
   save/load (with a brief temp-file exposure window). **Checkpoint JSON files
   and the checkpoint directory are not individually hardened**, and the evidence
   SQLite database (plus WAL/SHM) is not hardened. All ACL-repair tests
   monkeypatch the hardener; only the SDDL string and the single key `icacls`
   test are exercised against the OS.

**Net:** the CAP permit is an intact, tamper-evident control record, but the
**identity of the component that actually executes** is not bound into it and is
not reconciled after fallback; and the permit has no forward/backward
compatibility mechanism. Both are control-plane defects that must be closed
before the permit is allowed to cross any new (native/polyglot) executor
boundary.

---

## 2. Verification Matrix

Status vocabulary is restricted to:
`VERIFIED_IN_SOURCE_AND_TESTED`, `PRESENT_IN_SOURCE_NOT_TESTED`,
`PARTIALLY_IMPLEMENTED`, `CONTRADICTED_BY_SOURCE`, `UNVERIFIED`.
A status of `VERIFIED_IN_SOURCE_AND_TESTED` requires a test that exercises the
real code path — mocked-only coverage is never promoted to this status.

### Area A — ExecutionPermit schema evolution

| # | Claim / predicate | Status | Evidence |
|---|---|---|---|
| A1 | `ExecutionPermit` carries an explicit schema version | **CONTRADICTED_BY_SOURCE** | `app/core/contracts/policy.py:187-211` has no `schema_version` field; `grep` finds `schema_version` in checkpoint/evidence/session/plugin/bootstrap only, never in the permit. `policy_reference` is a *policy* ref, not a permit-schema version. |
| A2 | Permit integrity covers the entire record (all fields, including defaults) | **VERIFIED_IN_SOURCE_AND_TESTED** | `policy.py:257-259` signs `model_dump(exclude={"integrity_digest"})` via `_sign_permit`; `tests/security_adversarial/test_p13_permits.py` field-tampering tests fail integrity as expected. |
| A3 | Unknown/extra permit fields are rejected | **PRESENT_IN_SOURCE_NOT_TESTED** | `model_config = ConfigDict(frozen=True, extra="forbid")` (`policy.py:190`). Tampering tests mutate known fields; no test injects an unknown field. |
| A4 | Adding a field (even with a default) to the permit invalidates previously signed permits | **CONTRADICTED_BY_SOURCE** (no migration; breaks verification) | Signature derives from full `model_dump()`; a new defaulted field changes the signed canonical payload, so `verify_integrity()` returns `False` on an old stored permit. No compatibility shim exists. |
| A5 | A stored permit is persisted in checkpoints and re-validated on resume | **PARTIALLY_IMPLEMENTED** | Persisted inside `pipeline_state…tasks[].metadata["permit"]` (`app/runtime/checkpoint.py:185-214`); re-read via `ExecutionPermit.model_validate(pending_data)` (`app/core/orchestrator/engine.py:1024`) and `ExecutionPermit(**permit_data)` (`app/workflow/engine.py:568`). No test persists a real issued permit through checkpoint serialize→deserialize→validate (restart tests use stub orchestration / non-permit checkpoints). |
| A6 | An interface cannot inject/blanket a permit | **VERIFIED_IN_SOURCE_AND_TESTED** | `resume_pipeline` raises `ValueError("Interfaces may submit an approval decision, not an ExecutionPermit.")` (`engine.py:1006-1009`); covered by adversarial resume tests. |
| A7 | Incompatible stored permit fails closed with a classified diagnostic | **PARTIALLY_IMPLEMENTED** | Fails closed via `ValidationError` / integrity mismatch, but `CheckpointFailureCode` has no permit-schema code (`checkpoint.py:22-31`); the mismatch surfaces at resume as an unhandled validation error, not a clean operator diagnostic or migration prompt. |
| A8 | A v1→current permit migration/version contract exists | **CONTRADICTED_BY_SOURCE** | None found in `app/` (contrast: session store has explicit `schema_version` migration maps, `app/memory/session_store.py:126-214`). |

### Area B — Provider fallback authorization and identity fidelity

| # | Claim / predicate | Status | Evidence |
|---|---|---|---|
| B1 | Cloud providers are excluded under `requires_local_model=True` (sync + stream) | **VERIFIED_IN_SOURCE_AND_TESTED** | `_candidate_infos` filters on `execution_location == LOCAL` (`app/providers/manager.py:169-181`); `tests/production/test_p1_governance_convergence.py:501,536` assert `cloud_calls == 0`. Independent probe: cloud calls = 0. |
| B2 | Mock is excluded under `requires_local_model=True` | **CONTRADICTED_BY_SOURCE** | Independent probe (this session): candidates `['local','mock']`; result `success=True, provider_id='mock'`. Registered mock is `ExecutionLocation.LOCAL` (`app/core/app.py:717-727`); `ProviderManager` has no `provider_kind` notion (`app/providers/models.py`). |
| B3 | The Router excludes mock for sensitive routing | **VERIFIED_IN_SOURCE_AND_TESTED** | `app/router/router.py:73,91` filters `provider_kind != "mock"`. |
| B4 | Governance is re-evaluated for the provider that *actually* executes after fallback | **CONTRADICTED_BY_SOURCE** | `ProviderExecutor` calls `enforce_provider(routing.provider_id)` once (`app/runtime/executor.py:97-104`); fallback occurs inside `ProviderManager.execute_provider`, which never re-invokes governance. |
| B5 | The permit binds provider identity (so the executor can be reconciled) | **CONTRADICTED_BY_SOURCE** | `authorization_target("text_generation")` returns `"provider:text_generation"` (`policy.py:384-388`); no provider id participates in the permit or its digest. |
| B6 | The recorded result reflects the actual executing provider | **PARTIALLY_IMPLEMENTED** | Sync path: `_normalize_response` returns the real provider id (`manager.py:367`; executor `:238`). Streaming path: `output["provider_id"] = routing.provider_id` (`executor.py:205-211`) — records the *routed* provider even when a fallback produced the tokens. Tokens carry the real provider only in per-chunk metadata (`executor.py:192-195`). |
| B7 | Tests prove no forbidden provider is ever invoked | **PARTIALLY_IMPLEMENTED** | Tests prove cloud is never invoked; they deliberately monkeypatch mock `.execute` to fail (`test_p1_governance_convergence.py:516-517`), which *confirms* mock sits in the candidate list rather than asserting it is excluded. No test asserts mock is never selected for sensitive work, and none covers streaming identity. |

### Area C — Windows security-state coverage

| # | State surface | Hardened in source | Status | Evidence |
|---|---|---|---|---|
| C1 | `permit_signing.key` | Protected DACL (`D:P` + owner/SY/BA); created then hardened before first read; bounded repair for canonical path only; identity mismatch fails closed | **VERIFIED_IN_SOURCE_AND_TESTED** | `app/core/app.py:234-661`; live `icacls` assertion `tests/security_adversarial/test_p13_windows.py:55-65` (runs on win32: no inherited `(I)`, exactly three `(F)`). |
| C2 | `checkpoint_integrity.json` | Bound hardener applied on save + load/repair | **PARTIALLY_IMPLEMENTED** | `app/core/app.py:1762-1769`, `app/runtime/checkpoint.py:526-549`. Temp file `…<pid>.tmp` is created and `os.replace`d **before** `secure_file(path)` (`checkpoint.py:538-546`) → brief window with inherited DACL. Live OS-level assertion absent (tests monkeypatch the hardener, e.g. `test_checkpoint_integrity_reconciliation.py:127`). |
| C3 | Checkpoint JSON files (`<execution_id>.json`) | None | **CONTRADICTED_BY_SOURCE** | Written with plain `open(...)`, no `secure_file` (`checkpoint.py:209-220`); rely entirely on directory DACL. |
| C4 | Checkpoint directory | None | **CONTRADICTED_BY_SOURCE** | `self._directory.mkdir(parents=True, exist_ok=True)` only (`checkpoint.py:166-167`); never passed to a hardener. |
| C5 | Evidence SQLite DB (+ `-wal`/`-shm`) | None | **CONTRADICTED_BY_SOURCE** | `app/evidence/store.py:74-86` creates parent dir and uses WAL; no DACL hardening anywhere; wired without a hardener (`app/core/app.py:1778-1789`). |
| C6 | Interactive credentials | Windows Credential Manager, `CRED_PERSIST_LOCAL_MACHINE=2` | **PARTIALLY_IMPLEMENTED** | `app/config/credentials.py:82-121`. LocalMachine persistence means any same-user process can `CredRead` the blob; no per-credential ACL is set; live behavior untested (in-memory store injected in tests). |
| C7 | ACL enforcement verified against the live OS | — | **UNVERIFIED** (general) | Only the key DACL (C1) and SDDL string (`test_permit_signing_key_acl_repair.py:236`) are exercised for real; all repair/identity paths monkeypatch `_harden_private_file_permissions` (`:96,128,157,186,218,269,318,375,405`). |

---

## 3. Detailed Findings

### 3.1 Area A — no permit schema-evolution contract (HIGH, correctness/gate)
- The permit is a `frozen`, `extra="forbid"` Pydantic model signed over every
  field. Field evolution therefore has only two outcomes: silently verify (no
  change to signed fields) or fail closed (any change to the signed field set).
  There is no `schema_version`, no tolerant reader, and no migration map.
- On restart, an out-of-date stored permit reaches
  `ExecutionPermit.model_validate(...)` / `ExecutionPermit(**...)` and raises
  `ValidationError`. This happens *after* checkpoint integrity has passed, so it
  is not surfaced through `CheckpointFailureCode`; operators get a raw validation
  error rather than a "permit schema unsupported; migrate or discard" decision.
- Because defaults are signed, even an *additive, backward-compatible* field
  breaks verification of every pre-existing permit — the most dangerous class of
  change, since it looks harmless.

### 3.2 Area B — fallback is not permit-bound and not re-governed (HIGH, authorization scope)
- Confirmed independently this session:
  ```
  SYNC requires_local candidates: ['local', 'mock']
  SYNC result success: True provider_id: mock content: mock-content
  SYNC calls -> local: 0 mock: 1 cloud: 0
  STREAM chunks: [('started','local'),('token','mock'),('completed','mock')]
  ```
- `enforce_provider` runs once for `routing.provider_id`; the fallback provider
  executes with **no** governance decision recorded against it. Combined with
  B5, the permit's `target` (`provider:text_generation`) cannot be reconciled to
  the executing provider.
- Streaming compounds this: the assembled result advertises `routing.provider_id`
  (B6), so evidence/diagnostics can attribute mock output to a local model.
- Severity note: cloud is genuinely excluded under `requires_local_model`, so the
  defect is **fallback-fidelity / authorization-scope** (fabricated or
  mis-labeled output, unaudited executor identity), not direct cloud exfiltration.

### 3.3 Area C — uneven Windows security-state hardening (MEDIUM, defense-in-depth)
- The most sensitive artifact (signing key) is well defended and live-verified.
- The integrity index is hardened but with a short temp-file window and no live
  OS assertion.
- Checkpoints (which contain permits and pipeline state), the checkpoint
  directory, and the evidence DB rely on inherited directory permissions. On a
  default per-user install this is acceptable, but it is inconsistent with the
  stated "integrity-protect security state" posture and is the surface a native
  broker would need to inherit.

---

## 4. Proposed Decision (PROPOSED — not yet ratified)

> **DECISION (proposed):** Treat the permit as the single reconciled identity
> contract for execution. Before the permit may cross any new executor boundary
> (native broker, remote worker, plugin host), the following three changes are
> prerequisites:
>
> 1. **Bind executing identity and reconcile it.** Add an `executor_identity`
>    (provider id / tool id, and the transport used) to the permit's bound
>    operation, and require `ProviderExecutor` (sync **and** streaming) to
>    (a) re-invoke governance for the provider that actually executed, and
>    (b) record the actual provider id in the result. Fail closed if the actual
>    executor does not match the permit. Mock must be excluded whenever
>    `requires_local_model` is set, in `ProviderManager` — not only in the Router.
> 2. **Version the permit.** Add an explicit `permit_schema_version`, keep a
>    tolerant read path, and introduce a migration/`CheckpointFailureCode`
>    (`PERMIT_SCHEMA_UNSUPPORTED`) so stored-but-incompatible permits produce a
>    clean, classified, operator-visible outcome instead of a raw
>    `ValidationError`.
> 3. **Make Windows security-state hardening uniform and live-verified.** Extend
>    the bound hardener to the checkpoint directory/files and the evidence DB
>    (and close the integrity-index temp window), and add a live (non-mocked)
>    assertion equivalent to the existing key `icacls` test.

Concrete, minimal acceptance criteria:

- A sensitive (`requires_local_model=True`) request **cannot** complete via mock;
  a dedicated regression asserts `mock.calls == 0` in both sync and streaming
  paths.
- A permit issued today still verifies after crossing the checkpoint round-trip,
  and a permit carrying an unknown/older `permit_schema_version` is rejected with
  a classified `PERMIT_SCHEMA_UNSUPPORTED` diagnostic (test included).
- Streaming results report the **actual** provider id, and governance records a
  decision for it.
- `icacls`-level tests exist for `checkpoint_integrity.json` and at least one
  checkpoint file; all ACL tests stop monkeypatching the hardener for at least one
  real end-to-end case.

---

## 5. Consequences

- **Positive:** closes the only path where a CAP permit's stated scope diverges
  from what executed; makes permit evolution safe and auditable; makes Windows
  state coverage explicit and testable.
- **Cost / risk:** permit-versioning is a schema change to a security contract
  and must be done fail-closed with migration tests; provider-identity binding
  touches the hot routing/fallback path; hardening additional paths can fail on
  non-canonical/CI filesystems and must degrade with a warning, not a crash.
- **Non-goals:** no change to CAP semantics, no new executor authority, no
  polyglot component; this ADR is a gate on those, not a green light.
- **Explicitly rejected:** "fixing" fallback by trusting the Router alone
  (defense must exist at the execution boundary), and adding permit fields
  without a version/migration path.

---

## 6. Evidence Log (this session)

Environment: repo `C:\Users\user\Desktop\Samaktha`, HEAD `5cf87a1`; interpreter
`.venv\Scripts\python.exe` (CPython 3.14.5, pytest 9.1.1). All pytest runs used a
fresh `--basetemp` (the default user temp path raises `WinError 5`).

| Command | Result |
|---|---|
| `pytest tests/production/test_p1_governance_convergence.py` | 25 passed |
| `pytest tests/security_adversarial/{test_p13_permits,test_checkpoint_integrity_reconciliation,test_permit_signing_key_acl_repair,test_p13_windows}.py` | 59 passed, 2 warnings (intentional permit-tamper pydantic serializer warnings) |
| `pytest tests/providers tests/router tests/runtime tests/pilot tests/windows` | 218 passed, 1 warning |
| Independent fallback probe (temporary script, outside repo) | mock selected for `requires_local_model=True`; cloud excluded; streaming result attributes routed provider, tokens attribute mock |

Diagnostic artifacts were created only under the OS temp directory and are not
part of the repository.

## 7. References

- `app/core/contracts/policy.py` (permit model, signing, targets)
- `app/runtime/executor.py`, `app/providers/manager.py`, `app/router/router.py`, `app/providers/health.py`
- `app/runtime/checkpoint.py`, `app/core/app.py`, `app/evidence/store.py`, `app/config/credentials.py`
- `tests/security_adversarial/*`, `tests/production/test_p1_governance_convergence.py`, `tests/production/test_p6_runtime_reliability.py`, `tests/security_adversarial/test_p13_windows.py`
- Pre-existing hypotheses: `docs/architecture/SAMAKTHA_VERIFICATION_BASELINE.md` (S1/S2/M5), `docs/architecture/SAMAKTHA_POLYGLOT_ARCHITECTURE.md` (Stage 1), `docs/ARCHITECTURE_STATE.md` (invariants 7 and 2).
