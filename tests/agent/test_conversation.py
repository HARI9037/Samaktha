"""Tests for Samaktha Agent Conversation Manager."""

from app.agent.config import AgentConfig
from app.agent.conversation import ConversationManager
from app.agent.models import ConversationState

def test_append_messages():
    config = AgentConfig()
    manager = ConversationManager(config)
    state = ConversationState(session_id="test-1")
    
    manager.append_user_message(state, "Hello")
    assert len(state.history) == 1
    assert state.history[0]["role"] == "user"
    assert state.history[0]["content"] == "Hello"
    
    manager.append_assistant_message(state, "Hi there")
    assert len(state.history) == 2
    assert state.history[1]["role"] == "assistant"
    
    manager.append_tool_message(state, "search_tool", "Results found")
    assert len(state.history) == 3
    assert state.history[2]["role"] == "tool"

def test_trim_history():
    config = AgentConfig(max_context_tokens=10) # ~40 chars
    manager = ConversationManager(config)
    state = ConversationState(session_id="test-1")
    
    # Add messages that exceed the token limit
    manager.append_user_message(state, "First message that is reasonably long enough.")
    manager.append_assistant_message(state, "Second message that is also quite lengthy.")
    manager.append_user_message(state, "Third message to push it over the edge completely.")
    
    # It should have trimmed some history
    assert len(state.history) < 3
    # Most recent message should be kept
    assert state.history[-1]["content"] == "Third message to push it over the edge completely."

def test_summarize_conversation():
    config = AgentConfig()
    manager = ConversationManager(config)
    state = ConversationState(session_id="test-1")
    
    summary = manager.summarize_conversation(state)
    assert summary == "Empty conversation."
    
    manager.append_user_message(state, "I need to plan a trip to Paris.")
    manager.append_assistant_message(state, "I can help with that.")
    
    summary = manager.summarize_conversation(state)
    assert "Conversation with 1 user turns." in summary
    assert "I need to plan a trip to Paris." in summary
