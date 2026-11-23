"""End-to-end integration test for search with CAP approval flow.

This test verifies the complete search chain:
InternetTool -> ToolExecutor -> RuntimeEngine -> CAP approval -> DDGS "lite" backend -> results
"""

import os

import pytest

# Enable mock provider for LLM planning while using real DDGS "lite" backend for search
os.environ["MOCK_AGENT"] = "1"
# Increase DDGS timeout to 30 seconds to avoid timeout issues in tests
os.environ["SAMAKTHA_DDGS_TIMEOUT"] = "30.0"
# Use "lite" backend (default in settings)
os.environ["SAMAKTHA_DDGS_BACKEND"] = "lite"

from app.core.app import create_orchestrator
from app.core.contracts import RuntimeContext
from app.core.contracts.planning import TaskStatus


pytestmark = pytest.mark.asyncio


class TestSearchE2E:
    """End-to-end tests for search with CAP approval."""

    async def _run_search_with_retry(self, orchestrator, context, request, max_retries=2):
        """Run search with retry for flaky DDGS backend."""
        last_error = None
        for attempt in range(max_retries):
            state = await orchestrator.run_pipeline(
                request=request,
                runtime_context=context,
            )

            # Verify pipeline paused for CAP approval (ASK_USER)
            assert state.workflow_state is not None, "Workflow state should exist"
            assert state.workflow_state.status.value == "paused", "Pipeline should pause for approval"

            # Find the paused task (internet search task)
            paused_task = None
            for task in state.execution_plan.tasks:
                if task.metadata.get("tool") == "internet":
                    paused_task = task
                    paused_task_id = task.task_id
                    break

            assert paused_task is not None, "Internet search task should be in execution plan"
            assert paused_task_id is not None, "Task ID should exist"

            # Verify the permit is ASK_USER (requires human approval)
            permit = paused_task.metadata.get("permit")
            assert permit is not None, "Permit should exist for internet task"
            assert permit["decision"] == "ask_user", f"Expected ask_user, got {permit['decision']}"

            # Simulate user clicking [Y] Allow on approval dialog
            resume_context = RuntimeContext(
                request_id=f"{context.request_id}-resume-{attempt}",
                user_id="test-user",
                session_id=context.session_id,
            )
            resumed_state = await orchestrator.resume_pipeline(
                state=state,
                runtime_context=resume_context,
                task_id=paused_task_id,
                updates={
                    "approval_decision": "allow",
                    "approval_reasons": ["User approved via E2E test"],
                },
            )

            # Check if search succeeded
            if resumed_state.runtime_result is not None:
                if resumed_state.runtime_result.status == TaskStatus.COMPLETED:
                    return resumed_state
                last_error = resumed_state.runtime_result.error
                print(f"Attempt {attempt + 1} failed: {last_error}")

        # All retries failed
        raise AssertionError(f"Search failed after {max_retries} attempts. Last error: {last_error}")

    async def test_internet_search_with_approval(self) -> None:
        """
        Simulate: user asks search -> CAP requests approval -> user clicks Allow ->
        search executes -> results returned.

        Verifies:
        - DDGS "lite" backend returns results
        - CAP approval flow completes
        """
        # Create production orchestrator with mock LLM but real DDGS "lite" backend
        orchestrator = create_orchestrator()

        # Run pipeline with a search query that:
        # 1. Triggers internet search intent (contains "search" + "latest")
        # 2. Works with DDGS "lite" backend
        context = RuntimeContext(request_id="search-e2e-test", user_id="test-user")
        resumed_state = await self._run_search_with_retry(orchestrator, context, "search about latest ai llms")

        # Verify search results were returned
        output = resumed_state.runtime_result.output
        assert output is not None, "Output should exist"
        assert "content" in output or "response" in output, "Output should have content/response"

        # Verify DDGS "lite" backend was used (check for search results in output)
        content = output.get("content", "") or output.get("response", "")
        assert content, "Should have search result content"
        assert len(content) > 0, "Content should not be empty"

        # Verify workflow completed
        assert resumed_state.workflow_state is not None
        assert resumed_state.workflow_state.status.value == "completed"

    async def test_internet_search_denied_approval(self) -> None:
        """
        Verify that denying approval blocks the search.

        Verifies:
        - CAP approval flow blocks execution when denied
        - Proper error message returned
        """
        orchestrator = create_orchestrator()

        context = RuntimeContext(request_id="search-deny-test", user_id="test-user")
        state = await orchestrator.run_pipeline(
            request="search about latest ai llms",
            runtime_context=context,
        )

        # Verify pipeline paused for CAP approval
        assert state.workflow_state is not None
        assert state.workflow_state.status.value == "paused"

        # Find the paused task
        paused_task = None
        for task in state.execution_plan.tasks:
            if task.metadata.get("tool") == "internet":
                paused_task = task
                paused_task_id = task.task_id
                break

        assert paused_task is not None
        assert paused_task_id is not None

        # Simulate user clicking [N] Deny on approval dialog
        resume_context = RuntimeContext(
            request_id="search-deny-test-resume",
            user_id="test-user",
            session_id=context.session_id,
        )
        resumed_state = await orchestrator.resume_pipeline(
            state=state,
            runtime_context=resume_context,
            task_id=paused_task_id,
            updates={
                "approval_decision": "deny",
                "approval_reasons": ["User denied via E2E test"],
            },
        )

        # Verify pipeline failed due to denial
        assert resumed_state.runtime_result is not None
        assert resumed_state.runtime_result.status == TaskStatus.FAILED
        assert "denied" in (resumed_state.runtime_result.error or "").lower()


if __name__ == "__main__":
    import asyncio
    asyncio.run(pytest.main([__file__, "-v"]))