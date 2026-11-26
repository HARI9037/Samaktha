/// Localhost HTTP/SSE transport with reconnect logic for Samaktha protocol.
///
/// Implements the client-side transport layer for communicating with the Python backend
/// over HTTP and SSE. Includes version negotiation, cursor-based reconnection, and
/// exponential backoff with jitter.

use crate::protocol::{
    parse_sse_event, ExecutionCreateRequest, ExecutionCreateResponse,
    ExecutionStateResponse, ProtocolError, VersionNegotiationRequest,
    VersionNegotiationResponse, PROTOCOL_VERSION,
};
use anyhow::Result;
use bytes::Bytes;
use futures::{Stream, StreamExt};
use reqwest::Client;
use serde_json::Value;
use std::pin::Pin;
use std::task::{Context as TaskContext, Poll};
use std::time::Duration;
use tokio::time::{sleep, timeout};
use tracing::{error, info, warn};
use url::Url;

/// Transport configuration
#[derive(Debug, Clone)]
pub struct TransportConfig {
    pub base_url: String,
    pub connect_timeout: Duration,
    pub request_timeout: Duration,
    pub sse_timeout: Duration,
    pub max_reconnect_attempts: u32,
    pub base_reconnect_delay: Duration,
    pub max_reconnect_delay: Duration,
    pub jitter_factor: f64,
}

impl Default for TransportConfig {
    fn default() -> Self {
        Self {
            base_url: "http://127.0.0.1:8000".to_string(),
            connect_timeout: Duration::from_secs(5),
            request_timeout: Duration::from_secs(30),
            sse_timeout: Duration::from_secs(300), // 5 minutes for SSE stream
            max_reconnect_attempts: 10,
            base_reconnect_delay: Duration::from_millis(500),
            max_reconnect_delay: Duration::from_secs(30),
            jitter_factor: 0.2,
        }
    }
}

