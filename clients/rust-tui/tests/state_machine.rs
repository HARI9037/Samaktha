//! State machine tests - transitions, sequence validation, approval handling
//!
//! These tests verify the execution state machine correctly handles protocol events,
//! validates sequence numbers, manages approval flow, and handles resynchronization.

use rust_tui::protocol::{
    ApprovalDecision, ApprovalDecisionRequest, EventEnvelope, ExecutionStateResponse,
};
use rust_tui::state::{
    ExecutionState, ExecutionStateMachine, ExecutionStatus, StateTransition,
};
use chrono::{DateTime, Utc};
use serde_json::json;
use std::str::FromStr;

#[test]
fn test_status_parsing_from_string() {
    assert_eq!(ExecutionStatus::from_str("created"), Ok(ExecutionStatus::Created));
    assert_eq!(ExecutionStatus::from_str("running"), Ok(ExecutionStatus::Running));
    assert_eq!(
        ExecutionStatus::from_str("waiting_approval"),
        Ok(ExecutionStatus::WaitingApproval)
    );
    assert_eq!(ExecutionStatus::from_str("completed"), Ok(ExecutionStatus::Completed));
    assert_eq!(ExecutionStatus::from_str("failed"), Ok(ExecutionStatus::Failed));
    assert_eq!(ExecutionStatus::from_str("cancelled"), Ok(ExecutionStatus::Cancelled));
    assert_eq!(
        ExecutionStatus::from_str("unknown"),
        Err("Unknown execution status: unknown".to_string())
    );
}

#[test]
fn test_is_terminal_status() {
    assert!(!ExecutionStatus::Created.is_terminal());
    assert!(!ExecutionStatus::Running.is_terminal());
    assert!(!ExecutionStatus::WaitingApproval.is_terminal());
    assert!(ExecutionStatus::Completed.is_terminal());
    assert!(ExecutionStatus::Failed.is_terminal());
    assert!(ExecutionStatus::Cancelled.is_terminal());
}

#[test]
fn test_initialize_from_response() {
    let mut machine = ExecutionStateMachine::new();
    let response = ExecutionStateResponse {
        execution_id: "exec-123".to_string(),
        status: "running".to_string(),
        principal_id: "principal-456".to_string(),
        session_id: "sess-789".to_string(),
        pending_approval: false,
        result_available: false,
        created_at: DateTime::parse_from_rfc3339("2024-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc),
        updated_at: Some(
            DateTime::parse_from_rfc3339("2024-01-01T12:05:00Z")
                .unwrap()
                .with_timezone(&Utc),
        ),
        completed_at: None,
        error: None,
    };

    machine.initialize_from_response(response).unwrap();

    let state = machine.state().unwrap();
    assert_eq!(state.execution_id, "exec-123");
    assert_eq!(state.status, ExecutionStatus::Running);
    assert_eq!(state.principal_id, "principal-456");
    assert_eq!(state.session_id, "sess-789");
    assert!(!state.pending_approval);
    assert!(!state.result_available);
    assert_eq!(state.last_sequence, 0);
    assert_eq!(state.earliest_sequence, 0);
    assert_eq!(state.latest_sequence, 0);
}

#[test]
fn test_initialize_sets_earliest_latest() {
    let mut machine = ExecutionStateMachine::new();
    let response = ExecutionStateResponse {
        execution_id: "exec-123".to_string(),
        status: "running".to_string(),
        principal_id: "principal-456".to_string(),
        session_id: "sess-789".to_string(),
        pending_approval: false,
        result_available: false,
        created_at: DateTime::parse_from_rfc3339("2024-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc),
        updated_at: None,
        completed_at: None,
        error: None,
    };

    machine.initialize_from_response(response).unwrap();

    // Feed some events to test earliest/latest tracking (starting at sequence 1)
    let events = vec![
        EventEnvelope {
            sequence: 1,
            execution_id: "exec-123".to_string(),
            session_id: "sess-789".to_string(),
            event_type: "EXECUTION.STATE_CHANGED".to_string(),
            payload: json!({"status": "running", "protocol_version": "1.0"}),
            timestamp: DateTime::parse_from_rfc3339("2024-01-01T12:01:00Z")
                .unwrap()
                .with_timezone(&Utc),
        },
        EventEnvelope {
            sequence: 2,
            execution_id: "exec-123".to_string(),
            session_id: "sess-789".to_string(),
            event_type: "SEARCH.STARTED".to_string(),
            payload: json!({"query": "test", "backend": "local", "request_id": "req-1"}),
            timestamp: DateTime::parse_from_rfc3339("2024-01-01T12:02:00Z")
                .unwrap()
                .with_timezone(&Utc),
        },
    ];

    let mut transitions = Vec::new();
    for event in events {
        transitions.extend(machine.process_event(event).unwrap());
    }
    // Note: SEARCH.STARTED generates a transition, so we don't assert empty

    let state = machine.state().unwrap();
    assert_eq!(state.earliest_sequence, 1);
    assert_eq!(state.latest_sequence, 2);
    assert_eq!(state.last_sequence, 2);
}

// =============================================================================
// Sequence Validation Tests
// =============================================================================

#[test]
fn test_sequence_validation_normal_increment() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    // First event at sequence 1
    let events = vec![create_envelope(1, "EXECUTION.STATE_CHANGED", json!({"status": "running"}))];
    let mut transitions = Vec::new();
    for event in events {
        transitions.extend(machine.process_event(event).unwrap());
    }
    assert_eq!(machine.state().unwrap().last_sequence, 1);

    // Next event at sequence 2
    let events = vec![create_envelope(2, "SEARCH.STARTED", json!({"query": "test"}))];
    let mut transitions = Vec::new();
    for event in events {
        transitions.extend(machine.process_event(event).unwrap());
    }
    assert_eq!(machine.state().unwrap().last_sequence, 2);
}

#[test]
fn test_sequence_gap_detection_triggers_resync() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    // First event at sequence 1
    let events = vec![create_envelope(1, "EXECUTION.STATE_CHANGED", json!({"status": "running"}))];
    let mut transitions = Vec::new();
    for event in events {
        transitions.extend(machine.process_event(event).unwrap());
    }
    assert_eq!(machine.state().unwrap().last_sequence, 1);

    // Gap: next event at sequence 5 (gap > 1)
    let events = vec![create_envelope(5, "SEARCH.STARTED", json!({"query": "test"}))];
    let mut transitions = Vec::new();
    for event in events {
        transitions.extend(machine.process_event(event).unwrap());
    }

    // Should have Resynchronized transition
    let resync = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::Resynchronized { .. }));
    assert!(resync.is_some(), "Expected Resynchronized transition for gap > 1");

    if let StateTransition::Resynchronized { expected, actual, .. } = resync.unwrap() {
        assert_eq!(*expected, 2);
        assert_eq!(*actual, 5);
    } else {
        panic!("Expected Resynchronized transition");
    }

    // State should be updated to actual sequence
    assert_eq!(machine.state().unwrap().last_sequence, 5);
}

