import json
import re
import os
from openai import OpenAI
from neo4j import GraphDatabase
from dotenv import load_dotenv
# 加载当前目录下的 .env 文件
load_dotenv()

# ================= 配置区 =================
# Neo4j 配置
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# 通义千问 (阿里云 DashScope) API 配置
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# ================= LLM 配置（支持 qwen / deepseek） =================
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "qwen").lower()
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or (
    "https://api.deepseek.com" if LLM_PROVIDER == "deepseek"
    else "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME") or (
    "deepseek-chat" if LLM_PROVIDER == "deepseek"
    else "qwen-plus"
)
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY") if LLM_PROVIDER == "deepseek" else os.getenv("DASHSCOPE_API_KEY")

# ================= 初始化 =================

# 1. 配置 LLM 客户端 (利用兼容 OpenAI 的 endpoint)
client = OpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL
)

# 2. 初始化 Neo4j 驱动
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def extract_elements_with_llm(calculation_text):
    """
    调用通义千问大模型，从自然语言计算公式中提取分子和分母
    """
    prompt = f"""
    你是一个医疗数据分析专家。请阅读以下【三甲医院国考指标】的计算方法说明，从中提取出计算公式的“分子”和“分母”。
    
    要求：
    1. 提取的名称必须精炼（例如：去掉“计算方法：”等冗余字眼）。
    2. 如果该指标不是比率或分数形式（例如只包含单纯的总额或数量计算），请将分子设置为核心计算对象，分母设为 null。

    必须严格输出以下 JSON 格式：
    {{
        "is_ratio": true/false,
        "numerator": "分子的描述",
        "denominator": "分母的描述(如果没有则为null)"
    }}

    计算方法说明内容：
    "{calculation_text}"
    """
    
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个严格的数据抽取助手，只输出符合要求的 JSON 数据。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.01, # 极低温度，避免随机发挥
            response_format={"type": "json_object"} # 强制千问输出 JSON 格式
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # 即使开启了 json_object 模式，做一次正则清理也是好习惯
        result_text = re.sub(r'^```json\s*', '', result_text)
        result_text = re.sub(r'\s*```$', '', result_text)
        
        return json.loads(result_text)
        
    except Exception as e:
        print(f"千问解析失败或 JSON 格式错误: {e}")
        return None

def update_graph_with_elements(tx, indicator_id, extracted_data):
    """
    将大模型提取出的要素作为新节点回写到 Neo4j 中
    """
    cypher = """
    // 找到原始的指标节点
    MATCH (i:Indicator {id: $id})
    
    // 如果有分子，创建分子要素节点，并建立关联
    FOREACH (num IN CASE WHEN $numerator IS NOT NULL THEN [$numerator] ELSE[] END |
        MERGE (n_num:DataElement {name: num})
        ON CREATE SET n_num.type = 'numerator'
        MERGE (i)-[:HAS_NUMERATOR]->(n_num)
    )
    
    // 如果有分母，创建分母要素节点，并建立关联
    FOREACH (den IN CASE WHEN $denominator IS NOT NULL THEN [$denominator] ELSE[] END |
        MERGE (n_den:DataElement {name: den})
        ON CREATE SET n_den.type = 'denominator'
        MERGE (i)-[:HAS_DENOMINATOR]->(n_den)
    )
    """
    tx.run(cypher, 
           id=indicator_id, 
           numerator=extracted_data.get('numerator'),
           denominator=extracted_data.get('denominator'))

def main():
    print("正在连接 Neo4j 数据库获取定量指标...")
    
    with driver.session() as session:
        result = session.run("MATCH (i:Indicator) WHERE i.nature = '定量' RETURN i.id AS id, i.name AS name, i.calculation AS calc")
        indicators = [{"id": record["id"], "name": record["name"], "calc": record["calc"]} for record in result]
    
    print(f"找到 {len(indicators)} 个定量指标。开始调用模型 ({LLM_MODEL_NAME}) 处理...\n")
    
    for item in indicators:
        print(f"正在处理[{item['id']}] {item['name']} ...")
        
        extracted = extract_elements_with_llm(item['calc'])
        
        if extracted:
            print(f"   => 分子: {extracted.get('numerator')}")
            print(f"   => 分母: {extracted.get('denominator')}")
            
            with driver.session() as session:
                session.execute_write(update_graph_with_elements, item['id'], extracted)
        else:
            print(f"[!] 跳过，大模型提取失败。")
            
    print("\n所有指标计算要素提取并入库完成！")
    driver.close()

if __name__ == "__main__":
    main()