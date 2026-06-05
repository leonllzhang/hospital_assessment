import os
import json
import re
import sqlite3
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI
from neo4j import GraphDatabase

# ================= 载入环境变量 =================
# 加载当前目录下的 .env 文件
load_dotenv()

# 从环境变量中读取配置，如果没配 URI 和 USER 则使用默认值
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# ================= LLM 配置（支持 qwen / deepseek） =================
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "qwen").lower()
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or (
    "https://api.deepseek.com" if LLM_PROVIDER == "deepseek"
    else "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
LLM_LLM_MODEL_NAME = os.getenv("LLM_LLM_MODEL_NAME") or (
    "deepseek-chat" if LLM_PROVIDER == "deepseek"
    else "qwen-plus"
)
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY") if LLM_PROVIDER == "deepseek" else os.getenv("DASHSCOPE_API_KEY")

# 安全性检查
required_key_name = "DEEPSEEK_API_KEY" if LLM_PROVIDER == "deepseek" else "DASHSCOPE_API_KEY"
if not LLM_API_KEY or not NEO4J_PASSWORD:
    raise ValueError(f"🚨 启动失败：请确保在 .env 文件中配置了 {required_key_name} 和 NEO4J_PASSWORD！")

# ================= 初始化客户端 =================
client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ================= 1. 模拟底层业务数据库 (SQLite) =================
def init_mock_db(db_path: str) ->sqlite3.Connection :
    """初始化模拟的医院业务明细数据库"""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    
    # 创建表结构
    cursor.execute("DROP TABLE IF EXISTS surgery_records")
    cursor.execute("""
        CREATE TABLE surgery_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_month TEXT,
            department TEXT,
            is_weichuang INTEGER,
            surgery_level INTEGER
        )
    """)
    
    cursor.execute("DROP TABLE IF EXISTS financial_records")
    cursor.execute("""
        CREATE TABLE financial_records (
            record_month TEXT PRIMARY KEY,
            medical_income REAL,
            personnel_expenditure REAL,
            energy_expenditure REAL,
            assets REAL,
            liabilities REAL
        )
    """)

    # 1. 构建复杂的【手术记录】数据 (模拟2025年全年)
    departments = ["骨科", "普外科", "胸外科", "妇产科", "神经外科", "泌尿外科"]
    surgery_data = []
    for month in range(1, 13):
        month_str = f"2025-{month:02d}"
        for dept in departments:
            # 每个科室每月生成 20-50 条手术记录
            num_surgeries = random.randint(20, 50)
            for _ in range(num_surgeries):
                # 模拟不同科室微创占比不同，例如普外科微创率较高
                weichuang_prob = 0.7 if dept == "普外科" else 0.4
                is_weichuang = 1 if random.random() < weichuang_prob else 0
                # 模拟手术等级分布
                level = random.choices([1, 2, 3, 4], weights=[10, 30, 40, 20])[0]
                surgery_data.append((month_str, dept, is_weichuang, level))

    cursor.executemany(
        "INSERT INTO surgery_records (record_month, department, is_weichuang, surgery_level) VALUES (?, ?, ?, ?)",
        surgery_data
    )

    # 2. 构建【财务运营】数据
    financial_data = []
    base_income = 5000000.0
    for month in range(1, 13):
        month_str = f"2025-{month:02d}"
        income = base_income * random.uniform(0.9, 1.2) # 收入波动
        personnel = income * random.uniform(0.35, 0.45) # 人员支出占比 35%-45%
        energy = income * random.uniform(0.02, 0.05)    # 能耗支出占比
        assets = 100000000.0 + (income * 0.1 * month)   # 资产累积
        liabilities = 40000000.0 - (income * 0.02 * month) # 负债递减
        financial_data.append((month_str, income, personnel, energy, assets, liabilities))

    cursor.executemany(
        "INSERT INTO financial_records VALUES (?, ?, ?, ?, ?, ?)",
        financial_data
    )

    conn.commit()
    return conn

# ================= 2. 全局 Schema 约束定义 =================
# Neo4j 图谱结构约束
GRAPH_SCHEMA = """
- Category1, Category2, Indicator(id, name, nature, calculation)
- DataElement(name, type)
关系: (Indicator)-[:HAS_NUMERATOR/HAS_DENOMINATOR]->(DataElement)
"""

# 关系型数据库结构约束 (喂给大模型写 SQL 用)
DB_SCHEMA = """
表名: surgery_records (医院手术明细表)
字段:
- record_month (TEXT): 月份，格式如 '2026-03'
- department (TEXT): 临床科室，如 '骨科', '普外科'
- is_weichuang (INTEGER): 1表示微创手术，0表示非微创
- surgery_level (INTEGER): 手术级别，取值 1 到 4
"""

# ================= 3. 大模型 Agent 核心模块 =================

def intent_router(user_query):
    """意图路由：判断是查图谱(制度逻辑) 还是 查SQL(业务数据)"""
    prompt = f"""
    判断用户的提问类型：
    1. "graph_query": 询问国考指标的定义、考核标准、计算公式、包含哪些要素等【逻辑和制度】问题。
    2. "sql_query": 询问具体的科室、特定时间的指标占比数值、业务量等【需要计算底层明细数据】的问题。

    输出 JSON 格式: {{"intent": "graph_query" 或者是 "sql_query", "reason": "理由"}}
    提问: "{user_query}"
    """
    response = client.chat.completions.create(
        model=LLM_MODEL_NAME, messages=[{"role": "user", "content": prompt}],
        temperature=0.1, response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content.strip())

def text_to_cypher(user_query):
    """【分支 A】转换为 Neo4j 图谱查询语言"""
    prompt = f"根据Schema: {GRAPH_SCHEMA}\n将提问转为Cypher。提问: {user_query}\n只输出Cypher代码本身。"
    res = client.chat.completions.create(model=LLM_MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0)
    return re.sub(r'```(cypher)?|```', '', res.choices[0].message.content).strip()

def text_to_sql(user_query):
    """【分支 B】转换为 SQLite 查询语言"""
    prompt = f"""
    你是一个数据分析师。请根据以下 SQLite 表结构，将用户的提问转为精确的 SQL 查询语句。
    
    {DB_SCHEMA}
    
    注意：
    1. 微创手术占比的计算逻辑是: SUM(is_weichuang) * 1.0 / COUNT(*)
    2. 如果用户没有指定时间，默认查询全局数据。如果有时间，请用 WHERE record_month 过滤。
    3. 只输出 SQL 语句本身，不要带 ```sql 标签，不加任何解释。
    
    用户提问: "{user_query}"
    """
    res = client.chat.completions.create(model=LLM_MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0)
    return re.sub(r'```(sql)?|```', '', res.choices[0].message.content).strip()

def explain_results(user_query, raw_data, engine_type):
    """通用：大模型根据查出的数据，生成最终的自然语言汇报"""
    prompt = f"""
    你是一个三甲医院的数据专家。
    用户提问: "{user_query}"
    通过 {engine_type} 引擎查出的原始数据: {raw_data}
    
    请用专业、自然的语言向院长汇报。如果是百分比数据，请转为易读的格式（如 50.0%）。
    如果查出数据为空，请告知没有找到对应记录。
    """
    res = client.chat.completions.create(model=LLM_MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.3)
    return res.choices[0].message.content.strip()

# ================= 4. 主程序入口 =================
def main():
    print("⏳ 正在初始化医院模拟数据库...")
    sqlite_conn = init_mock_db()
    
    print("=== 欢迎进入三甲医院指标大模型问答系统 ===")
    print("支持的问题类型：")
    print(" 1. 制度查询 (图谱): '微创手术占比怎么算？'")
    print(" 2. 数据查询 (SQL): '2026年3月骨科的微创手术占比是多少？'")
    print("输入 'quit' 退出\n")
    
    while True:
        user_query = input("👨‍⚕️ 院长/医生: ")
        if user_query.lower() in ['quit', 'exit']:
            break
        if not user_query.strip(): continue
            
        print("🤖 [思考中] 判断意图...")
        route = intent_router(user_query)
        intent = route.get('intent')
        print(f"📍 意图: {intent} (理由: {route.get('reason')})")
        
        try:
            if intent == "graph_query":
                # ------- 链路 A: 走 Neo4j 图谱 -------
                cypher = text_to_cypher(user_query)
                print(f"🕸️ [生成 Cypher]: {cypher}")
                with neo4j_driver.session() as session:
                    records = session.run(cypher)
                    data =[dict(record) for record in records]
                answer = explain_results(user_query, data, "知识图谱")
                
            elif intent == "sql_query":
                # ------- 链路 B: 走 SQLite 关系数据库 -------
                sql = text_to_sql(user_query)
                print(f"🗄️[生成 SQL]: {sql}")
                cursor = sqlite_conn.cursor()
                cursor.execute(sql)
                # 获取列名和数据，组合成字典格式供大模型阅读
                columns = [col[0] for col in cursor.description]
                data =[dict(zip(columns, row)) for row in cursor.fetchall()]
                answer = explain_results(user_query, data, "业务数据库")
                
            print(f"\n💡 [系统汇报]:\n{answer}\n")
            print("-" * 50)
            
        except Exception as e:
            print(f"\n❌ [执行出错]: {str(e)}\n" + "-"*50)

if __name__ == "__main__":
    main()