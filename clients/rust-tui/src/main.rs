/// Main entry point for the Rust TUI client.
///
/// Implements terminal lifecycle, event loop, and integration with
/// transport layer and state machine for Samaktha protocol v1.0.

use rust_tui::protocol::{ApprovalDecision, ExecutionCreateRequest, ExecutionStateResponse, EventEnvelope, decode_event_envelope};
use rust_tui::state::{ExecutionStateMachine, StateTransition};
use rust_tui::transport::{create_transport, Transport, TransportConfig, TransportError, SseEvent};
use rust_tui::ui::{Ui, UiAction};
use futures::StreamExt;
use anyhow::{Context, Result};
use clap::{Parser, ValueEnum};
use crossterm::event::{self, Event};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::mpsc;
use tokio::time::interval;
use tracing::{error, info, warn};
use tracing_subscriber::{EnvFilter, FmtSubscriber};

/// Client type selection
#[derive(ValueEnum, Clone, Copy, Debug, PartialEq, Eq)]
enum ClientType {
    /// Textual TUI client (default)
    Textual,
    /// Rust ratatui TUI client
    Rust,
}

/// Command line arguments
#[derive(Parser, Debug)]
#[command(name = "rust-tui", version, about = "Samaktha Rust TUI Client")]
struct Args {
    /// Backend base URL
    #[arg(short, long, default_value = "http://127.0.0.1:8000")]
    url: String,

    /// Initial message to send
    #[arg(short, long)]
    message: Option<String>,

    /// Session ID to resume
    #[arg(short, long)]
    session: Option<String>,

    /// Idempotency key for execution creation
    #[arg(long)]
    idempotency_key: Option<String>,

    /// Enable debug logging
    #[arg(short, long)]
    debug: bool,

    /// Disable auto-reconnect
    #[arg(long)]
    no_reconnect: bool,

    /// Client type to use (default: textual)
    #[arg(long, value_enum, default_value = "textual")]
    client: ClientType,
}

/// Application state
struct App {
    transport: Arc<Transport>,
    state_machine: ExecutionStateMachine,
    ui: Ui,
    execution_id: Option<String>,
    session_id: Option<String>,
    initial_message: Option<String>,
    idempotency_key: Option<String>,
    reconnect_enabled: bool,
    shutdown: bool,
}

impl App {
    /// Create a new application instance
    async fn new(args: Args) -> Result<Self> {
        let transport = Arc::new(create_transport(&args.url)?);
        let state_machine = ExecutionStateMachine::new();
        let ui = Ui::new()?;

        Ok(Self {
            transport,
            state_machine,
            ui,
            execution_id: None,
            session_id: args.session,
            initial_message: args.message,
            idempotency_key: args.idempotency_key,
            reconnect_enabled: !args.no_reconnect,
            shutdown: false,
        })
    }

    /// Initialize the application
    async fn initialize(&mut self) -> Result<()> {
        info!("Initializing Rust TUI client");

        // Initialize UI
        self.ui.init()?;

        // Negotiate protocol version
        self.ui.set_status("Negotiating protocol version...".to_string());
        self.ui.draw()?;

        let version_response = self
            .transport
            .negotiate_version()
            .await
            .context("Protocol version negotiation failed")?;

        info!("Protocol version: {}", version_response.server_version);
        self.ui.set_status(format!("Connected (v{})", version_response.server_version));

        // Create execution if message provided
        if let Some(message) = self.initial_message.take() {
            self.ui.set_status("Creating execution...".to_string());
            self.ui.draw()?;

            let request = ExecutionCreateRequest {
                message,
                session_id: self.session_id.clone(),
                conversation: None,
                idempotency_key: self.idempotency_key.clone(),
            };

            let response = self
                .transport
                .create_execution(request)
                .await
                .context("Failed to create execution")?;

            self.execution_id = Some(response.execution_id.clone());
            self.session_id = Some(response.session_id.clone());

            // Initialize state machine from response
            let state_response = ExecutionStateResponse {
                execution_id: response.execution_id,
                status: response.status,
                principal_id: "".to_string(), // Will be filled from events
                session_id: self.session_id.clone().unwrap_or_default(),
                pending_approval: false,
                result_available: false,
                created_at: chrono::Utc::now(),
                updated_at: None,
                completed_at: None,
                error: None,
            };
            self.state_machine.initialize_from_response(state_response)?;

            self.ui.set_status("Execution created, streaming events...".to_string());
        }

        Ok(())
    }

