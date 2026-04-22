from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户问题")


class ChatResponse(BaseModel):
    status: str
    text: str
    chart_option: dict[str, Any] | None = None
