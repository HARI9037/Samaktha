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
    execution_id: str | None = None
    request_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    response: str | None = None
    error: str | None = None
    diagnostics: ExecutionReport | None = None


class ExecutionStateResponse(BaseModel):
    execution_id: str
    status: str
    principal_id: str
    session_id: str
    pending_approval: bool = False
    result_available: bool = False
    created_at: str
    updated_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class ApprovalDecisionRequest(BaseModel):
    approval_id: str
    decision: str = Field(pattern="^(allow|deny)$")
    reasons: list[str] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    session_id: str | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
