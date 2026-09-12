# Samaktha Pilot Core Reliability Convergence Report

Implementation/dependency verification: 5–6 September 2026. Final full-suite verification: **12 September 2026**, Windows, Python 3.14.5. This report concerns the cumulative local working tree, not the historical RC archive. No real-user acceptance is inferred from test results.

## 1. Executive R1–R6 Assessment

**Automated convergence is complete: 3,115 passed, zero failures/errors/skips. Real-user acceptance remains required.**

| Gate | Result | Boundary of the result |
|---|---|---|
| R1 — Resource parsing | PASS | Tested phrases, exact payloads, and real temporary-file execution |
| R2 — Workspace handling | PASS | Pre-approval resolution, named locations, no outside-root redirection, result evidence |
| R3 — Setup recovery | PASS | Fake-vault reopen/removal and dependent verification transitions; real wizard acceptance pending |
| R4 — Capability truth | PASS | Unsupported operations unavailable; experimental SMTP remains conditional, not live-validated |
| R5 — Dependencies/native isolation | PASS | Clean source-wheel installation/imports/round-trips; Docling quarantined, not repaired |
| R6 — Correctness | PASS | Final complete suite and named gate groups have zero failures |

These are engineering gates, not a public-release or universal desktop-assistant certification.

Samaktha's useful pilot identity is a **governed local workspace assistant**, not a universal computer operator. Its strongest practical workflows are conversation with a configured provider; saving explicit content as workspace files; basic document text extraction; approved web research; and scoped local memory, notes, tasks, and reminders. A useful pilot must make the destination, approval, result, and recovery steps understandable to an ordinary user.

The main application areas are: `core`/`workflow` for orchestration and planning; `governance`/CAP for authorization; `router`/`providers` for constrained model selection; `runtime`/`tools` for execution; `memory`/`conversation` for scoped persistence and references; `evidence` and signed checkpoints for audit/recovery; `setup`/`config` for onboarding; `tui`/`api`/CLI for interfaces; and integrations/plugins/voice for narrower conditional or experimental features. Source code existing in a module does not by itself establish a working user feature.

## 2. Verified Root Causes

- File intent detection and argument extraction used divergent phrase handling. Detecting a write intent did not guarantee a filename and content reached the tool.
- Conversation reference processing normalized whitespace before parsing, damaging multiline file payloads.
- Relative/named destinations were not consistently bound to the configured workspace before authorization.
- Empty-file writes legitimately return zero bytes, but execution-truth checks previously required positive bytes.
- Setup's hidden secret fields and validation state did not distinguish an unchanged saved credential from a missing credential.
- Email advertised operations beyond its real SMTP/preview implementation. Configured transport was not the same as verified send readiness.
- Direct runtime imports depended on undeclared or transitive packages. PDF fallback could enter a native Docling/Transformers/Torch load path that emitted Windows access violations.

These are distinct failure classes. An out-of-root file denial is an intended security outcome, not a parser failure. SMTP failure cannot be diagnosed as a specific user's bad password or blocked port without a live authorized test.

Key implementation evidence: [planner](C:/Users/user/Desktop/Samaktha/app/core/gambit/planner.py), [reference resolver](C:/Users/user/Desktop/Samaktha/app/conversation/reference_resolver.py), [execution truth](C:/Users/user/Desktop/Samaktha/app/runtime/execution_truth.py), [setup service](C:/Users/user/Desktop/Samaktha/app/setup/service.py), [setup transitions](C:/Users/user/Desktop/Samaktha/app/setup/field_state.py), [email tool](C:/Users/user/Desktop/Samaktha/app/communication/email_tool.py), [SMTP transport](C:/Users/user/Desktop/Samaktha/app/integrations/email_smtp.py), [document quarantine](C:/Users/user/Desktop/Samaktha/app/fileparsers/experimental.py), and [dependency declarations](C:/Users/user/Desktop/Samaktha/pyproject.toml).

## 3. File Parsing Before

Phrases such as “create a file”, “called”, “named”, “saying”, and a Desktop destination could produce incomplete tool arguments. A request could reach planning but stop with missing path/content instead of an executable operation. Payload newlines could be flattened during reference resolution.

## 4. File Parsing After

[resource_parser.py](C:/Users/user/Desktop/Samaktha/app/core/gambit/resource_parser.py) supplies one deterministic resource representation used by intent recognition and extraction: operation, path, format, content, optional target root, and overwrite intent. Directory creation selects `mkdir`; ordinary file creation selects the existing write path. Explicit personal-data requests such as “create a note” remain separate intents. File payloads mentioning other actions do not become those actions.

