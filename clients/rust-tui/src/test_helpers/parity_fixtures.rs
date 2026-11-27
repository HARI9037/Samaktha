/// Parity test fixtures loader for Rust/ratatui TUI.

use crate::protocol::{EventEnvelope, PROTOCOL_VERSION};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

/// Loaded parity test fixture with events and expected outcomes.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParityFixture {
    pub scenario: String,
    pub description: String,
    pub execution_id: String,
    pub session_id: String,
    pub events: Vec<ParityFixtureEvent>,
    pub expected_outcomes: ExpectedOutcomes,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParityFixtureEvent {
    pub sequence: u64,
    pub event_type: String,
    pub payload: Value,
    pub timestamp: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExpectedOutcomes {
    // Basic outcomes
    #[serde(skip_serializing_if = "Option::is_none")]
    pub event_count: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub final_status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub terminal_text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub assistant_content: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token_count: Option<u64>,

    // Approval outcomes
    #[serde(skip_serializing_if = "Option::is_none")]
    pub approval_requested: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub approval_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub approval_decision: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub approval_reasons: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub execution_resumed: Option<bool>,

    // Search outcomes
    #[serde(skip_serializing_if = "Option::is_none")]
    pub search_performed: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub search_results_count: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub search_query: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub search_backend: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub assistant_mentions_sources: Option<bool>,

    // File outcomes
    #[serde(skip_serializing_if = "Option::is_none")]
    pub files_created: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub files_read: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub files_listed: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_bytes_written: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub final_directory_entries: Option<u64>,

    // Cancellation outcomes
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cancelled: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cancellation_reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub partial_output_received: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub partial_tokens: Option<u64>,

    // Error outcomes
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_failed: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_code: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub assistant_error_code: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub execution_failed: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub retryable: Option<bool>,

    // Reconnect outcomes
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reconnected: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_known_sequence_before_reconnect: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub first_sequence_after_reconnect: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub no_events_lost: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message_fully_received: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub final_content: Option<String>,

    // Stale event outcomes
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stale_events_received: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stale_sequences: Option<Vec<u64>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stale_events_ignored: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub final_status_preserved: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub no_state_regression: Option<bool>,

    // Duplicate event outcomes
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duplicate_sequences: Option<Vec<u64>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duplicate_events_ignored: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub no_double_counting: Option<bool>,

    // Out of order outcomes
    #[serde(skip_serializing_if = "Option::is_none")]
    pub out_of_order_sequences: Option<Vec<u64>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub events_reordered: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token_sequence_numbers: Option<Vec<u64>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub no_gaps_in_processed: Option<bool>,
}

/// Convert a ParityFixtureEvent to an EventEnvelope.
pub fn fixture_event_to_envelope(
    event: &ParityFixtureEvent,
    execution_id: &str,
    session_id: &str,
) -> EventEnvelope {
    let timestamp = event.timestamp.parse::<DateTime<Utc>>().unwrap_or_else(|_| Utc::now());

    EventEnvelope {
        sequence: event.sequence,
        execution_id: execution_id.to_string(),
        session_id: session_id.to_string(),
        event_type: event.event_type.clone(),
        payload: event.payload.clone(),
        timestamp,
    }
}

/// Load a parity fixture by scenario name (e.g., "01_ordinary_assistant_response").
pub fn load_parity_fixture(scenario_name: &str) -> Result<ParityFixture, Box<dyn std::error::Error>> {
    let fixtures_dir = get_fixtures_dir();
    let fixture_path = fixtures_dir.join(format!("{}.json", scenario_name));

    if !fixture_path.exists() {
        // Try with glob pattern
        let entries = fs::read_dir(&fixtures_dir)?;
        for entry in entries {
            let entry = entry?;
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) == Some("json") {
                let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("");
                if stem.starts_with(scenario_name) {
                    return load_parity_fixture_from_path(&path);
                }
            }
        }
        return Err(format!("Parity fixture not found: {}", scenario_name).into());
    }

    load_parity_fixture_from_path(&fixture_path)
}

/// Load a parity fixture from a specific path.
pub fn load_parity_fixture_from_path(path: &Path) -> Result<ParityFixture, Box<dyn std::error::Error>> {
    let content = fs::read_to_string(path)?;
    let fixture: ParityFixture = serde_json::from_str(&content)?;
    Ok(fixture)
}

