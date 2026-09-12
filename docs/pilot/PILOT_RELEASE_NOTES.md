# Samaktha 0.5.0 Controlled Pilot Candidate

## Current source versus historical package

The R1–R6 working tree changes resource parsing, workspace resolution, setup
credential recovery, email capability truth, and native-document isolation.
The archive/hash below describe the historical RC only, not these source
changes. No final installer has been built for this convergence phase.
Current-source real-user acceptance and packaged validation are still required.

Final R1–R6 source verification on 12 September 2026: 3,115 passed, zero
failures/errors/skips, 87 warnings, 428.11 seconds. This includes the final SMTP
certificate-verification and recipient-envelope regressions. See
`PILOT_CORE_RELIABILITY_CONVERGENCE_REPORT.md` for scope, exact gate counts, and
manual acceptance steps. No commit, tag, push, or final installer was produced.

This candidate preserves the P0–P13 canonical authorization, capability, context, memory, lifecycle, recovery, tool security, evidence, plugin, packaging, stress, and adversarial security baselines. P14 adds pilot scope truth, Unicode-safe packaged CLI output, canonical bounded TUI logging, operational doctor checks, an explicit sanitized local diagnostic export, clearer denied/timeout truth, and exact redacted approval summaries.

This is an unsigned private pilot build. It is not a public release, does not include an updater, and does not claim field-pilot completion. See `PILOT_SCOPE.md` and `PILOT_KNOWN_LIMITATIONS.md` before use.

Post-P14, the default governed web/news adapter uses the maintained DDGS package
and requires no key, endpoint, Docker service, or background process. SearXNG
remains an explicit self-hosted HTTP/JSON option and Brave remains optional and
keyed. Search authorization, Runtime/ToolExecutor dispatch, evidence, and
ContentFetcher network protections are unchanged. There is no provider fallback.

The pre-DDGS-migration canonical baseline completed with 2,939 passing tests,
zero failures, zero skips, and 87 warnings under Python 3.14.5. This does not
alter the historical P14 tag or claim completion of a real-user pilot.

Post-migration canonical verification completed with 2,979 passing tests, zero
failures, zero skips, and 87 warnings under Python 3.14.5.

Canonical engineering acceptance used Python 3.14.5 and completed with 2,851
passing tests, zero failures, and zero skipped tests. Real-user installation,
comprehension, and multi-day reliability remain controlled-pilot objectives.

Verified RC archive: `Samaktha-0.5.0-pilot-rc-windows-x64.zip`

SHA-256: `32F51B8476403987F8E46730AA00189A7B7FAF6EBA48FC8F36484AB9B6812590`
