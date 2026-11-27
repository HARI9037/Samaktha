//! Parity assertion tests - validates Rust TUI behavior matches expected outcomes from fixtures.
//!
//! These tests consume the shared parity fixtures and run them through the Rust state machine,
//! verifying that the actual behavior matches the expected outcomes defined in the fixtures.
//! This ensures behavioral parity between Python/Textual and Rust/ratatui TUI clients.

use rust_tui::protocol::{EventEnvelope, ExecutionStateResponse, PROTOCOL_VERSION};
use rust_tui::state::{ExecutionStateMachine, ExecutionStatus, StateTransition};
use rust_tui::test_helpers::parity_fixtures::{
    load_all_parity_fixtures, load_parity_fixture, fixture_event_to_envelope, validate_expected_outcomes, ValidationResult, ParityFixture,
};
use chrono::{DateTime, Utc};
use serde_json::{json, Value};

/// Helper to create a test response for initializing the state machine.
fn create_test_response(execution_id: &str, status: &str) -> ExecutionStateResponse {
    ExecutionStateResponse {
        execution_id: execution_id.to_string(),
        status: status.to_string(),
        principal_id: "principal-123".to_string(),
        session_id: "sess-123".to_string(),
        pending_approval: status == "waiting_approval",
        result_available: false,
        created_at: DateTime::parse_from_rfc3339("2024-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc),
        updated_at: None,
        completed_at: None,
        error: None,
    }
}

/// Run a single parity fixture through the state machine and validate outcomes.
fn run_parity_fixture(fixture: &ParityFixture) -> ValidationResult {
    // Initialize state machine based on first event or default
    let mut machine = ExecutionStateMachine::new();
    let initial_status = if fixture.events.iter().any(|e| e.event_type == "EXECUTION.CREATED") {
        "created"
    } else {
        "running"
    };
    let response = create_test_response(&fixture.execution_id, initial_status);
    machine.initialize_from_response(response).unwrap();

    // Process all events through the state machine
    let mut all_transitions = Vec::new();

    for fixture_event in &fixture.events {
        let envelope = fixture_event_to_envelope(
            fixture_event,
            &fixture.execution_id,
            &fixture.session_id,
        );

        let transitions = machine.process_event(envelope);
        match transitions {
            Ok(trans) => all_transitions.extend(trans),
            Err(e) => {
                // Some fixtures may intentionally cause errors (e.g., stale events)
                // We still continue to collect envelopes for validation
                eprintln!("Warning: Error processing event {}: {}", fixture_event.sequence, e);
            }
        }
    }

    // Get final state
    let final_state = machine.state().unwrap();
    let final_status = format!("{:?}", final_state.status).to_lowercase();

    // Build terminal text: prefer MESSAGE_COMPLETED content (authoritative final content),
    // fall back to assistant_buffer for streaming display if no completion event
    let mut terminal_text = String::new();
    for trans in &all_transitions {
        if let StateTransition::AssistantMessageCompleted { content, .. } = trans {
            terminal_text = content.clone();
            break;
        }
    }
    if terminal_text.is_empty() {
        terminal_text = final_state.assistant_buffer.clone();
    }

    // Also include any execution state change messages from transitions
    for trans in &all_transitions {
        if let StateTransition::StatusChanged { to, .. } = trans {
            terminal_text.push_str(&format!(" [status: {:?}]", to));
        }
    }

    // Build processed events for validation:
    // Use event_log for all events (filters duplicates, maintains processed order)
    // But for ASSISTANT.TOKEN, use transitions which have correct processing order
    let event_log = &final_state.event_log;
    let mut processed_events: Vec<EventEnvelope> = Vec::new();

    // First, add all non-token events from event_log
    for entry in event_log {
        if entry.event_type != "ASSISTANT.TOKEN" {
            processed_events.push(EventEnvelope {
                sequence: entry.sequence,
                execution_id: fixture.execution_id.clone(),
                session_id: fixture.session_id.clone(),
                event_type: entry.event_type.clone(),
                payload: entry.raw_payload.clone(),
                timestamp: DateTime::parse_from_rfc3339(&entry.timestamp)
                    .unwrap()
                    .with_timezone(&Utc),
            });
        }
    }

    // Then add token events from transitions in processing order (correct sequence_number order)
    for trans in &all_transitions {
        if let StateTransition::AssistantToken { token, sequence_number } = trans {
            let mut payload = serde_json::Map::new();
            payload.insert("token".to_string(), Value::String(token.clone()));
            payload.insert("sequence_number".to_string(), Value::Number((*sequence_number).into()));
            processed_events.push(EventEnvelope {
                sequence: *sequence_number, // Use token sequence as envelope sequence for ordering
                execution_id: fixture.execution_id.clone(),
                session_id: fixture.session_id.clone(),
                event_type: "ASSISTANT.TOKEN".to_string(),
                payload: Value::Object(payload),
                timestamp: Utc::now(),
            });
        }
    }

    // Validate against expected outcomes
    validate_expected_outcomes(fixture, &processed_events, &final_status, &terminal_text)
}

#[test]
fn test_parity_all_fixtures() {
    let fixtures = load_all_parity_fixtures().expect("Failed to load parity fixtures");
    assert_eq!(fixtures.len(), 11, "Expected 11 parity fixtures");

    let mut all_errors = Vec::new();

    for fixture in &fixtures {
        eprintln!("Running parity test: {} ({})", fixture.scenario, fixture.description);
        let result = run_parity_fixture(fixture);

        if !result.is_ok() {
            for error in &result.errors {
                all_errors.push(format!("[{}] {}", fixture.scenario, error));
            }
        }
    }

    if !all_errors.is_empty() {
        panic!("Parity validation failed:\n{}", all_errors.join("\n"));
    }
}

#[test]
fn test_parity_01_ordinary_assistant_response() {
    let fixture = load_parity_fixture("01_ordinary_assistant_response")
        .expect("Failed to load fixture");
    let result = run_parity_fixture(&fixture);
    result.assert_ok();
}

#[test]
fn test_parity_02_search_results_sources() {
    let fixture = load_parity_fixture("02_search_results_sources")
        .expect("Failed to load fixture");
    let result = run_parity_fixture(&fixture);
    result.assert_ok();
}

#[test]
fn test_parity_03_create_then_write_file_context() {
    let fixture = load_parity_fixture("03_create_then_write_file_context")
        .expect("Failed to load fixture");
    let result = run_parity_fixture(&fixture);
    result.assert_ok();
}

#[test]
fn test_parity_04_approval_allow() {
    let fixture = load_parity_fixture("04_approval_allow")
        .expect("Failed to load fixture");
    let result = run_parity_fixture(&fixture);
    result.assert_ok();
}

#[test]
fn test_parity_05_approval_deny() {
    let fixture = load_parity_fixture("05_approval_deny")
        .expect("Failed to load fixture");
    let result = run_parity_fixture(&fixture);
    result.assert_ok();
}

#[test]
fn test_parity_06_cancellation() {
    let fixture = load_parity_fixture("06_cancellation")
        .expect("Failed to load fixture");
    let result = run_parity_fixture(&fixture);
    result.assert_ok();
}

#[test]
fn test_parity_07_provider_tool_failure() {
    let fixture = load_parity_fixture("07_provider_tool_failure")
        .expect("Failed to load fixture");
    let result = run_parity_fixture(&fixture);
    result.assert_ok();
}

#[test]
fn test_parity_08_reconnect() {
    let fixture = load_parity_fixture("08_reconnect")
        .expect("Failed to load fixture");
    let result = run_parity_fixture(&fixture);
    result.assert_ok();
}

#[test]
fn test_parity_09_stale_event() {
    let fixture = load_parity_fixture("09_stale_event")
        .expect("Failed to load fixture");
    let result = run_parity_fixture(&fixture);
    result.assert_ok();
}

#[test]
fn test_parity_10_duplicate_event() {
    let fixture = load_parity_fixture("10_duplicate_event")
        .expect("Failed to load fixture");
    let result = run_parity_fixture(&fixture);
    result.assert_ok();
}

#[test]
fn test_parity_11_out_of_order_event() {
    let fixture = load_parity_fixture("11_out_of_order_event")
        .expect("Failed to load fixture");
    let result = run_parity_fixture(&fixture);
    result.assert_ok();
}

#[test]
fn test_parity_fixture_events_are_valid_envelopes() {
    let fixtures = load_all_parity_fixtures().expect("Failed to load parity fixtures");

    for fixture in &fixtures {
        for event in &fixture.events {
            let envelope = fixture_event_to_envelope(event, &fixture.execution_id, &fixture.session_id);

            // Verify envelope has required fields
            assert_eq!(envelope.sequence, event.sequence);
            assert_eq!(envelope.execution_id, fixture.execution_id);
            assert_eq!(envelope.session_id, fixture.session_id);
            assert_eq!(envelope.event_type, event.event_type);
            assert_eq!(envelope.payload, event.payload);

            // Verify protocol version is present in relevant events
            if matches!(
                envelope.event_type.as_str(),
                "EXECUTION.CREATED" | "EXECUTION.STATE_CHANGED"
            ) {
                assert_eq!(
                    envelope.payload.get("protocol_version").and_then(|v| v.as_str()),
                    Some(PROTOCOL_VERSION)
                );
            }
        }
    }
}

#[test]
fn test_parity_expected_outcomes_structure() {
    let fixtures = load_all_parity_fixtures().expect("Failed to load parity fixtures");

    for fixture in &fixtures {
        let expected = &fixture.expected_outcomes;

        // Every fixture should have at least event_count and final_status
        assert!(
            expected.event_count.is_some(),
            "Fixture {} missing event_count",
            fixture.scenario
        );
        assert!(
            expected.final_status.is_some(),
            "Fixture {} missing final_status",
            fixture.scenario
        );

        // Verify expected outcomes match scenario type
        match fixture.scenario.as_str() {
            "ordinary_assistant_response" => {
                assert!(expected.assistant_content.is_some());
                assert!(expected.token_count.is_some());
            }
            "search_results_sources" => {
                assert!(expected.search_performed.is_some());
                assert!(expected.search_results_count.is_some());
                assert!(expected.search_query.is_some());
                assert!(expected.search_backend.is_some());
                assert!(expected.assistant_mentions_sources.is_some());
            }
            "create_then_write_file_context" => {
                assert!(expected.files_created.is_some());
                assert!(expected.files_read.is_some());
                assert!(expected.files_listed.is_some());
                assert!(expected.total_bytes_written.is_some());
                assert!(expected.final_directory_entries.is_some());
            }
            "approval_allow" => {
                assert!(expected.approval_requested.is_some());
                assert!(expected.approval_decision.is_some());
                assert!(expected.approval_reasons.is_some());
                assert!(expected.execution_resumed.is_some());
            }
            "approval_deny" => {
                assert!(expected.approval_requested.is_some());
                assert!(expected.approval_decision.is_some());
                assert!(expected.approval_reasons.is_some());
                assert!(expected.execution_failed.is_some());
                assert!(expected.error_code.is_some());
            }
            "cancellation" => {
                assert!(expected.cancelled.is_some());
                assert!(expected.cancellation_reason.is_some());
                assert!(expected.partial_output_received.is_some());
            }
            "provider_tool_failure" => {
                assert!(expected.tool_failed.is_some());
                assert!(expected.error_code.is_some());
                assert!(expected.retryable.is_some());
            }
            "reconnect" => {
                assert!(expected.reconnected.is_some());
                assert!(expected.last_known_sequence_before_reconnect.is_some());
                assert!(expected.first_sequence_after_reconnect.is_some());
                assert!(expected.no_events_lost.is_some());
                assert!(expected.message_fully_received.is_some());
            }
            "stale_event" => {
                assert!(expected.stale_events_received.is_some());
                assert!(expected.stale_sequences.is_some());
                assert!(expected.stale_events_ignored.is_some());
                assert!(expected.final_status_preserved.is_some());
                assert!(expected.no_state_regression.is_some());
            }
            "duplicate_event" => {
                assert!(expected.duplicate_sequences.is_some());
                assert!(expected.duplicate_events_ignored.is_some());
                assert!(expected.no_double_counting.is_some());
            }
            "out_of_order_event" => {
                assert!(expected.out_of_order_sequences.is_some());
                assert!(expected.events_reordered.is_some());
                assert!(expected.token_sequence_numbers.is_some());
                assert!(expected.no_gaps_in_processed.is_some());
            }
            _ => {}
        }
    }
}