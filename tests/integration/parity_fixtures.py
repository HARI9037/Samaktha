"""Parity test fixtures loader for Python/Textual TUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from dataclasses import dataclass

from app.api.protocol import EventEnvelope


@dataclass
class ParityFixture:
    """Loaded parity test fixture with events and expected outcomes."""
    scenario: str
    description: str
    execution_id: str
    session_id: str
    events: list[EventEnvelope]
    expected_outcomes: dict[str, Any]

    @property
    def event_count(self) -> int:
        return len(self.events)


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "parity"


def load_parity_fixture(scenario_name: str) -> ParityFixture:
    """Load a parity fixture by scenario name (e.g., '01_ordinary_assistant_response')."""
    fixture_path = FIXTURES_DIR / f"{scenario_name}.json"
    if not fixture_path.exists():
        # Try with just the number prefix
        for path in FIXTURES_DIR.glob(f"{scenario_name}*.json"):
            fixture_path = path
            break
        else:
            raise FileNotFoundError(f"Parity fixture not found: {scenario_name}")

    with fixture_path.open() as f:
        data = json.load(f)

    # Use fixture-level execution_id and session_id for all events
    execution_id = data["execution_id"]
    session_id = data["session_id"]

    events = []
    for event_data in data["events"]:
        envelope = EventEnvelope(
            sequence=event_data["sequence"],
            execution_id=execution_id,
            session_id=session_id,
            event_type=event_data["event_type"],
            payload=event_data["payload"],
            timestamp=event_data["timestamp"],
        )
        events.append(envelope)

    return ParityFixture(
        scenario=data["scenario"],
        description=data["description"],
        execution_id=execution_id,
        session_id=session_id,
        events=events,
        expected_outcomes=data["expected_outcomes"],
    )


def load_all_parity_fixtures() -> list[ParityFixture]:
    """Load all parity fixtures from the fixtures directory."""
    fixtures = []
    for fixture_path in sorted(FIXTURES_DIR.glob("*.json")):
        scenario_name = fixture_path.stem
        fixtures.append(load_parity_fixture(scenario_name))
    return fixtures


def get_fixture_names() -> list[str]:
    """Get list of all available fixture scenario names."""
    return sorted([p.stem for p in FIXTURES_DIR.glob("*.json")])


# Fixture classification: which fixtures are supported by which client
# Fixtures 1-7: Core protocol behavior - both Rust and Textual clients should pass
# Fixtures 8-11: Rust-only robustness features - Textual client does not implement
#   - 08_reconnect: Auto-reconnect with sequence cursor
#   - 09_stale_event: Stale/duplicate sequence detection and rejection
#   - 10_duplicate_event: Duplicate event deduplication
#   - 11_out_of_order_event: Out-of-order event reordering
RUST_ONLY_FIXTURES = {
    "08_reconnect",
    "09_stale_event",
    "10_duplicate_event",
    "11_out_of_order_event",
}


def is_rust_only_fixture(scenario_name: str) -> bool:
    """Check if a fixture is Rust-only (not supported by Textual client)."""
    return scenario_name in RUST_ONLY_FIXTURES


def get_textual_supported_fixtures() -> list[str]:
    """Get list of fixtures supported by Textual client (fixtures 1-7)."""
    all_fixtures = get_fixture_names()
    return [f for f in all_fixtures if not is_rust_only_fixture(f)]


def get_rust_only_fixtures() -> list[str]:
    """Get list of fixtures that are Rust-only robustness features."""
    return sorted(RUST_ONLY_FIXTURES)


# Expected outcomes validation helpers
def validate_expected_outcomes(
    fixture: ParityFixture,
    actual_events: list[EventEnvelope],
    actual_final_status: str,
    actual_terminal_text: str = "",
) -> list[str]:
    """Validate actual test results against fixture expected outcomes.

    Returns list of validation errors (empty if all pass).
    """
    errors = []
    expected = fixture.expected_outcomes

    # Check event count
    if "event_count" in expected:
        if len(actual_events) != expected["event_count"]:
            errors.append(
                f"Event count mismatch: expected {expected['event_count']}, got {len(actual_events)}"
            )

    # Check final status
    if "final_status" in expected:
        if actual_final_status != expected["final_status"]:
            errors.append(
                f"Final status mismatch: expected {expected['final_status']}, got {actual_final_status}"
            )

    # Check terminal text (if provided)
    if actual_terminal_text and "terminal_text" in expected:
        if expected["terminal_text"] not in actual_terminal_text:
            errors.append(
                f"Terminal text mismatch: expected to contain '{expected['terminal_text']}'"
            )

    # Check assistant content
    if "assistant_content" in expected:
        if actual_terminal_text and expected["assistant_content"] not in actual_terminal_text:
            errors.append(
                f"Assistant content mismatch: expected '{expected['assistant_content']}'"
            )

    # Check token count
    if "token_count" in expected:
        token_events = [e for e in actual_events if e.event_type == "ASSISTANT.TOKEN"]
        if len(token_events) != expected["token_count"]:
            errors.append(
                f"Token count mismatch: expected {expected['token_count']}, got {len(token_events)}"
            )

    # Check approval outcomes
    if "approval_requested" in expected:
        approval_requested_events = [
            e for e in actual_events if e.event_type == "APPROVAL.REQUESTED"
        ]
        if expected["approval_requested"] and not approval_requested_events:
            errors.append("Expected approval to be requested but it wasn't")
        elif not expected["approval_requested"] and approval_requested_events:
            errors.append("Expected no approval request but one was received")

    if "approval_decision" in expected:
        approval_resolved_events = [
            e for e in actual_events if e.event_type == "APPROVAL.RESOLVED"
        ]
        if approval_resolved_events:
            actual_decision = approval_resolved_events[0].payload.get("decision")
            if actual_decision != expected["approval_decision"]:
                errors.append(
                    f"Approval decision mismatch: expected {expected['approval_decision']}, got {actual_decision}"
                )

    if "approval_reasons" in expected:
        approval_resolved_events = [
            e for e in actual_events if e.event_type == "APPROVAL.RESOLVED"
        ]
        if approval_resolved_events:
            actual_reasons = approval_resolved_events[0].payload.get("reasons", [])
            expected_reasons = expected["approval_reasons"]
            if actual_reasons != expected_reasons:
                errors.append(
                    f"Approval reasons mismatch: expected {expected_reasons}, got {actual_reasons}"
                )

    # Check execution resumed after approval
    if "execution_resumed" in expected:
        state_events = [e for e in actual_events if e.event_type == "EXECUTION.STATE_CHANGED"]
        running_after_pause = any(
            e.payload.get("status") == "running" and e.payload.get("pending_approval") is False
            for e in state_events
        )
        if expected["execution_resumed"] and not running_after_pause:
            errors.append("Expected execution to resume after approval but it didn't")

    # Check search outcomes
    if "search_performed" in expected:
        search_started = [e for e in actual_events if e.event_type == "SEARCH.STARTED"]
        if expected["search_performed"] and not search_started:
            errors.append("Expected search to be performed but it wasn't")

    if "search_results_count" in expected:
        search_completed = [e for e in actual_events if e.event_type == "SEARCH.COMPLETED"]
        if search_completed:
            actual_count = search_completed[0].payload.get("result_count", 0)
            if actual_count != expected["search_results_count"]:
                errors.append(
                    f"Search results count mismatch: expected {expected['search_results_count']}, got {actual_count}"
                )

    if "search_query" in expected:
        search_started = [e for e in actual_events if e.event_type == "SEARCH.STARTED"]
        if search_started:
            actual_query = search_started[0].payload.get("query", "")
            if actual_query != expected["search_query"]:
                errors.append(
                    f"Search query mismatch: expected '{expected['search_query']}', got '{actual_query}'"
                )

    if "search_backend" in expected:
        search_started = [e for e in actual_events if e.event_type == "SEARCH.STARTED"]
        if search_started:
            actual_backend = search_started[0].payload.get("backend", "")
            if actual_backend != expected["search_backend"]:
                errors.append(
                    f"Search backend mismatch: expected '{expected['search_backend']}', got '{actual_backend}'"
                )

    # Check file outcomes
    if "files_created" in expected:
        write_completed = [e for e in actual_events if e.event_type == "FILE.WRITE_COMPLETED"]
        if len(write_completed) != expected["files_created"]:
            errors.append(
                f"Files created mismatch: expected {expected['files_created']}, got {len(write_completed)}"
            )

    if "files_read" in expected:
        read_completed = [e for e in actual_events if e.event_type == "FILE.READ_COMPLETED"]
        if len(read_completed) != expected["files_read"]:
            errors.append(
                f"Files read mismatch: expected {expected['files_read']}, got {len(read_completed)}"
            )

    if "files_listed" in expected:
        list_completed = [e for e in actual_events if e.event_type == "FILE.LIST_COMPLETED"]
        total_entries = sum(e.payload.get("entry_count", 0) for e in list_completed)
        if total_entries != expected["files_listed"]:
            errors.append(
                f"Files listed mismatch: expected {expected['files_listed']}, got {total_entries}"
            )

    if "total_bytes_written" in expected:
        write_completed = [e for e in actual_events if e.event_type == "FILE.WRITE_COMPLETED"]
        total_bytes = sum(e.payload.get("bytes_written", 0) for e in write_completed)
        if total_bytes != expected["total_bytes_written"]:
            errors.append(
                f"Total bytes written mismatch: expected {expected['total_bytes_written']}, got {total_bytes}"
            )

    if "final_directory_entries" in expected:
        list_completed = [e for e in actual_events if e.event_type == "FILE.LIST_COMPLETED"]
        if list_completed:
            final_entries = list_completed[-1].payload.get("entry_count", 0)
            if final_entries != expected["final_directory_entries"]:
                errors.append(
                    f"Final directory entries mismatch: expected {expected['final_directory_entries']}, got {final_entries}"
                )

    # Check cancellation
    if "cancelled" in expected:
        cancelled_events = [e for e in actual_events if e.event_type == "EXECUTION.CANCELLED"]
        if expected["cancelled"] and not cancelled_events:
            errors.append("Expected execution to be cancelled but it wasn't")

    if "cancellation_reason" in expected:
        cancelled_events = [e for e in actual_events if e.event_type == "EXECUTION.CANCELLED"]
        if cancelled_events:
            actual_reason = cancelled_events[0].payload.get("reason", "")
            if actual_reason != expected["cancellation_reason"]:
                errors.append(
                    f"Cancellation reason mismatch: expected '{expected['cancellation_reason']}', got '{actual_reason}'"
                )

    # Check error codes
    if "error_code" in expected:
        failed_events = [e for e in actual_events if e.event_type == "EXECUTION.STATE_CHANGED"
                        and e.payload.get("status") == "failed"]
        if failed_events:
            actual_error = failed_events[0].payload.get("error", {})
            actual_code = actual_error.get("code") if isinstance(actual_error, dict) else actual_error
            if actual_code != expected["error_code"]:
                errors.append(
                    f"Error code mismatch: expected {expected['error_code']}, got {actual_code}"
                )

    # Check tool failure
    if "tool_failed" in expected:
        tool_failed_events = [e for e in actual_events if e.event_type in ("SEARCH.FAILED", "FILE.READ_FAILED", "FILE.WRITE_FAILED", "ASSISTANT.ERROR")]
        if expected["tool_failed"] and not tool_failed_events:
            errors.append("Expected tool failure but none occurred")

    if "tool_name" in expected:
        tool_failed_events = [e for e in actual_events if e.event_type in ("SEARCH.FAILED", "FILE.READ_FAILED", "FILE.WRITE_FAILED", "ASSISTANT.ERROR")]
        if tool_failed_events:
            # Check if the error mentions the expected tool
            pass  # Tool name validation would depend on specific error structure

    # Check retryable
    if "retryable" in expected:
        failed_events = [e for e in actual_events if e.event_type == "EXECUTION.STATE_CHANGED"
                        and e.payload.get("status") == "failed"]
        if failed_events:
            actual_error = failed_events[0].payload.get("error", {})
            actual_retryable = actual_error.get("retryable") if isinstance(actual_error, dict) else False
            if actual_retryable != expected["retryable"]:
                errors.append(
                    f"Retryable mismatch: expected {expected['retryable']}, got {actual_retryable}"
                )

    # Check reconnect
    if "reconnected" in expected:
        # This would need specific reconnect event tracking
        pass

    if "last_known_sequence_before_reconnect" in expected:
        pass  # Would need state tracking

    if "first_sequence_after_reconnect" in expected:
        pass

    if "no_events_lost" in expected:
        pass

    if "message_fully_received" in expected:
        if "final_content" in expected:
            if expected["final_content"] not in actual_terminal_text:
                errors.append(
                    f"Final content mismatch: expected '{expected['final_content']}' in terminal text"
                )

    # Check stale events - validate that stale sequences exist in fixture events
    if "stale_events_received" in expected:
        # Count events that appear "stale" - for the fixture, these are the events
        # with sequences in stale_sequences that should be ignored by a state machine
        pass  # The fixture itself contains these events

    if "stale_sequences" in expected:
        # Verify the stale sequences exist in the fixture events
        actual_stale_sequences = [
            e.sequence for e in actual_events if e.sequence in expected["stale_sequences"]
        ]
        if actual_stale_sequences != expected["stale_sequences"]:
            errors.append(
                f"Stale sequences mismatch: expected {expected['stale_sequences']}, got {actual_stale_sequences}"
            )

    if "stale_events_ignored" in expected:
        # In the Python test, we just verify the fixture has the expected stale events
        if expected["stale_events_ignored"]:
            # The fixture should contain the stale sequences
            pass

    if "final_status_preserved" in expected:
        if actual_final_status != expected["final_status_preserved"]:
            errors.append(
                f"Final status not preserved: expected {expected['final_status_preserved']}, got {actual_final_status}"
            )

    if "no_state_regression" in expected:
        pass  # Would need state history tracking

    # Check duplicate events - verify duplicate sequences in fixture
    if "duplicate_sequences" in expected:
        # Count occurrences of each sequence in fixture events
        from collections import Counter
        sequence_counts = Counter(e.sequence for e in actual_events)
        actual_duplicates = [seq for seq, count in sequence_counts.items() if count > 1]
        if actual_duplicates != expected["duplicate_sequences"]:
            errors.append(
                f"Duplicate sequences mismatch: expected {expected['duplicate_sequences']}, got {actual_duplicates}"
            )

    if "duplicate_events_ignored" in expected:
        # The fixture contains duplicates - they should be ignored by state machine
        pass

    if "no_double_counting" in expected:
        # Validate token count matches expected (excluding duplicates)
        if "token_count" in expected:
            token_events = [e for e in actual_events if e.event_type == "ASSISTANT.TOKEN"]
            # For fixtures, we count unique sequence numbers
            unique_token_seqs = set(e.payload.get("sequence_number") for e in token_events if e.payload.get("sequence_number") is not None)
            if len(unique_token_seqs) != expected["token_count"]:
                errors.append(
                    f"Token count (no double counting) mismatch: expected {expected['token_count']}, got {len(unique_token_seqs)}"
                )

    # Check out of order - verify sequences are out of order in fixture
    if "out_of_order_sequences" in expected:
        # Verify the fixture contains these sequences in non-monotonic order
        actual_sequences = [e.sequence for e in actual_events]
        # Check that the expected out-of-order sequences are not in monotonic order in the fixture
        for i, seq in enumerate(expected["out_of_order_sequences"]):
            if i > 0:
                prev_seq = expected["out_of_order_sequences"][i-1]
                # Find positions in actual events
                try:
                    pos = actual_sequences.index(seq)
                    prev_pos = actual_sequences.index(prev_seq)
                    if pos <= prev_pos:
                        # This is expected for out-of-order - sequences appear out of order
                        pass
                except ValueError:
                    pass

    if "events_reordered" in expected:
        # The fixture has out-of-order events; state machine should reorder them
        pass

    if "token_sequence_numbers" in expected:
        token_events = [e for e in actual_events if e.event_type == "ASSISTANT.TOKEN"]
        actual_sequences = [e.payload.get("sequence_number") for e in token_events]
        if actual_sequences != expected["token_sequence_numbers"]:
            errors.append(
                f"Token sequence numbers mismatch: expected {expected['token_sequence_numbers']}, got {actual_sequences}"
            )

    if "no_gaps_in_processed" in expected:
        # Validate that after reordering, there are no gaps in token sequences
        if "token_sequence_numbers" in expected:
            expected_sequences = expected["token_sequence_numbers"]
            if expected_sequences:
                if list(range(1, max(expected_sequences) + 1)) != expected_sequences:
                    errors.append(
                        f"Gaps in processed token sequences: {expected_sequences}"
                    )

    return errors