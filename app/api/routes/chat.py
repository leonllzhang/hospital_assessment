# app/api/routes/chat.py
from fastapi import APIRouter
from app.models.chat import ChatRequest, ChatResponse
from app.services.hospital_qa import agent_controller

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("", response_model=ChatResponse)
def chat_api(request: ChatRequest) -> ChatResponse:
    try:
        # 交给 Agent Controller 处理
        result = agent_controller.run_agent_loop(request.query)
        return ChatResponse(
            status="success",
            text=result.get("text", ""),
            chart_option=result.get("chart_option"),
            engine=result.get("engine"),
            dashboard_data=result.get("dashboard_data") 
        )
    except Exception as exc:
        return ChatResponse(status="error", text=f"系统错误: {exc}")