#[test]
fn test_sequence_regression_detection() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    // First event at sequence 1
    let events = vec![create_envelope(1, "EXECUTION.STATE_CHANGED", json!({"status": "running"}))];
    let mut transitions = Vec::new();
    for event in events {
        transitions.extend(machine.process_event(event).unwrap());
    }
    assert_eq!(machine.state().unwrap().last_sequence, 1);

    // Next event at sequence 5
    let events = vec![create_envelope(5, "SEARCH.STARTED", json!({"query": "test"}))];
    let mut transitions = Vec::new();
    for event in events {
        transitions.extend(machine.process_event(event).unwrap());
    }
    assert_eq!(machine.state().unwrap().last_sequence, 5);

    // Regression: next event at sequence 3 (< 5)
    let event = create_envelope(3, "FILE.READ_COMPLETED", json!({"path": "/test/file.txt"}));
    let result = machine.process_event(event);

    assert!(result.is_err());
    let err = result.unwrap_err().to_string();
    assert!(
        err.contains("Sequence regression") || err.contains("regression"),
        "Expected sequence regression error, got: {}",
        err
    );
}

#[test]
fn test_duplicate_sequence_allowed() {
    // Duplicate sequence (same as last) should be allowed (idempotent replay)
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let event = create_envelope(1, "EXECUTION.STATE_CHANGED", json!({"status": "running"}));
    machine.process_event(event).unwrap();

    // Same sequence again
    let event = create_envelope(1, "EXECUTION.STATE_CHANGED", json!({"status": "running"}));
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    // Should not error, should not create resync transition
    assert!(transitions.is_empty());
    assert_eq!(machine.state().unwrap().last_sequence, 1);
}

// =============================================================================
// Approval Flow Tests
// =============================================================================

#[test]
fn test_approval_requested_transition() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let events = vec![create_envelope(
        1,
        "APPROVAL.REQUESTED",
        json!({
            "approval_id": "approval-123",
            "tool_name": "shell",
            "arguments": {"command": "rm -rf /"},
            "reason": "Destructive command",
            "expires_at": "2024-01-01T13:00:00Z"
        }),
    )];

    let mut transitions = Vec::new();
    for event in events {
        transitions.extend(machine.process_event(event).unwrap());
    }

    let approval_transition = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::ApprovalRequested { .. }));
    assert!(approval_transition.is_some());

    let state = machine.state().unwrap();
    assert!(state.pending_approval);
    assert_eq!(state.pending_approval_id, Some("approval-123".to_string()));
}

