/// Typed execution state machine with sequence validation for Samaktha protocol.
///
/// Implements a deterministic state machine that validates event sequence monotonicity,
/// handles protocol version checking, and provides explicit state transitions.
/// Zero governance logic - pure presentation layer state tracking.

use crate::protocol::{
    EventEnvelope, ExecutionStateResponse, ProtocolError, ResynchronizationSignal,
    PROTOCOL_VERSION,
};
use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use thiserror::Error;
use tracing::{debug, error, info, warn};

/// Execution status values from backend
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ExecutionStatus {
    Created,
    Running,
    WaitingApproval,
    Completed,
    Failed,
    Cancelled,
}

impl ExecutionStatus {
    /// Check if execution is in a terminal state
    pub fn is_terminal(&self) -> bool {
        matches!(self, Self::Completed | Self::Failed | Self::Cancelled)
    }

    /// Check if execution is active
    pub fn is_active(&self) -> bool {
        matches!(self, Self::Running | Self::WaitingApproval)
    }
}

impl std::str::FromStr for ExecutionStatus {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "created" => Ok(Self::Created),
            "running" => Ok(Self::Running),
            "waiting_approval" => Ok(Self::WaitingApproval),
            "completed" => Ok(Self::Completed),
            "failed" => Ok(Self::Failed),
            "cancelled" => Ok(Self::Cancelled),
            _ => Err(format!("Unknown execution status: {}", s)),
        }
    }
}

/// State machine error types
#[derive(Debug, Error)]
pub enum StateMachineError {
    #[error("Sequence gap detected: expected {expected}, got {actual}")]
    SequenceGap { expected: u64, actual: u64 },
    #[error("Duplicate sequence: {sequence}")]
    DuplicateSequence { sequence: u64 },
    #[error("Sequence regression: expected > {expected}, got {actual}")]
    SequenceRegression { expected: u64, actual: u64 },
    #[error("Protocol version mismatch: {0}")]
    VersionMismatch(String),
    #[error("Invalid state transition: {from:?} -> {to:?}")]
    InvalidTransition { from: ExecutionStatus, to: ExecutionStatus },
    #[error("Missing required field in event: {0}")]
    MissingField(String),
    #[error("Protocol error: {0}")]
    Protocol(#[from] ProtocolError),
}

/// Execution state tracked by the client
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionState {
    pub execution_id: String,
    pub session_id: String,
    pub status: ExecutionStatus,
    pub principal_id: String,
    pub pending_approval: bool,
    pub result_available: bool,
    pub created_at: String,
    pub updated_at: Option<String>,
    pub completed_at: Option<String>,
    pub error: Option<String>,

    // Sequence tracking
    pub last_sequence: u64,
    pub earliest_sequence: u64,
    pub latest_sequence: u64,

    // Pending approval info
    pub pending_approval_id: Option<String>,
    pub pending_approval_payload: Option<serde_json::Value>,

    // Accumulated events for display
    #[serde(skip)]
    pub event_log: Vec<EventLogEntry>,

    // Assistant streaming state
    #[serde(skip)]
    pub assistant_buffer: String,
    #[serde(skip)]
    pub assistant_model: Option<String>,
    #[serde(skip)]
    pub assistant_provider: Option<String>,
}

/// Event log entry for display
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventLogEntry {
    pub sequence: u64,
    pub event_type: String,
    pub timestamp: String,
    pub payload_summary: String,
    pub raw_payload: serde_json::Value,
}

/// State machine for execution lifecycle
pub struct ExecutionStateMachine {
    state: Option<ExecutionState>,
    expected_sequence: u64,
    protocol_version: String,
}

impl ExecutionStateMachine {
    /// Create a new state machine
    pub fn new() -> Self {
        Self {
            state: None,
            expected_sequence: 1,
            protocol_version: PROTOCOL_VERSION.to_string(),
        }
    }

