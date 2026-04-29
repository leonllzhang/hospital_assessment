# tests/test_action_server.py
import pytest
from app.services.hospital_qa import action_server

def test_execute_core_kpi_success():
    """测试：标准指标查询是否能正确返回结构化数据"""
    # 传入我们字典里的代号和月份
    result = action_server.execute_core_kpi(metric_code="weichuang_ratio", time_period="2026-03")
    
    assert result["status"] == "success"
    assert "微创" in result["metric_name"]
    # 确保查出了数据行
    assert len(result["data"]) > 0 
    assert "当前值" in result["data"][0]

def test_execute_core_kpi_not_found():
    """测试：查询不存在的指标应返回错误"""
    result = action_server.execute_core_kpi(metric_code="fake_metric_code")
    assert result["status"] == "error"
    assert "未知的指标代号" in result["message"]

def test_execute_ad_hoc_sql_valid():
    """测试：合法的动态探索 SQL"""
    sql = "SELECT COUNT(*) as cnt FROM surgery_records WHERE department='骨科'"
    result = action_server.execute_ad_hoc_sql(sql)
    
    assert result["status"] == "success"
    assert "cnt" in result["data"][0]

def test_execute_ad_hoc_sql_injection_defense():
    """测试：物理防弹衣是否生效（拦截危险 SQL）"""
    sql = "DROP TABLE surgery_records;"
    result = action_server.execute_ad_hoc_sql(sql)
    
    assert result["status"] == "error"
    assert "系统安全策略已拦截" in result["message"]

def test_get_dashboard_data():
    """测试：全院大屏数据是否完整汇聚了四大维度"""
    result = action_server.get_dashboard_data()
    
    assert result["status"] == "success"
    dashboard = result["dashboard_data"]
    
    # 验证四大维度是否存在
    assert "医疗质量" in dashboard
    assert "运营效率" in dashboard
    assert "持续发展" in dashboard
    assert "满意度评价" in dashboard
    
    # 验证总指标数量是否充足 (我们之前配置了56个)
    total_metrics = sum(len(dashboard[dim]) for dim in dashboard)
    assert total_metrics > 50