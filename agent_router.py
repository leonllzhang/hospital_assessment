import json
import os
import re
from openai import OpenAI
from dotenv import load_dotenv
from neo4j import GraphDatabase

# 加载当前目录下的 .env 文件
load_dotenv()
# ================= 配置区 =================
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

# ================= 初始化 =================
client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# 定义我们刚刚建好的图谱的 Schema (Schema 注入，防止大模型乱编 Cypher)
GRAPH_SCHEMA = """
节点类型及属性:
- Category1 (一级指标): name
- Category2 (二级指标): name
- Indicator (考核指标): id, name, is_national_monitor, nature, calculation
- DataSource (数据来源): name
- DataElement (计算要素): name, type ('numerator' 或 'denominator')

关系类型:
- (:Category1)-[:HAS_SUBCATEGORY]->(:Category2)
- (:Category2)-[:HAS_INDICATOR]->(:Indicator)
- (:Indicator)-[:SOURCED_FROM]->(:DataSource)
- (:Indicator)-[:HAS_NUMERATOR]->(:DataElement)
- (:Indicator)-[:HAS_DENOMINATOR]->(:DataElement)
"""

def intent_router(user_query):
    """
    智能体路由模块：识别用户意图
    """
    prompt = f"""
    你是一个三甲医院的智能数据助手大脑。用户的提问有两种类型：
    1. "graph_query" (图谱/逻辑查询): 用户在询问国考指标的定义、考核标准、计算公式、包含哪些要素、由哪个系统出数据等【制度和结构性】问题。
    2. "sql_query" (数据/数值查询): 用户在询问某个科室、某个时间段具体的指标得分、占比数值、医疗业务量等【需要计算真实底层明细数据】的问题。

    请分析用户的提问，并严格以 JSON 格式输出路由结果：
    {{
        "intent": "graph_query" 或 "sql_query",
        "reason": "你的判断理由"
    }}
    
    用户提问: "{user_query}"
    """
    response = client.chat.completions.create(
        model=LLM_MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"}
    )
    result = response.choices[0].message.content.strip()
    return json.loads(result)

def text_to_cypher(user_query):
    """
    将自然语言转化为 Cypher 查询语句
    """
    prompt = f"""
    你是一个熟练的 Neo4j 数据库专家。请根据以下图谱的 Schema，将用户的自然语言提问转化为准确的 Cypher 查询语句。
    
    图谱 Schema:
    {GRAPH_SCHEMA}
    
    要求：
    1. 只输出 Cypher 语句本身，不要带 ```cypher 标签，不要有任何其他解释文字。
    2. 使用模糊匹配时，请使用 CONTAINS 语法。例如: i.name CONTAINS '微创'
    3. 查询时尽量返回节点和关系的具体属性，而不是返回整个节点对象，方便后续大模型阅读。
    
    用户提问: "{user_query}"
    """
    response = client.chat.completions.create(
        model=LLM_MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    cypher_code = response.choices[0].message.content.strip()
    cypher_code = re.sub(r'^```cypher\s*', '', cypher_code, flags=re.IGNORECASE)
    cypher_code = re.sub(r'\s*```$', '', cypher_code).strip()
    return cypher_code

def execute_cypher_and_generate_answer(user_query, cypher_query):
    """
    执行 Cypher 并在获取数据后用大模型生成人性化回答
    """
    print(f"\n[执行 Cypher] -> {cypher_query}")
    try:
        with driver.session() as session:
            result = session.run(cypher_query)
            # 将查询结果转换为文本格式
            data_str = str([record.data() for record in result])
    except Exception as e:
        data_str = f"数据库查询执行失败: {str(e)}"
        print(data_str)

    # 最后一步：让大模型根据查出的数据回答用户
    prompt = f"""
    你是一个三甲医院的绩效解读专家。
    用户提问："{user_query}"
    这是从知识图谱中查出的底层数据结果：
    {data_str}
    
    请结合上述数据，用专业、清晰、自然的人类语言回答用户的问题。如果查出的数据为空，请如实告知。
    """
    response = client.chat.completions.create(
        model=LLM_MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4
    )
    return response.choices[0].message.content.strip()

def main():
    print("=== 欢迎使用三甲医院国考指标大模型大脑 ===")
    print("输入 'quit' 或 'exit' 退出\n")
    
    while True:
        user_query = input("院长/医生您好，请问有什么可以帮您：")
        if user_query.lower() in ['quit', 'exit']:
            break
        if not user_query.strip():
            continue
            
        print("---")
        print("🤖 [大脑思考中] 正在分析您的提问意图...")
        
        # 1. 意图路由
        route_result = intent_router(user_query)
        intent = route_result.get('intent')
        reason = route_result.get('reason')
        print(f"📍 [意图识别] -> {intent} (理由: {reason})")
        
        # 2. 根据意图执行分支
        if intent == "graph_query":
            print("🗺️  [图谱引擎] 正在将问题转化为图数据库查询...")
            # 2.1 翻译为 Cypher
            cypher = text_to_cypher(user_query)
            
            # 2.2 执行并回答
            answer = execute_cypher_and_generate_answer(user_query, cypher)
            print(f"\n💡 [系统回答]:\n{answer}\n")
            
        elif intent == "sql_query":
            print("\n📊 [SQL引擎] 您正在查询具体的业务数值。")
            print("⚠️ 系统提示：底层业务明细数据库（如 ClickHouse/MySQL）尚未接入，当前 Text2SQL 模块待开发！\n")
            
        else:
            print(f"\n❓ [系统错误] 无法识别的意图：{intent}\n")
            
        print("="*50)

if __name__ == "__main__":
    main()