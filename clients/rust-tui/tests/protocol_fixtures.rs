//! Protocol fixture tests - serialization/deserialization against known JSON fixtures
//!
//! These tests verify that the Rust protocol models correctly serialize to and
//! deserialize from JSON that matches the Python backend's wire format.

use rust_tui::protocol::{
    parse_sse_event, serialize_sse_event, sanitize_terminal_output, is_supported_version,
    ApprovalDecision, ApprovalDecisionRequest, EventEnvelope, ExecutionCreateRequest,
    ExecutionCreateResponse, ExecutionStateResponse, FileEventPayload, FileEventPayloadVariant,
    FileEventType, FileListCompletedPayload, FileListStartedPayload, FileReadCompletedPayload,
    FileReadStartedPayload, FileWriteCompletedPayload, FileWriteMode,
    FileWriteStartedPayload, SearchCompletedPayload, SearchEventPayload, SearchEventPayloadVariant,
    SearchEventType, SearchFailedPayload, SearchStartedPayload, VersionNegotiationRequest,
    VersionNegotiationResponse,
};
use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use std::collections::HashMap;

#[test]
fn test_version_negotiation_request_serialization() {
    let request = VersionNegotiationRequest {
        client_version: "1.0".to_string(),
    };
    let json = serde_json::to_value(&request).unwrap();
    assert_eq!(json["client_version"], "1.0");
    assert_eq!(json.as_object().unwrap().len(), 1); // deny_unknown_fields
}

#[test]
fn test_version_negotiation_response_serialization() {
    let response = VersionNegotiationResponse {
        supported: true,
        server_version: "1.0".to_string(),
        error: None,
    };
    let json = serde_json::to_value(&response).unwrap();
    assert_eq!(json["supported"], true);
    assert_eq!(json["server_version"], "1.0");
    assert!(json.get("error").is_none());
}

#[test]
fn test_version_negotiation_response_with_error() {
    let response = VersionNegotiationResponse {
        supported: false,
        server_version: "1.0".to_string(),
        error: Some("PROTOCOL_VERSION_UNSUPPORTED".to_string()),
    };
    let json = serde_json::to_value(&response).unwrap();
    assert_eq!(json["supported"], false);
    assert_eq!(json["error"], "PROTOCOL_VERSION_UNSUPPORTED");
}

#[test]
fn test_execution_create_request_full() {
    let mut conv_map = HashMap::new();
    conv_map.insert("role".to_string(), json!("user"));
    conv_map.insert("content".to_string(), json!("hello"));

    let request = ExecutionCreateRequest {
        message: "Test message".to_string(),
        session_id: Some("sess-123".to_string()),
        conversation: Some(vec![conv_map]),
        idempotency_key: Some("key-123".to_string()),
    };
    let json = serde_json::to_value(&request).unwrap();
    assert_eq!(json["message"], "Test message");
    assert_eq!(json["session_id"], "sess-123");
    assert_eq!(json["conversation"][0]["role"], "user");
    assert_eq!(json["idempotency_key"], "key-123");
}

#[test]
fn test_execution_create_request_minimal() {
    let request = ExecutionCreateRequest {
        message: "Test".to_string(),
        session_id: None,
        conversation: None,
        idempotency_key: None,
    };
    let json = serde_json::to_value(&request).unwrap();
    assert_eq!(json["message"], "Test");
    // Optional fields should not be present due to skip_serializing_if
    assert!(json.get("session_id").is_none());
    assert!(json.get("conversation").is_none());
    assert!(json.get("idempotency_key").is_none());
}

#[test]
fn test_execution_create_response() {
    let response = ExecutionCreateResponse {
        execution_id: "exec-456".to_string(),
        session_id: "sess-123".to_string(),
        status: "created".to_string(),
    };
    let json = serde_json::to_value(&response).unwrap();
    assert_eq!(json["execution_id"], "exec-456");
    assert_eq!(json["session_id"], "sess-123");
    assert_eq!(json["status"], "created");
}

