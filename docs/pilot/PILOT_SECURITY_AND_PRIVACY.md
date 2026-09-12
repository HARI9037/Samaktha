# Pilot Security and Privacy

## Preserved trust boundaries

All user-reachable provider/tool work remains CAP → GAMBIT → Router/Workflow → Runtime → ProviderExecutor or ToolExecutor. Tool actions remain behind exact signed permits, governance validation, ToolSecurityEnforcer, evidence sanitization, and scoped memory/session access. Scheduled reminder notifications obtain a fresh permit and re-enter Runtime.

## Setting classification

| Setting group | Classification | Pilot rule |
|---|---|---|
| Provider enable/default/model/base URL | User configurable | Configure through setup. Environment overrides remain a development compatibility path; unsupported models fail truthfully. |
| Provider API credentials | User secret | Setup uses Windows Credential Manager, with references only in TOML. Blank widgets retain existing secrets; explicit removal is separate. Never place credentials in issues, diagnostics or release artifacts. |
| Local model URL/model and cloud enable flags | User configurable | Strict local use requires disabling every cloud provider and fallback as documented. Typed P1 constraints remain authoritative per operation. |
| SMTP credentials | Advanced secret | Optional experimental setup uses Credential Manager and requires authentication verification. Legacy `SMTP_*` values take precedence but are not proof of verification; use setup for pilot sending. |
| Filesystem/shell roots | Advanced | Keep defaults unless an operator reviews all corresponding roots. They never remove approval/security checks. |
| Plugin root | Advanced / initial-pilot excluded | Discovery is metadata-only. No plugin is trusted or enabled by discovery. |
| Memory/personality behavior | User configurable where exposed | Existing personality CLI only; ownership/scope controls are internal and not user-disableable. |
| Log level/format | Advanced | TUI logs are local, rotating, 5 MB each with three backups. Debug logging may increase support detail; never send logs without review. |
| Runtime capacity, retry, checkpoint, evidence retention | Advanced operator | Defaults remain in the pilot. Security/reliability toggles are not exposed as convenience switches. |
| Permit signing, checkpoint integrity, evidence sanitization, SSRF policy | Internal security control | Never disable or expose through pilot UX. |
| Mock/dev/internal validation flags | Test only | Not supported in pilot builds or instructions. |

## Diagnostic privacy contract

The API defaults to `127.0.0.1` and uses the local principal without remote-user
authentication. It must not be exposed on `0.0.0.0`, a LAN, or the public internet.

`doctor --export` requires an explicit local command. It writes one JSON file under the per-user cache diagnostics directory and performs no upload. It excludes prompts, responses, conversation/memory contents, file and clipboard contents, email/message bodies, raw environment, raw exception detail, raw paths, checkpoint payloads, credentials, and signing material.

## Secrets and errors

Evidence and integration errors pass through the P13 sanitizer. The diagnostic export includes only health classes/statuses. Provider or tool failure must not expose credential values or become a success result. A user may voluntarily provide sanitized reproduction steps, but support must never request an API key, SMTP password, signing key, or raw user-content database.

## Plugin trust boundary

Plugins are trusted in-process Python code, not a hostile-code sandbox. The initial user cohort does not enable them. Engineering smoke uses manifest validation, explicit enablement, canonical Runtime/ToolExecutor/P7 execution, and P8 evidence. Discovery alone is never activation.