#[test]
fn test_approval_resolved_allow() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "waiting_approval");
    machine.initialize_from_response(response).unwrap();

    // First request approval
    let event = create_envelope(
        1,
        "APPROVAL.REQUESTED",
        json!({"approval_id": "approval-123", "tool_name": "shell"}),
    );
    machine.process_event(event).unwrap();
    assert!(machine.state().unwrap().pending_approval);

    // Then resolve with allow
    let event = create_envelope(
        2,
        "APPROVAL.RESOLVED",
        json!({"approval_id": "approval-123", "decision": "allow", "resolved_at": "2024-01-01T12:05:00Z"}),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let resolved = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::ApprovalResolved { decision, .. } if decision == "allow"));
    assert!(resolved.is_some());

    let state = machine.state().unwrap();
    assert!(!state.pending_approval);
    assert!(state.pending_approval_id.is_none());
}

#[test]
fn test_approval_resolved_deny() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "waiting_approval");
    machine.initialize_from_response(response).unwrap();

    let events = vec![create_envelope(
        1,
        "APPROVAL.REQUESTED",
        json!({"approval_id": "approval-456", "tool_name": "shell"}),
    )];
    for event in events {
        machine.process_event(event).unwrap();
    }

    let event = create_envelope(
        2,
        "APPROVAL.RESOLVED",
        json!({"approval_id": "approval-456", "decision": "deny", "resolved_at": "2024-01-01T12:05:00Z"}),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let resolved = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::ApprovalResolved { decision, .. } if decision == "deny"));
    assert!(resolved.is_some());

    let state = machine.state().unwrap();
    assert!(!state.pending_approval);
}

#[test]
fn test_approval_decision_with_reasons() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "waiting_approval");
    machine.initialize_from_response(response).unwrap();

    let event = create_envelope(
        1,
        "APPROVAL.REQUESTED",
        json!({"approval_id": "approval-789"}),
    );
    machine.process_event(event).unwrap();

    let event = create_envelope(
        2,
        "APPROVAL.RESOLVED",
        json!({
            "approval_id": "approval-789",
            "decision": "allow",
            "reasons": ["User approved", "Safe operation"],
            "resolved_at": "2024-01-01T12:05:00Z"
        }),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let resolved = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::ApprovalResolved { .. }));
    assert!(resolved.is_some());
}

// =============================================================================
// Search Event Transitions
// =============================================================================

#[test]
fn test_search_started_transition() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let event = create_envelope(
        1,
        "SEARCH.STARTED",
        json!({
            "query": "rust",
            "backend": "local",
            "filters": {"type": "file"},
            "request_id": "req-1"
        }),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let search_started = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::SearchStarted { .. }));
    assert!(search_started.is_some());

    let Some(StateTransition::SearchStarted { query, .. }) = search_started else { return; };
    assert_eq!(query, "rust");
}

#[test]
fn test_search_completed_transition() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let event = create_envelope(
        1,
        "SEARCH.COMPLETED",
        json!({
            "query": "rust",
            "backend": "local",
            "results": [{"path": "file1.rs"}],
            "result_count": 1,
            "request_id": "req-1"
        }),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let completed = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::SearchCompleted { .. }));
    assert!(completed.is_some());

    let Some(StateTransition::SearchCompleted { result_count, .. }) = completed else { return; };
    assert_eq!(*result_count, 1);
}

#[test]
fn test_search_failed_transition() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let event = create_envelope(
        1,
        "SEARCH.FAILED",
        json!({
            "query": "rust",
            "backend": "local",
            "error_code": "NOT_FOUND",
            "error_message": "No results",
            "request_id": "req-1"
        }),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let failed = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::SearchFailed { .. }));
    assert!(failed.is_some());

    let Some(StateTransition::SearchFailed { error_message, .. }) = failed else { return; };
    assert_eq!(error_message, "No results");
}

// =============================================================================
// File Event Transitions
// =============================================================================

#[test]
fn test_file_read_completed_transition() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let event = create_envelope(
        1,
        "FILE.READ_COMPLETED",
        json!({
            "path": "/test/file.txt",
            "content": "hello",
            "size": 5,
            "encoding": "utf-8",
            "request_id": "req-1"
        }),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let read_completed = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::FileReadCompleted { .. }));
    assert!(read_completed.is_some());

    let Some(StateTransition::FileReadCompleted { path, .. }) = read_completed else { return; };
    assert_eq!(path, "/test/file.txt");
}