#[test]
fn test_event_envelope_roundtrip() {
    let envelope = EventEnvelope {
        sequence: 42,
        execution_id: "exec-456".to_string(),
        session_id: "sess-123".to_string(),
        event_type: "EXECUTION.STATE_CHANGED".to_string(),
        payload: json!({"status": "running", "protocol_version": "1.0"}),
        timestamp: DateTime::parse_from_rfc3339("2024-01-01T12:00:00Z").unwrap().with_timezone(&Utc),
    };
    let json = serde_json::to_value(&envelope).unwrap();
    let decoded: EventEnvelope = serde_json::from_value(json).unwrap();
    assert_eq!(decoded.sequence, 42);
    assert_eq!(decoded.execution_id, "exec-456");
    assert_eq!(decoded.session_id, "sess-123");
    assert_eq!(decoded.event_type, "EXECUTION.STATE_CHANGED");
}

#[test]
fn test_event_envelope_deny_unknown_fields() {
    // Extra fields should cause deserialization error
    let json = json!({
        "sequence": 1,
        "execution_id": "exec-123",
        "session_id": "sess-123",
        "event_type": "EXECUTION.STATE_CHANGED",
        "payload": {},
        "timestamp": "2024-01-01T00:00:00Z",
        "unknown_field": "should_fail"
    });
    let result: Result<EventEnvelope, _> = serde_json::from_value(json);
    assert!(result.is_err());
}

#[test]
fn test_approval_decision_allow() {
    let request = ApprovalDecisionRequest {
        approval_id: "approval-123".to_string(),
        decision: ApprovalDecision::Allow,
        reasons: Some(vec!["User approved".to_string(), "Safe operation".to_string()]),
    };
    let json = serde_json::to_value(&request).unwrap();
    assert_eq!(json["approval_id"], "approval-123");
    assert_eq!(json["decision"], "allow");
    assert_eq!(json["reasons"][0], "User approved");
    assert_eq!(json["reasons"][1], "Safe operation");
}

#[test]
fn test_approval_decision_deny() {
    let request = ApprovalDecisionRequest {
        approval_id: "approval-456".to_string(),
        decision: ApprovalDecision::Deny,
        reasons: Some(vec!["User denied".to_string()]),
    };
    let json = serde_json::to_value(&request).unwrap();
    assert_eq!(json["decision"], "deny");
}

#[test]
fn test_approval_decision_no_reasons() {
    let request = ApprovalDecisionRequest {
        approval_id: "approval-789".to_string(),
        decision: ApprovalDecision::Allow,
        reasons: None,
    };
    let json = serde_json::to_value(&request).unwrap();
    assert!(json.get("reasons").is_none());
}

#[test]
fn test_execution_state_response() {
    let response = ExecutionStateResponse {
        execution_id: "exec-456".to_string(),
        status: "running".to_string(),
        principal_id: "principal-123".to_string(),
        session_id: "sess-123".to_string(),
        pending_approval: false,
        result_available: false,
        created_at: DateTime::parse_from_rfc3339("2024-01-01T12:00:00Z").unwrap().with_timezone(&Utc),
        updated_at: Some(DateTime::parse_from_rfc3339("2024-01-01T12:05:00Z").unwrap().with_timezone(&Utc)),
        completed_at: None,
        error: None,
    };
    let json = serde_json::to_value(&response).unwrap();
    assert_eq!(json["execution_id"], "exec-456");
    assert_eq!(json["status"], "running");
    assert_eq!(json["principal_id"], "principal-123");
    assert_eq!(json["pending_approval"], false);
    assert!(json["updated_at"].is_string());
    assert!(json.get("completed_at").is_none());
    assert!(json.get("error").is_none());
}

// =============================================================================
// M3: Structured Search Events
// =============================================================================

