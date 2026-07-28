"""Extra tests for Agent Runtime."""

import pytest

from app.agent.config import AgentConfig
from app.agent.conversation import ConversationManager
from app.agent.models import ConversationState
from app.agent.personality import PersonalityManager

def test_conversation_get_recent_context():
    config = AgentConfig()
    manager = ConversationManager(config)
    state = ConversationState(session_id="test-ctx")
    
    for i in range(15):
        manager.append_user_message(state, f"Msg {i}")
        
    recent = manager.get_recent_context(state, max_messages=5)
    assert len(recent) == 5
    assert recent[0]["content"] == "Msg 10"
    assert recent[-1]["content"] == "Msg 14"

def test_personality_fallback():
    config = AgentConfig(default_personality="unknown-personality")
    manager = PersonalityManager(config)
    prompt = manager.get_system_prompt()
    
    assert "You are an AI agent powered by Samaktha Core." in prompt

def test_conversation_model():
    state = ConversationState(session_id="model-test")
    assert state.session_id == "model-test"
    assert state.history == []
    assert state.active_tools == []
    assert state.memory_context_ids == []
