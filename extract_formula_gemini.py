import json
import re
import google.generativeai as genai
from neo4j import GraphDatabase

# ================= 配置区 =================
# Neo4j 配置
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = ""

# Gemini API 配置
# 请在此处填入您从 Google AI Studio 获取的 API Key
GEMINI_API_KEY = ""

# 推荐使用 gemini-1.5-flash (速度快、成本低) 或 gemini-1.5-pro (推理能力更强)
MODEL_NAME = "gemini-1.5-flash" 

# ================= 初始化 =================

# 1. 配置 Gemini API
genai.configure(api_key=GEMINI_API_KEY)

# 2. 初始化 Gemini 模型实例
# 关键设置：利用 response_mime_type 强制模型只输出合法的 JSON 格式
model = genai.GenerativeModel(
    model_name=MODEL_NAME,
    generation_config={
        "temperature": 0.1, # 保持极低的温度，确保逻辑提取的稳定性
        "response_mime_type": "application/json" # 强制结构化 JSON 输出
    }
)

# 3. 初始化 Neo4j 驱动
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def extract_elements_with_llm(calculation_text):
    """
    调用 Gemini 大模型，从自然语言计算公式中提取分子和分母
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
        # 调用 Gemini 生成内容
        response = model.generate_content(prompt)
        
        # 提取文本并解析
        result_text = response.text.strip()
        
        # 兜底清理（虽然指定了 MIME type，但为了绝对安全，清理可能残留的 markdown 标记）
        result_text = re.sub(r'^```json\s*', '', result_text)
        result_text = re.sub(r'\s*```$', '', result_text)
        
        return json.loads(result_text)
        
    except Exception as e:
        print(f"Gemini 解析失败或 JSON 格式错误: {e}")
        # 打印一下原始返回内容以供排查
        if 'response' in locals() and hasattr(response, 'text'):
            print(f"模型原始返回: {response.text}")
        return None

def update_graph_with_elements(tx, indicator_id, extracted_data):
    """
    将大模型提取出的要素作为新节点回写到 Neo4j 中
    (这里的 Cypher 语句与原来完全一致，保持向下兼容)
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
    
    print(f"找到 {len(indicators)} 个定量指标。开始调用 Gemini 处理...\n")
    
    # 2. 遍历指标，调用 Gemini 进行拆解，并回写图谱
    for item in indicators:
        print(f"正在处理[{item['id']}] {item['name']} ...")
        
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