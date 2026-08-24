# Controlled Pilot Known Limitations

- The Windows executable is unsigned. SmartScreen warnings are expected; verify SHA-256 and build origin.
- The verified pilot artifact is an ONEDIR ZIP. The repository contains Inno Setup source, but no compiled installer is part of this release candidate.
- This is a controlled 0.5.0 pilot candidate, not a 1.0 or public release.
- Provider credentials are configured in the launch process environment; there is no credential-manager onboarding UI.
- Strict local-model operation requires a separately running compatible local endpoint and explicit cloud/fallback disablement.
- Browser and media capabilities are unavailable.
- Message send/reply is simulated. No SMS, WhatsApp, Telegram, Slack, or Discord provider exists.
- Email is simulated unless SMTP is explicitly configured for engineering validation. SMTP provider acceptance is not delivery confirmation; remote mailbox read/search is not claimed.
- Calendar, contacts, tasks, notes, reminders, and memory are local-only. There is no account/device sync.
- Plugins are trusted in-process code. The canonical lifecycle exists, but enablement is process-local and no normal operator lifecycle CLI exists; plugins are excluded from the initial user cohort.
- Shell is an advanced, allowlisted, workspace-scoped capability and is not administrator/system-wide access.
- Mutable state is single-host SQLite/files. There is no distributed database, Redis, cloud sync, or multi-host coordination.
- There is no auto-updater or remote kill switch. Rollback is manual.
- Uninstall preserves user data by design.
- Accelerated P14 restart/session validation is not real multi-day user evidence. No real pilot-user result may be claimed until supplied.
