/// Rust wire models and JSON/SSE decoding for Samaktha protocol v1.0
///
/// Mirrors app/api/protocol.py v1.0 with extra=forbid equivalent behavior.
/// All models use serde with deny_unknown_fields for security-relevant fields.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use thiserror::Error;

/// Protocol version constant
pub const PROTOCOL_VERSION: &str = "1.0";
pub const PROTOCOL_VERSION_UNSUPPORTED_ERROR: &str = "PROTOCOL_VERSION_UNSUPPORTED";

/// Error codes for structured errors
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ErrorCode {
    ProtocolVersionUnsupported,
    CursorExpired,
    Unauthorized,
    NotFound,
    InternalError,
}

/// Protocol version negotiation request
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VersionNegotiationRequest {
    pub client_version: String,
}

/// Protocol version negotiation response
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VersionNegotiationResponse {
    pub supported: bool,
    pub server_version: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Execution creation request with optional idempotency key
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionCreateRequest {
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub conversation: Option<Vec<HashMap<String, Value>>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub idempotency_key: Option<String>,
}

/// Execution creation response
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionCreateResponse {
    pub execution_id: String,
    pub session_id: String,
    pub status: String,
}

/// Typed event envelope with monotonic sequence per execution
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EventEnvelope {
    pub sequence: u64,
    pub execution_id: String,
    pub session_id: String,
    pub event_type: String,
    #[serde(default)]
    pub payload: Value,
    pub timestamp: DateTime<Utc>,
}

/// Opaque approval decision — only allow/deny + bounded reason
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ApprovalDecisionRequest {
    pub approval_id: String,
    pub decision: ApprovalDecision,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reasons: Option<Vec<String>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ApprovalDecision {
    Allow,
    Deny,
}

/// Events cursor request (GET /executions/{execution_id}/events)
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EventsCursorRequest {
    #[serde(default)]
    pub after: u64,
}

/// Structured response when cursor predates retained history
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CursorExpiredResponse {
    pub error: String, // "CURSOR_EXPIRED"
    pub message: String,
    pub earliest_sequence: u64,
    pub latest_sequence: u64,
}

/// Public execution state — no permit, secrets, or raw metadata
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionStateResponse {
    pub execution_id: String,
    pub status: String,
    pub principal_id: String,
    pub session_id: String,
    pub pending_approval: bool,
    pub result_available: bool,
    pub created_at: DateTime<Utc>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub updated_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub completed_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Explicit resynchronization signal on sequence gap
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResynchronizationSignal {
    #[serde(rename = "type")]
    pub signal_type: String, // "RESYNC"
    pub expected_sequence: u64,
    pub actual_sequence: u64,
    pub message: String,
}

/// Structured error response
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StructuredErrorResponse {
    pub error: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<Value>,
}

// =============================================================================
// M3: Structured Search Events
// =============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchStartedPayload {
    pub query: String,
    pub backend: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub filters: Option<HashMap<String, Value>>,
    pub request_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchCompletedPayload {
    pub query: String,
    pub backend: String,
    #[serde(default)]
    pub results: Vec<Value>,
    pub result_count: u64,
    pub request_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchFailedPayload {
    pub query: String,
    pub backend: String,
    pub error_code: String,
    pub error_message: String,
    pub request_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchEventPayload {
    pub event_type: SearchEventType,
    pub payload: SearchEventPayloadVariant,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SearchEventType {
    Started,
    Completed,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum SearchEventPayloadVariant {
    Started(SearchStartedPayload),
    Completed(SearchCompletedPayload),
    Failed(SearchFailedPayload),
}

// =============================================================================
// M3: Structured File Events
// =============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileReadStartedPayload {
    pub path: String,
    #[serde(default)]
    pub offset: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub limit: Option<u64>,
    pub request_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileReadCompletedPayload {
    pub path: String,
    pub content: String,
    pub size: u64,
    #[serde(default = "default_utf8")]
    pub encoding: String,
    pub request_id: String,
}

fn default_utf8() -> String {
    "utf-8".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileWriteStartedPayload {
    pub path: String,
    pub content_length: u64,
    #[serde(default = "default_write_mode")]
    pub mode: FileWriteMode,
    pub request_id: String,
}

fn default_write_mode() -> FileWriteMode {
    FileWriteMode::Write
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum FileWriteMode {
    Write,
    Append,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileWriteCompletedPayload {
    pub path: String,
    pub bytes_written: u64,
    pub request_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileListStartedPayload {
    pub path: String,
    #[serde(default)]
    pub recursive: bool,
    pub request_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileListCompletedPayload {
    pub path: String,
    #[serde(default)]
    pub entries: Vec<Value>,
    pub entry_count: u64,
    pub request_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileEventPayload {
    pub event_type: FileEventType,
    pub payload: FileEventPayloadVariant,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum FileEventType {
    ReadStarted,
    ReadCompleted,
    WriteStarted,
    WriteCompleted,
    ListStarted,
    ListCompleted,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum FileEventPayloadVariant {
    ReadStarted(FileReadStartedPayload),
    ReadCompleted(FileReadCompletedPayload),
    WriteStarted(FileWriteStartedPayload),
    WriteCompleted(FileWriteCompletedPayload),
    ListStarted(FileListStartedPayload),
    ListCompleted(FileListCompletedPayload),
}

// =============================================================================
// M3: Structured Assistant Events
// =============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssistantMessageStartedPayload {
    pub model_id: String,
    pub provider_id: String,
    pub request_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trace_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssistantMessageCompletedPayload {
    pub model_id: String,
    pub provider_id: String,
    pub content: String,
    pub finish_reason: String,
    #[serde(default)]
    pub usage: HashMap<String, u64>,
    pub request_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trace_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssistantTokenPayload {
    pub model_id: String,
    pub provider_id: String,
    pub token: String,
    pub sequence_number: u64,
    pub request_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trace_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssistantErrorPayload {
    pub model_id: String,
    pub provider_id: String,
    pub error_code: String,
    pub error_message: String,
    pub request_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trace_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssistantEventPayload {
    pub event_type: AssistantEventType,
    pub payload: AssistantEventPayloadVariant,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AssistantEventType {
    MessageStarted,
    MessageCompleted,
    Token,
    Error,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum AssistantEventPayloadVariant {
    MessageStarted(AssistantMessageStartedPayload),
    MessageCompleted(AssistantMessageCompletedPayload),
    Token(AssistantTokenPayload),
    Error(AssistantErrorPayload),
}

// =============================================================================
// Serialization Helpers
// =============================================================================

/// Parse SSE id: field as integer sequence
pub fn parse_sse_id(id_str: &str) -> Option<u64> {
    id_str.parse().ok()
}

/// Format an SSE event with optional id: field (sequence)
pub fn serialize_sse_event(event_type: &str, data: &Value, sequence: Option<u64>) -> String {
    let mut lines = vec![format!("event: {}", event_type)];
    if let Some(seq) = sequence {
        lines.push(format!("id: {}", seq));
    }
    lines.push(format!("data: {}", data));
    format!("{}\n\n", lines.join("\n"))
}

/// Sanitize terminal output by stripping ANSI/OSC/control sequences
pub fn sanitize_terminal_output(input: &str) -> String {
    // Strip ANSI escape sequences (CSI, OSC, etc.)
    let ansi_regex = regex::Regex::new(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)").unwrap();
    let mut result = ansi_regex.replace_all(input, "").to_string();

    // Strip other control characters except newlines, tabs, and carriage returns
    result = result
        .chars()
        .filter(|c| {
            matches!(c, '\n' | '\t' | '\r' | ' ') || !c.is_control()
        })
        .collect();

    result
}

/// Parse a single SSE event from a string
pub fn parse_sse_event(sse_data: &str) -> Option<(String, Option<u64>, Value)> {
    let mut event_type = String::new();
    let mut sequence = None;
    let mut data = String::new();

    for line in sse_data.lines() {
        if line.starts_with("event:") {
            event_type = line["event:".len()..].trim().to_string();
        } else if line.starts_with("id:") {
            sequence = parse_sse_id(&line["id:".len()..].trim());
        } else if line.starts_with("data:") {
            data.push_str(&line["data:".len()..].trim());
            data.push('\n');
        }
    }

    if event_type.is_empty() {
        return None;
    }

    // Handle empty data field as null
    let json_data: Value = if data.trim().is_empty() {
        Value::Null
    } else {
        serde_json::from_str(data.trim()).ok()?
    };
    Some((event_type, sequence, json_data))
}

/// Decode an EventEnvelope from SSE event data
pub fn decode_event_envelope(event_type: &str, sequence: Option<u64>, data: &Value) -> Result<EventEnvelope, ProtocolError> {
    let mut envelope_data = data.clone();

    // Ensure required fields are present
    if envelope_data.get("sequence").is_none() {
        if let Some(seq) = sequence {
            envelope_data["sequence"] = Value::Number(serde_json::Number::from(seq));
        } else {
            return Err(ProtocolError::MissingField("sequence"));
        }
    }

    if envelope_data.get("execution_id").is_none() {
        return Err(ProtocolError::MissingField("execution_id"));
    }

    if envelope_data.get("session_id").is_none() {
        return Err(ProtocolError::MissingField("session_id"));
    }

    if envelope_data.get("event_type").is_none() {
        envelope_data["event_type"] = Value::String(event_type.to_string());
    }

    if envelope_data.get("timestamp").is_none() {
        envelope_data["timestamp"] = Value::String(Utc::now().to_rfc3339());
    }

    let envelope: EventEnvelope = serde_json::from_value(envelope_data)
        .map_err(|e| ProtocolError::Deserialization(e.to_string()))?;

    // Validate protocol version
    if let Some(payload_version) = envelope.payload.get("protocol_version") {
        if let Some(version_str) = payload_version.as_str() {
            if !is_supported_version(version_str) {
                return Err(ProtocolError::UnsupportedVersion(version_str.to_string()));
            }
        }
    }

    Ok(envelope)
}

/// Check if a protocol version is supported (same major version)
pub fn is_supported_version(version: &str) -> bool {
    version.starts_with("1.")
}

/// Protocol error types
#[derive(Debug, Error)]
pub enum ProtocolError {
    #[error("Missing required field: {0}")]
    MissingField(&'static str),
    #[error("Deserialization error: {0}")]
    Deserialization(String),
    #[error("Unsupported protocol version: {0}")]
    UnsupportedVersion(String),
    #[error("Invalid sequence: {0}")]
    InvalidSequence(String),
    #[error("SSE parsing error: {0}")]
    SseParsing(String),
}

impl From<serde_json::Error> for ProtocolError {
    fn from(e: serde_json::Error) -> Self {
        ProtocolError::Deserialization(e.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_protocol_version_constants() {
        assert_eq!(PROTOCOL_VERSION, "1.0");
        assert_eq!(PROTOCOL_VERSION_UNSUPPORTED_ERROR, "PROTOCOL_VERSION_UNSUPPORTED");
    }

    #[test]
    fn test_is_supported_version() {
        assert!(is_supported_version("1.0"));
        assert!(is_supported_version("1.1"));
        assert!(is_supported_version("1.99"));
        assert!(!is_supported_version("2.0"));
        assert!(!is_supported_version("0.9"));
    }

    #[test]
    fn test_parse_sse_id() {
        assert_eq!(parse_sse_id("1"), Some(1));
        assert_eq!(parse_sse_id("42"), Some(42));
        assert_eq!(parse_sse_id("0"), Some(0));
        assert_eq!(parse_sse_id("abc"), None);
        assert_eq!(parse_sse_id(""), None);
    }

    #[test]
    fn test_serialize_sse_event() {
        let data = json!({"test": "value"});
        let sse = serialize_sse_event("EXECUTION.STATE_CHANGED", &data, Some(5));
        assert!(sse.contains("event: EXECUTION.STATE_CHANGED"));
        assert!(sse.contains("id: 5"));
        assert!(sse.contains("data: {\"test\":\"value\"}"));
    }

    #[test]
    fn test_sanitize_terminal_output() {
        // ANSI CSI sequences
        assert_eq!(sanitize_terminal_output("\x1b[31mRed\x1b[0m"), "Red");
        // ANSI OSC sequences
        assert_eq!(sanitize_terminal_output("\x1b]0;Title\x07"), "");
        // Control characters
        assert_eq!(sanitize_terminal_output("Hello\x00\x01World"), "HelloWorld");
        // Preserve newlines and tabs
        assert_eq!(sanitize_terminal_output("Line1\nLine2\tTab"), "Line1\nLine2\tTab");
    }

    #[test]
    fn test_execution_create_request() {
        let req = ExecutionCreateRequest {
            message: "test".to_string(),
            session_id: Some("sess-123".to_string()),
            conversation: None,
            idempotency_key: Some("key-123".to_string()),
        };
        let json = serde_json::to_value(&req).unwrap();
        assert_eq!(json["message"], "test");
        assert_eq!(json["session_id"], "sess-123");
        assert_eq!(json["idempotency_key"], "key-123");
    }

    #[test]
    fn test_event_envelope_roundtrip() {
        let envelope = EventEnvelope {
            sequence: 1,
            execution_id: "exec-123".to_string(),
            session_id: "sess-123".to_string(),
            event_type: "EXECUTION.STATE_CHANGED".to_string(),
            payload: json!({"status": "running"}),
            timestamp: Utc::now(),
        };
        let json = serde_json::to_value(&envelope).unwrap();
        let decoded: EventEnvelope = serde_json::from_value(json).unwrap();
        assert_eq!(decoded.sequence, 1);
        assert_eq!(decoded.execution_id, "exec-123");
    }

    #[test]
    fn test_approval_decision_request() {
        let req = ApprovalDecisionRequest {
            approval_id: "approval-123".to_string(),
            decision: ApprovalDecision::Allow,
            reasons: Some(vec!["User approved".to_string()]),
        };
        let json = serde_json::to_value(&req).unwrap();
        assert_eq!(json["approval_id"], "approval-123");
        assert_eq!(json["decision"], "allow");
        assert_eq!(json["reasons"][0], "User approved");
    }

    #[test]
    fn test_decode_event_envelope_valid() {
        let data = json!({
            "sequence": 1,
            "execution_id": "exec-123",
            "session_id": "sess-123",
            "event_type": "EXECUTION.STATE_CHANGED",
            "payload": {"status": "running", "protocol_version": "1.0"},
            "timestamp": "2024-01-01T00:00:00Z"
        });
        let envelope = decode_event_envelope("EXECUTION.STATE_CHANGED", Some(1), &data).unwrap();
        assert_eq!(envelope.sequence, 1);
        assert_eq!(envelope.execution_id, "exec-123");
    }

    #[test]
    fn test_decode_event_envelope_missing_execution_id() {
        let data = json!({
            "sequence": 1,
            "session_id": "sess-123",
            "event_type": "EXECUTION.STATE_CHANGED",
        });
        let result = decode_event_envelope("EXECUTION.STATE_CHANGED", Some(1), &data);
        assert!(matches!(result, Err(ProtocolError::MissingField("execution_id"))));
    }

    #[test]
    fn test_decode_event_envelope_unsupported_version() {
        let data = json!({
            "sequence": 1,
            "execution_id": "exec-123",
            "session_id": "sess-123",
            "event_type": "EXECUTION.STATE_CHANGED",
            "payload": {"protocol_version": "2.0"},
            "timestamp": "2024-01-01T00:00:00Z"
        });
        let result = decode_event_envelope("EXECUTION.STATE_CHANGED", Some(1), &data);
        assert!(matches!(result, Err(ProtocolError::UnsupportedVersion(_))));
    }
}