    /// Initialize from ExecutionStateResponse (e.g., after reconnect)
    pub fn initialize_from_response(&mut self, response: ExecutionStateResponse) -> Result<()> {
        let status = response
            .status
            .parse::<ExecutionStatus>()
            .map_err(|e| anyhow::anyhow!("Failed to parse status: {}", e))?;

        let state = ExecutionState {
            execution_id: response.execution_id,
            session_id: response.session_id,
            status,
            principal_id: response.principal_id,
            pending_approval: response.pending_approval,
            result_available: response.result_available,
            created_at: response.created_at.to_rfc3339(),
            updated_at: response.updated_at.map(|dt| dt.to_rfc3339()),
            completed_at: response.completed_at.map(|dt| dt.to_rfc3339()),
            error: response.error,
            last_sequence: 0,
            earliest_sequence: 0,
            latest_sequence: 0,
            pending_approval_id: None,
            pending_approval_payload: None,
            event_log: Vec::new(),
            assistant_buffer: String::new(),
            assistant_model: None,
            assistant_provider: None,
        };

        self.state = Some(state);
        self.expected_sequence = 1;
        info!("State machine initialized for execution");
        Ok(())
    }

    /// Process an event envelope, validating sequence and updating state
    pub fn process_event(&mut self, envelope: EventEnvelope) -> Result<Vec<StateTransition>> {
        // Validate sequence (needs &self)
        let validation_result = self.validate_sequence(envelope.sequence);

        // Handle duplicate sequence (idempotent replay) - silently ignore
        if let Err(StateMachineError::SequenceRegression { expected, actual })
            = &validation_result
        {
            let state = self.state.as_ref().context("State machine not initialized")?;
            if actual == &state.last_sequence {
                // Duplicate sequence - idempotent, no transition, no state change
                return Ok(Vec::new());
            }
            // Otherwise it's a real regression, return the error
            return Err(validation_result.unwrap_err().into());
        }

        // Handle gap - should trigger resync transition instead of error
        if let Err(StateMachineError::SequenceGap { expected, actual }) = &validation_result {
            // Convert gap to resync transition
            let state = self
                .state
                .as_mut()
                .context("State machine not initialized")?;

            warn!(
                "Sequence gap detected: expected {}, got {} - triggering resynchronization",
                expected, actual
            );

            // Update expected sequence to actual + 1
            self.expected_sequence = actual + 1;
            state.last_sequence = *actual;

            // Update bounds
            state.earliest_sequence = state.earliest_sequence.min(*actual);
            state.latest_sequence = state.latest_sequence.max(*actual);

            return Ok(vec![StateTransition::Resynchronized {
                expected: *expected,
                actual: *actual,
                message: format!("Sequence gap: expected {}, got {}", expected, actual),
            }]);
        }

        // For other errors (including real regression), propagate
        validation_result?;

        // Validate protocol version in payload if present (needs &self)
        // Call before getting mutable borrow
        let protocol_version = envelope.payload.get("protocol_version").and_then(|v| v.as_str());
        if let Some(version) = protocol_version {
            self.validate_protocol_version(&envelope.payload)?;
        }

        // Now get mutable state and apply event
        let state = self
            .state
            .as_mut()
            .context("State machine not initialized")?;

        // Generate transitions based on event type
        let transitions = ExecutionStateMachine::apply_event(state, &envelope)?;

        // Update expected sequence
        self.expected_sequence = envelope.sequence + 1;
        state.last_sequence = envelope.sequence;

        // Update earliest/latest sequence bounds
        if state.earliest_sequence == 0 || envelope.sequence < state.earliest_sequence {
            state.earliest_sequence = envelope.sequence;
        }
        if envelope.sequence > state.latest_sequence {
            state.latest_sequence = envelope.sequence;
        }

        // Log event
        state.event_log.push(EventLogEntry {
            sequence: envelope.sequence,
            event_type: envelope.event_type.clone(),
            timestamp: envelope.timestamp.to_rfc3339(),
            payload_summary: summarize_payload(&envelope.event_type, &envelope.payload),
            raw_payload: envelope.payload.clone(),
        });

        Ok(transitions)
    }

    /// Process a resynchronization signal
    pub fn process_resync(&mut self, signal: ResynchronizationSignal) -> Result<Vec<StateTransition>> {
        let state = self
            .state
            .as_mut()
            .context("State machine not initialized")?;

        warn!(
            "Resynchronization signal: expected {}, got {} - {}",
            signal.expected_sequence, signal.actual_sequence, signal.message
        );

        // Reset expected sequence to actual + 1
        self.expected_sequence = signal.actual_sequence + 1;
        state.last_sequence = signal.actual_sequence;

        // Update bounds
        state.earliest_sequence = signal.expected_sequence.min(signal.actual_sequence);
        state.latest_sequence = signal.actual_sequence.max(state.latest_sequence);

        Ok(vec![StateTransition::Resynchronized {
            expected: signal.expected_sequence,
            actual: signal.actual_sequence,
            message: signal.message,
        }])
    }

