# Samaktha Core

**Version 0.5.0 — engineering-ready controlled-pilot candidate**

Samaktha is a local-first AI-agent infrastructure project for policy-governed,
observable execution. Models may plan or generate content, but deterministic
application code controls authorization, provider selection, tools, recovery,
and execution evidence.

This repository is ready for a private Windows pilot. It is not a public
release, and no real-user pilot result is claimed yet.

## Canonical production architecture

```text
Interface (API / CLI / TUI / Voice adapter)
  → ExecutionCoordinator
  → SamakthaOrchestrator
  → CAP policy, approval, and exact ExecutionPermit
  → GAMBIT deterministic planning
  → WorkflowEngine
  → Router
  → RuntimeEngine
      → ProviderExecutor → ProviderManager → provider
      → ToolExecutor → ToolSecurityEnforcer → ToolManager → tool
  → scoped Memory / durable Evidence / signed Checkpoints
```

`create_orchestrator()` is the production composition root. Runtime is the
only user-reachable provider/tool execution boundary. Tool success comes from
actual execution evidence, never generated prose.

### Architectural invariants

- CAP issues the final permit bound to the exact principal, action, target,
  payload, permissions, risk, and execution constraints.
- GAMBIT plans; it does not execute providers or tools.
- Runtime validates every task permit before executor dispatch, including
  batch/parallel work.
- Router and provider fallback preserve typed local-only/privacy constraints.
- Tool actions pass through `ToolExecutor` and `ToolSecurityEnforcer`.
- Memory and sessions are scoped by principal, session, and workspace.
- Checkpoints are integrity protected; uncertain non-idempotent effects are not
  replayed automatically.
- Evidence is correlated, sanitized, persistent, and separate from generated
  response prose.
- Plugin discovery is not enablement. Enabled plugins remain trusted in-process
  code and execute through the canonical Runtime/tool-security path.

See [Architecture State](docs/ARCHITECTURE_STATE.md) for the maintained public
architecture contract.

## Capability status

| Capability | Pilot status | Notes |
|---|---|---|
| Provider conversation | **Conditional** | Requires a configured healthy local or cloud provider; local-only work cannot fall back to cloud. |
| Filesystem | **Production ready** | Governed roots, approval, path/link controls, and execution evidence. |
| Internet | **Conditional** | Read-only network capability when configured; SSRF, redirect, port, header, and response bounds apply. |
| Shell | **Production ready / advanced** | Allowlisted executable and arguments, governed working directory, timeout, and output bounds. |
| Memory, sessions, reminders, notes, tasks, contacts, calendar | **Local only** | Scoped local persistence; no account or device synchronization. |
| Clipboard, notifications, limited Windows operations | **Local only** | Permission and platform dependent. |
| Email | **Simulated by default** | SMTP is engineering/advanced configuration; provider acceptance is not delivery confirmation. |
| Messaging | **Simulated** | No external SMS or chat provider is connected. |
| Plugins | **Engineering only** | Explicit lifecycle and canonical execution exist; excluded from the initial user cohort. |
| Document extraction | **Internal** | Not independently advertised as a user capability. |
| Browser/media | **Unavailable** | Not registered in production. |

The detailed pilot contract is [PILOT_SCOPE.md](docs/pilot/PILOT_SCOPE.md).

## Requirements and installation

- Python 3.12 or newer for source development
- Windows for the validated 0.5.0 packaged pilot

```powershell
git clone https://github.com/HARI9037/Samaktha.git
cd Samaktha
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Provider credentials are process-environment secrets. `.env` files, runtime
databases, signing keys, checkpoint state, and diagnostic output are ignored and
must never be committed.

## Running Samaktha

```powershell
# First-run state and health
.\.venv\Scripts\samaktha.exe bootstrap
.\.venv\Scripts\samaktha.exe bootstrap --status
.\.venv\Scripts\samaktha.exe doctor

# Interfaces
.\.venv\Scripts\samaktha.exe tui
.\.venv\Scripts\samaktha.exe backend
```

`doctor --export` creates an explicit local, sanitized diagnostic bundle. It
does not upload data and excludes prompts, memory, files, credentials, signing
material, and checkpoint payloads.

Controlled-pilot operators should begin with
[PILOT_INSTALLATION.md](docs/pilot/PILOT_INSTALLATION.md) and
[PILOT_RUNBOOK.md](docs/pilot/PILOT_RUNBOOK.md).

## Testing

The canonical P14 acceptance environment used Python 3.14.5:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONNOUSERSITE = "1"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q
```

Verified P14 engineering baseline:

```text
2851 passed
0 failed
0 skipped
149 warnings
```

Maintained suites include architecture guards, exact-production governance and
capability tests, memory isolation, recovery, tool security, persistent
evidence, plugins, packaging, stress, adversarial security, and pilot readiness.

## Packaging

- `samaktha.spec` is the canonical PyInstaller ONEDIR specification.
- `scripts/build_windows.ps1` performs the Windows build and smoke checks.
- `samaktha.iss` is the per-user Inno Setup source; user data is preserved on
  uninstall.
- `build/`, `dist/`, installer output, and runtime state are generated and are
  not committed.

The current pilot executable is unsigned. Pilot users must verify the artifact
hash supplied in [PILOT_RELEASE_NOTES.md](docs/pilot/PILOT_RELEASE_NOTES.md).

## Documentation

- [Architecture State](docs/ARCHITECTURE_STATE.md)
- [Changelog](docs/CHANGELOG.md)
- [Plugin Guide](docs/PLUGINS.md)
- [Pilot Scope](docs/pilot/PILOT_SCOPE.md)
- [Pilot Security and Privacy](docs/pilot/PILOT_SECURITY_AND_PRIVACY.md)
- [Known Pilot Limitations](docs/pilot/PILOT_KNOWN_LIMITATIONS.md)
- [Pilot Release Notes](docs/pilot/PILOT_RELEASE_NOTES.md)

Version-specific phase documents remain historical engineering records; they do
not override the current architecture state or pilot capability contract.

## License

Samaktha is proprietary software. This public repository is provided for
demonstration, portfolio, transparency, and educational viewing. No license is
granted to copy, modify, redistribute, or commercially use the project.

Copyright © 2026 Sreehari R Nair. All rights reserved.
