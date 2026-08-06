import pytest
from app.core.gambit.goal_parser import GoalParser
from app.core.contracts.planning import GoalIntent

def test_goal_parser_no_substring_collision():
    parser = GoalParser()
    
    # Bug 1 regression tests
    req_bread = "Create notes.md in C:/Desktop with the content: # Shopping List - Milk - Bread"
    goal_bread = parser.parse(req_bread)
    assert goal_bread.intent == GoalIntent.WRITE_RESOURCE, "Bread triggered READ_RESOURCE"

    req_thread = "Create thread.txt with content 'main thread'"
    goal_thread = parser.parse(req_thread)
    assert goal_thread.intent == GoalIntent.WRITE_RESOURCE, "thread triggered READ_RESOURCE"

    req_spreadsheet = "Create spreadsheet.xlsx with content 'data'"
    goal_spreadsheet = parser.parse(req_spreadsheet)
    assert goal_spreadsheet.intent == GoalIntent.WRITE_RESOURCE, "spreadsheet triggered READ_RESOURCE"

    req_already = "Create status.txt with content 'already done'"
    goal_already = parser.parse(req_already)
    assert goal_already.intent == GoalIntent.WRITE_RESOURCE, "already triggered READ_RESOURCE"

    # Valid READ requests should still work
    req_read = "read file notes.md"
    goal_read = parser.parse(req_read)
    assert goal_read.intent == GoalIntent.READ_RESOURCE

    req_open = "open the document report.docx"
    goal_open = parser.parse(req_open)
    assert goal_open.intent == GoalIntent.READ_RESOURCE

    req_summarize = "summarize C:/Users/user/Desktop/hello.txt"
    goal_summarize = parser.parse(req_summarize)
    assert goal_summarize.intent == GoalIntent.READ_RESOURCE