## 5. Supported File Phrases

Automated execution cases include “create file report.txt with content hello”, “create a file report.txt”, “create a file called/named report.txt”, “write report.txt saying hello”, “create report.txt and put hello in it”, empty files, Word documents, CSV, Markdown, Excel, text files, uppercase commands, and multiline content. Creation without content creates an empty artifact where supported. `save as report.txt` asks for content; `save this as report.txt` can use actual generated conversation content. A directory named `reports` uses `mkdir`. A parent folder named `directory` does not turn a file write into directory creation.

This is a tested phrase set, not a claim of unrestricted natural-language coverage. Natural-language PDF creation remains explicitly unavailable, even though an internal PDF writer exists.

## 6. Multiline Content Preservation

The parser separates the body before locating filenames. Reference resolution retains the explicit payload. Tests compare actual file contents, including indentation, blank lines, punctuation, and a trailing newline. One delimiter newline after `content:` is removed; body newlines are preserved. No model-generated filler is used for missing content.

## 7. Workspace Resolution and Discoverability

Relative destinations resolve against the configured default workspace before the permit is issued. Installed defaults and source-development paths are distinct; setup can select a dedicated workspace. Setup completion and `samaktha doctor` expose the actual configured directory. Completion and denial messages also identify the relevant path. No new “open workspace” shell action was added: no suitable existing governed file-manager action was found, and adding one would expand this phase.

## 8. Named Windows Locations

Desktop/Documents resolution uses Windows folder lookup, including redirected folders, rather than assuming `C:\Users\name\Desktop`. Tests replace the lookup with temporary directories. If lookup fails, production planning returns needs-input and asks for an explicit path. Explicit absolute paths retain their intended destination. Unsafe expansion/device/drive-relative forms are left for the existing security checks, not expanded into access.

## 9. Approval and Filesystem Security

Resolved arguments enter the existing CAP approval/permit flow. GAMBIT does not execute the write. Runtime and ToolSecurityEnforcer still validate the operation and filesystem scope. An outside destination fails without writing there and without redirecting into the workspace. Choosing another workspace or changing configured access is a user decision, not an automatic privilege expansion.

## 10. Result Path Truth

Successful writes provide the actual Runtime path and byte count. Empty writes additionally verify file existence before zero-byte completion is accepted. User-facing creation text is synthesized from this output, not a model's claim. DOCX/XLSX tests reopen the resulting files; text cases compare exact bytes/text. The tests inspect the destination in plan arguments before approval and prove no file exists at that stage.

## 11. Real Execution Tests

The new file suite exercises the composed orchestrator, approval pause/resume, Runtime, filesystem security, actual temporary file creation, and output evidence. Named and explicit outside-root destinations are denied. It does not merely test parser return values. All new file tests use temporary application state and suppress real SMTP credential resolution; setup tests use a fake credential store.

## 12. Setup Saved-Credential Root Cause

An intentionally empty password widget was being treated like an absent credential, and unchanged captures could invalidate previously verified settings. The corrected service checks saved credential references and retrieves a secret only when the explicit operation needs it. Blank UI fields do not overwrite saved secrets.

## 13. Secret Field State Model

The model distinguishes `no_secret_configured`, `unchanged_existing_secret`, `new_secret_provided`, and `remove_secret_requested`. Blank means unchanged. A nonblank value replaces the credential. Removal requires an explicit control. Provider, Brave, and SMTP secrets remain excluded from serialized draft output.

## 14. Setup Reopen Behavior

Tests save verified provider/search/SMTP state using a fake vault, reopen through the controller, leave secret widgets blank, commit, and verify credentials and verification flags survive. Saved provider testing reuses the hidden secret. Explicit provider removal switches the configuration to offline rather than requiring re-entry of the deleted credential. Real Windows Credential Manager and visual wizard acceptance remain manual checks.

## 15. Verification Invalidation Rules

Provider verification resets when provider/model/endpoint/key/removal/environment-import selection changes. Search verification resets when the selected provider, SearXNG URL, Brave key, or removal changes. SMTP authentication resets for host/port/security/username/sender/password/removal changes. SMTP send-acceptance verification also resets for material transport or credential changes. Unrelated profile/workspace edits do not clear these tests. Invalid port text no longer silently becomes 587.

## 16. Credential Security

Persisted non-secret configuration stores references, not passwords. Existing secrets are not loaded into wizard widgets or normal serialized drafts. Fake-vault regressions cover preservation and explicit deletion without exposing real credentials. No real SMTP email, credential deletion, or user Credential Manager mutation was performed by these tests. Legacy environment overrides still take precedence where implemented; an old SMTP environment configuration does not manufacture setup authentication verification.