    /// Run the main event loop
    async fn run(&mut self) -> Result<()> {
        let execution_id = match &self.execution_id {
            Some(id) => id.clone(),
            None => {
                // No execution to stream, just run UI
                return self.run_ui_only().await;
            }
        };

        // Create channels for event communication
        let (event_tx, mut event_rx) = mpsc::unbounded_channel::<Result<EventEnvelope, TransportError>>();
        let (ui_tx, mut ui_rx) = mpsc::unbounded_channel::<UiAction>();

        // Spawn SSE event stream task
        let transport = self.transport.clone();
        let exec_id = execution_id.clone();
        let reconnect = self.reconnect_enabled;
        tokio::spawn(async move {
            let mut after_sequence = 0;
            loop {
                match Self::stream_events_with_reconnect(transport.clone(), &exec_id, after_sequence, reconnect).await {
                    Ok(mut stream) => {
                        while let Some(result) = stream.next().await {
                            match result {
                                Ok(sse_event) => {
                                    // Decode SSE event into EventEnvelope
                                    match decode_event_envelope(&sse_event.event_type, sse_event.sequence, &sse_event.data) {
                                        Ok(envelope) => {
                                            // Update after_sequence for reconnect cursor
                                            after_sequence = envelope.sequence;
                                            if let Err(e) = event_tx.send(Ok(envelope)) {
                                                warn!("Event channel closed: {}", e);
                                                return;
                                            }
                                        }
                                        Err(e) => {
                                            error!("Failed to decode event: {}", e);
                                            if let Err(_) = event_tx.send(Err(TransportError::SseError(e.to_string()))) {
                                                return;
                                            }
                                        }
                                    }
                                }
                                Err(e) => {
                                    if let Err(_) = event_tx.send(Err(e)) {
                                        return;
                                    }
                                }
                            }
                        }
                    }
                    Err(e) => {
                        if let Err(_) = event_tx.send(Err(e)) {
                            return;
                        }
                        if !reconnect {
                            return;
                        }
                    }
                }

                if !reconnect {
                    break;
                }
                // Wait before reconnecting
                tokio::time::sleep(Duration::from_secs(1)).await;
            }
        });

        // Spawn UI input handler
        let mut ui_clone = self.ui.clone_for_input();
        tokio::spawn(async move {
            loop {
                if event::poll(Duration::from_millis(50)).unwrap_or(false) {
                    if let Ok(Event::Key(key)) = event::read() {
                        let action = ui_clone.handle_key(key);
                        if ui_tx.send(action).is_err() {
                            break;
                        }
                        if action == UiAction::Quit {
                            break;
                        }
                    }
                }
                tokio::time::sleep(Duration::from_millis(16)).await; // ~60fps
            }
        });

        // Main event loop
        let mut render_interval = interval(Duration::from_millis(100)); // 10fps render
        let mut pending_approval_id: Option<String> = None;

        loop {
            tokio::select! {
                // Handle SSE events
                Some(result) = event_rx.recv() => {
                    match result {
                        Ok(envelope) => {
                            // Process event through state machine
                            match self.state_machine.process_event(envelope) {
                                Ok(transitions) => {
                                    self.ui.process_transitions(transitions);
                                    self.ui.set_execution_state(self.state_machine.state().cloned());

                                    // Check for approval
                                    if let Some(state) = self.state_machine.state() {
                                        if state.pending_approval {
                                            pending_approval_id = state.pending_approval_id.clone();
                                        } else {
                                            pending_approval_id = None;
                                        }
                                    }
                                }
                                Err(e) => {
                                    error!("Failed to process event: {}", e);
                                    self.ui.set_error(Some(format!("Event processing error: {}", e)));
                                }
                            }
                        }
                        Err(e) => {
                            error!("SSE error: {}", e);
                            self.ui.set_error(Some(format!("Connection error: {}", e)));
                            if !self.reconnect_enabled {
                                break;
                            }
                        }
                    }
                }

                // Handle UI actions
                Some(action) = ui_rx.recv() => {
                    match action {
                        UiAction::Quit => {
                            self.shutdown = true;
                            break;
                        }
                        UiAction::AllowApproval => {
                            if let Some(approval_id) = &pending_approval_id {
                                if let Some(exec_id) = &self.execution_id {
                                    if let Err(e) = self.transport.send_approval_decision(
                                        exec_id,
                                        approval_id,
                                        ApprovalDecision::Allow,
                                        None,
                                    ).await {
                                        error!("Failed to send approval: {}", e);
                                        self.ui.set_error(Some(format!("Approval failed: {}", e)));
                                    }
                                }
                            }
                        }
                        UiAction::DenyApproval => {
                            if let Some(approval_id) = &pending_approval_id {
                                if let Some(exec_id) = &self.execution_id {
                                    if let Err(e) = self.transport.send_approval_decision(
                                        exec_id,
                                        approval_id,
                                        ApprovalDecision::Deny,
                                        Some(vec!["User denied via TUI".to_string()]),
                                    ).await {
                                        error!("Failed to send denial: {}", e);
                                        self.ui.set_error(Some(format!("Denial failed: {}", e)));
                                    }
                                }
                            }
                        }
                        UiAction::Refresh => {
                            // Refresh execution state
                            if let Some(exec_id) = &self.execution_id {
                                match self.transport.get_execution_state(exec_id).await {
                                    Ok(state) => {
                                        self.state_machine.initialize_from_response(state).ok();
                                    }
                                    Err(e) => {
                                        error!("Failed to refresh state: {}", e);
                                    }
                                }
                            }
                        }
                        UiAction::None => {}
                    }
                }

                // Periodic render
                _ = render_interval.tick() => {
                    if let Err(e) = self.ui.draw() {
                        error!("Render error: {}", e);
                    }
                }
            }

            // Check for terminal state
            if self.state_machine.is_terminal() && self.reconnect_enabled {
                info!("Execution reached terminal state");
                // Keep UI running to show final state
            }
        }

        Ok(())
    }

