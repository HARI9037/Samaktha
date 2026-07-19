import pytest

def test_contracts_does_not_import_runtime():
    with open('app/core/contracts/runtime.py') as f:
        content = f.read()
    assert 'from app.runtime' not in content
    assert 'import app.runtime' not in content

def test_tool_executor_uses_execute_tool(monkeypatch):
    from app.runtime.executor import ToolExecutor
    from app.core.contracts import RuntimeContext, RuntimeTask, RoutingDecision
    import asyncio
    
    class MockToolResult:
        @property
        def ok(self): return True
        @property
        def data(self): return {'output': 'success'}
        @property
        def error(self): return None

    class MockToolManager:
        def __init__(self):
            self.called_execute = False
        def resolve_tool(self, tool_id):
            return None
        async def execute_tool(self, tool_id, arguments):
            self.called_execute = True
            return MockToolResult()
            
    manager = MockToolManager()
    executor = ToolExecutor(tool_manager=manager)
    
    context = RuntimeContext(request_id='test')
    task = RuntimeTask(task_id='t1', title='T', description='T', action_type='mock_tool')
    routing = RoutingDecision(provider_id='mock', router_id='mock', model_id='mock', reasoning_summary='mock')
    
    result = asyncio.run(executor.execute(context, task, routing))
    
    assert manager.called_execute, 'ToolExecutor must use ToolManager.execute_tool!'
    assert result.status.value == 'completed'
    assert result.output == {'output': 'success'}
