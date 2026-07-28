import os
import tempfile
from pathlib import Path

import pytest
from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.runtime.executor import ToolExecutor
from app.tools import FileSystemTool, ToolInfo, ToolManager, ToolRegistry


def test_tool_info_creation():
    info = ToolInfo(tool_id="test", description="Test tool", capabilities=["read"])
    assert info.tool_id == "test"
    assert "read" in info.capabilities


def test_tool_registry():
    registry = ToolRegistry()
    tool = FileSystemTool("dummy")
    info = ToolInfo(tool_id="filesystem", description="desc")
    registry.register("filesystem", tool, info)

    assert registry.get_tool("filesystem") is tool
    assert registry.get_tool("unknown") is None
    assert len(registry.list_tools()) == 1


def test_tool_manager():
    registry = ToolRegistry()
    tool = FileSystemTool("dummy")
    info = ToolInfo(tool_id="filesystem", description="desc")
    registry.register("filesystem", tool, info)
    manager = ToolManager(registry)

    assert manager.resolve_tool("filesystem") is tool
    assert len(manager.list_tools()) == 1


@pytest.mark.asyncio
async def test_filesystem_tool_write_read():
    with tempfile.TemporaryDirectory() as temp_dir:
        tool = FileSystemTool(temp_dir)
        
        # Test write
        write_result = await tool.run({
            "action": "write_file",
            "path": "test.txt",
            "content": "hello world"
        })
        assert write_result.ok is True
        
        # Test read
        read_result = await tool.run({
            "action": "read_file",
            "path": "test.txt"
        })
        assert read_result.ok is True
        assert read_result.data["content"] == "hello world"


@pytest.mark.asyncio
async def test_filesystem_tool_list_directory():
    with tempfile.TemporaryDirectory() as temp_dir:
        tool = FileSystemTool(temp_dir)
        
        await tool.run({"action": "write_file", "path": "test1.txt", "content": "1"})
        await tool.run({"action": "write_file", "path": "dir/test2.txt", "content": "2"})
        
        list_result = await tool.run({"action": "list_directory", "path": ""})
        assert list_result.ok is True
        items = list_result.data["items"]
        assert len(items) == 2
        file_names = {f["name"] for f in items}
        assert "test1.txt" in file_names
        assert "dir" in file_names


@pytest.mark.asyncio
async def test_filesystem_tool_path_traversal():
    with tempfile.TemporaryDirectory() as temp_dir:
        tool = FileSystemTool(temp_dir)
        
        # Test path traversal
        traversal_result = await tool.run({
            "action": "read_file",
            "path": "../outside.txt"
        })
        assert traversal_result.ok is False
        assert "traversal" in traversal_result.error.lower()


@pytest.mark.asyncio
async def test_tool_executor_success():
    with tempfile.TemporaryDirectory() as temp_dir:
        registry = ToolRegistry()
        tool = FileSystemTool(temp_dir)
        info = ToolInfo(tool_id="filesystem", description="desc")
        registry.register("filesystem", tool, info)
        manager = ToolManager(registry)
        
        executor = ToolExecutor(manager)
        
        context = RuntimeContext(request_id="req-1")
        task = RuntimeTask(
            task_id="task-1",
            title="Test",
            description="Test task",
            action_type="filesystem",
            inputs={"action": "write_file", "path": "test.txt", "content": "hello executor"}
        )
        routing = RoutingDecision(provider_id="", model_id="", reasoning_summary="")
        
        result = await executor.execute(context, task, routing)
        assert result.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_tool_executor_unknown_tool():
    registry = ToolRegistry()
    manager = ToolManager(registry)
    executor = ToolExecutor(manager)
    
    context = RuntimeContext(request_id="req-1")
    task = RuntimeTask(
        task_id="task-1",
        title="Test",
        description="Test task",
        action_type="unknown_tool",
        inputs={}
    )
    routing = RoutingDecision(provider_id="", model_id="", reasoning_summary="")
    
    result = await executor.execute(context, task, routing)
    assert result.status == TaskStatus.FAILED
    assert "not found" in result.error