#[test]
fn test_file_write_completed_transition() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let event = create_envelope(
        1,
        "FILE.WRITE_COMPLETED",
        json!({
            "path": "/test/file.txt",
            "bytes_written": 100,
            "request_id": "req-1"
        }),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let write_completed = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::FileWriteCompleted { .. }));
    assert!(write_completed.is_some());

    let Some(StateTransition::FileWriteCompleted { path, bytes_written, .. }) = write_completed else { return; };
    assert_eq!(path, "/test/file.txt");
    assert_eq!(*bytes_written, 100);
}

// =============================================================================
// Assistant Streaming Tests
// =============================================================================

#[test]
fn test_assistant_message_started_transition() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let event = create_envelope(
        1,
        "ASSISTANT.MESSAGE_STARTED",
        json!({
            "model_id": "gpt-4",
            "request_id": "req-1"
        }),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let started = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::AssistantMessageStarted { .. }));
    assert!(started.is_some());

    let Some(StateTransition::AssistantMessageStarted { model_id, .. }) = started else { return; };
    assert_eq!(model_id, "gpt-4");
}

#[test]
fn test_assistant_token_accumulates_in_buffer() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    // First token (sequence_number: 1)
    let event = create_envelope(
        1,
        "ASSISTANT.TOKEN",
        json!({"token": "Hello", "request_id": "req-1", "sequence_number": 1}),
    );
    machine.process_event(event).unwrap();

    // Second token (sequence_number: 2)
    let event = create_envelope(
        2,
        "ASSISTANT.TOKEN",
        json!({"token": " world", "request_id": "req-1", "sequence_number": 2}),
    );
    machine.process_event(event).unwrap();

    let state = machine.state().unwrap();
    assert_eq!(state.assistant_buffer, "Hello world");
}

#[test]
fn test_assistant_message_completed_clears_buffer() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    // Accumulate tokens
    let event = create_envelope(
        1,
        "ASSISTANT.TOKEN",
        json!({"token": "Hello", "request_id": "req-1"}),
    );
    machine.process_event(event).unwrap();

    // Complete message
    let event = create_envelope(
        2,
        "ASSISTANT.MESSAGE_COMPLETED",
        json!({"request_id": "req-1", "total_tokens": 5}),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let completed = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::AssistantMessageCompleted { .. }));
    assert!(completed.is_some());

    let state = machine.state().unwrap();
    // Buffer should be cleared or contain final message
    assert!(state.assistant_buffer.is_empty() || state.assistant_buffer == "Hello");
}

#[test]
fn test_assistant_error_transition() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let event = create_envelope(
        1,
        "ASSISTANT.ERROR",
        json!({
            "error_code": "RATE_LIMIT",
            "error_message": "Rate limit exceeded",
            "request_id": "req-1"
        }),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let error = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::AssistantError { .. }));
    assert!(error.is_some());

    let Some(StateTransition::AssistantError { error_message, .. }) = error else { return; };
    assert_eq!(error_message, "Rate limit exceeded");
}

// =============================================================================
// Execution State Change Tests
// =============================================================================

#[test]
fn test_execution_state_changed_running_to_completed() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let event = create_envelope(
        1,
        "EXECUTION.STATE_CHANGED",
        json!({"status": "completed", "protocol_version": "1.0"}),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let status_changed = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::StatusChanged { .. }));
    assert!(status_changed.is_some());

    let Some(StateTransition::StatusChanged { from, to }) = status_changed else { return; };
    assert_eq!(*from, ExecutionStatus::Running);
    assert_eq!(*to, ExecutionStatus::Completed);

    assert!(machine.state().unwrap().status == ExecutionStatus::Completed);
}

#[test]
fn test_execution_state_changed_to_failed() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let event = create_envelope(
        1,
        "EXECUTION.STATE_CHANGED",
        json!({"status": "failed", "protocol_version": "1.0", "error": "Task failed"}),
    );
    let mut transitions = Vec::new();
    transitions.extend(machine.process_event(event).unwrap());

    let status_changed = transitions
        .iter()
        .find(|t| matches!(t, StateTransition::StatusChanged { .. }));
    assert!(status_changed.is_some());

    let Some(StateTransition::StatusChanged { from, to }) = status_changed else { return; };
    assert_eq!(*from, ExecutionStatus::Running);
    assert_eq!(*to, ExecutionStatus::Failed);

    let state = machine.state().unwrap();
    assert_eq!(state.status, ExecutionStatus::Failed);
}

