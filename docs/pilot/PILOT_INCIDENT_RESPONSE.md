# Pilot Incident Response

## Severity

**SEV-0 — security/privacy emergency:** unauthorized side effect, active permit/governance bypass, exposed credential/signing material, or confirmed cross-principal data disclosure. Stop pilot expansion immediately, stop affected instances, preserve sanitized evidence, rotate exposed secrets/keys, and do not reuse suspect state until reviewed.

**SEV-1 — safety/integrity failure:** duplicate/destructive effect, cross-session leak, unsafe unknown-mutation replay, unrecoverable corruption, checkpoint integrity failure, or plugin execution outside the canonical path. Stop pilot expansion and roll back/quarantine affected state.

**SEV-2 — major reliability failure:** persistent crash, failed recovery, unusable provider/tool capability, broken installation on a supported machine, or diagnostics unable to explain a failure. Pause the affected cohort/capability; advancement requires a reproduced fix and relevant regression/stress rerun.

**SEV-3 — non-critical UX/configuration/documentation defect:** confusing copy, recoverable setup error, or cosmetic issue without incorrect execution truth. Track and prioritize without weakening controls.

## Intake and containment

1. Assign an incident ID, severity, owner, start time, affected version/hash, and cohort stage.
2. Ask the user to stop Samaktha if continued execution could cause harm.
3. Do not request credentials or raw prompts/memory/files. Request an execution/correlation ID and optional user-generated diagnostic bundle.
4. Preserve the affected binary hash and a copy of user state only with explicit user consent. Sanitize before sharing.
5. Disable the affected provider locally, deny/cancel pending operations, or remove the build shortcut as appropriate.
6. For SEV-0/SEV-1, freeze cohort expansion until root cause, fix, regression, rollback decision, and user notification are complete.

## Engineering response

Classify the issue as validation harness, documentation, UX/operational, production correctness, or security/privacy. Security fixes rerun relevant P13 adversarial tests. Recovery/concurrency fixes rerun relevant P12 stress/packaged tests. Never create a bypass to restore convenience.

## Closure

Record root cause, affected scope, evidence, code/doc changes, exact verification results, data/credential remediation, and the decision to resume or terminate the pilot stage.