#[test]
fn test_search_started_payload() {
    let mut filters = HashMap::new();
    filters.insert("type".to_string(), json!("file"));

    let payload = SearchStartedPayload {
        query: "test query".to_string(),
        backend: "local".to_string(),
        filters: Some(filters),
        request_id: "req-123".to_string(),
    };
    let json = serde_json::to_value(&payload).unwrap();
    assert_eq!(json["query"], "test query");
    assert_eq!(json["backend"], "local");
    assert_eq!(json["filters"]["type"], "file");
    assert_eq!(json["request_id"], "req-123");
}

#[test]
fn test_search_completed_payload() {
    let payload = SearchCompletedPayload {
        query: "test query".to_string(),
        backend: "local".to_string(),
        results: vec![json!({"path": "file1.rs"}), json!({"path": "file2.rs"})],
        result_count: 2,
        request_id: "req-123".to_string(),
    };
    let json = serde_json::to_value(&payload).unwrap();
    assert_eq!(json["result_count"], 2);
    assert_eq!(json["results"].as_array().unwrap().len(), 2);
}

#[test]
fn test_search_failed_payload() {
    let payload = SearchFailedPayload {
        query: "test query".to_string(),
        backend: "local".to_string(),
        error_code: "NOT_FOUND".to_string(),
        error_message: "No results found".to_string(),
        request_id: "req-123".to_string(),
    };
    let json = serde_json::to_value(&payload).unwrap();
    assert_eq!(json["error_code"], "NOT_FOUND");
    assert_eq!(json["error_message"], "No results found");
}

#[test]
fn test_search_event_payload_started() {
    let event = SearchEventPayload {
        event_type: SearchEventType::Started,
        payload: SearchEventPayloadVariant::Started(SearchStartedPayload {
            query: "test".to_string(),
            backend: "local".to_string(),
            filters: None,
            request_id: "req-1".to_string(),
        }),
    };
    let json = serde_json::to_value(&event).unwrap();
    assert_eq!(json["event_type"], "STARTED");
    assert_eq!(json["payload"]["query"], "test");
}

#[test]
fn test_search_event_payload_completed() {
    let event = SearchEventPayload {
        event_type: SearchEventType::Completed,
        payload: SearchEventPayloadVariant::Completed(SearchCompletedPayload {
            query: "test".to_string(),
            backend: "local".to_string(),
            results: vec![],
            result_count: 0,
            request_id: "req-1".to_string(),
        }),
    };
    let json = serde_json::to_value(&event).unwrap();
    assert_eq!(json["event_type"], "COMPLETED");
    assert_eq!(json["payload"]["result_count"], 0);
}

#[test]
fn test_search_event_payload_failed() {
    let event = SearchEventPayload {
        event_type: SearchEventType::Failed,
        payload: SearchEventPayloadVariant::Failed(SearchFailedPayload {
            query: "test".to_string(),
            backend: "local".to_string(),
            error_code: "ERROR".to_string(),
            error_message: "Failed".to_string(),
            request_id: "req-1".to_string(),
        }),
    };
    let json = serde_json::to_value(&event).unwrap();
    assert_eq!(json["event_type"], "FAILED");
    assert_eq!(json["payload"]["error_code"], "ERROR");
}

// =============================================================================
// M3: Structured File Events
// =============================================================================

#[test]
fn test_file_read_started_payload() {
    let payload = FileReadStartedPayload {
        path: "/test/file.txt".to_string(),
        offset: 0,
        limit: Some(100),
        request_id: "req-1".to_string(),
    };
    let json = serde_json::to_value(&payload).unwrap();
    assert_eq!(json["path"], "/test/file.txt");
    assert_eq!(json["offset"], 0);
    assert_eq!(json["limit"], 100);
}

#[test]
fn test_file_read_completed_payload() {
    let payload = FileReadCompletedPayload {
        path: "/test/file.txt".to_string(),
        content: "file content".to_string(),
        size: 12,
        encoding: "utf-8".to_string(),
        request_id: "req-1".to_string(),
    };
    let json = serde_json::to_value(&payload).unwrap();
    assert_eq!(json["content"], "file content");
    assert_eq!(json["size"], 12);
    assert_eq!(json["encoding"], "utf-8");
}

