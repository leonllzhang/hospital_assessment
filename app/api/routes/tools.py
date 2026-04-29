# app/api/routes/tools.py
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.services.hospital_qa import action_server

router = APIRouter(prefix="/tools", tags=["agent_tools"])

# --- 请求体定义 ---
class MetricQueryReq(BaseModel):
    metric_code: str
    time_period: Optional[str] = ""
    department: Optional[str] = ""

class SqlQueryReq(BaseModel):
    sql_query: str

# --- 供 Agent 调用的 3 个 API 工具 ---

@router.post("/query_metric", summary="Tool 1: 查询核心考核指标")
def tool_query_metric(req: MetricQueryReq):
    """供大模型调用：传递解析好的指标代号获取精准数据"""
    return action_server.execute_core_kpi(req.metric_code, req.time_period, req.department)

@router.post("/query_sql", summary="Tool 2: 探索底层数据库")
def tool_query_sql(req: SqlQueryReq):
    """供大模型调用：传递大模型自己写的 SQL 获取原始流水"""
    return action_server.execute_ad_hoc_sql(req.sql_query)

@router.post("/get_dashboard", summary="Tool 3: 获取全院大屏")
def tool_get_dashboard():
    """供大模型调用：一键获取 56 项指标的全景数据"""
    return action_server.get_dashboard_data()