//! Rust TUI Client Library
//!
//! Protocol-compatible Rust TUI client for Samaktha.
//! Implements typed HTTP/SSE protocol v1.0 communication with Python backend.

pub mod protocol;
pub mod transport;
pub mod state;
pub mod ui;

#[cfg(test)]
mod tests {
    use crate::protocol::{parse_sse_event, serialize_sse_event};

    #[test]
    fn test_sse_roundtrip() {
        let data = serde_json::json!({"status": "running"});
        let sse = serialize_sse_event("EXECUTION.STATE_CHANGED", &data, Some(42));
        let parsed = parse_sse_event(&sse).unwrap();
        assert_eq!(parsed.0, "EXECUTION.STATE_CHANGED");
        assert_eq!(parsed.1, Some(42));
        assert_eq!(parsed.2["status"], "running");
    }
}