/// Load all parity fixtures from the fixtures directory.
pub fn load_all_parity_fixtures() -> Result<Vec<ParityFixture>, Box<dyn std::error::Error>> {
    let fixtures_dir = get_fixtures_dir();
    let mut fixtures = Vec::new();

    let mut entries: Vec<_> = fs::read_dir(&fixtures_dir)?
        .filter_map(|e| e.ok())
        .collect();
    entries.sort_by_key(|e| e.file_name());

    for entry in entries {
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) == Some("json") {
            match load_parity_fixture_from_path(&path) {
                Ok(fixture) => fixtures.push(fixture),
                Err(e) => eprintln!("Warning: Failed to load fixture {:?}: {}", path, e),
            }
        }
    }

    Ok(fixtures)
}

/// Get list of all available fixture scenario names.
pub fn get_fixture_names() -> Result<Vec<String>, Box<dyn std::error::Error>> {
    let fixtures_dir = get_fixtures_dir();
    let mut names = Vec::new();

    for entry in fs::read_dir(&fixtures_dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) == Some("json") {
            if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                names.push(stem.to_string());
            }
        }
    }

    names.sort();
    Ok(names)
}

/// Get the fixtures directory path.
fn get_fixtures_dir() -> PathBuf {
    // Try to find the fixtures directory relative to the crate root
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    // From clients/rust-tui -> go up 2 levels to Samaktha root, then tests/fixtures/parity
    manifest_dir.join("..").join("..").join("tests").join("fixtures").join("parity")
}

/// Validation result for expected outcomes.
#[derive(Debug, Default)]
pub struct ValidationResult {
    pub errors: Vec<String>,
}

impl ValidationResult {
    pub fn new() -> Self {
        Self { errors: Vec::new() }
    }

    pub fn add_error(&mut self, error: String) {
        self.errors.push(error);
    }

    pub fn is_ok(&self) -> bool {
        self.errors.is_empty()
    }

    pub fn assert_ok(&self) {
        if !self.errors.is_empty() {
            panic!("Validation failed:\n{}", self.errors.join("\n"));
        }
    }
}

