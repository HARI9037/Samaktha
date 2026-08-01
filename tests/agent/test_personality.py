"""Tests for Samaktha Agent Personality Manager."""

from app.agent.config import AgentConfig
from app.agent.personality import PersonalityManager

def test_personality_default():
    config = AgentConfig()
    manager = PersonalityManager(config)
    prompt = manager.get_system_prompt()
    
    assert "You are Samaktha." in prompt
    assert "Mission:" in prompt
    assert "Strict Guidelines" in prompt
    assert "AI language model" not in prompt
    assert "ChatGPT" not in prompt

def test_personality_custom():
    config = AgentConfig(default_personality="helpful-assistant")
    manager = PersonalityManager(config)
    prompt = manager.get_system_prompt()
    
    assert "You are a helpful and friendly AI assistant" in prompt
    assert "Strict Guidelines" in prompt