// =============================================================================
// Resynchronization Tests
// =============================================================================

#[test]
fn test_resync_signal_processing() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    let resync_signal = rust_tui::protocol::ResynchronizationSignal {
        signal_type: "RESYNC".to_string(),
        expected_sequence: 10,
        actual_sequence: 20,
        message: "Resync test".to_string(),
    };

    machine.process_resync(resync_signal).unwrap();

    let state = machine.state().unwrap();
    assert_eq!(state.earliest_sequence, 10);
    assert_eq!(state.latest_sequence, 20);
    assert_eq!(state.last_sequence, 20); // Should jump to latest
}

#[test]
fn test_protocol_version_validation() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "running");
    machine.initialize_from_response(response).unwrap();

    // Valid version
    let events = vec![create_envelope(
        1,
        "EXECUTION.STATE_CHANGED",
        json!({"status": "running", "protocol_version": "1.0"}),
    )];
    for event in events {
        let result = machine.process_event(event);
        assert!(result.is_ok());
    }

    // Invalid version
    let events = vec![create_envelope(
        2,
        "EXECUTION.STATE_CHANGED",
        json!({"status": "running", "protocol_version": "2.0"}),
    )];
    let mut has_error = false;
    for event in events {
        let result = machine.process_event(event);
        if result.is_err() {
            has_error = true;
            let err = result.unwrap_err().to_string();
            assert!(
                err.contains("protocol version") || err.contains("PROTOCOL_VERSION"),
                "Expected protocol version error, got: {}",
                err
            );
        }
    }
    assert!(has_error, "Expected an error for invalid protocol version");
}

// =============================================================================
// Approval Handling via Events
// =============================================================================

#[test]
fn test_approval_requested_event() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "waiting_approval");
    machine.initialize_from_response(response).unwrap();

    // Process approval requested event
    let event = create_envelope(
        1,
        "APPROVAL.REQUESTED",
        json!({"approval_id": "approval-123", "tool_name": "shell"}),
    );
    let transitions = machine.process_event(event).unwrap();

    // Should generate ApprovalRequested transition
    assert!(matches!(transitions[0], StateTransition::ApprovalRequested { .. }));

    let state = machine.state().unwrap();
    assert!(state.pending_approval);
    assert_eq!(state.pending_approval_id, Some("approval-123".to_string()));
}

#[test]
fn test_approval_resolved_allow_event() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "waiting_approval");
    machine.initialize_from_response(response).unwrap();

    // First, set up pending approval
    let event1 = create_envelope(
        1,
        "APPROVAL.REQUESTED",
        json!({"approval_id": "approval-123", "tool_name": "shell"}),
    );
    machine.process_event(event1).unwrap();

    // Then process approval resolved with allow
    let event2 = create_envelope(
        2,
        "APPROVAL.RESOLVED",
        json!({"approval_id": "approval-123", "decision": "allow"}),
    );
    let transitions = machine.process_event(event2).unwrap();

    // Should generate ApprovalResolved transition
    assert!(matches!(transitions[0], StateTransition::ApprovalResolved { ref decision, .. } if decision == "allow"));

    let state = machine.state().unwrap();
    assert!(!state.pending_approval);
}

#[test]
fn test_approval_resolved_deny_event() {
    let mut machine = ExecutionStateMachine::new();
    let response = create_test_response("exec-1", "waiting_approval");
    machine.initialize_from_response(response).unwrap();

    // First, set up pending approval
    let event1 = create_envelope(
        1,
        "APPROVAL.REQUESTED",
        json!({"approval_id": "approval-456", "tool_name": "shell"}),
    );
    machine.process_event(event1).unwrap();

    // Then process approval resolved with deny
    let event2 = create_envelope(
        2,
        "APPROVAL.RESOLVED",
        json!({"approval_id": "approval-456", "decision": "deny", "reasons": ["User denied"]}),
    );
    let transitions = machine.process_event(event2).unwrap();

    // Should generate ApprovalResolved transition with deny
    assert!(matches!(transitions[0], StateTransition::ApprovalResolved { ref decision, .. } if decision == "deny"));

    let state = machine.state().unwrap();
    assert!(!state.pending_approval);
}

// =============================================================================
// Helper Functions
// =============================================================================

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

fn create_envelope(
    sequence: u64,
    event_type: &str,
    payload: serde_json::Value,
) -> EventEnvelope {
    EventEnvelope {
        sequence,
        execution_id: "exec-1".to_string(),
        session_id: "sess-123".to_string(),
        event_type: event_type.to_string(),
        payload,
        timestamp: DateTime::parse_from_rfc3339("2024-01-01T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc),
    }
}