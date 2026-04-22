import os
import json
import re
import sqlite3
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

API_KEY = os.getenv("DASHSCOPE_API_KEY")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = "qwen-plus"

# 安全性检查
if not API_KEY or not NEO4J_PASSWORD:
    raise ValueError("🚨 启动失败：请确保在 .env 文件中配置了 DASHSCOPE_API_KEY 和 NEO4J_PASSWORD！")

# ================= 初始化客户端 =================
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ================= 1. 模拟底层业务数据库 (SQLite) =================
def init_mock_db():
    """初始化模拟的医院业务明细数据库"""
    conn = sqlite3.connect(':memory:')  # 使用内存数据库，每次运行重置，方便测试
    cursor = conn.cursor()
    
    # 建表: 模拟手术明细表
    cursor.execute('''
        CREATE TABLE surgery_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_month TEXT,       -- 记录月份 (如 '2026-03')
            department TEXT,         -- 科室名称 (如 '骨科', '普外科')
            is_weichuang INTEGER,    -- 是否微创手术 (1为是，0为否)
            surgery_level INTEGER    -- 手术级别 (1, 2, 3, 4)
        )
    ''')
    
    # 插入一些模拟测试数据
    mock_data =[
        ('2026-03', '骨科', 1, 3), ('2026-03', '骨科', 0, 4), 
        ('2026-03', '骨科', 1, 2), ('2026-03', '骨科', 0, 3), # 骨科微创占比 2/4 = 50%
        ('2026-03', '普外科', 0, 4), ('2026-03', '普外科', 0, 3), 
        ('2026-03', '普外科', 1, 2), ('2026-03', '普外科', 0, 4), # 普外微创占比 1/4 = 25%
        ('2026-02', '骨科', 1, 4) # 干扰数据，测试时间条件
    ]
    cursor.executemany('INSERT INTO surgery_records (record_month, department, is_weichuang, surgery_level) VALUES (?, ?, ?, ?)', mock_data)
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
        model=MODEL_NAME, messages=[{"role": "user", "content": prompt}],
        temperature=0.1, response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content.strip())

def text_to_cypher(user_query):
    """【分支 A】转换为 Neo4j 图谱查询语言"""
    prompt = f"根据Schema: {GRAPH_SCHEMA}\n将提问转为Cypher。提问: {user_query}\n只输出Cypher代码本身。"
    res = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0)
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
    res = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0)
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
    res = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.3)
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