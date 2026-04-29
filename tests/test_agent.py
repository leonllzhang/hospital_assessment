# tests/test_agent.py
import pytest
from app.services.hospital_qa import agent_controller

# ---------------------------------------------------------
# 测试一：模糊匹配器（极其重要的本地逻辑，不耗 Token）
# ---------------------------------------------------------
@pytest.mark.parametrize("user_keyword, expected_code", [
    ("微创占比", "weichuang_ratio"),
    ("四级手术", "level4_ratio"),
    ("资产负债率", "asset_liability_ratio"),
    ("门诊满意度", "op_satisfaction"),
    ("不存在的离谱指标", None)
])
def test_fuzzy_match_metric(user_keyword, expected_code):
    """验证模糊匹配算法能否从口语化词汇精准映射到标准代号"""
    matched_code = agent_controller._fuzzy_match_metric(user_keyword)
    assert matched_code == expected_code

# ---------------------------------------------------------
# 测试二：Agent 路由决策与工作流执行 (真实请求大模型)
# ---------------------------------------------------------
# 使用 pytest.mark.parametrize 批量测试不同的用户意图
@pytest.mark.parametrize("query, expected_engine_or_text", [
    ("2026年3月份出院患者微创手术占比是多少？", "agentic_workflow"),  # 预期走核心指标查询
    ("骨科上个月一共做了几台手术？", "agentic_workflow"),           # 预期走SQL探索
    ("帮我打开院长驾驶舱", "dashboard_agent"),                  # 预期触发布局拦截，直接出大屏
    ("今天北京天气怎么样？", "direct_chat")                      # 预期触发系统护栏，拒绝回答
])
def test_agent_loop_integration(query, expected_engine_or_text):
    """
    端到端验证 Agent 的流转。
    注意：此测试会发起真实的网络请求，消耗微量 Token。
    """
    result = agent_controller.run_agent_loop(query)
    
    # 1. 验证返回的 engine 标识是否符合预期
    assert result.get("engine") == expected_engine_or_text
    
    # 2. 验证护栏防御：如果是问天气，大模型应该礼貌拒绝，不调任何工具
    if expected_engine_or_text == "direct_chat":
        text = result.get("text", "")
        # 验证回答中包含拒绝的意味（根据您的 system_prompt 定制）
        assert "医院" in text or "绩效" in text or "数据" in text