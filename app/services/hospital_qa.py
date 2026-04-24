import json
import re
import sqlite3
import random
from typing import Any

from neo4j import GraphDatabase
from openai import OpenAI

from app.core.config import settings

GRAPH_SCHEMA = (
    "节点: Category1, Category2, Indicator(id, name, nature, calculation), "
    "DataElement(name, type)。关系: "
    "(Indicator)-[:HAS_NUMERATOR/HAS_DENOMINATOR]->(DataElement)"
)

DB_SCHEMA = (
    "1. 手术记录表 (surgery_records): record_month(月份), department(科室), is_weichuang(微创 1是0否), surgery_level(手术等级 1-4)\n"
    "2. 财务运营表 (financial_records): record_month(月份), medical_income(医疗收入), personnel_expenditure(人员支出), energy_expenditure(能耗支出), assets(总资产), liabilities(总负债)\n"
    "3. 满意度表 (satisfaction_records): record_month(月份), outpatient_score(门诊满意度分), inpatient_score(住院满意度分)"
)

def init_mock_db(db_path: str) -> sqlite3.Connection:
    # 真正使用传入的 db_path，实现持久化存储
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    
    # 初始化表结构
    cursor.execute("DROP TABLE IF EXISTS surgery_records")
    cursor.execute(
        """
        CREATE TABLE surgery_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_month TEXT,
            department TEXT,
            is_weichuang INTEGER,
            surgery_level INTEGER
        )
        """
    )
    
    cursor.execute("DROP TABLE IF EXISTS financial_records")
    cursor.execute(
        """
        CREATE TABLE financial_records (
            record_month TEXT PRIMARY KEY,
            medical_income REAL,
            personnel_expenditure REAL,
            energy_expenditure REAL,
            assets REAL,
            liabilities REAL
        )
        """
    )
    
    # 生成复杂模拟数据（代替原先硬编码的几条数据）
    # 1. 模拟手术数据
    departments = ["骨科", "普外科", "胸外科", "妇产科", "神经外科", "泌尿外科"]
    surgery_data = []
    for month in range(1, 13):
        month_str = f"2026-{month:02d}"
        for dept in departments:
            num_surgeries = random.randint(20, 50)
            for _ in range(num_surgeries):
                weichuang_prob = 0.7 if dept == "普外科" else 0.4
                is_weichuang = 1 if random.random() < weichuang_prob else 0
                level = random.choices([1, 2, 3, 4], weights=[10, 30, 40, 20])[0]
                surgery_data.append((month_str, dept, is_weichuang, level))

    cursor.executemany(
        "INSERT INTO surgery_records (record_month, department, is_weichuang, surgery_level) VALUES (?, ?, ?, ?)",
        surgery_data
    )

    # 2. 模拟财务数据
    financial_data = []
    base_income = 5000000.0
    for month in range(1, 13):
        month_str = f"2026-{month:02d}"
        income = base_income * random.uniform(0.9, 1.2)
        personnel = income * random.uniform(0.35, 0.45)
        energy = income * random.uniform(0.02, 0.05)
        assets = 100000000.0 + (income * 0.1 * month)
        liabilities = 40000000.0 - (income * 0.02 * month)
        financial_data.append((month_str, income, personnel, energy, assets, liabilities))

    cursor.executemany(
        "INSERT INTO financial_records VALUES (?, ?, ?, ?, ?, ?)",
        financial_data
    )

    conn.commit()
    return conn


