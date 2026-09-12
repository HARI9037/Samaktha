# Samaktha Core

**Version 0.5.0 — pilot core reliability validation**

Samaktha is a local-first AI-agent infrastructure project for policy-governed,
observable execution. Models may plan or generate content, but deterministic
application code controls authorization, provider selection, tools, recovery,
and execution evidence.

The current source passed R1–R6 automated reliability convergence: 3,115 tests
passed on 12 September 2026. Real-user acceptance and packaged validation remain
required; no real-user pilot result is claimed yet. See the
[full reliability report](docs/pilot/PILOT_CORE_RELIABILITY_CONVERGENCE_REPORT.md).

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
| Internet | **Conditional** | Governed web/news search uses the zero-key DDGS adapter by default. SearXNG and Brave remain explicit options. Content fetching retains SSRF, redirect, port, header, and response bounds. |
| Shell | **Production ready / advanced** | Allowlisted executable and arguments, governed working directory, timeout, and output bounds. |
| Memory, sessions, reminders, notes, tasks, contacts, calendar | **Local only** | Scoped local persistence; no account or device synchronization. |
| Clipboard, notifications, limited Windows operations | **Local only** | Permission and platform dependent. |
| Email previews | **Local only** | Compose/draft returns an unsaved preview. A requested SEND is never silently converted into a preview. |
| Experimental SMTP send | **Conditional** | Requires explicit setup, secure credential storage, authentication validation, CAP approval, and manual acceptance. Provider acceptance is not delivery confirmation. |
| Messaging | **Simulated** | No external SMS or chat provider is connected. |
| Plugins | **Engineering only** | Explicit lifecycle and canonical execution exist; excluded from the initial user cohort. |
| Document extraction | **Internal** | Basic TXT/Markdown/HTML/DOCX/XLSX and PDF text extraction. OCR is experimental. Docling is disabled after native DLL faults; no document AI claim. |
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

Installed users configure Samaktha with `samaktha setup`. Non-secret settings
are stored under `%LOCALAPPDATA%\Samaktha\config`; provider and SMTP secrets
use the per-user Windows Credential Manager. Environment variables and `.env`
remain higher-precedence development compatibility inputs. `.env` files, runtime
databases, signing keys, checkpoint state, and diagnostic output are ignored and
must never be committed.

Reopening setup with blank secret fields keeps existing credentials and
verification. Enter a replacement to change a credential, or use its explicit
Remove checkbox. Removing the active provider credential switches setup to
offline mode. Stored credentials are never displayed.

The workspace is shown by `samaktha doctor` and at setup completion. For example,
`create a file called report.txt with the text Hello` writes inside that workspace
after authorization. Approval and completion show the actual path. Desktop and
Documents resolve to their Windows locations and remain subject to allowed-root
policy; an outside path is never redirected. `create notes.txt` creates an empty
file; `save as notes.txt` asks for content when no explicit saved-content reference
exists. Basic PDF writing exists internally, but natural-language PDF creation
remains unavailable.

For reproducible Windows Python 3.14 versions, install with
`python -m pip install -c requirements/pilot-windows-py314.txt .` in a fresh
environment. Tkinter/Tcl must be supplied by Python. Heavy voice/document packages
remain declared for compatibility; installing them does not enable pilot features.

The backend defaults to `127.0.0.1` and has no remote-user authentication. Keep it
on loopback; do not expose it to a LAN or the internet.

### Governed web search

DDGS is the default `SearchProvider` and needs no API key, endpoint, Docker
service, or background process:

```powershell
$env:SAMAKTHA_SEARCH_PROVIDER = "ddgs"  # optional; this is the default
```

DDGS sends the approved query to external public search backends. Availability,
rate limits, and result coverage are controlled by those services; Samaktha does
not claim an availability SLA. Search remains CAP approval-gated and has no
automatic cross-provider fallback.

SearXNG remains an explicit self-hosted/operator-configured option. Configure an
instance with JSON output enabled:

```powershell
$env:SAMAKTHA_SEARCH_PROVIDER = "searxng"
$env:SAMAKTHA_SEARXNG_URL = "http://127.0.0.1:8080"
```

SearXNG does not require an API key by default, but its endpoint is mandatory
when explicitly selected. Brave remains an explicit keyed option using
`SAMAKTHA_SEARCH_PROVIDER=brave` and `SAMAKTHA_BRAVE_API_KEY`. A selected
provider failure is surfaced truthfully; it never triggers another provider.

Web/news requests remain CAP approval-gated for DDGS and even when SearXNG runs
on localhost. ContentFetcher URLs remain untrusted and retain the existing
private-address and localhost protections.

## Running Samaktha

```powershell
# First-run state and health
.\.venv\Scripts\samaktha.exe bootstrap
.\.venv\Scripts\samaktha.exe bootstrap --status
.\.venv\Scripts\samaktha.exe doctor
.\.venv\Scripts\samaktha.exe setup

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

Pre-DDGS-migration canonical baseline:

```text
2939 passed
0 failed
0 skipped
87 warnings
```

Post-DDGS-migration canonical verification:

```text
2979 passed
0 failed
0 skipped
87 warnings
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
