# Controlled Pilot Operator Runbook

## Scope

Operate only private Stage A–C cohorts. Do not publish, auto-enroll, auto-update, or claim public-release readiness. Use the capability contract in `PILOT_SCOPE.md` as product truth.

## Stage A — internal smoke

Participants: maintainers on known Windows machines.

Required before advancement:

- verified artifact hash and build origin;
- fresh install, bootstrap, offline doctor, mutex, recovery, and uninstall-retention checks pass;
- P13 adversarial, architecture, production, stress, plugin, pilot, and full suites have zero failures;
- no SEV-0/SEV-1 event;
- every discovered operational issue has a reproducible record.

## Stage B — very small trusted cohort

Participants: 3–5 invited technical users. Plugins remain excluded.

Required before advancement:

- at least 90% first-attempt installation and first-start success, with every failure understood;
- 100% of participants can identify what an approval will do and can deny/cancel it;
- no unauthorized or duplicate effect, cross-user/session leak, signing/checkpoint corruption, or false success;
- diagnostic bundles are sufficient without collecting prompts, responses, memory, or file contents;
- no open SEV-0/SEV-1 and a documented disposition for every SEV-2.

## Stage C — expanded controlled cohort

Participants: 10–15 invited users only after Stage B passes.

Advancement is paused immediately for any SEV-0/SEV-1, unexplained duplicate effect, isolation failure, unsafe recovery, or release-hash mismatch. P14 engineering readiness alone does not authorize Stage B or C.

## Normal operating procedure

1. Give the user the artifact, exact version, SHA-256, unsigned-build warning, release notes, and rollback document.
2. Have the user run `bootstrap`, `bootstrap --status`, then `doctor`.
3. Configure a provider only in the launch process environment. Never ask for the credential value.
4. Keep work inside the governed workspace.
5. Explain that approvals bind one exact operation. Deny or cancel anything unclear.
6. Treat simulated message/email results and SMTP `PROVIDER_ACCEPTED` as non-delivery.
7. If support is needed, ask the user to run `samaktha.exe doctor --export`. The user decides whether to share the resulting local JSON file.
8. Stop with Ctrl+C/normal TUI exit. If unresponsive, terminate the Samaktha process; recovery rules prevent unsafe unknown-mutation replay.

## Local stop controls

- Stop the process or remove its shortcut to prevent restart.
- Clear/disable external-provider environment variables before relaunch.
- Deny or cancel pending executions through the existing interface/API.
- Cancel pending reminders using the governed reminder action.
- Plugins are excluded from the initial pilot. Engineering operators can disable/unload a test plugin through the existing P9 lifecycle harness; no remote kill switch exists.

## Privacy-preserving local metrics

Record only aggregate installation success, first-start/doctor status, crash count, execution result classes, approvals, cancellations, recoveries, provider error classes, startup latency, plugin engineering-smoke failures, and resource-health summaries. Never aggregate prompts, responses, memory, files, clipboard, or message/email bodies.

## Support package

The default diagnostic bundle contains version/platform, health labels/statuses, provider names/configuration booleans, capability names/modes, aggregate store/plugin counts, and active thread count. It is local and never uploaded automatically.
