# Samaktha Controlled Pilot Scope

This is the product contract for the controlled Windows pilot of Samaktha 0.5.0. It is derived from the tools and metadata composed by `create_orchestrator()`; code existing elsewhere in the repository is not treated as a user capability.

## Capability matrix

| Capability | Availability | Implementation | Location | Mutation | Approval | External delivery | Pilot support | Important limitation |
|---|---|---|---|---|---|---|---|---|
| Provider conversation | Conditional | Canonical Router → Runtime → ProviderExecutor | Local or cloud, selected under typed constraints | No tool mutation | Policy-dependent | Model response only | Yes, when a configured provider is healthy | An unconfigured fresh install remains usable for bootstrap/doctor but cannot generate model responses. Local-only work cannot fall back to cloud. |
| Filesystem | Production ready | Resolver → Runtime → ToolExecutor → ToolSecurityEnforcer → filesystem/document tools | Local | Read and governed write/copy/move/delete | Required by CAP for requested file permissions | No | Yes | Only configured roots are reachable. Relative paths resolve inside the configured workspace; protected paths, traversal, unsafe links, and out-of-root targets are rejected. |
| Memory | Local only | Runtime tool plus canonical memory/session stores | Local SQLite/session files | Search/retrieve and governed deletion | Required by CAP for requested permissions | No | Yes | Memory is principal/session/workspace scoped. There is no cross-device sync. |
| Windows operations | Local only | Runtime → ToolExecutor → ToolSecurityEnforcer → WindowsTool | Local | Process listing, clipboard read/write; terminal action declared | Required for read/write/execute | No | Limited | Terminal launching is disabled by default. No administrator or system-wide control is supported. |
| Internet | Production ready when configured | Runtime → ToolExecutor → ToolSecurityEnforcer → InternetTool/Brave | Cloud network | Read-only network access | Required for network access | Search/fetch results | Conditional | Brave credentials are required for search. SSRF, port, redirect, response-size, and sensitive-header controls apply. |
| Shell | Production ready, advanced | Runtime → ToolExecutor → ToolSecurityEnforcer → ShellTool | Local process | Executes allowlisted programs | Always required | No | Limited trusted cohort only | Structured executable/argument invocation, allowlist, workspace CWD, timeout, and output bounds apply. No unrestricted shell or administrator access. |
| Clipboard | Local only | Runtime → ToolExecutor → ToolSecurityEnforcer → ClipboardTool | Local | Read/write | Required by CAP for requested permissions | No | Yes | Size limits apply; clipboard write can be disabled. Clipboard content is not included in diagnostics. |
| Notification | Local only | Runtime → ToolExecutor → ToolSecurityEnforcer → NotificationTool | Local | Desktop notification | Required by the canonical permit path | OS notification only | Conditional | Depends on the Windows notification environment. A returned tool failure is never described as delivery. |
| Reminder | Local only | ReminderTool plus governed scheduler callback → CAP → Runtime → ToolExecutor | Local | Create/update/cancel/snooze/complete and later notification | Required by CAP for requested permissions; due firing is freshly authorized | Local notification only | Yes | Reminder persistence is signed/scoped. Restart behavior is local; there is no cloud reminder service. |
| Notes | Local only | Runtime → NotesTool | Local SQLite/files | CRUD | Required by CAP for requested permissions | No | Yes | Local data only; no collaboration service. |
| Tasks | Local only | Runtime → TasksTool | Local SQLite | CRUD/complete | Required by CAP for requested permissions | No | Yes | Local data only; no external task-service sync. |
| Contacts | Local only | Runtime → ContactsTool | Local SQLite/files | CRUD/import | Required by CAP for requested permissions | No | Yes | Local address book only; no device/account sync. Export is governed filesystem output. |
| Calendar | Local only | Runtime → CalendarTool | Local SQLite | CRUD | Required by CAP for requested permissions | No | Yes | Local calendar only; no Google/Microsoft calendar delivery or sync. |
| Email | Simulated unless SMTP is explicitly configured | Runtime → EmailTool → SMTPIntegrationProvider | Local draft or SMTP network | Draft/send/reply/forward | Required; network permission when external | `PROVIDER_ACCEPTED`, never delivery confirmation | Conditional | With no SMTP configuration it is explicitly simulated. With SMTP, acceptance is not recipient delivery. Read/search/folders do not imply a remote mailbox implementation. |
| Message | Simulated | Runtime → MessageTool | Local simulation | Draft/send/reply simulation | Required for mutating intent | No | Yes as a labeled simulation | No SMS, WhatsApp, Telegram, Slack, or other external message provider is connected. |
| Trusted local plugins | Engineering smoke only | PluginManager lifecycle → PluginToolAdapter → Runtime → ToolExecutor → ToolSecurityEnforcer | In-process local plugin code | Manifest-dependent | Canonical CAP/Runtime policy | Plugin-dependent | No in the initial user cohort | Discovery never enables a plugin. Installation, compatibility validation, explicit enable, and load are required, but there is no normal operator lifecycle CLI and enablement is process-local. P14 will not invent persistence/auto-load. Arbitrary hostile Python plugins are outside the trust boundary. |
| Document extraction | Internal only | DocumentTool/PDF/Image helpers | Local | Read-only | Governed if reached through a canonical tool action | No | Not advertised | Kept internal because production natural-language capability wiring does not advertise it independently. |
| Browser/media | Unavailable | No production tool registration | N/A | N/A | N/A | No | No | Classes or roadmap references do not make these product capabilities. |

## Pilot exclusions

The pilot does not support administrator-level actions, arbitrary system-wide shell access, unrestricted filesystem access, malicious-plugin isolation, automatic plugin enablement, external messaging services, cloud calendar/contact synchronization, browser automation, media generation, public webhooks, remote telemetry, or any public-launch promise.

`CommunicationManager`, `AgentPlanner`, `MultimodalExecutor`, and `ToolChainExecutor` remain outside canonical production execution. Pilot feedback must not be used to activate them or create a path around CAP, Runtime, ToolExecutor, or ToolSecurityEnforcer.

## Execution truth

Generated prose is not execution evidence. A side-effect claim is valid only when the canonical Runtime result and evidence support it. The pilot distinguishes completed, denied, awaiting approval, cancelled, timed out, failed, recovery-required, simulated, provider-accepted, needs-input, and unavailable outcomes.
