# Controlled Pilot Installation

This procedure is for a private, explicitly invited Windows pilot. It is not a public release procedure.

## Before installation

Obtain the verified 0.5.0 pilot ONEDIR archive directly from the pilot operator. No compiled installer is part of the current release candidate. Verify the archive SHA-256 value against the operator-provided release record before running it. The current build is unsigned; Windows SmartScreen may warn. Do not bypass a hash mismatch.

Extract the archive to a user-controlled application directory, conventionally `%LOCALAPPDATA%\Programs\Samaktha`. Mutable user state is kept under `%LOCALAPPDATA%\Samaktha`. The packaged application does not require a separately installed Python runtime.

## First start

From PowerShell in the unpacked/installed Samaktha directory:

```powershell
.\samaktha.exe --version
.\samaktha.exe setup
.\samaktha.exe doctor
```

An incomplete installed configuration opens the same setup wizard on normal
startup. Setup commits non-secret TOML settings atomically, stores credentials
in the per-user Windows Credential Manager, and initializes security state
through the production composition. `setup` is safe to reopen. `doctor` uses
the same validators in read-only mode; it does not create or repair security
state. The legacy `bootstrap` command remains available for engineering flows.

An unconfigured provider causes `doctor` to return a non-zero health result and show the default provider as `ERROR`. This is expected and truthful: bootstrap/local stores work, but model generation does not.

## Provider configuration

The installed controlled pilot uses the setup wizard and Windows Credential
Manager; no source files need editing. Process environment variables remain a
higher-precedence development/operator override. Never place API keys in
committed files or diagnostic reports.

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

## Search configuration

Web and news search use DDGS by default. It is installed with Samaktha and needs
no API key, configured endpoint, Docker service, or background process:

```powershell
$env:SAMAKTHA_SEARCH_PROVIDER = "ddgs"  # optional default
$env:SAMAKTHA_DDGS_TIMEOUT = "10"
```

DDGS sends approved queries to public search backends. Their availability and
rate limits are outside Samaktha's control. SearXNG remains an explicit option
for operators running a trusted service with JSON output enabled:

```powershell
$env:SAMAKTHA_SEARCH_PROVIDER = "searxng"
$env:SAMAKTHA_SEARXNG_URL = "http://127.0.0.1:8080"
$env:SAMAKTHA_SEARXNG_TIMEOUT = "15"
$env:SAMAKTHA_SEARXNG_MAX_RETRIES = "2"
```

No SearXNG API key is required by default, but the configured instance must
support `GET /search` with `format=json`; Samaktha does not scrape HTML or
choose a public instance. Selecting SearXNG without a URL makes only search
unavailable and does not prevent offline startup.

Brave remains an explicit optional selection:

```powershell
$env:SAMAKTHA_SEARCH_PROVIDER = "brave"
$env:SAMAKTHA_BRAVE_API_KEY = Read-Host "Brave Search API key"
```

There is no automatic fallback among DDGS, SearXNG, and Brave. Search always
requires CAP approval, including DDGS and `127.0.0.1` or `localhost`. A remote SearXNG service
receives the query directly; a local service may still forward it to configured
upstream search engines. This trusted service endpoint does not weaken the
separate ContentFetcher restrictions on localhost, private addresses, redirects,
DNS resolution, ports, headers, or response size.

## Workspace configuration

The default governed workspace is `%LOCALAPPDATA%\Samaktha\workspace`. Setup can choose a different dedicated folder; this sets both filesystem and shell roots. `samaktha doctor` and setup completion show the folder. Advanced multi-root environment overrides require operator review. A filesystem root never bypasses CAP or ToolSecurityEnforcer.

`create a file called report.txt with the text Hello` resolves inside that workspace.
Approval shows the actual destination; completion uses the Runtime file result.
`create notes.txt` creates an empty file. `save as notes.txt` asks for content if
none is supplied or available through an explicit conversation reference.
Desktop/Documents resolve to their actual Windows locations, including redirected
folders. If outside allowed roots, the action is denied without silently saving
elsewhere. No automatic root expansion occurs.

Reopening setup and leaving secret fields blank preserves existing credentials
and verification. Enter a replacement or select Remove explicitly. Removing the
active provider credential switches setup to offline mode. SMTP can remain
disabled throughout core onboarding; its send test is optional and external.

## Installation path coverage

The release candidate is validated with a default per-user root, paths containing spaces, Unicode paths, and launch from an unrelated working directory. Mutable state must never appear beside the executable or under the launch CWD.

## Upgrade and uninstall

There is no claimed migration history before the current 0.5/P13-compatible schema. Before changing pilot builds, stop Samaktha and back up `%LOCALAPPDATA%\Samaktha`.

The maintained Inno Setup source is not a compiled pilot artifact. Manual removal of the ONEDIR application files must preserve `%LOCALAPPDATA%\Samaktha`, including configuration, memory, evidence, checkpoints, workspace files, logs, and plugin files. Deleting user data is a separate, explicit user decision.
