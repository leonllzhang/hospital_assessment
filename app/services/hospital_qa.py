import json
import re
import sqlite3
from typing import Any

from neo4j import GraphDatabase
from openai import OpenAI

from app.core.config import settings


GRAPH_SCHEMA = (
    "节点: Category1, Category2, Indicator(id, name, nature, calculation), "
    "DataElement(name, type)。关系: "
    "(Indicator)-[:HAS_NUMERATOR/HAS_DENOMINATOR]->(DataElement)"
)

# 扩展数据库 Schema 描述，以便 LLM 生成更精准的 SQL
DB_SCHEMA = (
    "1. 手术记录表 (surgery_records): record_month(月份), department(科室), is_weichuang(微创 1是0否), surgery_level(手术等级 1-4)\n"
    "2. 财务运营表 (financial_records): record_month(月份), medical_income(医疗收入), personnel_expenditure(人员支出), energy_expenditure(能耗支出), assets(总资产), liabilities(总负债)\n"
    "3. 满意度表 (satisfaction_records): record_month(月份), outpatient_score(门诊满意度分), inpatient_score(住院满意度分)"
)


def init_mock_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    cursor = conn.cursor()
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
    mock_data = [
        ("2026-03", "骨科", 1, 3),
        ("2026-03", "骨科", 0, 4),
        ("2026-03", "骨科", 1, 2),
        ("2026-03", "骨科", 0, 3),
        ("2026-03", "普外科", 0, 4),
        ("2026-03", "普外科", 0, 3),
        ("2026-03", "普外科", 1, 2),
        ("2026-03", "普外科", 0, 4),
        ("2026-02", "骨科", 1, 4),
    ]
    cursor.executemany(
        """
        INSERT INTO surgery_records (record_month, department, is_weichuang, surgery_level)
        VALUES (?, ?, ?, ?)
        """,
        mock_data,
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
        # 使用配置文件中的路径初始化文件数据库
        self.sqlite_conn = init_mock_db(settings.sqlite_db_path)

    def intent_router(self, user_query: str) -> str:
        prompt = (
            '判断提问类型：1. "graph_query"(查制度/逻辑) '
            '2. "sql_query"(查数据数值)。输出JSON: '
            '{"intent": "graph_query"或"sql_query"}。'
            f'提问: "{user_query}"'
        )
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content.strip())
        return payload.get("intent", "graph_query")

    def text_to_cypher(self, user_query: str) -> str:
        prompt = (
            f"根据Schema: {GRAPH_SCHEMA}\n"
            f"转为Cypher。提问: {user_query}\n"
            "只输出Cypher本身。"
        )
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return re.sub(
            r"```(cypher)?|```", "", response.choices[0].message.content
        ).strip()

    def text_to_sql(self, user_query: str) -> str:
        prompt = (
            f"根据表结构: {DB_SCHEMA}\n"
            "微创占比为 SUM(is_weichuang)*1.0/COUNT(*)。"
            "无时间默认查全局。"
            f"提问: {user_query}\n"
            "只输出SQL本身。"
        )
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return re.sub(
            r"```(sql)?|```", "", response.choices[0].message.content
        ).strip()

    def explain_and_draw(
        self, user_query: str, raw_data: list[dict[str, Any]], intent: str
    ) -> dict[str, Any]:
        prompt = f"""
        你是一个数据汇报专家。用户提问: "{user_query}"。查出的数据: {raw_data}。
        请严格按照以下 JSON 格式输出：
        {{
            "text": "用专业的人话向院长解释数据结果（支持Markdown格式）。",
            "chart_option": {{}} // 如果是图谱查询(graph_query)或不需要画图请设为 null。若是查具体数据(sql_query)，请生成一个合法的 ECharts option JSON（如柱状对比图、饼图等）。
        }}
        """
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content.strip())

    def _run_graph_query(self, user_query: str) -> dict[str, Any]:
        cypher = self.text_to_cypher(user_query)
        with self.neo4j_driver.session() as session:
            data = [dict(record) for record in session.run(cypher)]
        return self.explain_and_draw(user_query, data, "graph_query")

    def _run_sql_query(self, user_query: str) -> dict[str, Any]:
        sql = self.text_to_sql(user_query)
        cursor = self.sqlite_conn.cursor()
        cursor.execute(sql)
        columns = [column[0] for column in cursor.description]
        data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return self.explain_and_draw(user_query, data, "sql_query")

    def answer(self, user_query: str) -> dict[str, Any]:
        intent = self.intent_router(user_query)
        if intent == "graph_query":
            return self._run_graph_query(user_query)
        return self._run_sql_query(user_query)


qa_service = HospitalQAService()