/// Transport error types
#[derive(Debug, thiserror::Error)]
pub enum TransportError {
    #[error("Protocol version negotiation failed: {0}")]
    VersionNegotiation(String),
    #[error("Unsupported protocol version: {0}")]
    UnsupportedVersion(String),
    #[error("HTTP error: {status} - {message}")]
    HttpError { status: u16, message: String },
    #[error("Request timeout")]
    Timeout,
    #[error("SSE stream error: {0}")]
    SseError(String),
    #[error("SSE stream ended unexpectedly")]
    SseEnded,
    #[error("Cursor expired: earliest={earliest}, latest={latest}")]
    CursorExpired { earliest: u64, latest: u64 },
    #[error("Max reconnect attempts exceeded")]
    MaxReconnectAttempts,
    #[error("Invalid response: {0}")]
    InvalidResponse(String),
    #[error("Network error: {0}")]
    Network(#[from] reqwest::Error),
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("Protocol error: {0}")]
    Protocol(#[from] ProtocolError),
    #[error("URL parse error: {0}")]
    UrlParse(#[from] url::ParseError),
}

/// Result of an SSE event stream read
#[derive(Debug, Clone)]
pub struct SseEvent {
    pub event_type: String,
    pub sequence: Option<u64>,
    pub data: Value,
}

/// HTTP/SSE transport client
#[derive(Clone)]
pub struct Transport {
    client: Client,
    config: TransportConfig,
}

impl Transport {
    /// Create a new transport client
    pub fn new(config: TransportConfig) -> Result<Self> {
        let client = Client::builder()
            .timeout(config.request_timeout)
            .connect_timeout(config.connect_timeout)
            .cookie_store(true)
            .build()?;

        Ok(Self {
            client,
            config,
        })
    }

    /// Create a transport with default configuration
    pub fn default() -> Result<Self> {
        Self::new(TransportConfig::default())
    }

    /// Get the base URL
    pub fn base_url(&self) -> &str {
        &self.config.base_url
    }

    /// Perform protocol version negotiation
    pub async fn negotiate_version(&self) -> Result<VersionNegotiationResponse, TransportError> {
        let url = format!("{}/api/v1/version/negotiate", self.config.base_url);
        let request = VersionNegotiationRequest {
            client_version: PROTOCOL_VERSION.to_string(),
        };

        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .map_err(TransportError::Network)?;

        let status = response.status();
        if !status.is_success() {
            let message = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(TransportError::HttpError {
                status: status.as_u16(),
                message,
            });
        }

        let version_response: VersionNegotiationResponse = response
            .json()
            .await
            .map_err(|e| TransportError::InvalidResponse(format!("Failed to parse version response: {}", e)))?;

        if !version_response.supported {
            return Err(TransportError::UnsupportedVersion(
                version_response
                    .error
                    .unwrap_or_else(|| "Version not supported".to_string()),
            ));
        }

        info!("Protocol version negotiated: {}", version_response.server_version);
        Ok(version_response)
    }

    /// Create a new execution
    pub async fn create_execution(
        &self,
        request: ExecutionCreateRequest,
    ) -> Result<ExecutionCreateResponse, TransportError> {
        let url = format!("{}/api/v1/executions", self.config.base_url);

        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .map_err(TransportError::Network)?;

        let status = response.status();
        if !status.is_success() {
            let message = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(TransportError::HttpError {
                status: status.as_u16(),
                message,
            });
        }

        let exec_response: ExecutionCreateResponse = response
            .json()
            .await
            .map_err(|e| TransportError::InvalidResponse(format!("Failed to parse execution response: {}", e)))?;

        Ok(exec_response)
    }

    /// Get execution state
    pub async fn get_execution_state(
        &self,
        execution_id: &str,
    ) -> Result<ExecutionStateResponse, TransportError> {
        let url = format!(
            "{}/api/v1/executions/{}",
            self.config.base_url, execution_id
        );

        let response = self
            .client
            .get(&url)
            .send()
            .await
            .map_err(TransportError::Network)?;

        let status = response.status();
        if !status.is_success() {
            let message = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(TransportError::HttpError {
                status: status.as_u16(),
                message,
            });
        }

        let state: ExecutionStateResponse = response
            .json()
            .await
            .map_err(|e| TransportError::InvalidResponse(format!("Failed to parse state response: {}", e)))?;

        Ok(state)
    }

    /// Send approval decision
    pub async fn send_approval_decision(
        &self,
        execution_id: &str,
        approval_id: &str,
        decision: crate::protocol::ApprovalDecision,
        reasons: Option<Vec<String>>,
    ) -> Result<(), TransportError> {
        let url = format!(
            "{}/api/v1/executions/{}/approvals/{}",
            self.config.base_url, execution_id, approval_id
        );

        let request = crate::protocol::ApprovalDecisionRequest {
            approval_id: approval_id.to_string(),
            decision,
            reasons,
        };

        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .map_err(TransportError::Network)?;

        let status = response.status();
        if !status.is_success() {
            let message = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(TransportError::HttpError {
                status: status.as_u16(),
                message,
            });
        }

        Ok(())
    }

    /// Stream events via SSE with reconnect logic
    pub async fn stream_events(
        &self,
        execution_id: &str,
        mut after_sequence: u64,
    ) -> Result<impl StreamExt<Item = Result<SseEvent, TransportError>>, TransportError> {
        let url = format!(
            "{}/api/v1/executions/{}/events",
            self.config.base_url, execution_id
        );

        let stream = self
            .connect_sse_with_reconnect(&url, after_sequence)
            .await?;

        Ok(stream)
    }

    /// Internal: connect to SSE endpoint with exponential backoff reconnect
    async fn connect_sse_with_reconnect(
        &self,
        url: &str,
        initial_after: u64,
    ) -> Result<
        impl StreamExt<Item = Result<SseEvent, TransportError>> + use<>,
        TransportError,
    > {
        let mut after_sequence = initial_after;
        let mut attempt = 0;

        loop {
            match self.connect_sse_once(url, after_sequence).await {
                Ok(stream) => {
                    info!("SSE connection established (attempt {})", attempt + 1);
                    return Ok(stream);
                }
                Err(TransportError::CursorExpired { earliest, latest }) => {
                    // Cursor expired - need to resync from earliest available
                    warn!(
                        "Cursor expired, resyncing from sequence {} (was {})",
                        earliest, after_sequence
                    );
                    after_sequence = earliest;
                    // Don't count cursor expiry as a reconnect attempt
                    continue;
                }
                Err(e) => {
                    attempt += 1;
                    if attempt >= self.config.max_reconnect_attempts {
                        error!("Max reconnect attempts ({}) exceeded", self.config.max_reconnect_attempts);
                        return Err(TransportError::MaxReconnectAttempts);
                    }

                    let delay = self.calculate_backoff(attempt);
                    warn!(
                        "SSE connection failed (attempt {}/{}): {}. Retrying in {:?}",
                        attempt,
                        self.config.max_reconnect_attempts,
                        e,
                        delay
                    );
                    sleep(delay).await;
                    // After reconnect, resume from where we left off
                }
            }
        }
    }

    /// Single SSE connection attempt
    async fn connect_sse_once(
        &self,
        url: &str,
        after_sequence: u64,
    ) -> Result<impl StreamExt<Item = Result<SseEvent, TransportError>>, TransportError> {
        let mut request_url = Url::parse(url)?;
        request_url
            .query_pairs_mut()
            .append_pair("after", &after_sequence.to_string());

        let mut request = self.client.get(request_url);

        // Add Last-Event-ID header for cursor-based reconnect
        if after_sequence > 0 {
            request = request.header("Last-Event-ID", after_sequence.to_string());
        }

        let response = timeout(self.config.sse_timeout, request.send())
            .await
            .map_err(|_| TransportError::Timeout)?
            .map_err(TransportError::Network)?;

        let status = response.status();
        if !status.is_success() {
            if status.as_u16() == 410 {
                // Cursor expired
                let body: Value = response.json().await
                    .map_err(|e| TransportError::InvalidResponse(format!("Failed to parse cursor expired response: {}", e)))?;
                return Err(TransportError::CursorExpired {
                    earliest: body
                        .get("earliest_sequence")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0),
                    latest: body
                        .get("latest_sequence")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0),
                });
            }
            let message = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(TransportError::HttpError {
                status: status.as_u16(),
                message,
            });
        }

        let byte_stream = response.bytes_stream();

        // Convert byte stream to SSE events using a custom stream that buffers data
        let event_stream = SseEventStream::new(byte_stream);

        Ok(event_stream)
    }