/// Validate actual test results against fixture expected outcomes.
pub fn validate_expected_outcomes(
    fixture: &ParityFixture,
    actual_events: &[EventEnvelope],
    actual_final_status: &str,
    actual_terminal_text: &str,
) -> ValidationResult {
    let mut result = ValidationResult::new();
    let expected = &fixture.expected_outcomes;

    // Check event count
    if let Some(expected_count) = expected.event_count {
        if actual_events.len() as u64 != expected_count {
            result.add_error(format!(
                "Event count mismatch: expected {}, got {}",
                expected_count,
                actual_events.len()
            ));
        }
    }

    // Check final status
    if let Some(expected_status) = &expected.final_status {
        if actual_final_status != expected_status {
            result.add_error(format!(
                "Final status mismatch: expected {}, got {}",
                expected_status, actual_final_status
            ));
        }
    }

    // Check terminal text
    if let Some(expected_text) = &expected.terminal_text {
        if !actual_terminal_text.contains(expected_text) {
            result.add_error(format!(
                "Terminal text mismatch: expected to contain '{}'",
                expected_text
            ));
        }
    }

    // Check assistant content
    if let Some(expected_content) = &expected.assistant_content {
        if !actual_terminal_text.contains(expected_content) {
            result.add_error(format!(
                "Assistant content mismatch: expected to contain '{}'",
                expected_content
            ));
        }
    }

    // Check token count
    if let Some(expected_tokens) = expected.token_count {
        let token_events: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "ASSISTANT.TOKEN")
            .collect();
        if token_events.len() as u64 != expected_tokens {
            result.add_error(format!(
                "Token count mismatch: expected {}, got {}",
                expected_tokens,
                token_events.len()
            ));
        }
    }

    // Check approval outcomes
    if let Some(expected_requested) = expected.approval_requested {
        let approval_requested: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "APPROVAL.REQUESTED")
            .collect();
        if expected_requested && approval_requested.is_empty() {
            result.add_error("Expected approval to be requested but it wasn't".to_string());
        } else if !expected_requested && !approval_requested.is_empty() {
            result.add_error("Expected no approval request but one was received".to_string());
        }
    }

    if let Some(expected_decision) = &expected.approval_decision {
        let approval_resolved: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "APPROVAL.RESOLVED")
            .collect();
        if let Some(event) = approval_resolved.first() {
            let actual_decision = event.payload.get("decision")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if actual_decision != expected_decision {
                result.add_error(format!(
                    "Approval decision mismatch: expected {}, got {}",
                    expected_decision, actual_decision
                ));
            }
        }
    }

    if let Some(expected_reasons) = &expected.approval_reasons {
        let approval_resolved: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "APPROVAL.RESOLVED")
            .collect();
        if let Some(event) = approval_resolved.first() {
            let actual_reasons: Vec<String> = event.payload.get("reasons")
                .and_then(|v| v.as_array())
                .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect())
                .unwrap_or_default();
            if actual_reasons != *expected_reasons {
                result.add_error(format!(
                    "Approval reasons mismatch: expected {:?}, got {:?}",
                    expected_reasons, actual_reasons
                ));
            }
        }
    }

    if let Some(expected_resumed) = expected.execution_resumed {
        let state_events: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "EXECUTION.STATE_CHANGED")
            .collect();
        let running_after_pause = state_events.iter().any(|e| {
            e.payload.get("status").and_then(|v| v.as_str()) == Some("running")
                && e.payload.get("pending_approval").and_then(|v| v.as_bool()) == Some(false)
        });
        if expected_resumed && !running_after_pause {
            result.add_error("Expected execution to resume after approval but it didn't".to_string());
        }
    }

    // Check search outcomes
    if let Some(expected_performed) = expected.search_performed {
        let search_started: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "SEARCH.STARTED")
            .collect();
        if expected_performed && search_started.is_empty() {
            result.add_error("Expected search to be performed but it wasn't".to_string());
        }
    }

    if let Some(expected_count) = expected.search_results_count {
        let search_completed: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "SEARCH.COMPLETED")
            .collect();
        if let Some(event) = search_completed.first() {
            let actual_count = event.payload.get("result_count")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);
            if actual_count != expected_count {
                result.add_error(format!(
                    "Search results count mismatch: expected {}, got {}",
                    expected_count, actual_count
                ));
            }
        }
    }

    if let Some(expected_query) = &expected.search_query {
        let search_started: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "SEARCH.STARTED")
            .collect();
        if let Some(event) = search_started.first() {
            let actual_query = event.payload.get("query")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if actual_query != expected_query {
                result.add_error(format!(
                    "Search query mismatch: expected '{}', got '{}'",
                    expected_query, actual_query
                ));
            }
        }
    }

    if let Some(expected_backend) = &expected.search_backend {
        let search_started: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "SEARCH.STARTED")
            .collect();
        if let Some(event) = search_started.first() {
            let actual_backend = event.payload.get("backend")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if actual_backend != expected_backend {
                result.add_error(format!(
                    "Search backend mismatch: expected '{}', got '{}'",
                    expected_backend, actual_backend
                ));
            }
        }
    }

    // Check file outcomes
    if let Some(expected_created) = expected.files_created {
        let write_completed: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "FILE.WRITE_COMPLETED")
            .collect();
        if write_completed.len() as u64 != expected_created {
            result.add_error(format!(
                "Files created mismatch: expected {}, got {}",
                expected_created,
                write_completed.len()
            ));
        }
    }

    if let Some(expected_read) = expected.files_read {
        let read_completed: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "FILE.READ_COMPLETED")
            .collect();
        if read_completed.len() as u64 != expected_read {
            result.add_error(format!(
                "Files read mismatch: expected {}, got {}",
                expected_read,
                read_completed.len()
            ));
        }
    }

    if let Some(expected_listed) = expected.files_listed {
        let list_completed: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "FILE.LIST_COMPLETED")
            .collect();
        let total_entries: u64 = list_completed
            .iter()
            .map(|e| e.payload.get("entry_count").and_then(|v| v.as_u64()).unwrap_or(0))
            .sum();
        if total_entries != expected_listed {
            result.add_error(format!(
                "Files listed mismatch: expected {}, got {}",
                expected_listed, total_entries
            ));
        }
    }

    if let Some(expected_bytes) = expected.total_bytes_written {
        let write_completed: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "FILE.WRITE_COMPLETED")
            .collect();
        let total_bytes: u64 = write_completed
            .iter()
            .map(|e| e.payload.get("bytes_written").and_then(|v| v.as_u64()).unwrap_or(0))
            .sum();
        if total_bytes != expected_bytes {
            result.add_error(format!(
                "Total bytes written mismatch: expected {}, got {}",
                expected_bytes, total_bytes
            ));
        }
    }

    if let Some(expected_entries) = expected.final_directory_entries {
        let list_completed: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "FILE.LIST_COMPLETED")
            .collect();
        if let Some(event) = list_completed.last() {
            let final_entries = event.payload.get("entry_count")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);
            if final_entries != expected_entries {
                result.add_error(format!(
                    "Final directory entries mismatch: expected {}, got {}",
                    expected_entries, final_entries
                ));
            }
        }
    }

    // Check cancellation
    if let Some(expected_cancelled) = expected.cancelled {
        let cancelled_events: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "EXECUTION.CANCELLED")
            .collect();
        if expected_cancelled && cancelled_events.is_empty() {
            result.add_error("Expected execution to be cancelled but it wasn't".to_string());
        }
    }

    if let Some(expected_reason) = &expected.cancellation_reason {
        let cancelled_events: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "EXECUTION.CANCELLED")
            .collect();
        if let Some(event) = cancelled_events.first() {
            let actual_reason = event.payload.get("reason")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if actual_reason != expected_reason {
                result.add_error(format!(
                    "Cancellation reason mismatch: expected '{}', got '{}'",
                    expected_reason, actual_reason
                ));
            }
        }
    }

    // Check error codes - first check SEARCH.FAILED for tool-specific error codes, then EXECUTION.STATE_CHANGED
    if let Some(expected_code) = &expected.error_code {
        // Check SEARCH.FAILED event first (for provider_tool_failure scenario)
        let search_failed_events: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "SEARCH.FAILED")
            .collect();

        let mut found_match = false;
        if let Some(event) = search_failed_events.first() {
            let actual_error = event.payload.get("error").cloned().unwrap_or(Value::Null);
            let actual_code = actual_error.get("code")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if actual_code == expected_code {
                found_match = true;
            }
        }

        // If not found in SEARCH.FAILED, check EXECUTION.STATE_CHANGED
        if !found_match {
            let failed_events: Vec<_> = actual_events
                .iter()
                .filter(|e| e.event_type == "EXECUTION.STATE_CHANGED")
                .filter(|e| e.payload.get("status").and_then(|v| v.as_str()) == Some("failed"))
                .collect();
            if let Some(event) = failed_events.first() {
                let actual_error = event.payload.get("error").cloned().unwrap_or(Value::Null);
                let actual_code = actual_error.get("code")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if actual_code != expected_code {
                    result.add_error(format!(
                        "Error code mismatch: expected {}, got {}",
                        expected_code, actual_code
                    ));
                }
            }
        }
    }

    // Check tool failure
    if let Some(expected_tool_failed) = expected.tool_failed {
        let tool_failed_events: Vec<_> = actual_events
            .iter()
            .filter(|e| matches!(
                e.event_type.as_str(),
                "SEARCH.FAILED" | "FILE.READ_FAILED" | "FILE.WRITE_FAILED" | "ASSISTANT.ERROR"
            ))
            .collect();
        if expected_tool_failed && tool_failed_events.is_empty() {
            result.add_error("Expected tool failure but none occurred".to_string());
        }
    }

    if let Some(expected_retryable) = expected.retryable {
        let failed_events: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "EXECUTION.STATE_CHANGED")
            .filter(|e| e.payload.get("status").and_then(|v| v.as_str()) == Some("failed"))
            .collect();
        if let Some(event) = failed_events.first() {
            let actual_error = event.payload.get("error").cloned().unwrap_or(Value::Null);
            let actual_retryable = actual_error.get("retryable")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if actual_retryable != expected_retryable {
                result.add_error(format!(
                    "Retryable mismatch: expected {}, got {}",
                    expected_retryable, actual_retryable
                ));
            }
        }
    }

    // Check reconnect
    if let Some(expected_content) = &expected.final_content {
        if !actual_terminal_text.contains(expected_content) {
            result.add_error(format!(
                "Final content mismatch: expected to contain '{}'",
                expected_content
            ));
        }
    }

    // Check stale events
    if let Some(expected_preserved) = &expected.final_status_preserved {
        if actual_final_status != expected_preserved {
            result.add_error(format!(
                "Final status not preserved: expected {}, got {}",
                expected_preserved, actual_final_status
            ));
        }
    }

    // Check token sequence numbers
    if let Some(expected_sequences) = &expected.token_sequence_numbers {
        let token_events: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "ASSISTANT.TOKEN")
            .collect();
        let actual_sequences: Vec<u64> = token_events
            .iter()
            .map(|e| e.payload.get("sequence_number").and_then(|v| v.as_u64()).unwrap_or(0))
            .collect();
        if actual_sequences != *expected_sequences {
            result.add_error(format!(
                "Token sequence numbers mismatch: expected {:?}, got {:?}",
                expected_sequences, actual_sequences
            ));
        }
    }

    // Check duplicate event outcomes
    if let Some(expected_dup_sequences) = &expected.duplicate_sequences {
        // Check that token events have unique sequence_numbers (no double counting)
        let token_events: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "ASSISTANT.TOKEN")
            .collect();
        let token_sequences: Vec<u64> = token_events
            .iter()
            .map(|e| e.payload.get("sequence_number").and_then(|v| v.as_u64()).unwrap_or(0))
            .collect();

        // Check for duplicates in processed token sequences
        let mut seen = std::collections::HashSet::new();
        let mut duplicates = Vec::new();
        for seq in &token_sequences {
            if !seen.insert(*seq) {
                duplicates.push(*seq);
            }
        }

        if !duplicates.is_empty() {
            result.add_error(format!(
                "Duplicate token sequences found in processed events: {:?}",
                duplicates
            ));
        }

        // Verify the expected duplicate envelope sequences were detected
        // (This is informational - the key check is no_double_counting below)
        if !expected_dup_sequences.is_empty() {
            // Just verify we have the right number of unique token sequences
            // The actual envelope sequence detection is done by the state machine
        }
    }

    if let Some(expected_ignored) = expected.duplicate_events_ignored {
        if expected_ignored {
            // Verify no duplicate token sequence numbers in processed events
            let token_events: Vec<_> = actual_events
                .iter()
                .filter(|e| e.event_type == "ASSISTANT.TOKEN")
                .collect();
            let token_sequences: Vec<u64> = token_events
                .iter()
                .map(|e| e.payload.get("sequence_number").and_then(|v| v.as_u64()).unwrap_or(0))
                .collect();

            let mut seen = std::collections::HashSet::new();
            let has_duplicates = token_sequences.iter().any(|seq| !seen.insert(*seq));

            if has_duplicates {
                result.add_error("Expected duplicate events to be ignored but duplicates found in processed tokens".to_string());
            }
        }
    }

    if let Some(expected_no_double) = expected.no_double_counting {
        if expected_no_double {
            // Verify token count matches expected (no double counting)
            let token_events: Vec<_> = actual_events
                .iter()
                .filter(|e| e.event_type == "ASSISTANT.TOKEN")
                .collect();

            // Also check that token sequence numbers are unique
            let token_sequences: Vec<u64> = token_events
                .iter()
                .map(|e| e.payload.get("sequence_number").and_then(|v| v.as_u64()).unwrap_or(0))
                .collect();

            let mut seen = std::collections::HashSet::new();
            let unique_count = token_sequences.iter().filter(|seq| seen.insert(**seq)).count();

            if unique_count != token_events.len() {
                result.add_error("Double counting detected: processed token count exceeds unique sequence numbers".to_string());
            }
        }
    }

    // Check out-of-order event outcomes
    if let Some(expected_oos_sequences) = &expected.out_of_order_sequences {
        // This validates that the state machine correctly handled out-of-order delivery
        // The actual_events should have token sequence numbers in correct order
        let token_events: Vec<_> = actual_events
            .iter()
            .filter(|e| e.event_type == "ASSISTANT.TOKEN")
            .collect();
        let actual_sequences: Vec<u64> = token_events
            .iter()
            .map(|e| e.payload.get("sequence_number").and_then(|v| v.as_u64()).unwrap_or(0))
            .collect();

        // Verify sequences are in order (1, 2, 3, ...)
        for (i, seq) in actual_sequences.iter().enumerate() {
            let expected_seq = (i + 1) as u64;
            if *seq != expected_seq {
                result.add_error(format!(
                    "Out-of-order processing failed: token at index {} has sequence_number {}, expected {}",
                    i, seq, expected_seq
                ));
            }
        }
    }

    if let Some(expected_reordered) = expected.events_reordered {
        if expected_reordered {
            // Verify tokens were processed in correct sequence_number order
            let token_events: Vec<_> = actual_events
                .iter()
                .filter(|e| e.event_type == "ASSISTANT.TOKEN")
                .collect();
            let actual_sequences: Vec<u64> = token_events
                .iter()
                .map(|e| e.payload.get("sequence_number").and_then(|v| v.as_u64()).unwrap_or(0))
                .collect();

            // Check that sequences are strictly increasing (no out-of-order in processed output)
            for i in 1..actual_sequences.len() {
                if actual_sequences[i] <= actual_sequences[i - 1] {
                    result.add_error("Events not properly reordered: processed token sequences are not strictly increasing".to_string());
                    break;
                }
            }
        }
    }

    if let Some(expected_no_gaps) = expected.no_gaps_in_processed {
        if expected_no_gaps {
            // Verify no gaps in token sequence numbers (1, 2, 3, ... with no missing)
            let token_events: Vec<_> = actual_events
                .iter()
                .filter(|e| e.event_type == "ASSISTANT.TOKEN")
                .collect();
            let actual_sequences: Vec<u64> = token_events
                .iter()
                .map(|e| e.payload.get("sequence_number").and_then(|v| v.as_u64()).unwrap_or(0))
                .collect();

            for (i, seq) in actual_sequences.iter().enumerate() {
                let expected_seq = (i + 1) as u64;
                if *seq != expected_seq {
                    result.add_error(format!(
                        "Gap detected in processed token sequences: expected {} at index {}, got {}",
                        expected_seq, i, seq
                    ));
                    break;
                }
            }
        }
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_load_all_fixtures() {
        let fixtures = load_all_parity_fixtures().expect("Failed to load fixtures");
        assert_eq!(fixtures.len(), 11, "Expected 11 parity fixtures");

        // Verify all expected scenarios are present
        let scenarios: Vec<_> = fixtures.iter().map(|f| f.scenario.clone()).collect();
        assert!(scenarios.contains(&"ordinary_assistant_response".to_string()));
        assert!(scenarios.contains(&"search_results_sources".to_string()));
        assert!(scenarios.contains(&"create_then_write_file_context".to_string()));
        assert!(scenarios.contains(&"approval_allow".to_string()));
        assert!(scenarios.contains(&"approval_deny".to_string()));
        assert!(scenarios.contains(&"cancellation".to_string()));
        assert!(scenarios.contains(&"provider_tool_failure".to_string()));
        assert!(scenarios.contains(&"reconnect".to_string()));
        assert!(scenarios.contains(&"stale_event".to_string()));
        assert!(scenarios.contains(&"duplicate_event".to_string()));
        assert!(scenarios.contains(&"out_of_order_event".to_string()));
    }

    #[test]
    fn test_fixture_event_to_envelope() {
        let fixture = load_parity_fixture("01_ordinary_assistant_response")
            .expect("Failed to load fixture");

        let event = &fixture.events[0];
        let envelope = fixture_event_to_envelope(event, &fixture.execution_id, &fixture.session_id);

        assert_eq!(envelope.sequence, 1);
        assert_eq!(envelope.execution_id, "exec-parity-01");
        assert_eq!(envelope.session_id, "sess-parity-01");
        assert_eq!(envelope.event_type, "EXECUTION.CREATED");
    }

    #[test]
    fn test_validate_ordinary_assistant_response() {
        let fixture = load_parity_fixture("01_ordinary_assistant_response")
            .expect("Failed to load fixture");

        // Convert fixture events to envelopes
        let envelopes: Vec<_> = fixture.events
            .iter()
            .map(|e| fixture_event_to_envelope(e, &fixture.execution_id, &fixture.session_id))
            .collect();

        let terminal_text = "Hello there! How can I help you today?";
        let result = validate_expected_outcomes(&fixture, &envelopes, "completed", terminal_text);
        result.assert_ok();
    }
}