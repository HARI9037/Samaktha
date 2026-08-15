from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str
    degraded: bool = False
    providers: dict[str, str] = Field(default_factory=dict)