    /// Calculate exponential backoff with jitter
    pub fn calculate_backoff(&self, attempt: u32) -> Duration {
        let base_delay = self.config.base_reconnect_delay.as_millis() as f64;
        let exponential_delay = base_delay * 2_f64.powi(attempt as i32 - 1);
        let jitter = exponential_delay * self.config.jitter_factor * (rand::random::<f64>() * 2.0 - 1.0);
        let delay = (exponential_delay + jitter).max(base_delay) as u64;
        Duration::from_millis(delay.min(self.config.max_reconnect_delay.as_millis() as u64))
    }
}

/// SSE Event Stream that properly parses Server-Sent Events from a byte stream
pin_project_lite::pin_project! {
    struct SseEventStream<S> {
        #[pin]
        inner: S,
        buffer: String,
    }
}

impl<S> SseEventStream<S>
where
    S: Stream<Item = Result<Bytes, reqwest::Error>>,
{
    fn new(inner: S) -> Self {
        Self {
            inner,
            buffer: String::new(),
        }
    }
}

impl<S> Stream for SseEventStream<S>
where
    S: Stream<Item = Result<Bytes, reqwest::Error>>,
{
    type Item = Result<SseEvent, TransportError>;

    fn poll_next(self: Pin<&mut Self>, cx: &mut TaskContext<'_>) -> Poll<Option<Self::Item>> {
        let mut this = self.project();

        loop {
            // Try to parse a complete event from the buffer
            if let Some(event) = parse_sse_event(&this.buffer) {
                // Remove the parsed event from buffer
                let event_end = this.buffer.find("\n\n").map(|i| i + 2).unwrap_or(this.buffer.len());
                this.buffer.drain(..event_end.min(this.buffer.len()));

                return Poll::Ready(Some(Ok(SseEvent {
                    event_type: event.0,
                    sequence: event.1,
                    data: event.2,
                })));
            }

            // Need more data - poll the inner stream
            match this.inner.as_mut().poll_next(cx) {
                Poll::Ready(Some(Ok(bytes))) => {
                    // Append new data to buffer
                    match String::from_utf8(bytes.to_vec()) {
                        Ok(text) => this.buffer.push_str(&text),
                        Err(e) => {
                            return Poll::Ready(Some(Err(TransportError::SseError(e.to_string()))));
                        }
                    }
                }
                Poll::Ready(Some(Err(e))) => {
                    return Poll::Ready(Some(Err(TransportError::Network(e))));
                }
                Poll::Ready(None) => {
                    // Stream ended - try to parse any remaining data
                    if !this.buffer.trim().is_empty() {
                        if let Some(event) = parse_sse_event(&this.buffer) {
                            return Poll::Ready(Some(Ok(SseEvent {
                                event_type: event.0,
                                sequence: event.1,
                                data: event.2,
                            })));
                        }
                    }
                    return Poll::Ready(None);
                }
                Poll::Pending => {
                    return Poll::Pending;
                }
            }
        }
    }
}

