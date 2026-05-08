import json
from neo4j import GraphDatabase

# Neo4j 数据库连接配置 (请根据您的实际环境修改密码)
URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "neo4j@1234"

def load_data(file_path):
    """读取 JSON 数据文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def import_to_neo4j(tx, data):
    """
    使用 Cypher 语句将 JSON 数据批量导入 Neo4j。
    使用 UNWIND 展开数组，使用 MERGE 保证不重复创建。
    """
    cypher_query = """
    UNWIND $data AS row
    
    // 1. 创建或合并 一级指标节点 (Category1)
    MERGE (c1:Category1 {name: row.category_1})
    
    // 2. 创建或合并 二级指标节点 (Category2)
    MERGE (c2:Category2 {name: row.category_2})
    
    // 建立 一级指标 -> 二级指标 的关系
    MERGE (c1)-[:HAS_SUBCATEGORY]->(c2)
    
    // 3. 创建或合并 具体考核指标节点 (Indicator)
    MERGE (i:Indicator {id: row.id})
    SET i.name = row.name,
        i.is_national_monitor = row.is_national_monitor,
        i.nature = row.nature,
        i.calculation = row.calculation
        
    // 建立 二级指标 -> 具体考核指标 的关系
    MERGE (c2)-[:HAS_INDICATOR]->(i)
    
    // 4. 创建或合并 数据来源节点 (DataSource)
    MERGE (ds:DataSource {name: row.source})
    
    // 建立 考核指标 -> 数据来源 的关系
    MERGE (i)-[:SOURCED_FROM]->(ds)
    """
    
    # 执行 Cypher 语句
    result = tx.run(cypher_query, data=data)
    return result.consume()

def main():
    json_file = "hos.json"
    
    try:
        # 读取数据
        print(f"正在读取 {json_file} ...")
        hospital_data = load_data(json_file)
        print(f"成功读取 {len(hospital_data)} 条指标数据。")
        
        # 连接到 Neo4j
        print("正在连接 Neo4j 数据库...")
        driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
        
        # 执行写入操作
        with driver.session() as session:
            summary = session.execute_write(import_to_neo4j, hospital_data)
            print("导入完成！")
            print(f"新增节点数: {summary.counters.nodes_created}")
            print(f"新增关系数: {summary.counters.relationships_created}")
            print(f"更新属性数: {summary.counters.properties_set}")
            
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        if 'driver' in locals():
            driver.close()

if __name__ == "__main__":
    main()