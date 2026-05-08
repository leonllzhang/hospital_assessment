# app/api/routes/alert.py
# 红绿灯预警系统 API 路由

from fastapi import APIRouter
from typing import Optional
from app.services.hospital_qa import action_server

router = APIRouter(tags=["alert"])


@router.post("/alert/patrol")
def api_alert_patrol(month: str = ""):
    """Layer 2: 手动触发数据巡检"""
    return action_server.run_alert_patrol(month)


@router.get("/alert/list")
def api_alert_list(month: str = "", level: str = ""):
    """Layer 2: 查询预警列表"""
    if not month:
        month = action_server._get_latest_month()
    alerts = action_server.alert_engine.get_active_alerts(month, level)
    summary = action_server.alert_engine.get_alert_summary(month)
    return {"status": "success", "month": month, "alerts": alerts, "summary": summary}


@router.get("/alert/summary")
def api_alert_summary(month: str = ""):
    """Layer 2: 预警统计摘要"""
    if not month:
        month = action_server._get_latest_month()
    return action_server.alert_engine.get_alert_summary(month)


@router.post("/alert/{alert_id}/analyze")
def api_alert_analyze(alert_id: int):
    """Layer 3: AI 归因分析（按需触发，消耗 Token）"""
    result = action_server.alert_engine.run_ai_attribution(alert_id)
    return {"status": "success", "alert_id": alert_id, **result}


@router.post("/alert/{alert_id}/read")
def api_alert_mark_read(alert_id: int):
    """标记预警为已读"""
    action_server.alert_engine.mark_read(alert_id)
    return {"status": "success"}


@router.get("/alert/{alert_id}/escalate")
def api_alert_escalate(alert_id: int):
    """Layer 4: 获取分级上报话术"""
    alerts = action_server.alert_engine.get_active_alerts()
    for a in alerts:
        if a["id"] == alert_id:
            msg = action_server.alert_engine.get_escalation_message(a)
            return {"status": "success", "alert_id": alert_id, **msg}
    return {"status": "error", "message": "未找到该预警记录"}
