from pydantic import BaseModel, Field
from app.runtime.report import ExecutionReport


class ExecuteRequest(BaseModel):
    """HTTP request body for executing a Samaktha request."""

    message: str = Field(min_length=1)


class ExecuteResponse(BaseModel):
    """HTTP response body returned by the execute endpoint."""

    status: str
    response: str | None = None
    error: str | None = None
    diagnostics: ExecutionReport | None = None