/// Convenience function to create a transport with custom base URL
pub fn create_transport(base_url: &str) -> Result<Transport> {
    let config = TransportConfig {
        base_url: base_url.to_string(),
        ..Default::default()
    };
    Transport::new(config)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::ApprovalDecision;

    #[test]
    fn test_transport_config_default() {
        let config = TransportConfig::default();
        assert_eq!(config.base_url, "http://127.0.0.1:8000");
        assert_eq!(config.connect_timeout, Duration::from_secs(5));
        assert_eq!(config.max_reconnect_attempts, 10);
    }

    #[test]
    fn test_calculate_backoff() {
        let config = TransportConfig::default();
        let transport = Transport::new(config).unwrap();

        // First attempt: base delay (500ms) with jitter
        let delay1 = transport.calculate_backoff(1);
        assert!(delay1 >= Duration::from_millis(400)); // Allow for jitter
        assert!(delay1 <= Duration::from_millis(600));

        // Second attempt: ~1000ms with jitter
        let delay2 = transport.calculate_backoff(2);
        assert!(delay2 >= Duration::from_millis(800));
        assert!(delay2 <= Duration::from_millis(1200));

        // Max delay cap
        let config = TransportConfig {
            max_reconnect_delay: Duration::from_secs(1),
            ..Default::default()
        };
        let transport = Transport::new(config).unwrap();
        let delay_max = transport.calculate_backoff(10);
        assert!(delay_max <= Duration::from_secs(1));
    }

    #[test]
    fn test_version_negotiation_request_serialization() {
        let request = VersionNegotiationRequest {
            client_version: "1.0".to_string(),
        };
        let json = serde_json::to_value(&request).unwrap();
        assert_eq!(json["client_version"], "1.0");
    }

    #[test]
    fn test_execution_create_request_serialization() {
        let request = ExecutionCreateRequest {
            message: "Test message".to_string(),
            session_id: Some("sess-123".to_string()),
            conversation: None,
            idempotency_key: Some("key-123".to_string()),
        };
        let json = serde_json::to_value(&request).unwrap();
        assert_eq!(json["message"], "Test message");
        assert_eq!(json["session_id"], "sess-123");
        assert_eq!(json["idempotency_key"], "key-123");
    }

    #[test]
    fn test_approval_decision_serialization() {
        let request = crate::protocol::ApprovalDecisionRequest {
            approval_id: "approval-123".to_string(),
            decision: ApprovalDecision::Allow,
            reasons: Some(vec!["User approved".to_string()]),
        };
        let json = serde_json::to_value(&request).unwrap();
        assert_eq!(json["approval_id"], "approval-123");
        assert_eq!(json["decision"], "allow");
    }
}