#[test]
fn test_file_write_started_payload() {
    let payload = FileWriteStartedPayload {
        path: "/test/file.txt".to_string(),
        content_length: 12,
        mode: FileWriteMode::Write,
        request_id: "req-1".to_string(),
    };
    let json = serde_json::to_value(&payload).unwrap();
    assert_eq!(json["path"], "/test/file.txt");
    assert_eq!(json["content_length"], 12);
    assert_eq!(json["mode"], "write");
}

#[test]
fn test_file_write_mode_append() {
    let payload = FileWriteStartedPayload {
        path: "/test/file.txt".to_string(),
        content_length: 5,
        mode: FileWriteMode::Append,
        request_id: "req-1".to_string(),
    };
    let json = serde_json::to_value(&payload).unwrap();
    assert_eq!(json["mode"], "append");
}

#[test]
fn test_file_write_completed_payload() {
    let payload = FileWriteCompletedPayload {
        path: "/test/file.txt".to_string(),
        bytes_written: 12,
        request_id: "req-1".to_string(),
    };
    let json = serde_json::to_value(&payload).unwrap();
    assert_eq!(json["bytes_written"], 12);
}

#[test]
fn test_file_list_started_payload() {
    let payload = FileListStartedPayload {
        path: "/test".to_string(),
        recursive: true,
        request_id: "req-1".to_string(),
    };
    let json = serde_json::to_value(&payload).unwrap();
    assert_eq!(json["path"], "/test");
    assert_eq!(json["recursive"], true);
}

#[test]
fn test_file_list_completed_payload() {
    let payload = FileListCompletedPayload {
        path: "/test".to_string(),
        entries: vec![json!({"name": "file1.txt"}), json!({"name": "file2.txt"})],
        entry_count: 2,
        request_id: "req-1".to_string(),
    };
    let json = serde_json::to_value(&payload).unwrap();
    assert_eq!(json["entry_count"], 2);
    assert_eq!(json["entries"].as_array().unwrap().len(), 2);
}

#[test]
fn test_file_event_payload_read_started() {
    let event = FileEventPayload {
        event_type: FileEventType::ReadStarted,
        payload: FileEventPayloadVariant::ReadStarted(FileReadStartedPayload {
            path: "/test/file.txt".to_string(),
            offset: 0,
            limit: None,
            request_id: "req-1".to_string(),
        }),
    };
    let json = serde_json::to_value(&event).unwrap();
    assert_eq!(json["event_type"], "READ_STARTED");
    assert_eq!(json["payload"]["path"], "/test/file.txt");
}

#[test]
fn test_file_event_payload_write_completed() {
    let event = FileEventPayload {
        event_type: FileEventType::WriteCompleted,
        payload: FileEventPayloadVariant::WriteCompleted(FileWriteCompletedPayload {
            path: "/test/file.txt".to_string(),
            bytes_written: 100,
            request_id: "req-1".to_string(),
        }),
    };
    let json = serde_json::to_value(&event).unwrap();
    assert_eq!(json["event_type"], "WRITE_COMPLETED");
    assert_eq!(json["payload"]["bytes_written"], 100);
}

// =============================================================================
// SSE Serialization Helpers
// =============================================================================

#[test]
fn test_serialize_sse_event_with_sequence() {
    let data = json!({"status": "running"});
    let sse = serialize_sse_event("EXECUTION.STATE_CHANGED", &data, Some(5));
    assert!(sse.contains("event: EXECUTION.STATE_CHANGED"));
    assert!(sse.contains("id: 5"));
    assert!(sse.contains("data: {\"status\":\"running\"}"));
    assert!(sse.ends_with("\n\n"));
}

#[test]
fn test_serialize_sse_event_without_sequence() {
    let data = json!({"status": "created"});
    let sse = serialize_sse_event("EXECUTION.STATE_CHANGED", &data, None);
    assert!(sse.contains("event: EXECUTION.STATE_CHANGED"));
    assert!(!sse.contains("id:"));
    assert!(sse.contains("data: {\"status\":\"created\"}"));
}

