from pydantic import BaseModel, Field

from app.core.contracts.conversation import ConversationMessage
from app.runtime.report import ExecutionReport


class ExecuteRequest(BaseModel):
    """HTTP request body for executing a Samaktha request.

    ``session_id`` is optional: when supplied, the conversation state manager
    and session memory are scoped to that session (conversation continuity,
    P1.5); when omitted, execution uses the default session.
    """

    message: str = Field(min_length=1, max_length=100_000)
    session_id: str | None = None
    conversation: list[ConversationMessage] | None = None


class ExecuteResponse(BaseModel):
    """HTTP response body returned by the execute endpoint."""

    status: str
    request_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    response: str | None = None
    error: str | None = None
    diagnostics: ExecutionReport | None = None
