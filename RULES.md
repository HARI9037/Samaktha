# Samaktha Development Rules

These rules govern the incremental Rust TUI migration and future sessions working on it.

## 1. Read the project context first

At the start of every session:

1. Read `RULES.md`.
2. Read the current migration plan/design under `docs/superpowers/`.
3. Check `git status`, current branch, recent commits, and any active milestone.
4. Confirm the requested change does not violate the architecture invariants below.

Do not start implementation before identifying the active milestone and its acceptance criteria.

## 2. Architecture invariants

- CAP remains the authority for policy, risk, privacy, permissions, and approval.
- GAMBIT remains the authority for goal parsing, decomposition, and planning.
- Signed permits remain mandatory for governed effects.
- Runtime permit validation remains mandatory immediately before execution.
- The TUI is a client/presentation layer. It must never execute tools directly.
- The TUI must not forge, modify, replay, or locally substitute approval or permit state.
- Backend authorization must validate every state-changing request from every client.
- Existing tools and providers remain reachable through governed backend paths during migration.

## 3. Migration rules

- Use incremental migration, not a big-bang rewrite.
- Define and test the backend protocol before relying on new Rust-only behavior.
- Keep the Python/Textual TUI available as a rollback path until Rust parity is verified.
- Do not rewrite CAP, GAMBIT, or runtime enforcement as part of a UI task.
- Workflow, event transport, and presentation may change when their safety and behavior are covered by tests.
- Prefer adapters and small migrations over deleting working implementations.
- One logical change per commit; avoid unrelated cleanup in feature commits.

## 4. Testing and verification

- For every bug fix or behavior change, add a focused regression test before or alongside the implementation.
- Test complete paths where possible: request → plan → CAP → permit → runtime → tool → event → TUI.
- Required regression areas include search results, file follow-up context, approvals, denial, cancellation, errors, reconnects, and stale events.
- Never claim a milestone is complete without running its documented verification commands.
- Record each milestone as `Not started`, `In progress`, `Blocked`, or `Completed` with evidence.

## 5. Security and data hygiene

- Never commit or push credentials, API keys, signing keys, local databases, permit material, `.env` files, runtime state, or generated private data.
- Inspect staged files before every commit and push.
- Do not expose the local backend beyond its intended loopback boundary without an explicit security design and review.
- Treat client input, event payloads, paths, and tool arguments as untrusted until validated by the backend.

## 6. Git and GitHub workflow

- Work on a feature branch; do not rewrite or force-push shared history.
- Before a commit: inspect the diff, run relevant tests, and check staged paths for secrets.
- After each completed, verified milestone or intentionally isolated logical change: create a focused commit and push it to the designated GitHub branch.
- Do not push failing, unreviewed, or partially implemented milestone work merely to satisfy a cadence.
- If the remote, branch, or authorization is unclear, stop and ask before pushing.
- Never use force-push unless the user explicitly requests it for a named branch.
- Commit messages must end with the required Claude Code attribution line.

## 7. Session handoff

Every session must begin by checking the plan and rules, then update the active milestone status before stopping. A session must leave a short handoff note containing:

- What changed
- Tests run and results
- Current milestone status
- Remaining risks/blockers
- Next recommended action

## 8. Change approval boundary

Before implementation of a new project-sized phase, maintain a design/plan document with goals, non-goals, acceptance criteria, alternatives, and rollback criteria. If a proposed change would alter CAP, GAMBIT, signed permits, or runtime authorization, stop and request an explicit architecture review.