#[test]
fn test_parse_sse_event_valid() {
    let sse_data = "event: EXECUTION.STATE_CHANGED\nid: 42\ndata: {\"status\":\"running\"}\n\n";
    let result = parse_sse_event(sse_data);
    assert!(result.is_some());
    let (event_type, sequence, data) = result.unwrap();
    assert_eq!(event_type, "EXECUTION.STATE_CHANGED");
    assert_eq!(sequence, Some(42));
    assert_eq!(data["status"], "running");
}

#[test]
fn test_parse_sse_event_no_id() {
    let sse_data = "event: EXECUTION.CREATED\ndata: {\"execution_id\":\"exec-123\"}\n\n";
    let result = parse_sse_event(sse_data);
    assert!(result.is_some());
    let (event_type, sequence, data) = result.unwrap();
    assert_eq!(event_type, "EXECUTION.CREATED");
    assert_eq!(sequence, None);
    assert_eq!(data["execution_id"], "exec-123");
}

#[test]
fn test_parse_sse_event_multiline_data() {
    // Valid multiline JSON - single JSON object split across multiple data: lines
    let sse_data = "event: ASSISTANT.TOKEN\nid: 100\ndata: {\ndata:   \"token\": \"hello world\"\ndata: }\n\n";
    let result = parse_sse_event(sse_data);
    assert!(result.is_some());
    let (event_type, sequence, data) = result.unwrap();
    assert_eq!(event_type, "ASSISTANT.TOKEN");
    assert_eq!(sequence, Some(100));
    assert_eq!(data["token"], "hello world");
}

#[test]
fn test_parse_sse_event_invalid() {
    // Missing event type
    let sse_data = "id: 1\ndata: {}\n\n";
    let result = parse_sse_event(sse_data);
    assert!(result.is_none());
}

#[test]
fn test_parse_sse_event_empty() {
    let result = parse_sse_event("");
    assert!(result.is_none());
}

// =============================================================================
// Terminal Output Sanitization
// =============================================================================

#[test]
fn test_sanitize_ansi_csi_sequences() {
    // Red text
    assert_eq!(sanitize_terminal_output("\x1b[31mRed\x1b[0m"), "Red");
    // Bold + color
    assert_eq!(sanitize_terminal_output("\x1b[1;32mGreen Bold\x1b[0m"), "Green Bold");
    // Cursor movement
    assert_eq!(sanitize_terminal_output("\x1b[10;20HHello"), "Hello");
    // Clear screen
    assert_eq!(sanitize_terminal_output("\x1b[2J\x1b[HContent"), "Content");
}

#[test]
fn test_sanitize_ansi_osc_sequences() {
    // Window title
    assert_eq!(sanitize_terminal_output("\x1b]0;Title\x07"), "");
    // With ST terminator
    assert_eq!(sanitize_terminal_output("\x1b]0;Title\x1b\\"), "");
}

#[test]
fn test_sanitize_control_characters() {
    // Null, bell, etc.
    assert_eq!(sanitize_terminal_output("Hello\x00\x01\x07World"), "HelloWorld");
    // Preserve newlines, tabs, carriage returns, spaces
    assert_eq!(sanitize_terminal_output("Line1\nLine2\tTab\rReturn"), "Line1\nLine2\tTab\rReturn");
}

#[test]
fn test_sanitize_mixed_content() {
    let input = "\x1b[31mError:\x1b[0m Something went wrong\n\x1b]0;Title\x07Details";
    let expected = "Error: Something went wrong\nDetails";
    assert_eq!(sanitize_terminal_output(input), expected);
}

// =============================================================================
// Protocol Version Support
// =============================================================================

#[test]
fn test_is_supported_version() {
    assert!(is_supported_version("1.0"));
    assert!(is_supported_version("1.1"));
    assert!(is_supported_version("1.99"));
    assert!(!is_supported_version("2.0"));
    assert!(!is_supported_version("0.9"));
    assert!(!is_supported_version("0.1"));
}