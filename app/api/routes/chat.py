from fastapi import APIRouter

from app.models.chat import ChatRequest, ChatResponse
from app.services.hospital_qa import qa_service


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat_api(request: ChatRequest) -> ChatResponse:
    try:
        result = qa_service.answer(request.query)
        return ChatResponse(
            status="success",
            text=result.get("text", ""),
            chart_option=result.get("chart_option"),
            engine=result.get("engine"),  # [新增]：传递引擎标识
            dashboard_data=result.get("dashboard_data") # [新增]
        )
    except Exception as exc:
        return ChatResponse(
            status="error",
            text=f"系统错误: {exc}",
            chart_option=None,
            engine=None,
            dashboard_data=None
        )