## 17. Capability Truth Audit

Conversation/search are conditional on configuration and provider availability. Files are governed local actions. Notes/tasks/calendar/contacts/memory are local, not synchronized accounts. Notifications depend on a working backend; backend absence is stated, and `sent=false` is not evidence of delivery. Messaging is labeled simulation. Plugins are trusted engineering-only code, not a pilot marketplace promise. Browser/media automation is unavailable in production composition.

## 18. Email Truth and Why Setup Asks for an SMTP Port

| Operation | Actual status |
|---|---|
| Compose/draft | Local unsaved preview; neither persisted draft nor sent email |
| SMTP send | Optional experimental transport; enabled, authentication-verified configuration and CAP approval required |
| Read/search/folders | Unavailable; no real mailbox implementation |
| Reply/forward | Unavailable as mailbox operations |
| Attachments | Unsupported and rejected before dispatch, not silently discarded |
| Gmail/Outlook API | Not implemented; an SMTP preset is not an API integration |

SMTP is the outgoing-mail protocol used by this project. The **host** identifies the mail server; the **port** identifies the service on that server. Setup defaults to port **587 with STARTTLS**. The transport also supports **SSL/TLS**, with a 465 fallback when configured without a port. Port and security mode must match the administrator/provider's configuration; choosing a number alone does not set up an account or grant sending permission.

The implementation connects, negotiates TLS according to the selected mode, optionally authenticates with username/password, then disconnects for “Test Authentication”. That test sends no mail. A separately confirmed send goes through canonical authorization and submits an email to the server. `PROVIDER_ACCEPTED` means the server accepted submission; recipient delivery remains unknown. Blocking SMTP work runs off the event loop.

Final transport review also found implicit unverified stdlib TLS contexts and a joined recipient-envelope list. Both are corrected: authentication and delivery now use default certificate/hostname-verifying contexts, and envelope recipients remain separate addresses. Mocked tests check both TLS modes, prove authentication testing never sends, reject certificate failure before login, and inspect the multiple-recipient envelope. No live transport result is claimed.

Failure can occur at configuration, connection, TLS, authentication, authorization, or submission. Provider account policies and network restrictions are external conditions not proven by mocked tests. The core pilot should leave SMTP disabled unless the user deliberately needs this experimental feature. Gmail/Outlook preset labels do not prove present-day account compatibility.

## 19. OCR / Document Truth

Basic text/Markdown/HTML/PDF extraction remains. DOCX/XLSX now have lightweight readers avoiding Docling; Excel extraction has a row bound. OCR remains optional/experimental and depends on an installed engine. Blank/corrupt PDF tests prove the core fallback does not attempt Docling/Torch imports. Advanced document understanding and PPTX extraction through the quarantined adapter are not promised. An empty document can be created successfully even when extracting readable text from it naturally yields none.

## 20. Connector / Plugin Truth

Only registered production capabilities establish availability. Unreachable adapters were not activated. Browser/media, external chat services, mailbox APIs, and account synchronization remain outside pilot scope. Plugins retain explicit lifecycle and authorization controls but execute trusted Python in-process; they are not a sandbox for hostile extensions.

## 21. Runtime Dependency Audit

Direct declarations were added for Textual, PyMuPDF, pdfplumber, pypdf, BeautifulSoup4, Pillow, pyperclip, and Windows-marked pystray/keyboard/Windows-Toasts/pywin32. PyInstaller is declared as a development dependency. Existing httpx, provider frameworks, DDGS, Office readers, and voice/document dependencies remain. Optional guarded EasyOCR/plyer/win10toast imports are not core requirements. Tesseract is an external executable. Tkinter is a Python-distribution component, not something this project can reliably install through a pip requirement.

## 22. Textual / httpx and Other Direct Runtime Dependencies

Textual is explicitly constrained to `>=8.2.8,<9`; httpx was already directly declared at `>=0.27.0`. The Windows/Python 3.14 constraints record exact resolved package versions, including Textual 8.2.8, httpx 0.28.1, DDGS 9.16.0, and PyMuPDF 1.28.2. This is a platform-specific version constraint set, not a hash-locked, all-platform release guarantee.

## 23. Clean Dependency Reproducibility