    /// Stream events with reconnect logic
    async fn stream_events_with_reconnect(
        transport: Arc<Transport>,
        execution_id: &str,
        mut after_sequence: u64,
        _reconnect: bool,
    ) -> Result<impl futures::Stream<Item = Result<SseEvent, TransportError>>, TransportError> {
        transport.stream_events(execution_id, after_sequence).await
    }

    /// Run UI only (no SSE streaming)
    async fn run_ui_only(&mut self) -> Result<()> {
        let (ui_tx, mut ui_rx) = mpsc::unbounded_channel::<UiAction>();

        // Spawn UI input handler
        let mut ui_clone = self.ui.clone_for_input();
        tokio::spawn(async move {
            loop {
                if event::poll(Duration::from_millis(50)).unwrap_or(false) {
                    if let Ok(Event::Key(key)) = event::read() {
                        let action = ui_clone.handle_key(key);
                        if ui_tx.send(action).is_err() {
                            break;
                        }
                        if action == UiAction::Quit {
                            break;
                        }
                    }
                }
                tokio::time::sleep(Duration::from_millis(16)).await;
            }
        });

        let mut render_interval = interval(Duration::from_millis(100));

        loop {
            tokio::select! {
                Some(action) = ui_rx.recv() => {
                    if action == UiAction::Quit {
                        break;
                    }
                }
                _ = render_interval.tick() => {
                    if let Err(e) = self.ui.draw() {
                        error!("Render error: {}", e);
                    }
                }
            }
        }

        Ok(())
    }

    /// Shutdown and cleanup
    async fn shutdown(&mut self) -> Result<()> {
        info!("Shutting down...");
        self.ui.restore()?;
        Ok(())
    }
}

// Add a helper trait to clone UI for input handling
trait UiClone {
    fn clone_for_input(&self) -> Ui;
}

impl UiClone for Ui {
    fn clone_for_input(&self) -> Ui {
        // Create a minimal UI for input handling
        Ui::new().expect("Failed to create UI for input")
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    // Initialize tracing
    let filter = if args.debug {
        EnvFilter::new("debug,rust_tui=debug,transport=debug,state=debug,ui=debug")
    } else {
        EnvFilter::new("info,rust_tui=info,transport=warn,state=warn,ui=warn")
    };

    FmtSubscriber::builder()
        .with_env_filter(filter)
        .with_writer(std::io::stderr)
        .init();

    info!("Starting Samaktha Rust TUI client v{}", env!("CARGO_PKG_VERSION"));
    info!("Client type: {:?}", args.client);

    // Client selection: default is textual (for backwards compatibility with test harness)
    // This binary always runs the Rust TUI; the flag is for test harness compatibility
    match args.client {
        ClientType::Textual => {
            info!("Client type 'textual' selected - running Rust TUI (this binary)");
            // For compatibility, we run the Rust TUI. In a full deployment,
            // a wrapper script would delegate to the Textual client.
        }
        ClientType::Rust => {
            info!("Client type 'rust' selected - running Rust TUI");
        }
    }

    let mut app = App::new(args).await?;

    // Initialize
    if let Err(e) = app.initialize().await {
        error!("Initialization failed: {}", e);
        app.ui.set_error(Some(format!("Init failed: {}", e)));
        app.ui.draw()?;
        tokio::time::sleep(Duration::from_secs(2)).await;
        app.shutdown().await?;
        return Err(e);
    }

    // Run main loop
    if let Err(e) = app.run().await {
        error!("Runtime error: {}", e);
        app.ui.set_error(Some(format!("Runtime error: {}", e)));
        app.ui.draw()?;
        tokio::time::sleep(Duration::from_secs(2)).await;
    }

    // Shutdown
    app.shutdown().await?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use rust_tui::protocol::ExecutionCreateRequest;

    #[test]
    fn test_args_parsing() {
        let args = Args::try_parse_from(["rust-tui", "-u", "http://localhost:8000", "-m", "test"]).unwrap();
        assert_eq!(args.url, "http://localhost:8000");
        assert_eq!(args.message, Some("test".to_string()));
    }

    #[test]
    fn test_args_default_url() {
        let args = Args::try_parse_from(["rust-tui"]).unwrap();
        assert_eq!(args.url, "http://127.0.0.1:8000");
    }

    #[test]
    fn test_execution_create_request() {
        let request = ExecutionCreateRequest {
            message: "test".to_string(),
            session_id: Some("sess-123".to_string()),
            conversation: None,
            idempotency_key: Some("key-123".to_string()),
        };
        let json = serde_json::to_value(&request).unwrap();
        assert_eq!(json["message"], "test");
        assert_eq!(json["session_id"], "sess-123");
        assert_eq!(json["idempotency_key"], "key-123");
    }
}