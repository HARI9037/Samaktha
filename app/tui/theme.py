"""Minimal Phase 6 conversation-first design system."""

SAMAKTHA_ORANGE = "#FF8C00"
SAMAKTHA_AMBER = "#FFA733"
SAMAKTHA_BLACK = "#000000"
SAMAKTHA_TEXT = "#E8E8E8"
SAMAKTHA_SUCCESS = "#00C96E"
SAMAKTHA_WARNING = "#FFB300"
SAMAKTHA_ERROR = "#FF4040"
SAMAKTHA_DIM = "#777777"
SAMAKTHA_DIM2 = "#202020"
SAMAKTHA_SURFACE = "#080808"
SAMAKTHA_SURFACE2 = "#111111"
SAMAKTHA_BORDER = "#242424"
SAMAKTHA_USER_BG = "#000000"

SAMAKTHA_CSS = f"""
Screen {{
    background: {SAMAKTHA_BLACK};
    color: {SAMAKTHA_TEXT};
    layout: vertical;
}}

SamakthaHeader {{
    height: auto;
}}

#header {{
    height: 4;
    width: 1fr;
    padding: 0 2;
    background: {SAMAKTHA_BLACK};
    border-bottom: solid {SAMAKTHA_BORDER};
    layout: horizontal;
    align: left middle;
}}

#header-mascot-cell {{
    width: 4;
    height: 2;
    align: left middle;
}}

#header-mascot {{
    width: 3;
    color: {SAMAKTHA_ORANGE};
    text-style: bold;
    content-align: left middle;
}}

#header-text-cell {{
    width: 1fr;
    height: 2;
    layout: vertical;
    align: left middle;
}}

#header-title {{
    height: 1;
    color: {SAMAKTHA_ORANGE};
    text-style: bold;
}}

#header-subtitle {{
    height: 1;
    color: {SAMAKTHA_DIM};
}}

#status-panel {{
    height: 1;
    width: 1fr;
    padding: 0 2;
    background: {SAMAKTHA_BLACK};
}}

#status-panel > Horizontal {{
    height: 1;
    width: 1fr;
    align: left middle;
}}

#card-status {{
    width: auto;
    height: 1;
    margin-right: 2;
    padding: 0;
    background: transparent;
    border: none;
    color: {SAMAKTHA_DIM};
}}

#agent-state-badge {{
    width: auto;
    color: {SAMAKTHA_AMBER};
}}

#voice-status-badge {{
    width: auto;
    height: 1;
    padding: 0;
    background: transparent;
    border: none;
    color: {SAMAKTHA_DIM};
}}

#conversation {{
    height: 1fr;
    width: 1fr;
    padding: 1 2;
    background: {SAMAKTHA_BLACK};
    align: left top;
    scrollbar-color: {SAMAKTHA_ORANGE} {SAMAKTHA_BLACK};
    scrollbar-background: {SAMAKTHA_BLACK};
}}

#welcome-card {{
    width: 1fr;
    height: auto;
    margin: 1 0;
    padding: 1 2;
    align: left top;
    background: transparent;
    border: none;
}}

#welcome-mascot {{
    height: 1;
    color: {SAMAKTHA_ORANGE};
    text-align: left;
}}

#welcome-title {{
    color: {SAMAKTHA_TEXT};
    text-style: bold;
    text-align: left;
    margin-top: 1;
}}

#welcome-name {{
    color: {SAMAKTHA_ORANGE};
    text-align: left;
}}

#welcome-subtitle {{
    color: {SAMAKTHA_DIM};
    text-align: left;
    margin-top: 1;
}}

#welcome-capabilities {{
    color: {SAMAKTHA_DIM};
    text-align: left;
    margin-top: 2;
}}

#welcome-hint {{
    color: {SAMAKTHA_AMBER};
    text-align: left;
    margin-top: 2;
}}

RenderedMessage {{
    width: 1fr;
    height: auto;
}}

.msg-user-container, .msg-assistant-container {{
    width: 1fr;
    height: auto;
    margin: 0 0 1 0;
    padding: 0 1;
    background: transparent;
    border: none;
}}

ConversationWelcome {{
    width: 1fr;
    height: auto;
}}

.msg-user-label, .msg-assistant-label {{
    height: 1;
    text-style: bold;
}}

.msg-user-label {{ color: {SAMAKTHA_DIM}; }}
.msg-user-content {{ color: {SAMAKTHA_TEXT}; margin-top: 0; }}
.msg-separator {{ color: {SAMAKTHA_BORDER}; height: 1; }}
.msg-assistant-label {{ color: {SAMAKTHA_ORANGE}; }}
.msg-system {{ color: {SAMAKTHA_DIM}; margin: 0 0 1 0; width: 1fr; }}

.msg-approval-buttons {{
    height: auto;
    width: 1fr;
    margin-top: 1;
}}
.msg-approval-buttons Button {{
    margin-right: 1;
}}


#input-bar {{
    height: 3;
    width: 1fr;
    padding: 0 2;
    background: {SAMAKTHA_BLACK};
    border-top: solid {SAMAKTHA_BORDER};
    layout: horizontal;
    align: left middle;
}}

#input-prompt {{
    width: 3;
    color: {SAMAKTHA_ORANGE};
    text-style: bold;
    content-align: center middle;
}}

#user-input {{
    width: 1fr;
    height: 1;
    padding: 0;
    background: {SAMAKTHA_BLACK};
    color: {SAMAKTHA_TEXT};
    border: none;
}}

#user-input:focus {{ border: none; }}

NotificationHost {{
    dock: bottom;
    width: 1fr;
    height: auto;
    max-height: 5;
    padding: 0 2;
}}

NotificationBanner {{
    width: auto;
    height: 1;
    margin: 0 0 1 0;
    padding: 0 1;
}}

StartupScreen {{
    background: {SAMAKTHA_BLACK};
    align: center middle;
}}

#startup-outer {{ width: 1fr; height: auto; margin: 0 4; }}
#startup-brand-box {{ height: auto; padding: 1 2; align: center middle; background: transparent; border: none; }}
#startup-name {{ color: {SAMAKTHA_ORANGE}; text-style: bold; text-align: center; }}
#startup-tagline {{ color: {SAMAKTHA_DIM}; text-align: center; }}
#startup-steps-box {{ padding: 1 2; background: transparent; border: none; }}
.startup-step-done {{ color: {SAMAKTHA_SUCCESS}; }}
.startup-step-pending {{ color: {SAMAKTHA_DIM}; }}
#startup-ready {{ color: {SAMAKTHA_ORANGE}; text-align: center; text-style: bold; margin-top: 1; display: none; }}
"""