class HospitalQAService:
    def __init__(self) -> None:
        missing = settings.missing_required_values
        if missing:
            missing_str = ", ".join(missing)
            raise ValueError(f"启动失败，请在 .env 中配置: {missing_str}")

        self.client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )
        self.model_name = settings.model_name
        self.neo4j_driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        self.sqlite_conn = init_mock_db(settings.sqlite_db_path)

    def intent_router(self, user_query: str) -> str:
        # [修改]：兼顾 Few-shot 示例和强制 JSON 输出的终极版 Prompt
        prompt = f"""
        你是一个专业的三级公立医院考核指标问答系统的意图识别路由。
        请根据用户的问题，将其精准分类到以下三个类别之一。
        必须严格输出合法的 JSON 格式，例如：{{"intent": "core_kpi"}}。

        【类别定义与示例】：
        1. "graph_query": 查制度、逻辑、概念定义、计算公式等文本知识（知识图谱）
           - 例：“什么是多学科诊疗？”、“日间手术的定义是什么？”

        2. "core_kpi": 查明确的核心考核指标数值（标准语义层/MDL）
           - 例：“上个月微创手术占比是多少？”、“一季度骨科的四级手术量是多少？”、“去年总收入情况？”

        3. "sql_query": 复杂的、临时的交叉数据探索，非核心考核指标（Text-to-SQL）
           - 例：“昨天做手术的患者里，年龄最大的是多少？”、“普外科主任上周做了几台手术？”

        用户问题："{user_query}"
        """
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        try:
            payload = json.loads(response.choices[0].message.content.strip())
            intent = payload.get("intent", "graph_query")
            # 容错处理：如果不在这三个约定类别里，默认走到动态 SQL 进行探索
            if intent not in ["graph_query", "core_kpi", "sql_query"]:
                return "sql_query"
            return intent
        except Exception:
            return "sql_query"

    def text_to_cypher(self, user_query: str) -> str:
        prompt = f"根据Schema: {GRAPH_SCHEMA}\n转为Cypher。提问: {user_query}\n只输出Cypher本身。"
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return re.sub(r"```(cypher)?|```", "", response.choices[0].message.content).strip()

    def text_to_sql(self, user_query: str) -> str:
        prompt = f"根据表结构: {DB_SCHEMA}\n无时间默认查全局。提问: {user_query}\n只输出SQL本身。"
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return re.sub(r"```(sql)?|```", "", response.choices[0].message.content).strip()

    # [新增]：提取 MDL JSON
    def text_to_mdl(self, user_query: str) -> dict[str, Any]:
        prompt = (
            '将用户的提问转化为JSON结构查询协议(MDL)。\n'
            '支持的指标 metric_code:\n'
            '- "weichuang_ratio" (微创手术占比)\n'
            '- "level4_surgery_vol" (四级手术量)\n'
            '- "total_income" (医疗总收入)\n'
            '输出JSON格式:\n'
            '{\n'
            '  "metric_code": "...",\n'
            '  "time_period": "2026-03", // 提取年月，若无则为空字符串\n'
            '  "department": "骨科" // 提取科室，若无则为空字符串\n'
            '}\n'
            f'提问: {user_query}'
        )
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content.strip())

    def explain_and_draw(
        self, user_query: str, raw_data: Any, intent: str
    ) -> dict[str, Any]:
        prompt = f"""
        你是一个数据汇报专家。用户提问: "{user_query}"。查出的数据: {raw_data}。
        请严格按照以下 JSON 格式输出：
        {{
            "text": "用专业的人话向院长解释数据结果（支持Markdown格式）。",
            "chart_option": {{}} // 如果是图谱查询或不需画图设为 null。若是数值查询，请尝试生成合法的 ECharts option JSON。
        }}
        """
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        try:
            result = json.loads(response.choices[0].message.content.strip())
        except Exception:
            result = {"text": "解析回答失败", "chart_option": None}
        
        # [修改]：将 intent (引擎标识) 一起返回出去，供前端 UI 区分展示
        result["engine"] = intent
        return result

    def _run_graph_query(self, user_query: str) -> dict[str, Any]:
        cypher = self.text_to_cypher(user_query)
        try:
            with self.neo4j_driver.session() as session:
                data = [dict(record) for record in session.run(cypher)]
            return self.explain_and_draw(user_query, data, "graph_query")
        except Exception as e:
            return self.explain_and_draw(user_query, f"图谱查询失败: {e}", "graph_query")

    def _run_sql_query(self, user_query: str) -> dict[str, Any]:
        sql = self.text_to_sql(user_query)
        try:
            cursor = self.sqlite_conn.cursor()
            cursor.execute(sql)
            columns = [column[0] for column in cursor.description]
            data = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return self.explain_and_draw(user_query, data, "sql_query")
        except Exception as e:
            return self.explain_and_draw(user_query, f"SQL执行失败: {e}\nSQL为: {sql}", "sql_query")

    # [新增]：执行安全准确的 MDL 白名单模板
    def _run_mdl_query(self, user_query: str) -> dict[str, Any]:
        mdl = self.text_to_mdl(user_query)
        metric_code = mdl.get("metric_code")
        time_period = mdl.get("time_period", "")
        department = mdl.get("department", "")

        # 核心指标白名单 SQL 模板
        METRIC_SQL = {
            "weichuang_ratio": "SELECT COUNT(CASE WHEN is_weichuang = 1 THEN 1 END)*100.0/NULLIF(COUNT(*), 0) as result, '微创占比(%)' as indicator FROM surgery_records WHERE 1=1 {t} {d}",
            "level4_surgery_vol": "SELECT COUNT(*) as result, '四级手术量(台)' as indicator FROM surgery_records WHERE surgery_level = 4 {t} {d}",
            "total_income": "SELECT SUM(medical_income) as result, '医疗总收入(元)' as indicator FROM financial_records WHERE 1=1 {t}"
        }

        if metric_code not in METRIC_SQL:
             return self.explain_and_draw(user_query, "抱歉，该指标暂未纳入核心考核指标库。", "core_kpi")

        t_cond = f" AND record_month LIKE '{time_period}%'" if time_period else ""
        d_cond = f" AND department = '{department}'" if department else ""
        
        sql = METRIC_SQL[metric_code].format(t=t_cond, d=d_cond)

        try:
            cursor = self.sqlite_conn.cursor()
            cursor.execute(sql)
            columns = [column[0] for column in cursor.description]
            data = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # 丰富传给解释器的上下文
            context_data = {
                "查询的指标": metric_code,
                "解析的过滤条件": mdl,
                "数据库结果": data
            }
            return self.explain_and_draw(user_query, context_data, "core_kpi")
        except Exception as e:
            return self.explain_and_draw(user_query, f"MDL核心指标执行失败: {e}", "core_kpi")

    def answer(self, user_query: str) -> dict[str, Any]:
        intent = self.intent_router(user_query)
        if intent == "graph_query":
            return self._run_graph_query(user_query)
        elif intent == "core_kpi":
            return self._run_mdl_query(user_query)
        else:
            return self._run_sql_query(user_query)

qa_service = HospitalQAService()