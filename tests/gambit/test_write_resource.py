import pytest
from app.core.gambit.goal_parser import GoalParser
from app.core.contracts.planning import GoalIntent, Goal, GoalComplexity
from app.core.gambit.task_decomposer import TaskDecomposer

def test_goal_parser_detects_create_file():
    parser = GoalParser()
    request = "Create a hello.txt in C:/Users/user/Desktop with the content 'Hello, I'm Samaktha'"
    goal = parser.parse(request)
    assert goal.intent == GoalIntent.WRITE_RESOURCE
    assert goal.target_path is not None
    assert "Hello, I'm Samaktha" in goal.query

def test_goal_parser_detects_write_file():
    parser = GoalParser()
    request = "write file /tmp/test.txt with the content 'test'"
    goal = parser.parse(request)
    assert goal.intent == GoalIntent.WRITE_RESOURCE
    assert "/tmp/test.txt" in goal.target_path
    assert "test" in goal.query

def test_goal_parser_detects_save_file():
    parser = GoalParser()
    request = "save file as output.md with content 'markdown content'"
    goal = parser.parse(request)
    assert goal.intent == GoalIntent.WRITE_RESOURCE
    assert "output.md" in goal.target_path
    assert "markdown content" in goal.query

def test_task_decomposer_write_resource():
    decomposer = TaskDecomposer()
    goal = Goal(
        goal_id="test",
        raw_request="create output.txt with content 'data'",
        summary="summary",
        complexity=GoalComplexity.LOW,
        intent=GoalIntent.WRITE_RESOURCE,
        target_path="output.txt",
        query="data",
        requires_long_context=False,
        requires_code=False,
        requires_local_model=False,
        requires_fast_response=False,
        estimated_context_tokens=10,
        constraints=[]
    )
    
    tasks = decomposer.decompose(goal, [])
    
    # [UNDERSTAND, resolver(write), REFLECT]
    assert len(tasks) == 3
    assert tasks[1].metadata["tool"] == "resolver"
    assert tasks[1].metadata["action"] == "write"
    assert tasks[1].metadata["args"]["path"] == "output.txt"
    assert tasks[1].metadata["args"]["content"] == "data"
    
    # Should not fallback to text_generation
    assert tasks[1].execution_action_type == "tool"
