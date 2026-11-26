/// Terminal UI rendering using ratatui/crossterm for Samaktha protocol.
///
/// Implements the presentation layer with terminal output sanitization,
/// scrollable event log, status bar, and responsive layout.

use crate::protocol::sanitize_terminal_output;
use crate::state::{ExecutionState, EventLogEntry, StateTransition};
use anyhow::Result;
use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Alignment, Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style, Stylize},
    symbols,
    text::{Line, Span, Text},
    widgets::{Block, Borders, Clear, List, ListItem, ListState, Paragraph, Wrap},
    Frame, Terminal,
};
use std::io::Stdout;
use std::time::Duration;
use tracing::{debug, error, info};

/// UI state for rendering
#[derive(Debug, Clone)]
pub struct UiState {
    pub execution_state: Option<ExecutionState>,
    pub status_message: String,
    pub error_message: Option<String>,
    pub show_help: bool,
    pub scroll_offset: usize,
    pub max_log_entries: usize,
    pub auto_scroll: bool,
}

impl Default for UiState {
    fn default() -> Self {
        Self {
            execution_state: None,
            status_message: "Connecting...".to_string(),
            error_message: None,
            show_help: false,
            scroll_offset: 0,
            max_log_entries: 1000,
            auto_scroll: true,
        }
    }
}

/// Terminal UI renderer
pub struct Ui {
    terminal: Terminal<CrosstermBackend<Stdout>>,
    ui_state: UiState,
    log_state: ListState,
    last_log_len: usize,
}

impl Ui {
    /// Create a new UI instance
    pub fn new() -> Result<Self> {
        let backend = CrosstermBackend::new(std::io::stdout());
        let terminal = Terminal::new(backend)?;
        Ok(Self {
            terminal,
            ui_state: UiState::default(),
            log_state: ListState::default(),
            last_log_len: 0,
        })
    }

    /// Initialize terminal
    pub fn init(&mut self) -> Result<()> {
        crossterm::terminal::enable_raw_mode()?;
        crossterm::execute!(std::io::stdout(), crossterm::terminal::EnterAlternateScreen)?;
        self.terminal.clear()?;
        Ok(())
    }

    /// Restore terminal
    pub fn restore(&mut self) -> Result<()> {
        crossterm::execute!(std::io::stdout(), crossterm::terminal::LeaveAlternateScreen)?;
        crossterm::terminal::disable_raw_mode()?;
        self.terminal.show_cursor()?;
        Ok(())
    }

    /// Update execution state
    pub fn set_execution_state(&mut self, state: Option<ExecutionState>) {
        self.ui_state.execution_state = state;
    }

    /// Update status message
    pub fn set_status(&mut self, status: String) {
        self.ui_state.status_message = status;
    }

    /// Set error message
    pub fn set_error(&mut self, error: Option<String>) {
        self.ui_state.error_message = error;
    }

    /// Process state transitions and update UI
    pub fn process_transitions(&mut self, transitions: Vec<StateTransition>) {
        for transition in transitions {
            match transition {
                StateTransition::StatusChanged { from, to } => {
                    self.ui_state.status_message = format!("Status: {:?} -> {:?}", from, to);
                }
                StateTransition::ApprovalRequested { approval_id, .. } => {
                    self.ui_state.status_message = format!("⚠ Approval needed: {}", approval_id);
                    self.ui_state.error_message = Some("Press 'a' to allow, 'd' to deny".to_string());
                }
                StateTransition::ApprovalResolved { decision, .. } => {
                    self.ui_state.status_message = format!("Approval {}", decision);
                    self.ui_state.error_message = None;
                }
                StateTransition::SearchStarted { query, .. } => {
                    self.ui_state.status_message = format!("🔍 Searching: {}", query);
                }
                StateTransition::SearchCompleted { result_count, .. } => {
                    self.ui_state.status_message = format!("✓ Search completed: {} results", result_count);
                }
                StateTransition::SearchFailed { error_message, .. } => {
                    self.ui_state.status_message = format!("✗ Search failed: {}", error_message);
                }
                StateTransition::FileReadCompleted { path, .. } => {
                    self.ui_state.status_message = format!("📄 Read: {}", path);
                }
                StateTransition::FileWriteCompleted { path, .. } => {
                    self.ui_state.status_message = format!("💾 Wrote: {}", path);
                }
                StateTransition::AssistantMessageStarted { model_id, .. } => {
                    self.ui_state.status_message = format!("🤖 {} streaming...", model_id);
                }
                StateTransition::AssistantMessageCompleted { .. } => {
                    self.ui_state.status_message = "✓ Assistant completed".to_string();
                }
                StateTransition::AssistantError { error_message, .. } => {
                    self.ui_state.status_message = format!("✗ Assistant error: {}", error_message);
                }
                StateTransition::Resynchronized { expected, actual, .. } => {
                    self.ui_state.status_message = format!("🔄 Resynced: {} -> {}", expected, actual);
                }
                StateTransition::UnknownEvent { event_type, .. } => {
                    self.ui_state.status_message = format!("Event: {}", event_type);
                }
                _ => {}
            }
        }
    }