    /// Validate sequence monotonicity
    /// Returns error only for true regression (sequence < expected AND sequence != last_sequence).
    /// Gaps (sequence > expected) and duplicates (sequence == last_sequence) are handled in process_event.
    fn validate_sequence(&self, sequence: u64) -> Result<()> {
        // Only error on true regression (going backwards past last_sequence)
        // Gaps and duplicates are handled at the call site with state access
        if sequence < self.expected_sequence {
            return Err(StateMachineError::SequenceRegression {
                expected: self.expected_sequence,
                actual: sequence,
            }
            .into());
        }

        // sequence >= expected_sequence is valid here (gaps and normal handled in process_event)
        Ok(())
    }

    /// Validate protocol version in payload
    fn validate_protocol_version(&self, payload: &serde_json::Value) -> Result<()> {
        if let Some(version) = payload.get("protocol_version").and_then(|v| v.as_str()) {
            if !version.starts_with("1.") {
                return Err(StateMachineError::VersionMismatch(format!(
                    "Unsupported protocol version: {}",
                    version
                ))
                .into());
            }
        }
        Ok(())
    }

    /// Apply event to state and generate transitions (standalone function to avoid borrow issues)
    fn apply_event(
        state: &mut ExecutionState,
        envelope: &EventEnvelope,
    ) -> Result<Vec<StateTransition>> {
        let mut transitions = Vec::new();

        match envelope.event_type.as_str() {
            // Execution lifecycle events
            "EXECUTION.STATE_CHANGED" => {
                if let Some(new_status_str) = envelope.payload.get("status").and_then(|v| v.as_str())
                {
                    let new_status = new_status_str
                        .parse::<ExecutionStatus>()
                        .map_err(|e| anyhow::anyhow!("Failed to parse status: {}", e))?;

                    if new_status != state.status {
                        transitions.push(StateTransition::StatusChanged {
                            from: state.status,
                            to: new_status,
                        });
                        state.status = new_status;
                    }
                }
            }

            "EXECUTION.COMPLETED" => {
                if state.status != ExecutionStatus::Completed {
                    transitions.push(StateTransition::StatusChanged {
                        from: state.status,
                        to: ExecutionStatus::Completed,
                    });
                    state.status = ExecutionStatus::Completed;
                    state.result_available = true;
                }
            }

            "EXECUTION.FAILED" => {
                let error_msg = envelope
                    .payload
                    .get("error")
                    .and_then(|v| v.as_str())
                    .unwrap_or("Unknown error")
                    .to_string();
                if state.status != ExecutionStatus::Failed {
                    transitions.push(StateTransition::StatusChanged {
                        from: state.status,
                        to: ExecutionStatus::Failed,
                    });
                    state.status = ExecutionStatus::Failed;
                    state.error = Some(error_msg);
                }
            }

            "EXECUTION.CANCELLED" => {
                if state.status != ExecutionStatus::Cancelled {
                    transitions.push(StateTransition::StatusChanged {
                        from: state.status,
                        to: ExecutionStatus::Cancelled,
                    });
                    state.status = ExecutionStatus::Cancelled;
                }
            }

            // Approval events
            "APPROVAL.REQUESTED" => {
                state.pending_approval = true;
                state.pending_approval_id = envelope
                    .payload
                    .get("approval_id")
                    .and_then(|v| v.as_str())
                    .map(String::from);
                state.pending_approval_payload = Some(envelope.payload.clone());
                transitions.push(StateTransition::ApprovalRequested {
                    approval_id: state.pending_approval_id.clone().unwrap_or_default(),
                    payload: envelope.payload.clone(),
                });
            }

            "APPROVAL.RESOLVED" => {
                state.pending_approval = false;
                let approval_id = state.pending_approval_id.take();
                state.pending_approval_payload = None;
                transitions.push(StateTransition::ApprovalResolved {
                    approval_id: approval_id.unwrap_or_default(),
                    decision: envelope
                        .payload
                        .get("decision")
                        .and_then(|v| v.as_str())
                        .unwrap_or("unknown")
                        .to_string(),
                });
            }

            // Structured search events
            "SEARCH.STARTED" => {
                transitions.push(StateTransition::SearchStarted {
                    request_id: envelope
                        .payload
                        .get("request_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    query: envelope
                        .payload
                        .get("query")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    backend: envelope
                        .payload
                        .get("backend")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                });
            }

            "SEARCH.COMPLETED" => {
                transitions.push(StateTransition::SearchCompleted {
                    request_id: envelope
                        .payload
                        .get("request_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    result_count: envelope
                        .payload
                        .get("result_count")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0),
                });
            }

            "SEARCH.FAILED" => {
                transitions.push(StateTransition::SearchFailed {
                    request_id: envelope
                        .payload
                        .get("request_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    error_code: envelope
                        .payload
                        .get("error_code")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    error_message: envelope
                        .payload
                        .get("error_message")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                });
            }

            // Structured file events
            "FILE.READ_STARTED" => {
                transitions.push(StateTransition::FileReadStarted {
                    request_id: envelope
                        .payload
                        .get("request_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    path: envelope
                        .payload
                        .get("path")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                });
            }

            "FILE.READ_COMPLETED" => {
                transitions.push(StateTransition::FileReadCompleted {
                    request_id: envelope
                        .payload
                        .get("request_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    path: envelope
                        .payload
                        .get("path")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    size: envelope
                        .payload
                        .get("size")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0),
                });
            }

            "FILE.WRITE_STARTED" => {
                transitions.push(StateTransition::FileWriteStarted {
                    request_id: envelope
                        .payload
                        .get("request_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    path: envelope
                        .payload
                        .get("path")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    content_length: envelope
                        .payload
                        .get("content_length")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0),
                });
            }

            "FILE.WRITE_COMPLETED" => {
                transitions.push(StateTransition::FileWriteCompleted {
                    request_id: envelope
                        .payload
                        .get("request_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    path: envelope
                        .payload
                        .get("path")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    bytes_written: envelope
                        .payload
                        .get("bytes_written")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0),
                });
            }

            "FILE.LIST_STARTED" => {
                transitions.push(StateTransition::FileListStarted {
                    request_id: envelope
                        .payload
                        .get("request_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    path: envelope
                        .payload
                        .get("path")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                });
            }

            "FILE.LIST_COMPLETED" => {
                transitions.push(StateTransition::FileListCompleted {
                    request_id: envelope
                        .payload
                        .get("request_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    path: envelope
                        .payload
                        .get("path")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    entry_count: envelope
                        .payload
                        .get("entry_count")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0),
                });
            }

            // Structured assistant events
            "ASSISTANT.MESSAGE_STARTED" => {
                state.assistant_buffer.clear();
                state.assistant_model = envelope
                    .payload
                    .get("model_id")
                    .and_then(|v| v.as_str())
                    .map(String::from);
                state.assistant_provider = envelope
                    .payload
                    .get("provider_id")
                    .and_then(|v| v.as_str())
                    .map(String::from);
                transitions.push(StateTransition::AssistantMessageStarted {
                    model_id: state.assistant_model.clone().unwrap_or_default(),
                    provider_id: state.assistant_provider.clone().unwrap_or_default(),
                    request_id: envelope
                        .payload
                        .get("request_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                });
            }

            "ASSISTANT.TOKEN" => {
                if let Some(token) = envelope.payload.get("token").and_then(|v| v.as_str()) {
                    state.assistant_buffer.push_str(token);
                    transitions.push(StateTransition::AssistantToken {
                        token: token.to_string(),
                        sequence_number: envelope
                            .payload
                            .get("sequence_number")
                            .and_then(|v| v.as_u64())
                            .unwrap_or(0),
                    });
                }
            }

            "ASSISTANT.MESSAGE_COMPLETED" => {
                let content = envelope
                    .payload
                    .get("content")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                // Use buffered content if available, otherwise use from event
                let final_content = if state.assistant_buffer.is_empty() {
                    content
                } else {
                    std::mem::take(&mut state.assistant_buffer)
                };
                transitions.push(StateTransition::AssistantMessageCompleted {
                    content: final_content,
                    finish_reason: envelope
                        .payload
                        .get("finish_reason")
                        .and_then(|v| v.as_str())
                        .unwrap_or("stop")
                        .to_string(),
                    usage: envelope
                        .payload
                        .get("usage")
                        .cloned()
                        .unwrap_or_default(),
                });
            }

            "ASSISTANT.ERROR" => {
                transitions.push(StateTransition::AssistantError {
                    error_code: envelope
                        .payload
                        .get("error_code")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    error_message: envelope
                        .payload
                        .get("error_message")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                });
            }

            _ => {
                debug!("Unknown event type: {}", envelope.event_type);
                transitions.push(StateTransition::UnknownEvent {
                    event_type: envelope.event_type.clone(),
                    payload: envelope.payload.clone(),
                });
            }
        }

        Ok(transitions)
    }

    /// Get current state
    pub fn state(&self) -> Option<&ExecutionState> {
        self.state.as_ref()
    }

    /// Get mutable state
    pub fn state_mut(&mut self) -> Option<&mut ExecutionState> {
        self.state.as_mut()
    }

    /// Check if execution is in terminal state
    pub fn is_terminal(&self) -> bool {
        self.state
            .as_ref()
            .map(|s| s.status.is_terminal())
            .unwrap_or(false)
    }

    /// Get expected next sequence
    pub fn expected_sequence(&self) -> u64 {
        self.expected_sequence
    }

    /// Get protocol version
    pub fn protocol_version(&self) -> &str {
        &self.protocol_version
    }
}

/// State transitions for UI updates
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum StateTransition {
    StatusChanged {
        from: ExecutionStatus,
        to: ExecutionStatus,
    },
    ApprovalRequested {
        approval_id: String,
        payload: serde_json::Value,
    },
    ApprovalResolved {
        approval_id: String,
        decision: String,
    },
    SearchStarted {
        request_id: String,
        query: String,
        backend: String,
    },
    SearchCompleted {
        request_id: String,
        result_count: u64,
    },
    SearchFailed {
        request_id: String,
        error_code: String,
        error_message: String,
    },
    FileReadStarted {
        request_id: String,
        path: String,
    },
    FileReadCompleted {
        request_id: String,
        path: String,
        size: u64,
    },
    FileWriteStarted {
        request_id: String,
        path: String,
        content_length: u64,
    },
    FileWriteCompleted {
        request_id: String,
        path: String,
        bytes_written: u64,
    },
    FileListStarted {
        request_id: String,
        path: String,
    },
    FileListCompleted {
        request_id: String,
        path: String,
        entry_count: u64,
    },
    AssistantMessageStarted {
        model_id: String,
        provider_id: String,
        request_id: String,
    },
    AssistantToken {
        token: String,
        sequence_number: u64,
    },
    AssistantMessageCompleted {
        content: String,
        finish_reason: String,
        usage: serde_json::Value,
    },
    AssistantError {
        error_code: String,
        error_message: String,
    },
    Resynchronized {
        expected: u64,
        actual: u64,
        message: String,
    },
    UnknownEvent {
        event_type: String,
        payload: serde_json::Value,
    },
}

/// Summarize payload for display
fn summarize_payload(event_type: &str, payload: &serde_json::Value) -> String {
    match event_type {
        "EXECUTION.STATE_CHANGED" => {
            payload
                .get("status")
                .and_then(|v| v.as_str())
                .map(|s| format!("status: {}", s))
                .unwrap_or_else(|| "state changed".to_string())
        }
        "APPROVAL.REQUESTED" => {
            payload
                .get("approval_id")
                .and_then(|v| v.as_str())
                .map(|s| format!("approval: {}", s))
                .unwrap_or_else(|| "approval requested".to_string())
        }
        "SEARCH.STARTED" => {
            payload
                .get("query")
                .and_then(|v| v.as_str())
                .map(|s| format!("search: {}", truncate(s, 50)))
                .unwrap_or_else(|| "search started".to_string())
        }
        "SEARCH.COMPLETED" => {
            payload
                .get("result_count")
                .and_then(|v| v.as_u64())
                .map(|c| format!("{} results", c))
                .unwrap_or_else(|| "search completed".to_string())
        }
        "FILE.READ_COMPLETED" => {
            payload
                .get("path")
                .and_then(|v| v.as_str())
                .map(|s| format!("read: {}", s))
                .unwrap_or_else(|| "file read".to_string())
        }
        "FILE.WRITE_COMPLETED" => {
            payload
                .get("path")
                .and_then(|v| v.as_str())
                .map(|s| format!("write: {}", s))
                .unwrap_or_else(|| "file write".to_string())
        }
        "ASSISTANT.MESSAGE_STARTED" => {
            payload
                .get("model_id")
                .and_then(|v| v.as_str())
                .map(|s| format!("assistant: {}", s))
                .unwrap_or_else(|| "assistant started".to_string())
        }
        "ASSISTANT.TOKEN" => "token".to_string(),
        "ASSISTANT.MESSAGE_COMPLETED" => "assistant completed".to_string(),
        _ => format!("{} event", event_type),
    }
}

fn truncate(s: &str, max_len: usize) -> String {
    if s.len() <= max_len {
        s.to_string()
    } else {
        format!("{}...", &s[..max_len - 3])
    }
}

impl Default for ExecutionStateMachine {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::EventEnvelope;
    use chrono::Utc;
    use serde_json::json;

    #[test]
    fn test_execution_status_parsing() {
        assert_eq!("created".parse::<ExecutionStatus>().unwrap(), ExecutionStatus::Created);
        assert_eq!("running".parse::<ExecutionStatus>().unwrap(), ExecutionStatus::Running);
        assert_eq!("waiting_approval".parse::<ExecutionStatus>().unwrap(), ExecutionStatus::WaitingApproval);
        assert_eq!("completed".parse::<ExecutionStatus>().unwrap(), ExecutionStatus::Completed);
        assert_eq!("failed".parse::<ExecutionStatus>().unwrap(), ExecutionStatus::Failed);
        assert_eq!("cancelled".parse::<ExecutionStatus>().unwrap(), ExecutionStatus::Cancelled);
        assert!("unknown".parse::<ExecutionStatus>().is_err());
    }

    #[test]
    fn test_execution_status_terminal() {
        assert!(ExecutionStatus::Completed.is_terminal());
        assert!(ExecutionStatus::Failed.is_terminal());
        assert!(ExecutionStatus::Cancelled.is_terminal());
        assert!(!ExecutionStatus::Created.is_terminal());
        assert!(!ExecutionStatus::Running.is_terminal());
        assert!(!ExecutionStatus::WaitingApproval.is_terminal());
    }

    #[test]
    fn test_state_machine_initialization() {
        let mut sm = ExecutionStateMachine::new();
        let response = ExecutionStateResponse {
            execution_id: "exec-123".to_string(),
            status: "running".to_string(),
            principal_id: "principal-123".to_string(),
            session_id: "sess-123".to_string(),
            pending_approval: false,
            result_available: false,
            created_at: DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z").unwrap().into(),
            updated_at: None,
            completed_at: None,
            error: None,
        };
        sm.initialize_from_response(response).unwrap();
        assert!(sm.state().is_some());
        assert_eq!(sm.state().unwrap().status, ExecutionStatus::Running);
        assert_eq!(sm.expected_sequence(), 1);
    }

    #[test]
    fn test_sequence_validation_valid() {
        let mut sm = ExecutionStateMachine::new();
        let response = ExecutionStateResponse {
            execution_id: "exec-123".to_string(),
            status: "running".to_string(),
            principal_id: "principal-123".to_string(),
            session_id: "sess-123".to_string(),
            pending_approval: false,
            result_available: false,
            created_at: DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z").unwrap().into(),
            updated_at: None,
            completed_at: None,
            error: None,
        };
        sm.initialize_from_response(response).unwrap();

        // Sequence 1 should be valid
        let envelope = EventEnvelope {
            sequence: 1,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "EXECUTION.STATE_CHANGED".to_string(),
            payload: json!({"status": "running"}),
            timestamp: Utc::now(),
        };
        let transitions = sm.process_event(envelope).unwrap();
        assert_eq!(transitions.len(), 0); // No status change (same status)
        assert_eq!(sm.expected_sequence(), 2);
    }

    #[test]
    fn test_sequence_gap_detection() {
        let mut sm = ExecutionStateMachine::new();
        let response = ExecutionStateResponse {
            execution_id: "exec-123".to_string(),
            status: "running".to_string(),
            principal_id: "principal-123".to_string(),
            session_id: "sess-123".to_string(),
            pending_approval: false,
            result_available: false,
            created_at: DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z").unwrap().into(),
            updated_at: None,
            completed_at: None,
            error: None,
        };
        sm.initialize_from_response(response).unwrap();

        // Skip to sequence 3 (gap)
        let envelope = EventEnvelope {
            sequence: 3,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "EXECUTION.STATE_CHANGED".to_string(),
            payload: json!({"status": "running"}),
            timestamp: Utc::now(),
        };
        let result = sm.process_event(envelope);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err().downcast_ref::<StateMachineError>(),
            Some(StateMachineError::SequenceGap { expected: 1, actual: 3 })
        ));
    }

    #[test]
    fn test_sequence_regression_detection() {
        let mut sm = ExecutionStateMachine::new();
        let response = ExecutionStateResponse {
            execution_id: "exec-123".to_string(),
            status: "running".to_string(),
            principal_id: "principal-123".to_string(),
            session_id: "sess-123".to_string(),
            pending_approval: false,
            result_available: false,
            created_at: DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z").unwrap().into(),
            updated_at: None,
            completed_at: None,
            error: None,
        };
        sm.initialize_from_response(response).unwrap();

        // Process sequence 1
        let envelope1 = EventEnvelope {
            sequence: 1,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "EXECUTION.STATE_CHANGED".to_string(),
            payload: json!({"status": "running"}),
            timestamp: Utc::now(),
        };
        sm.process_event(envelope1).unwrap();

        // Try to process sequence 1 again (regression)
        let envelope2 = EventEnvelope {
            sequence: 1,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "EXECUTION.STATE_CHANGED".to_string(),
            payload: json!({"status": "running"}),
            timestamp: Utc::now(),
        };
        let result = sm.process_event(envelope2);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err().downcast_ref::<StateMachineError>(),
            Some(StateMachineError::SequenceRegression { expected: 2, actual: 1 })
        ));
    }

    #[test]
    fn test_status_transition() {
        let mut sm = ExecutionStateMachine::new();
        let response = ExecutionStateResponse {
            execution_id: "exec-123".to_string(),
            status: "running".to_string(),
            principal_id: "principal-123".to_string(),
            session_id: "sess-123".to_string(),
            pending_approval: false,
            result_available: false,
            created_at: DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z").unwrap().into(),
            updated_at: None,
            completed_at: None,
            error: None,
        };
        sm.initialize_from_response(response).unwrap();

        // Transition to completed
        let envelope = EventEnvelope {
            sequence: 1,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "EXECUTION.COMPLETED".to_string(),
            payload: json!({}),
            timestamp: Utc::now(),
        };
        let transitions = sm.process_event(envelope).unwrap();
        assert_eq!(transitions.len(), 1);
        assert!(matches!(transitions[0], StateTransition::StatusChanged { from: ExecutionStatus::Running, to: ExecutionStatus::Completed }));
        assert!(sm.is_terminal());
    }

    #[test]
    fn test_approval_flow() {
        let mut sm = ExecutionStateMachine::new();
        let response = ExecutionStateResponse {
            execution_id: "exec-123".to_string(),
            status: "running".to_string(),
            principal_id: "principal-123".to_string(),
            session_id: "sess-123".to_string(),
            pending_approval: false,
            result_available: false,
            created_at: DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z").unwrap().into(),
            updated_at: None,
            completed_at: None,
            error: None,
        };
        sm.initialize_from_response(response).unwrap();

        // Approval requested
        let envelope1 = EventEnvelope {
            sequence: 1,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "APPROVAL.REQUESTED".to_string(),
            payload: json!({"approval_id": "approval-123", "tool": "file_write", "path": "/tmp/test.txt"}),
            timestamp: Utc::now(),
        };
        let transitions = sm.process_event(envelope1).unwrap();
        assert_eq!(transitions.len(), 1);
        assert!(matches!(transitions[0], StateTransition::ApprovalRequested { .. }));
        assert!(sm.state().unwrap().pending_approval);

        // Approval resolved
        let envelope2 = EventEnvelope {
            sequence: 2,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "APPROVAL.RESOLVED".to_string(),
            payload: json!({"approval_id": "approval-123", "decision": "allow"}),
            timestamp: Utc::now(),
        };
        let transitions = sm.process_event(envelope2).unwrap();
        assert_eq!(transitions.len(), 1);
        assert!(matches!(transitions[0], StateTransition::ApprovalResolved { ref decision, .. } if decision == "allow"));
        assert!(!sm.state().unwrap().pending_approval);
    }

    #[test]
    fn test_assistant_streaming() {
        let mut sm = ExecutionStateMachine::new();
        let response = ExecutionStateResponse {
            execution_id: "exec-123".to_string(),
            status: "running".to_string(),
            principal_id: "principal-123".to_string(),
            session_id: "sess-123".to_string(),
            pending_approval: false,
            result_available: false,
            created_at: DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z").unwrap().into(),
            updated_at: None,
            completed_at: None,
            error: None,
        };
        sm.initialize_from_response(response).unwrap();

        // Message started
        let envelope1 = EventEnvelope {
            sequence: 1,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "ASSISTANT.MESSAGE_STARTED".to_string(),
            payload: json!({"model_id": "gpt-4o", "provider_id": "openai", "request_id": "req-123"}),
            timestamp: Utc::now(),
        };
        let transitions = sm.process_event(envelope1).unwrap();
        assert_eq!(transitions.len(), 1);
        assert!(matches!(transitions[0], StateTransition::AssistantMessageStarted { ref model_id, .. } if model_id == "gpt-4o"));

        // Token 1
        let envelope2 = EventEnvelope {
            sequence: 2,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "ASSISTANT.TOKEN".to_string(),
            payload: json!({"token": "Hello", "sequence_number": 1, "request_id": "req-123"}),
            timestamp: Utc::now(),
        };
        let transitions = sm.process_event(envelope2).unwrap();
        assert_eq!(transitions.len(), 1);
        assert!(matches!(transitions[0], StateTransition::AssistantToken { ref token, .. } if token == "Hello"));

        // Token 2
        let envelope3 = EventEnvelope {
            sequence: 3,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "ASSISTANT.TOKEN".to_string(),
            payload: json!({"token": " world", "sequence_number": 2, "request_id": "req-123"}),
            timestamp: Utc::now(),
        };
        let transitions = sm.process_event(envelope3).unwrap();
        assert_eq!(transitions.len(), 1);
        assert!(matches!(transitions[0], StateTransition::AssistantToken { ref token, .. } if token == " world"));

        // Message completed
        let envelope4 = EventEnvelope {
            sequence: 4,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "ASSISTANT.MESSAGE_COMPLETED".to_string(),
            payload: json!({"content": "Hello world", "finish_reason": "stop", "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "request_id": "req-123"}),
            timestamp: Utc::now(),
        };
        let transitions = sm.process_event(envelope4).unwrap();
        assert_eq!(transitions.len(), 1);
        assert!(matches!(transitions[0], StateTransition::AssistantMessageCompleted { ref content, .. } if content == "Hello world"));
    }

    #[test]
    fn test_resynchronization() {
        let mut sm = ExecutionStateMachine::new();
        let response = ExecutionStateResponse {
            execution_id: "exec-123".to_string(),
            status: "running".to_string(),
            principal_id: "principal-123".to_string(),
            session_id: "sess-123".to_string(),
            pending_approval: false,
            result_available: false,
            created_at: DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z").unwrap().into(),
            updated_at: None,
            completed_at: None,
            error: None,
        };
        sm.initialize_from_response(response).unwrap();

        // Process some events
        for i in 1..=5 {
            let envelope = EventEnvelope {
                sequence: i,
                execution_id: "exec-123".to_string(),
                session_id: "sess-123".to_string(),
                event_type: "EXECUTION.STATE_CHANGED".to_string(),
                payload: json!({"status": "running"}),
                timestamp: Utc::now(),
            };
            sm.process_event(envelope).unwrap();
        }

        // Resync signal
        let signal = crate::protocol::ResynchronizationSignal {
            signal_type: "RESYNC".to_string(),
            expected_sequence: 6,
            actual_sequence: 10,
            message: "Gap detected".to_string(),
        };
        let transitions = sm.process_resync(signal).unwrap();
        assert_eq!(transitions.len(), 1);
        assert!(matches!(transitions[0], StateTransition::Resynchronized { expected: 6, actual: 10, .. }));
        assert_eq!(sm.expected_sequence(), 11);
    }

    #[test]
    fn test_protocol_version_validation() {
        let mut sm = ExecutionStateMachine::new();
        let response = ExecutionStateResponse {
            execution_id: "exec-123".to_string(),
            status: "running".to_string(),
            principal_id: "principal-123".to_string(),
            session_id: "sess-123".to_string(),
            pending_approval: false,
            result_available: false,
            created_at: DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z").unwrap().into(),
            updated_at: None,
            completed_at: None,
            error: None,
        };
        sm.initialize_from_response(response).unwrap();

        // Valid version
        let envelope = EventEnvelope {
            sequence: 1,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "EXECUTION.STATE_CHANGED".to_string(),
            payload: json!({"status": "running", "protocol_version": "1.0"}),
            timestamp: Utc::now(),
        };
        let result = sm.process_event(envelope);
        assert!(result.is_ok());

        // Invalid version (2.0)
        let envelope2 = EventEnvelope {
            sequence: 2,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "EXECUTION.STATE_CHANGED".to_string(),
            payload: json!({"status": "running", "protocol_version": "2.0"}),
            timestamp: Utc::now(),
        };
        let result = sm.process_event(envelope2);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err().downcast_ref::<StateMachineError>(),
            Some(StateMachineError::VersionMismatch(_))
        ));
    }
}