Created `.cache/reliability/clean` separately from the canonical `.venv`. A dry-run resolution report produced `requirements/pilot-windows-py314.txt`. Full constrained installation built and installed the project wheel and dependencies successfully. An initial Windows cache permission failure required an approved retry. From an unrelated temporary CWD, `python -I -B` imported core/CLI/TUI/setup from that environment's `site-packages`, with no Torch/Docling/Transformers/voice stack loaded. Installed TXT/DOCX/XLSX writer/parser round-trips passed. `pip check` reported no broken requirements. This verifies the source-wheel dependency route, not every feature under those newly resolved versions; the canonical full suite uses the existing `.venv`. No final executable/installer was built.

## 24. Package Size Contributors

The historical ONEDIR tree is approximately 0.95 GiB and predates these source changes. Approximate directory sizes from that tree are not predictions for a new build:

| Component | MiB | Main capability cost |
|---|---:|---|
| Torch | 315.6 | Native ML/document stack |
| OpenCV (`cv2`) | 111.7 | Image/OCR processing |
| AV native libraries | 62.6 | Audio/video decoding |
| CTranslate2 | 58.8 | Speech inference |
| SciPy + native libraries | 70.3 | Scientific/ML support |
| PyMuPDF | 37.7 | PDF handling |
| ONNX Runtime | 33.7 | Inference/wake-word ecosystem |
| NumPy native libraries | 20.0 | Array/numerical support |
| Pillow / pandas / docling_parse | 12.8 / 12.8 / 12.4 | Images, tabular data, document parsing |

Quarantining execution does not remove installed package size. An optional-extras/package-splitting effort is deferred; removing these stacks now would require separate compatibility and packaged validation.

## 25. Docling/Torch Access Violation

Reproduced in the original full-suite PDF fallback: Docling conversion imported Transformers/Torch and entered native DLL loading. Pytest continued, but that did not make the fault acceptable. The precise DLL/ABI cause and whether Python 3.14 contributed remain unproven. Core import alone did not reproduce the fault. Mitigation is explicit Docling quarantine before import, lightweight Office extraction, and regression guards around blank/corrupt PDF fallback. This is not a claim that Torch itself has been repaired.

## 26. Historical Mock Provider Failure Root Cause

The reported historical `test_sensitive_router_request_rejects_preferred_cloud` failure was **not reproduced**: the baseline targeted test passed, and the initial full suite passed 3,057 tests. There is insufficient evidence to assign an exact historical cause. No production router weakening was made to obtain a pass. Newly introduced fixture/source-check failures during this phase are reported separately from that historical issue.

## 27. Mock Provider Production Guard

`ProviderSettings.mock_allowed()` remains the explicit guard; production composition only registers mock under the allowed development/test modes. Missing production credentials are not converted into a successful mock response. Existing architecture and production tests exercise this boundary and local-only routing. New temporary execution tests explicitly request mock mode; this is not a change to production defaults.

## 28. Focused Tests

Final full-run subsets: setup **42**, GAMBIT **85**, conversation **71**, communication **69**, and file parsers **33**, all passed (**300** combined). The new regressions comprise file reliability **26**, setup recovery **15**, core dependencies/native guards **4**, and email truth/TLS **13**: **58 new tests**, all passed within the full suite.

Independent checkpoints included 208 file/planning/conversation tests; 26 expanded file tests; 50 dependency/email/setup/security/reference tests; and the final 60 email/setup/integration tests (6.45 seconds). Counts overlap and must not be added to the full-suite total.

Intermediate failures were resolved or revalidated: a test-only static-method mock signature error was corrected; the planner's literal-source boundary check rejected the built-in name `RuntimeError`, so path-loop conversion moved to the resource resolver without weakening the guard. Overlapping suites interfered with the packaged per-user mutex; subsequent serial stress and full runs passed. Interrupted runs were not counted as acceptance evidence.

## 29. Architecture

**124 passed; 0 failed/errors/skipped**, extracted from the final full-run XML.

## 30. Security

**191 passed total:** security **21** plus security-adversarial **170**; **0 failed/errors/skipped**. Authorization, permit tampering, routing/privacy, filesystem and integration boundaries remain covered. This is regression evidence, not an independent penetration-test certification.

## 31. Production

**219 passed; 0 failed/errors/skipped**. Includes real temporary file operations, capability integrity, setup-related composition, email truth, and historical local-only routing regression.

## 32. Stress

**159 passed; 0 failed/errors/skipped** in the final full run. Also independently passed serially: **159 passed, 5 warnings, 92.40 seconds**. The earlier overlapping run's mutex failure is not treated as a green result. Packaged tests use the existing historical executable and do not validate a new R1–R6 package.

## 33. Pilot

**27 passed; 0 failed/errors/skipped**. These automated tests cover operational/pilot contracts and historical package behavior; they are not evidence that a human completed the new file/setup workflow.