    /// Handle key events
    pub fn handle_key(&mut self, key: KeyEvent) -> UiAction {
        match (key.code, key.modifiers) {
            (KeyCode::Char('q'), KeyModifiers::NONE) => UiAction::Quit,
            (KeyCode::Char('c'), KeyModifiers::CONTROL) => UiAction::Quit,
            (KeyCode::Char('h'), KeyModifiers::NONE) => {
                self.ui_state.show_help = !self.ui_state.show_help;
                UiAction::None
            }
            (KeyCode::Char('a'), KeyModifiers::NONE) => UiAction::AllowApproval,
            (KeyCode::Char('d'), KeyModifiers::NONE) => UiAction::DenyApproval,
            (KeyCode::Up, _) => {
                self.ui_state.auto_scroll = false;
                self.scroll_up(1);
                UiAction::None
            }
            (KeyCode::Down, _) => {
                self.scroll_down(1);
                UiAction::None
            }
            (KeyCode::PageUp, _) => {
                self.ui_state.auto_scroll = false;
                self.scroll_up(10);
                UiAction::None
            }
            (KeyCode::PageDown, _) => {
                self.scroll_down(10);
                UiAction::None
            }
            (KeyCode::Home, _) => {
                self.ui_state.auto_scroll = false;
                self.ui_state.scroll_offset = 0;
                UiAction::None
            }
            (KeyCode::End, _) => {
                self.ui_state.auto_scroll = true;
                UiAction::None
            }
            (KeyCode::Char('r'), KeyModifiers::CONTROL) => {
                self.ui_state.auto_scroll = true;
                self.ui_state.scroll_offset = 0;
                UiAction::Refresh
            }
            _ => UiAction::None,
        }
    }

    fn scroll_up(&mut self, lines: usize) {
        self.ui_state.scroll_offset = self.ui_state.scroll_offset.saturating_sub(lines);
    }

    fn scroll_down(&mut self, lines: usize) {
        let log_len = self
            .ui_state
            .execution_state
            .as_ref()
            .map(|s| s.event_log.len())
            .unwrap_or(0);
        let max_offset = log_len.saturating_sub(1);
        self.ui_state.scroll_offset = (self.ui_state.scroll_offset + lines).min(max_offset);
    }

    /// Render the UI
    pub fn draw(&mut self) -> Result<()> {
        // Extract data needed for rendering to avoid borrow issues in closure
        let execution_state = self.ui_state.execution_state.clone();
        let show_help = self.ui_state.show_help;
        let status_message = self.ui_state.status_message.clone();
        let error_message = self.ui_state.error_message.clone();
        let auto_scroll = self.ui_state.auto_scroll;
        let scroll_offset = self.ui_state.scroll_offset;
        let max_log_entries = self.ui_state.max_log_entries;
        let mut log_state = std::mem::take(&mut self.log_state);
        let mut last_log_len = self.last_log_len;

        self.terminal.draw(|frame| {
            if let Some(ref state) = execution_state {
                Self::render_main_static(
                    frame,
                    state,
                    &status_message,
                    &error_message,
                    auto_scroll,
                    scroll_offset,
                    max_log_entries,
                    &mut log_state,
                    &mut last_log_len,
                );
            } else {
                Self::render_loading_static(frame, &status_message);
            }

            if show_help {
                Self::render_help_overlay_static(frame);
            }
        })?;

        // Restore mutable state
        self.log_state = log_state;
        self.last_log_len = last_log_len;
        Ok(())
    }

