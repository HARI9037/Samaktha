# Controlled Pilot Rollback

## Stop safely

1. Deny or cancel pending actions when the interface is responsive.
2. Exit the TUI or stop the backend with Ctrl+C.
3. If hung, terminate the Samaktha process. Do not repeatedly relaunch an execution with an uncertain non-idempotent outcome.
4. Remove/disable the launch shortcut to prevent restart. There is no remote kill switch.

## Preserve state before rollback

Copy `%LOCALAPPDATA%\Samaktha` to a user-controlled backup while Samaktha is stopped. It contains configuration, workspace, memory, sessions, evidence, checkpoints, logs, and plugin files. Protect it as user data.

## Restore the previous build

Remove or rename only the application binary directory `%LOCALAPPDATA%\Programs\Samaktha`; do not delete `%LOCALAPPDATA%\Samaktha`. Restore the exact previous ONEDIR build whose hash was recorded, then run:

```powershell
.\samaktha.exe --version
.\samaktha.exe bootstrap --status
.\samaktha.exe doctor
```

Reuse state only when the rollback record says the schema is compatible and integrity checks pass. The current project has no supported arbitrary downgrade migration. If corruption, a signing-key incident, or an incompatible schema is suspected, quarantine the state directory and do not force the old build to open it.

## Capability containment

Clear provider variables in the launch process to disable cloud access. Plugins are excluded from the initial user cohort; engineering operators must unload/disable a test plugin before discarding its process. Cancel reminders through the governed action when state is healthy.

Uninstall removes application files but preserves user data. Permanent user-data deletion is separate and must be explicit.
