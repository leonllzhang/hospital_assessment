# app/services/hospital_qa.py
import os
import json
import sqlite3
import random
from typing import Any, Dict
from openai import OpenAI

from neo4j import GraphDatabase
from app.core.config import settings

def init_mock_db(db_path: str) -> sqlite3.Connection:
    """初始化底层的原子数据表 (用于 Ad-Hoc 探索) 和 KPI 事实表 (用于标准大屏)"""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    
    # ======== 1. 创建底层业务流水表 (省略具体数据生成以精简代码) ========
    cursor.execute("DROP TABLE IF EXISTS surgery_records")
    cursor.execute("CREATE TABLE surgery_records (id INTEGER PRIMARY KEY, record_month TEXT, department TEXT, is_weichuang INTEGER, surgery_level INTEGER)")
    
    # ======== 2. 创建并生成国考 KPI 事实表 ========
    cursor.execute("DROP TABLE IF EXISTS kpi_monthly_results")
    cursor.execute("""
        CREATE TABLE kpi_monthly_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_month TEXT,        
            dimension TEXT,           
            metric_code TEXT,         
            metric_name TEXT,         
            metric_value REAL,        
            target_value REAL,        
            unit TEXT                 
        )
    """)
    
    # 抽取几个核心指标生成模拟数据
    kpi_defs = [
        ("医疗质量", "weichuang_ratio", "出院患者微创手术占比", 15.0, 25.0, "%"),
        ("医疗质量", "level4_ratio", "出院患者四级手术比例", 10.0, 20.0, "%"),
        ("运营效率", "personnel_exp_ratio", "人员支出占业务支出比重", 35.0, 45.0, "%"),
        ("运营效率", "asset_liability_ratio", "资产负债率", 40.0, 60.0, "%"),
        ("持续发展", "research_fund_per_100", "每百名卫技人员科研经费", 80.0, 250.0, "万元"),
        ("满意度评价", "op_satisfaction", "门诊患者满意度", 86.0, 96.0, "分")
    ]
    
    mock_data = []
    for month in range(1, 13):
        month_str = f"2026-{month:02d}"
        for dim, code, name, min_val, max_val, unit in kpi_defs:
            val = round(random.uniform(min_val, max_val), 2)
            target = round(max_val * 0.95 if unit in ["%", "分"] else (min_val+max_val)/2, 2)
            mock_data.append((month_str, dim, code, name, val, target, unit))
            
    cursor.executemany("""
        INSERT INTO kpi_monthly_results 
        (record_month, dimension, metric_code, metric_name, metric_value, target_value, unit) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, mock_data)
    conn.commit()
    return conn


class HospitalActionServer:
    """
    无头执行引擎 (Headless Action Server)
    没有 LLM，没有 Prompt，只负责接收确定性的参数并执行安全的数据查询。
    """
    def __init__(self) -> None:
        # 1. 挂载图形数据库
        self.neo4j_driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        # 2. 挂载关系型数据库
        self.sqlite_conn = init_mock_db(settings.sqlite_db_path)
        # 3. 加载标准指标库
        self.metrics_registry = self._load_metrics_registry()

    def _load_metrics_registry(self) -> dict:
        path = os.path.join(os.path.dirname(__file__), 'metrics.json')
        try:
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception: return {}

    # ==========================================================
    # 核心工具 1：标准国考指标查询 (100% 避免幻觉的白名单 SQL)
    # ==========================================================
    def execute_core_kpi(self, metric_code: str, time_period: str = "", department: str = "") -> Dict[str, Any]:
        metric_info = self.metrics_registry.get(metric_code)
        if not metric_info:
            return {"status": "error", "message": f"未知的指标代号: {metric_code}"}

        t_cond = f" AND record_month LIKE '{time_period}%'" if time_period else ""
        d_cond = f" AND department = '{department}'" if department else ""
        
        sql_template = metric_info.get("sql", "SELECT 0 as result, '未配置SQL' as remark")
        sql = sql_template.format(t=t_cond, d=d_cond)

        try:
            cursor = self.sqlite_conn.cursor()
            cursor.execute(sql)
            columns = [column[0] for column in cursor.description]
            data = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            return {
                "status": "success",
                "metric_name": metric_info.get("name"),
                "category": metric_info.get("category"),
                "query_params": {"time": time_period, "dept": department},
                "data": data
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ==========================================================
    # 核心工具 2：动态探索查询 (供 Agent 自由探索底层流水)
    # ==========================================================
    def execute_ad_hoc_sql(self, sql_query: str) -> Dict[str, Any]:
        """危险动作：执行 Agent 传来的裸 SQL，建议后续增加 SELECT 限制"""
        try:
            cursor = self.sqlite_conn.cursor()
            cursor.execute(sql_query)
            columns = [column[0] for column in cursor.description]
            data = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return {"status": "success", "executed_sql": sql_query, "data": data[:50]} # 限制返回条数
        except Exception as e:
            return {"status": "error", "message": f"SQL执行失败: {str(e)}"}

    # ==========================================================
    # 核心工具 3：获取全院驾驶舱大屏数据
    # ==========================================================
    def get_dashboard_data(self) -> Dict[str, Any]:
        try:
            cursor = self.sqlite_conn.cursor()
            cursor.execute("SELECT MAX(record_month) FROM kpi_monthly_results")
            latest_month = cursor.fetchone()[0]

            cursor.execute("SELECT dimension, metric_code, metric_name, metric_value, target_value, unit FROM kpi_monthly_results WHERE record_month = ?", (latest_month,))
            
            dashboard_data = {"医疗质量": [], "运营效率": [], "持续发展": [], "满意度评价": []}
            negative_codes = ["complication_rate", "asset_liability_ratio"]

            for dim, code, name, val, target, unit in cursor.fetchall():
                if dim not in dashboard_data: continue
                is_ok = (val <= target) if code in negative_codes else (val >= target)
                dashboard_data[dim].append({
                    "code": code, "name": name, "value": val, "target": target, 
                    "unit": unit, "is_ok": is_ok, "is_negative": code in negative_codes
                })

            return {"status": "success", "month": latest_month, "dashboard_data": dashboard_data}
        except Exception as e:
            return {"status": "error", "message": str(e)}

action_server = HospitalActionServer()


class LiteAgentController:
    """
    轻量级 Agent 调度器 (模拟 OpenClaw 的行为)
    负责调用 OpenAI (或兼容的基座模型如 Hermes/Qwen)，并执行 Function Calling 闭环。
    """
    def __init__(self, action_server_instance):
        # 挂载后厨 (之前写好的无头引擎)
        self.action_server = action_server_instance
        
        # 挂载主厨 (连接具备 Tool Calling 能力的大模型)
        self.client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )
        self.model_name = settings.model_name

        # 【新增】：设定 Agent 的人设与绝对规则 (System Persona)
        self.system_prompt = """
        你是一位资深、严谨的三级公立医院绩效考核（国考）数据分析专家兼院长助理。
        你的核心任务是协助医院管理者精准调取、分析运营数据。

        【绝对行为准则】：
        1. 必须调用系统提供的 Tools 获取数据，严禁凭空捏造任何医疗、财务数据（零幻觉）。
        2. 如果用户询问与“医院管理、绩效考核、医疗数据”完全无关的问题（如天气、娱乐、写诗等），请礼貌且坚决地拒绝，并引导用户回到医院数据分析的场景。
        3. 回答要有逻辑、分段落，适当使用加粗（Markdown）突出核心指标数值。
        4. 在解释数据时，请站在“医院高质量发展”的角度，给出简短的专业洞察（例如提示某些指标的改善空间）。
        """

        # 定义发给大模型的工具清单
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "query_core_kpi",
                    "description": "查询明确的核心考核指标（如微创占比、总收入、满意度等）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "metric_keyword": {"type": "string", "description": "提取用户提问的指标关键词。"},
                            "time_period": {"type": "string", "description": "月份，如 '2026-03'，若无则传 ''"}
                        },
                        "required": ["metric_keyword"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "query_ad_hoc_sql",
                    "description": "生成SQL查询底层数据。⚠️【极度重要】：必须严格使用 SQLite 语法！绝对不能用 DATE_FORMAT 等 MySQL 函数！",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql_query": {
                                "type": "string", 
                                "description": "必须使用 SQLite 语法。可用表1: surgery_records(id, record_month, department, is_weichuang, surgery_level)。注意：月份字段是 record_month (格式 'YYYY-MM')，没有 surgery_date！假设当前系统时间是 2026年4月，如果用户问'上个月'，则直接使用 '2026-03' 进行字符串 LIKE 或 = 匹配。"
                            }
                        },
                        "required": ["sql_query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "open_dean_dashboard",
                    "description": "当用户要求'查看全院大屏'、'打开院长驾驶舱'时调用。",
                    "parameters": {"type": "object", "properties": {}}
                }
            }
        ]

    def _fuzzy_match_metric(self, keyword: str) -> str:
        if not keyword: 
            return None
            
        best_match = None
        highest_score = 0
        
        # 清洗掉容易干扰的常见虚词
        clean_keyword = keyword.replace("的", "").replace("是多少", "")
        
        for code, info in self.action_server.metrics_registry.items():
            name = info.get("name", "")
            category = info.get("category", "")
            
            # 1. 如果完全包含，直接秒中
            if clean_keyword in name or name in clean_keyword:
                return code
                
            # 2. 字符交集重合度打分
            # 例: keyword="微创占比", name="出院患者微创手术占比"
            # 交集包含 '微','创','占','比' 4个字，得分 4 / 4 = 1.0 (100%匹配)
            match_count = sum(1 for char in clean_keyword if char in name)
            score = match_count / len(clean_keyword) if len(clean_keyword) > 0 else 0
            
            # 如果匹配度超过 60%，且是当前最高分，则记录
            if score > highest_score and score >= 0.6:
                highest_score = score
                best_match = code
                
        return best_match

    def _summarize_results(self, user_query: str, raw_data: dict) -> dict:
        """拿到数据后，再次调用大模型生成解释文本"""
        prompt = f"用户提问: {user_query}\n底层系统返回的真实数据: {json.dumps(raw_data, ensure_ascii=False)}\n请作为专家解读这些数据。"
        
        res = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2 # 极低的温度，保证专业严谨
        )
        return {"text": res.choices[0].message.content, "engine": "agentic_workflow"}

    # 【升级】：在主循环中注入 System Persona
    def run_agent_loop(self, user_query: str) -> dict:
        """核心流转：提问 -> 大模型思考调工具 -> 执行工具 -> 大模型总结"""
        print(f"🧐 Agent 收到问题: {user_query}")
        
        # 组装带护栏的对话历史
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_query}
        ]
        
        # Step 1: 让大模型决定用什么工具
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            tools=self.tools,
            tool_choice="auto",
            temperature=0.1 # 路由决策时温度极低，追求确定性
        )
        
        message = response.choices[0].message
        
        # Step 2: 拦截并执行工具
        if message.tool_calls:
            tool_call = message.tool_calls[0]
            func_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            
            print(f"🛠️ Agent 决定调用: {func_name}, 参数: {args}")

            if func_name == "query_core_kpi":
                code = self._fuzzy_match_metric(args.get("metric_keyword"))
                if not code:
                    return {"text": f"系统未能在国考标准库中找到与“{args.get('metric_keyword')}”高度匹配的指标。建议您使用标准的医学术语，或者询问具体的底层业务数据（如：上个月做了几台手术）。"}
                data = self.action_server.execute_core_kpi(code, args.get("time_period"))
                return self._summarize_results(user_query, data)
                
            elif func_name == "query_ad_hoc_sql":
                data = self.action_server.execute_ad_hoc_sql(args.get("sql_query"))
                # 防御性编程：如果 SQL 执行报错，让 AI 用人话解释错误
                if data.get("status") == "error":
                     return self._summarize_results(user_query, {"error": "SQL执行失败", "details": data.get("message"), "advice": "请提醒用户这可能是一个无法直接通过现有表结构查询的复杂维度。"})
                return self._summarize_results(user_query, data)
                
            elif func_name == "open_dean_dashboard":
                data = self.action_server.get_dashboard_data()
                return {
                    "text": "✅ 院长您好，已为您自动汇总全院56项国考核心指标数据。请在下方【绩效考核驾驶舱】中审阅。图中高亮部分为本月待改进指标，请重点关注。",
                    "dashboard_data": data.get("dashboard_data"),
                    "engine": "dashboard_agent"
                }

        # Step 3: 如果不需要工具（闲聊或超纲问题），系统会基于 System Prompt 兜底回复
        print("💬 Agent 决定直接回复 (触发闲聊或拦截机制)")
        return {"text": message.content, "engine": "direct_chat"}

# 初始化并暴露全局单例
agent_controller = LiteAgentController(action_server)