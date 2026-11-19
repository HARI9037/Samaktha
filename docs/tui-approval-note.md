# TUI Approval Flow Behavior

## Overview

The TUI (Text User Interface) approval flow in Samaktha requires explicit button clicks to approve or deny actions. Typed input is **not** treated as approval.

## Button Interface

When an approval request is displayed, two buttons are rendered:

- **[Y] Allow** — Approves the action and resumes the workflow
- **[N] Deny** — Denies the action and resumes the workflow with a denial

## Expected User Behavior

### Correct Usage
- Click the **[Y] Allow** button to approve
- Click the **[N] Deny** button to deny

### Incorrect Usage (Will Not Work)
- Typing "approved" and pressing Enter
- Typing "allow" and pressing Enter
- Typing "y" or "yes" and pressing Enter
- Any other text input

## Implementation Details

- The approval widget is rendered by `RenderedApprovalMessage` in `app/tui/renderer.py`
- Button clicks are handled by `MainScreen.on_button_pressed()` in `app/tui/app.py`
- Typed input is handled by `MainScreen._handle_user_input()` which treats all non-slash-command input as new chat messages
- The approval flow uses `asyncio.create_task()` to call `_submit_resume()` which invokes the runtime's `resume()` method

## Testing

The behavior is verified by tests in `tests/tui/test_approval_flow.py`:
- `test_tui_approval_button_click_resumes` — Verifies Allow button triggers resume
- `test_tui_approval_deny_button_click_resumes` — Verifies Deny button triggers resume
- `test_tui_approval_typed_input_treated_as_message` — Verifies typed "approved" is treated as a new message