## 34. Full Suite

**PASS — completed on 12 September 2026.**

| Metric | Final result |
|---|---:|
| Collected/executed | 3,115 |
| Passed | 3,115 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |
| Warnings | 87 |
| Pytest reported duration | 428.11 seconds (7 minutes 8 seconds) |

Command: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q --junitxml=.cache/reliability/full-final.xml`, with `PYTHONDONTWRITEBYTECODE=1` and `PYTHONNOUSERSITE=1`. The XML option records evidence only. [Final XML](C:/Users/user/Desktop/Samaktha/.cache/reliability/full-final.xml) records all 3,115 cases with zero failures/errors/skips; its test-phase timing (417.147 seconds) excludes some overhead included in the console duration.

The warnings include legacy test-provider/API deprecations, intentional migration/recovery and tampered-enum tests, and unawaited AsyncMock warnings. They are disclosed, not suppressed. No Docling/Torch access-violation trace appeared in the final run. The canonical environment was not replaced by the separate clean dependency environment.

## 35. Documentation Convergence

Updated README; pilot installation, scope, known limitations, runbook, security/privacy, and release notes; changelog; and this report. Historical archive/hash and historical test counts remain history, not certification of the current working tree. Doctor's OCR wording now explicitly states Docling is disabled.

## 36. Real-User Validation

**AUTOMATED VERIFIED:** the specific temporary-file, setup/fake-vault, email-fake-transport, dependency-import, and regression behaviors documented above, with the completed final suite recorded in section 34.

**REAL-USER VALIDATION REQUIRED:** launch the actual TUI; create a text file and a Word document after reviewing the exact path; inspect contents in the user workspace; request an out-of-root Desktop file and verify clear denial/no redirection; close/reopen setup without re-entering keys and run doctor; run an explicitly approved live DDGS search; create/recall scoped memory across the intended session/restart workflow. SMTP is optional and requires a separately authorized live acceptance test if enabled. No real email or live-key validation is claimed here.

Suggested manual sequence from the project root:

1. Run `.\.venv\Scripts\samaktha.exe doctor` and note the workspace path.
2. Run `.\.venv\Scripts\samaktha.exe tui`; request `create a file called report.txt with the text Samaktha pilot test.` Review the absolute destination before Allow, then inspect the actual file.
3. Request `create a Word document called report.docx with the text Samaktha pilot test.` Open the result in a document reader.
4. With Desktop outside allowed roots, request `create a file on my Desktop named outside_test.txt with content hello`. Expect a clear scope failure and no copy silently saved elsewhere.
5. Reopen setup, leave saved secrets blank, finish unchanged, and run doctor again. Provider/search/workspace/security state should agree.
6. Approve `search the internet for three current AI news results`; distinguish transport errors from poor answer quality. Exercise memory recall across a restart using non-sensitive test content.

Use disposable filenames or review the existing overwrite policy before approving. These steps are a checklist for the user, not a claim that they have been performed.

## 37. Installer Gate

**READY_FOR_PACKAGED_VALIDATION** — engineering eligibility only. Perform the real-user checklist before freezing a new pilot package/installer. This is **not** READY_FOR_INNO_IMPLEMENTATION and does not authorize building the final installer in this phase. No final installer was built; the historical package is not current-source acceptance evidence.

## 38. Remaining Pilot Risks

Manual interaction and actual user-machine behavior remain unverified. Public search availability/rate limits are external. SMTP acceptance is not delivery and account compatibility is conditional. OCR/voice/notifications are platform-dependent. Docling is disabled, not repaired. Heavy dependencies retain footprint and packaging risk. Enabled plugins are trusted in-process code. The API must remain loopback/local because this phase does not add public-service authentication. There is no updater or broad external-account synchronization promise.

## 39. Git Status

Read-only status: **72 tracked modified files; 27 untracked status entries representing 36 files; 0 staged files**. Ignored clean-environment/test artifacts are not included. No staging, commit, tag, push, reset, restore, checkout, clean, or stash was performed. The dirty working tree contains earlier user-owned work as well as this phase; cumulative changes must not be attributed entirely to this phase. A read-only per-command `safe.directory` override was used for ownership checks; no global Git configuration was changed. Diff checking still reports eight whitespace-only lines in cumulative conversation/orchestrator edits; unrelated formatting was not rewritten.

## 40. Final Decision

SAMAKTHA PILOT CORE RELIABILITY CONVERGENCE COMPLETE — REAL-USER ACCEPTANCE REQUIRED — DO NOT COMMIT
