from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    """HTTP request body for executing a Samaktha request."""

    message: str = Field(min_length=1)


class ExecuteResponse(BaseModel):
    """HTTP response body returned by the execute endpoint."""

    status: str
    response: str | None = None
    error: str | None = None
