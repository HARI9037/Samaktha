# M7 Task 7: Prove Rust/Textual Behavioral Parity and Compatibility Selection

## Overview
Prove both Rust and Textual clients behave identically against the same governed backend contract, implement explicit client selection with Textual as default/fallback, and verify all tests pass.

## Global Constraints
- Protocol version: "1.0"
- Backend governs: CAP (policy/approval), GAMBIT (planning), signed ExecutionPermit
- Loopback-only binding (127.0.0.1)
- No credentials in repo
- Fail-closed version negotiation
- 11 parity fixtures in /tests/fixtures/parity/

## Tasks (Sequential)

### Task 1: Define fixture-driven parity cases (11 cases)
Fix the failing parity tests. Currently 9 passing, 5 failing:
1. provider_tool_failure - error code mismatch
2. stale_event - final status not preserved  
3. out_of_order_event - token sequence numbers mismatch
4. duplicate_event - event/token count mismatch
5. approval_allow/deny - execution_resumed validation issue

### Task 2: Add failing parity assertions
Add assertions for any missing expected outcomes in fixtures

### Task 3: Implement explicit client selection
Add `--client textual|rust` flag to CLI, default to textual

### Task 4: Run parity and full test suites
Run `cargo test parity` and full test suite, verify all pass

### Task 5: Record parity evidence and review rollback
Document parity results, verify rollback path works

### Task 6: Commit as `test: verify rust and textual tui parity`
Final commit with evidence

## Acceptance Criteria
- All 11 parity tests pass
- Client selection works (--client flag)
- Textual is default/fallback
- Full test suite passes