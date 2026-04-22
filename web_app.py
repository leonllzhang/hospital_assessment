import os
import json
import re
import sqlite3
from dotenv import load_dotenv
from openai import OpenAI
from neo4j import GraphDatabase
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# ================= 载入环境变量 =================
load_dotenv()
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
API_KEY = os.getenv("DASHSCOPE_API_KEY")

if not API_KEY or not NEO4J_PASSWORD:
    raise ValueError("🚨 请确保 .env 中配置了 DASHSCOPE_API_KEY 和 NEO4J_PASSWORD！")

# ================= 初始化 =================
client = OpenAI(api_key=API_KEY, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL_NAME = "qwen-plus"
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ================= 1. 模拟底层业务数据库 =================
def init_mock_db():
    conn = sqlite3.connect(':memory:', check_same_thread=False) 
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE surgery_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_month TEXT,
            department TEXT,
            is_weichuang INTEGER,
            surgery_level INTEGER
        )
    ''')
    mock_data =[
        ('2026-03', '骨科', 1, 3), ('2026-03', '骨科', 0, 4), 
        ('2026-03', '骨科', 1, 2), ('2026-03', '骨科', 0, 3), 
        ('2026-03', '普外科', 0, 4), ('2026-03', '普外科', 0, 3), 
        ('2026-03', '普外科', 1, 2), ('2026-03', '普外科', 0, 4), 
        ('2026-02', '骨科', 1, 4) 
    ]
    cursor.executemany('INSERT INTO surgery_records (record_month, department, is_weichuang, surgery_level) VALUES (?, ?, ?, ?)', mock_data)
    conn.commit()
    return conn

sqlite_conn = init_mock_db()

# ================= 2. Schema 与大模型方法 =================
GRAPH_SCHEMA = "节点: Category1, Category2, Indicator(id, name, nature, calculation), DataElement(name, type). 关系: (Indicator)-[:HAS_NUMERATOR/HAS_DENOMINATOR]->(DataElement)"
DB_SCHEMA = "表名: surgery_records。字段: record_month(TEXT), department(TEXT), is_weichuang(INTEGER 1是0否), surgery_level(INTEGER)"

def intent_router(user_query):
    prompt = f'判断提问类型：1. "graph_query"(查制度/逻辑) 2. "sql_query"(查数据数值)。输出JSON: {{"intent": "graph_query"或"sql_query"}}。提问: "{user_query}"'
    res = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.1, response_format={"type": "json_object"})
    return json.loads(res.choices[0].message.content.strip()).get("intent", "graph_query")

def text_to_cypher(user_query):
    prompt = f"根据Schema: {GRAPH_SCHEMA}\n转为Cypher。提问: {user_query}\n只输出Cypher本身。"
    res = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0)
    return re.sub(r'```(cypher)?|```', '', res.choices[0].message.content).strip()

def text_to_sql(user_query):
    prompt = f"根据表结构: {DB_SCHEMA}\n微创占比为 SUM(is_weichuang)*1.0/COUNT(*)。无时间默认查全局。提问: {user_query}\n只输出SQL本身。"
    res = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0)
    return re.sub(r'```(sql)?|```', '', res.choices[0].message.content).strip()

def explain_and_draw(user_query, raw_data, intent):
    prompt = f"""
    你是一个数据汇报专家。用户提问: "{user_query}"。查出的数据: {raw_data}。
    请严格按照以下 JSON 格式输出：
    {{
        "text": "用专业的人话向院长解释数据结果（支持Markdown格式）。",
        "chart_option": {{}} // 如果是图谱查询(graph_query)或不需要画图请设为 null。若是查具体数据(sql_query)，请生成一个合法的 ECharts option JSON（如柱状对比图、饼图等）。
    }}
    """
    res = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.1, response_format={"type": "json_object"})
    return json.loads(res.choices[0].message.content.strip())

# ================= 3. FastAPI Web 接口 =================
app = FastAPI()

class ChatRequest(BaseModel):
    query: str

@app.post("/api/chat")
def chat_api(request: ChatRequest):
    user_query = request.query
    intent = intent_router(user_query)
    try:
        if intent == "graph_query":
            cypher = text_to_cypher(user_query)
            with neo4j_driver.session() as session:
                data =[dict(record) for record in session.run(cypher)]
            result = explain_and_draw(user_query, data, intent)
        else:
            sql = text_to_sql(user_query)
            cursor = sqlite_conn.cursor()
            cursor.execute(sql)
            columns =[col[0] for col in cursor.description]
            data =[dict(zip(columns, row)) for row in cursor.fetchall()]
            result = explain_and_draw(user_query, data, intent)
            
        return {"status": "success", "text": result.get("text"), "chart_option": result.get("chart_option")}
    except Exception as e:
        return {"status": "error", "text": f"系统错误: {str(e)}", "chart_option": None}

# ================= 4. 前端 HTML (使用 Vue 3 渲染) =================
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>三甲医院国考大模型 (Vue 3版)</title>
    <!-- 引入 Vue 3, Echarts, Marked -->
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        [v-cloak] { display: none; }
        body { font-family: 'Microsoft YaHei', sans-serif; background: #f0f2f5; margin: 0; padding: 20px; display: flex; justify-content: center; }
        .container { width: 900px; background: white; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); display: flex; flex-direction: column; height: 90vh; }
        .header { background: #1677ff; color: white; padding: 15px 20px; border-radius: 10px 10px 0 0; font-size: 1.2em; font-weight: bold; }
        .chat-box { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 15px; }
        .msg-wrapper { display: flex; flex-direction: column; max-width: 85%; }
        .wrapper-user { align-self: flex-end; align-items: flex-end; }
        .wrapper-ai { align-self: flex-start; align-items: flex-start; width: 100%; }
        .msg { padding: 12px 16px; border-radius: 8px; line-height: 1.6; }
        .msg-user { background: #e6f4ff; color: #000; border-radius: 10px 0 10px 10px; }
        .msg-ai { background: #f6f6f6; color: #000; border-radius: 0 10px 10px 10px; width: 100%; }
        .chart-container { width: 100%; height: 350px; margin-top: 15px; background: #fff; border: 1px solid #e8e8e8; border-radius: 8px; }
        .input-area { padding: 15px; border-top: 1px solid #eee; display: flex; gap: 10px; }
        input { flex: 1; padding: 10px 15px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 1em; outline: none; transition: all 0.3s;}
        input:focus { border-color: #1677ff; box-shadow: 0 0 0 2px rgba(22,119,255,0.2); }
        button { padding: 10px 25px; background: #1677ff; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 1em; transition: background 0.3s; }
        button:hover { background: #0958d9; }
        button:disabled { background: #d9d9d9; cursor: not-allowed; }
        /* Markdown 基础样式 */
        .msg-ai table { border-collapse: collapse; width: 100%; margin-top: 10px; }
        .msg-ai th, .msg-ai td { border: 1px solid #ddd; padding: 8px; }
        .msg-ai th { background-color: #fafafa; }
    </style>
</head>
<body>
    <div id="app" class="container" v-cloak>
        <div class="header">🏥 三甲国考指标大模型大脑 (Vue 3 驱动)</div>
        
        <div class="chat-box" ref="chatBoxRef">
            <!-- 遍历渲染对话消息 -->
            <div v-for="msg in messages" :key="msg.id" 
                 :class="['msg-wrapper', msg.sender === 'user' ? 'wrapper-user' : 'wrapper-ai']">
                
                <!-- 文本渲染框 -->
                <div :class="['msg', msg.sender === 'user' ? 'msg-user' : 'msg-ai']">
                    <!-- 判断是用户还是AI，AI的话渲染解析后的Markdown格式 -->
                    <div v-if="msg.sender === 'user'">{{ msg.text }}</div>
                    <div v-else v-html="msg.htmlText"></div>
                    
                    <!-- 动态渲染图表组件 -->
                    <chart-component 
                        v-if="msg.chartOption" 
                        :option="msg.chartOption" 
                        :chart-id="'chart-' + msg.id">
                    </chart-component>
                </div>
            </div>
        </div>

        <div class="input-area">
            <input type="text" v-model="userInput" @keyup.enter="sendMessage" placeholder="请输入您的问题（查制度定义 或 查具体数据）..." :disabled="isLoading">
            <button @click="sendMessage" :disabled="isLoading">{{ isLoading ? '思考中...' : '发送' }}</button>
        </div>
    </div>

    <script>
        const { createApp, ref, nextTick, watch, onMounted } = Vue;

        // 【子组件】Echarts 图表组件封装
        const ChartComponent = {
            props: ['option', 'chartId'],
            template: `<div :id="chartId" class="chart-container"></div>`,
            mounted() {
                this.initChart();
            },
            methods: {
                initChart() {
                    // 使用原生 DOM 获取，避免 Vue 响应式劫持 Echarts 实例
                    const dom = document.getElementById(this.chartId);
                    if (dom && this.option) {
                        this.chartInstance = echarts.init(dom);
                        this.chartInstance.setOption(this.option);
                        
                        // 监听窗口缩放动态调整图表大小
                        window.addEventListener('resize', () => {
                            this.chartInstance.resize();
                        });
                    }
                }
            }
        };

        // 【主根组件】
        const App = {
            components: {
                ChartComponent
            },
            setup() {
                const userInput = ref('');
                const isLoading = ref(false);
                const chatBoxRef = ref(null);
                
                // 初始欢迎消息
                const welcomeText = "院长您好！您可以问我指标的 **制度逻辑**（如：*微创占比怎么算？*），或者直接查询 **业务数据**（如：*上个月骨科和普外科的手术对比*）。";
                const messages = ref([
                    {
                        id: Date.now(),
                        sender: 'ai',
                        text: welcomeText,
                        htmlText: marked.parse(welcomeText),
                        chartOption: null
                    }
                ]);

                // 滚动到底部的方法
                const scrollToBottom = async () => {
                    await nextTick();
                    if (chatBoxRef.value) {
                        chatBoxRef.value.scrollTop = chatBoxRef.value.scrollHeight;
                    }
                };

                // 发送消息核心逻辑
                const sendMessage = async () => {
                    const text = userInput.value.trim();
                    if (!text || isLoading.value) return;

                    // 1. 添加用户消息
                    messages.value.push({
                        id: Date.now(),
                        sender: 'user',
                        text: text,
                        htmlText: text, // 用户文字不需要 markdown
                        chartOption: null
                    });
                    
                    userInput.value = '';
                    isLoading.value = true;
                    scrollToBottom();

                    // 2. 添加 AI 的 Loading 占位消息
                    const aiMsgId = Date.now() + 1;
                    messages.value.push({
                        id: aiMsgId,
                        sender: 'ai',
                        text: '思考分析中...',
                        htmlText: '<span style="color: #999;">🤖 大脑正在分析意图并生成代码...</span>',
                        chartOption: null
                    });
                    scrollToBottom();

                    // 3. 发送网络请求
                    try {
                        const response = await fetch('/api/chat', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ query: text })
                        });
                        const result = await response.json();

                        // 4. 更新刚才那条占位消息
                        const targetMsg = messages.value.find(m => m.id === aiMsgId);
                        if (targetMsg) {
                            if (result.status === 'success') {
                                targetMsg.text = result.text;
                                targetMsg.htmlText = marked.parse(result.text); // 解析大模型返回的 markdown (加粗/表格等)
                                targetMsg.chartOption = result.chart_option;    // 挂载图表配置
                            } else {
                                targetMsg.htmlText = `<span style="color: red;">❌ ${result.text}</span>`;
                            }
                        }
                    } catch (error) {
                        const targetMsg = messages.value.find(m => m.id === aiMsgId);
                        if (targetMsg) {
                            targetMsg.htmlText = `<span style="color: red;">❌ 网络请求失败，请检查终端报错。</span>`;
                        }
                    } finally {
                        isLoading.value = false;
                        scrollToBottom();
                    }
                };

                return {
                    userInput,
                    isLoading,
                    messages,
                    chatBoxRef,
                    sendMessage
                };
            }
        };

        // 创建并挂载 Vue 应用
        createApp(App).mount('#app');
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def get_index():
    return HTML_CONTENT

# ================= 5. 启动服务 =================
if __name__ == "__main__":
    print("🚀 正在启动 Web 服务...")
    print("👉 请在浏览器中打开: http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")