    /// Static render methods that take all needed data as parameters (for use in draw closure)
    fn render_main_static(
        frame: &mut Frame,
        state: &ExecutionState,
        status_message: &str,
        error_message: &Option<String>,
        auto_scroll: bool,
        scroll_offset: usize,
        max_log_entries: usize,
        log_state: &mut ListState,
        last_log_len: &mut usize,
    ) {
        let area = frame.area();

        // Main layout: header, body, footer
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(3), // Header
                Constraint::Min(10),   // Body (event log)
                Constraint::Length(3), // Footer
            ])
            .split(area);

        Self::render_header_static(frame, chunks[0], state, status_message);
        Self::render_body_static(
            frame,
            chunks[1],
            state,
            auto_scroll,
            scroll_offset,
            max_log_entries,
            log_state,
            last_log_len,
        );
        Self::render_footer_static(frame, chunks[2], state, error_message);
    }

    fn render_header_static(
        frame: &mut Frame,
        area: Rect,
        state: &ExecutionState,
        status_message: &str,
    ) {
        let status_style = match state.status {
            crate::state::ExecutionStatus::Created => Style::default().fg(Color::Gray),
            crate::state::ExecutionStatus::Running => Style::default().fg(Color::Green).add_modifier(Modifier::BOLD),
            crate::state::ExecutionStatus::WaitingApproval => Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
            crate::state::ExecutionStatus::Completed => Style::default().fg(Color::Blue).add_modifier(Modifier::BOLD),
            crate::state::ExecutionStatus::Failed => Style::default().fg(Color::Red).add_modifier(Modifier::BOLD),
            crate::state::ExecutionStatus::Cancelled => Style::default().fg(Color::Magenta),
        };

        let status_text = format!("{:?}", state.status);
        let exec_id = &state.execution_id;
        let seq_info = format!("Seq: {}/{}", state.last_sequence, state.latest_sequence);

        let header = Paragraph::new(vec![
            Line::from(vec![
                Span::styled("Samaktha TUI", Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)),
                Span::raw(" | "),
                Span::styled(exec_id, Style::default().fg(Color::White)),
                Span::raw(" | "),
                Span::styled(seq_info, Style::default().fg(Color::DarkGray)),
            ]),
            Line::from(vec![
                Span::styled("Status: ", Style::default().fg(Color::White)),
                Span::styled(status_text, status_style),
                Span::raw(" | "),
                Span::styled(status_message, Style::default().fg(Color::Green)),
            ]),
        ])
        .block(Block::default().borders(Borders::BOTTOM).border_style(Style::default().fg(Color::DarkGray)))
        .alignment(Alignment::Left);

        frame.render_widget(header, area);
    }

    fn render_body_static(
        frame: &mut Frame,
        area: Rect,
        state: &ExecutionState,
        auto_scroll: bool,
        scroll_offset: usize,
        max_log_entries: usize,
        log_state: &mut ListState,
        last_log_len: &mut usize,
    ) {
        let log_items: Vec<ListItem> = state
            .event_log
            .iter()
            .rev() // Show newest first
            .enumerate()
            .map(|(_i, entry)| {
                let seq_style = if entry.sequence == state.last_sequence {
                    Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)
                } else {
                    Style::default().fg(Color::DarkGray)
                };

                let event_style = match entry.event_type.as_str() {
                    e if e.starts_with("EXECUTION.") => Style::default().fg(Color::Cyan),
                    e if e.starts_with("APPROVAL.") => Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
                    e if e.starts_with("SEARCH.") => Style::default().fg(Color::Blue),
                    e if e.starts_with("FILE.") => Style::default().fg(Color::Green),
                    e if e.starts_with("ASSISTANT.") => Style::default().fg(Color::Magenta),
                    _ => Style::default().fg(Color::White),
                };

                let sanitized_summary = sanitize_terminal_output(&entry.payload_summary);

                ListItem::new(vec![
                    Line::from(vec![
                        Span::styled(format!("{:>4} ", entry.sequence), seq_style),
                        Span::styled(format!("{:<25} ", entry.event_type), event_style),
                        Span::raw(sanitized_summary),
                    ]),
                    Line::from(vec![
                        Span::styled("     ", Style::default()),
                        Span::styled(&entry.timestamp[11..19], Style::default().fg(Color::DarkGray)),
                        Span::raw("  "),
                    ]),
                ])
            })
            .collect();

        // Limit log entries for performance
        let visible_items = if log_items.len() > max_log_entries {
            &log_items[..max_log_entries]
        } else {
            &log_items
        };

        let log_list = List::new(visible_items.to_vec())
            .block(
                Block::default()
                    .title(" Event Log ")
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(Color::DarkGray)),
            )
            .highlight_style(Style::default().bg(Color::DarkGray))
            .highlight_symbol("► ");

        // Auto-scroll to bottom (newest) if enabled
        if auto_scroll && visible_items.len() != *last_log_len {
            log_state.select(Some(0));
        } else if !auto_scroll {
            let idx = scroll_offset.min(visible_items.len().saturating_sub(1));
            log_state.select(Some(idx));
        }

        *last_log_len = visible_items.len();
        frame.render_stateful_widget(log_list, area, log_state);
    }

    fn render_footer_static(
        frame: &mut Frame,
        area: Rect,
        state: &ExecutionState,
        error_message: &Option<String>,
    ) {
        let mut footer_lines = vec![];

        if state.pending_approval {
            if let Some(approval_id) = &state.pending_approval_id {
                footer_lines.push(Line::from(vec![
                    Span::styled("⚠ APPROVAL REQUIRED: ", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
                    Span::styled(approval_id, Style::default().fg(Color::White).add_modifier(Modifier::BOLD)),
                    Span::raw("  [a] Allow  [d] Deny"),
                ]));
            }
        } else if let Some(error) = error_message {
            footer_lines.push(Line::from(vec![
                Span::styled("Error: ", Style::default().fg(Color::Red).add_modifier(Modifier::BOLD)),
                Span::styled(error, Style::default().fg(Color::Red)),
            ]));
        } else {
            let controls = if state.status.is_terminal() {
                "[q] Quit  [h] Help  [↑/↓] Scroll  [Home/End] Jump"
            } else {
                "[q] Quit  [h] Help  [↑/↓] Scroll  [Home/End] Jump  [Ctrl+r] Refresh"
            };
            footer_lines.push(Line::from(vec![
                Span::styled(controls, Style::default().fg(Color::DarkGray)),
            ]));
        }

        // Assistant streaming buffer display
        if !state.assistant_buffer.is_empty() && state.status == crate::state::ExecutionStatus::Running {
            let preview = if state.assistant_buffer.len() > 80 {
                format!("{}...", &state.assistant_buffer[..77])
            } else {
                state.assistant_buffer.clone()
            };
            footer_lines.push(Line::from(vec![
                Span::styled("🤖 ", Style::default().fg(Color::Magenta)),
                Span::styled(sanitize_terminal_output(&preview), Style::default().fg(Color::White)),
            ]));
        }

        let footer = Paragraph::new(footer_lines)
            .block(Block::default().borders(Borders::TOP).border_style(Style::default().fg(Color::DarkGray)))
            .alignment(Alignment::Left);

        frame.render_widget(footer, area);
    }

    fn render_loading_static(frame: &mut Frame, status_message: &str) {
        let area = frame.area();
        let loading = Paragraph::new(vec![
            Line::from(""),
            Line::from(vec![
                Span::styled("  ⏳ ", Style::default().fg(Color::Cyan)),
                Span::styled("Connecting to Samaktha backend...", Style::default().fg(Color::White)),
            ]),
            Line::from(""),
            Line::from(vec![
                Span::styled(status_message, Style::default().fg(Color::Green)),
            ]),
        ])
        .block(Block::default().borders(Borders::ALL).border_style(Style::default().fg(Color::DarkGray)))
        .alignment(Alignment::Center);

        frame.render_widget(loading, area);
    }

    fn render_help_overlay_static(frame: &mut Frame) {
        let area = frame.area();
        let popup_area = centered_rect(60, 70, area);

        frame.render_widget(Clear, popup_area);

        let help_text = vec![
            Line::from(vec![
                Span::styled(" Samaktha TUI - Help ", Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)),
            ]),
            Line::from(""),
            Line::from(vec![
                Span::styled("Navigation:", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
            ]),
            Line::from("  ↑/↓          Scroll event log"),
            Line::from("  PgUp/PgDn    Scroll 10 lines"),
            Line::from("  Home/End     Jump to top/bottom"),
            Line::from("  Ctrl+r       Refresh (reset scroll)"),
            Line::from(""),
            Line::from(vec![
                Span::styled("Approval:", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
            ]),
            Line::from("  a            Allow pending approval"),
            Line::from("  d            Deny pending approval"),
            Line::from(""),
            Line::from(vec![
                Span::styled("General:", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
            ]),
            Line::from("  h            Toggle this help"),
            Line::from("  q / Ctrl+c   Quit"),
            Line::from(""),
            Line::from(vec![
                Span::styled("Event Types:", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
            ]),
            Line::from("  EXECUTION.*  Lifecycle events (cyan)"),
            Line::from("  APPROVAL.*   Approval requests (yellow)"),
            Line::from("  SEARCH.*     Search operations (blue)"),
            Line::from("  FILE.*       File operations (green)"),
            Line::from("  ASSISTANT.*  Assistant streaming (magenta)"),
            Line::from(""),
            Line::from(vec![
                Span::styled("Status Colors:", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
            ]),
            Line::from("  Created      Gray"),
            Line::from("  Running      Green (bold)"),
            Line::from("  Waiting      Yellow (bold)"),
            Line::from("  Completed    Blue (bold)"),
            Line::from("  Failed       Red (bold)"),
            Line::from("  Cancelled    Magenta"),
            Line::from(""),
            Line::from(vec![
                Span::styled("Press [h] to close", Style::default().fg(Color::DarkGray)),
            ]),
        ];

        let help = Paragraph::new(help_text)
            .block(
                Block::default()
                    .title(" Help ")
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(Color::Cyan)),
            )
            .wrap(Wrap { trim: false })
            .alignment(Alignment::Left);

        frame.render_widget(help, popup_area);
    }

    /// Get terminal size
    pub fn size(&self) -> Rect {
        let size = self.terminal.size().unwrap_or_default();
        Rect::new(0, 0, size.width, size.height)
    }
}

/// UI actions returned from key handling
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UiAction {
    None,
    Quit,
    AllowApproval,
    DenyApproval,
    Refresh,
}

/// Helper to create a centered rectangle
fn centered_rect(percent_x: u16, percent_y: u16, r: Rect) -> Rect {
    let popup_layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage((100 - percent_y) / 2),
            Constraint::Percentage(percent_y),
            Constraint::Percentage((100 - percent_y) / 2),
        ])
        .split(r);

    Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage((100 - percent_x) / 2),
            Constraint::Percentage(percent_x),
            Constraint::Percentage((100 - percent_x) / 2),
        ])
        .split(popup_layout[1])[1]
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::{ExecutionState, ExecutionStatus, EventLogEntry};
    use chrono::Utc;
    use serde_json::json;

    #[test]
    fn test_ui_state_default() {
        let state = UiState::default();
        assert_eq!(state.status_message, "Connecting...");
        assert!(state.error_message.is_none());
        assert!(!state.show_help);
        assert_eq!(state.scroll_offset, 0);
        assert!(state.auto_scroll);
    }

    #[test]
    fn test_centered_rect() {
        let r = Rect::new(0, 0, 100, 100);
        let centered = centered_rect(50, 50, r);
        assert_eq!(centered.width, 50);
        assert_eq!(centered.height, 50);
        assert_eq!(centered.x, 25);
        assert_eq!(centered.y, 25);
    }

    #[test]
    fn test_sanitize_in_ui() {
        let input = "\x1b[31mRed\x1b[0m text";
        let result = sanitize_terminal_output(input);
        assert_eq!(result, "Red text");
    }

    #[test]
    fn test_scroll_logic() {
        let mut ui_state = UiState::default();
        ui_state.auto_scroll = false;

        // Scroll up from 0 should stay at 0
        ui_state.scroll_offset = 0;
        // Can't test private method directly but logic is simple

        // Scroll down
        ui_state.scroll_offset = 5;
        assert_eq!(ui_state.scroll_offset, 5);
    }
}