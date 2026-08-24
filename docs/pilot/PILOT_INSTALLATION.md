# Controlled Pilot Installation

This procedure is for a private, explicitly invited Windows pilot. It is not a public release procedure.

## Before installation

Obtain the verified 0.5.0 pilot ONEDIR archive directly from the pilot operator. No compiled installer is part of the current release candidate. Verify the archive SHA-256 value against the operator-provided release record before running it. The current build is unsigned; Windows SmartScreen may warn. Do not bypass a hash mismatch.

Extract the archive to a user-controlled application directory, conventionally `%LOCALAPPDATA%\Programs\Samaktha`. Mutable user state is kept under `%LOCALAPPDATA%\Samaktha`. The packaged application does not require a separately installed Python runtime.

## First start

From PowerShell in the unpacked/installed Samaktha directory:

```powershell
.\samaktha.exe --version
.\samaktha.exe bootstrap
.\samaktha.exe bootstrap --status
.\samaktha.exe doctor
```

`bootstrap` is safe to repeat. It creates configuration, data, cache, log, workspace, checkpoint, and plugin directories plus the memory/evidence databases. `doctor` composes the real production runtime and creates the private permit-signing key if it does not exist.

An unconfigured provider causes `doctor` to return a non-zero health result and show the default provider as `ERROR`. This is expected and truthful: bootstrap/local stores work, but model generation does not.

## Provider configuration

The controlled pilot uses process environment variables; no source files need editing. Set variables only in the PowerShell process used to launch Samaktha. This avoids writing API keys to release files or command examples that are committed to the repository.

Example Groq setup (replace the placeholder interactively and do not paste it into an issue):

```powershell
$env:SAMAKTHA_DEFAULT_PROVIDER = "groq"
$env:SAMAKTHA_GROQ_API_KEY = Read-Host "Groq API key"
.\samaktha.exe doctor
.\samaktha.exe tui
```

OpenAI and OpenRouter use `SAMAKTHA_OPENAI_API_KEY` and `SAMAKTHA_OPENROUTER_API_KEY`. Provider names and health may appear in diagnostics; credential values never should.

For a strict local-model pilot session, configure all of the following before launch:

```powershell
$env:SAMAKTHA_DEFAULT_PROVIDER = "local"
$env:SAMAKTHA_LOCAL_ENABLED = "true"
$env:SAMAKTHA_LOCAL_BASE_URL = "http://127.0.0.1:11434"
$env:SAMAKTHA_LOCAL_MODEL = "<registered-local-model>"
$env:SAMAKTHA_GROQ_ENABLED = "false"
$env:SAMAKTHA_OPENAI_ENABLED = "false"
$env:SAMAKTHA_OPENROUTER_ENABLED = "false"
$env:SAMAKTHA_FALLBACK_ENABLED = "false"
```

This prevents model fallback to cloud. It does not authorize InternetTool use; tool network access remains a separately governed action.

## Workspace configuration

The default governed workspace is `%LOCALAPPDATA%\Samaktha\workspace`. For the initial pilot, use this default. Advanced custom roots require coordinated `SAMAKTHA_FILESYSTEM_*` and `SAMAKTHA_SHELL_*` JSON-list settings and must be reviewed by the operator; a filesystem root is not permission to bypass CAP or ToolSecurityEnforcer.

## Installation path coverage

The release candidate is validated with a default per-user root, paths containing spaces, Unicode paths, and launch from an unrelated working directory. Mutable state must never appear beside the executable or under the launch CWD.

## Upgrade and uninstall

There is no claimed migration history before the current 0.5/P13-compatible schema. Before changing pilot builds, stop Samaktha and back up `%LOCALAPPDATA%\Samaktha`.

The maintained Inno Setup source is not a compiled pilot artifact. Manual removal of the ONEDIR application files must preserve `%LOCALAPPDATA%\Samaktha`, including configuration, memory, evidence, checkpoints, workspace files, logs, and plugin files. Deleting user data is a separate, explicit user decision.
