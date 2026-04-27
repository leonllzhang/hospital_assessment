from typing import Any, Optional, Dict
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户问题")


class ChatResponse(BaseModel):
    status: str
    text: str
    chart_option: dict[str, Any] | None = None
    engine: str | None = None  # [新增]：用于告诉前端本次使用了哪个引擎
    dashboard_data: dict[str, Any] | None = None  # [新增] 驾驶舱专属数据

