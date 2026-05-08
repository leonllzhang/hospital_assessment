import json
import re
from openai import OpenAI
from neo4j import GraphDatabase

# ================= 配置区 =================
# Neo4j 配置
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "neo4j@1234"

# 大模型 API 配置 (这里以调用兼容 OpenAI 格式的本地 Ollama/vLLM 或 API 为例)
# 如果你用第三方云 API，填入对应的 BASE_URL 和 API_KEY
LLM_BASE_URL = "https://api.openai.com/v1" # 例如: "http://localhost:11434/v1" (Ollama)
LLM_API_KEY = "your_api_key"
MODEL_NAME = "gpt-4o" # 或者 "qwen2.5", "deepseek-chat" 等

# ==========================================

client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def extract_elements_with_llm(calculation_text):
    """
    调用大模型，从自然语言计算公式中提取分子和分母
    """
    prompt = f"""
    你是一个医疗数据分析专家。请阅读以下【三甲医院国考指标】的计算方法说明，从中提取出计算公式的“分子”和“分母”。
    
    要求：
    1. 提取的名称必须精炼（例如：去掉“计算方法：”等冗余字眼）。
    2. 如果该指标不是比率或分数形式（例如只包含单纯的总额或数量计算），请将分子设置为核心计算对象，分母设为null。
    3. 必须严格以 JSON 格式输出，不要包含任何其他说明文字（不要加 ```json 标签）。

    输出 JSON 格式要求：
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
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1, # 保持极低的温度，确保输出的稳定性
        )
        
        # 提取模型返回的文本，并尝试解析为 JSON
        result_text = response.choices[0].message.content.strip()
        # 简单清洗可能的 Markdown 标签
        result_text = re.sub(r'```json|```', '', result_text).strip()
        
        return json.loads(result_text)
    except Exception as e:
        print(f"大模型解析失败或 JSON 格式错误: {e}")
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
    
    # 1. 查出所有需要处理的“定量”指标
    with driver.session() as session:
        result = session.run("MATCH (i:Indicator) WHERE i.nature = '定量' RETURN i.id AS id, i.name AS name, i.calculation AS calc")
        indicators = [{"id": record["id"], "name": record["name"], "calc": record["calc"]} for record in result]
    
    print(f"找到 {len(indicators)} 个需要拆解计算要素的指标。开始调用 LLM 处理...\n")
    
    # 2. 遍历指标，调用大模型进行拆解，并回写图谱
    for item in indicators:
        print(f"正在处理 [{item['id']}] {item['name']} ...")
        
        # 调用大模型提取
        extracted = extract_elements_with_llm(item['calc'])
        
        if extracted:
            print(f"   => 分子: {extracted.get('numerator')}")
            print(f"   => 分母: {extracted.get('denominator')}")
            
            # 回写 Neo4j
            with driver.session() as session:
                session.execute_write(update_graph_with_elements, item['id'], extracted)
        else:
            print(f"   [!] 跳过，大模型提取失败。")
            
    print("\n所有指标计算要素提取并入库完成！")
    driver.close()

if __name__ == "__main__":
    main()