import pytest
from app.core.orchestrator.tool_response_synthesizer import synthesize_tool_response

def test_synthesize_tool_response_write():
    # TXT
    output = {
        "path": "C:/Users/user/Desktop/hello.txt",
        "format": "text",
        "written_bytes": 19
    }
    resp = synthesize_tool_response(output)
    assert "✅ Created" in resp
    assert "hello.txt" in resp
    assert "19 B" in resp
    assert "Format" not in resp  # text format is ignored

    # DOCX
    output = {
        "path": "C:/Users/user/Desktop/report.docx",
        "format": "docx",
        "written_bytes": 36630
    }
    resp = synthesize_tool_response(output)
    assert "✅ Created" in resp
    assert "report.docx" in resp
    assert "Format: DOCX" in resp
    assert "35.8 KB" in resp

    # Markdown
    output = {
        "path": "C:/Users/user/Desktop/notes.md",
        "format": "text",
        "written_bytes": 30
    }
    resp = synthesize_tool_response(output)
    assert "✅ Created" in resp
    assert "notes.md" in resp
    assert "30 B" in resp

def test_synthesize_tool_response_ignores_existing_content():
    output = {
        "path": "C:/hello.txt",
        "format": "text",
        "written_bytes": 10,
        "content": "This is read content"
    }
    assert synthesize_tool_response(output) == ""

    output = {
        "path": "C:/hello.txt",
        "format": "text",
        "written_bytes": 10,
        "response": "This is response"
    }
    assert synthesize_tool_response(output) == ""
