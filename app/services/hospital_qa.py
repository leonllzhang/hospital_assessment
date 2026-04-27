# app/services/hospital_qa.py

import os
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

def init_kpi_mock_db(db_path: str = "hospital_data.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    
    # 创建国考指标月度事实表
    cursor.execute("DROP TABLE IF EXISTS kpi_monthly_results")
    cursor.execute("""
        CREATE TABLE kpi_monthly_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_month TEXT,        -- 月份 (如 2026-03)
            dimension TEXT,           -- 四大维度 (医疗质量, 运营效率, 持续发展, 满意度评价)
            metric_code TEXT,         -- 指标代码
            metric_name TEXT,         -- 指标名称
            metric_value REAL,        -- 实际数值
            target_value REAL,        -- 考核目标值/国家均值
            unit TEXT                 -- 单位 (%, 分, 元, 次等)
        )
    """)
    
    # ==========================================
    # 三级公立医院绩效考核完整 56 项指标配置字典
    # 格式: (维度, 代码, 名称, 模拟最小值, 模拟最大值, 单位)
    # ==========================================
    kpi_definitions = [
        # ------------------------------------
        # 一、 医疗质量 (24项)
        # ------------------------------------
        ("医疗质量", "outpatient_inpatient_ratio", "门诊人次数与出院人次数比", 1.5, 3.5, "比值"),
        ("医疗质量", "downward_transfer_vol", "下转患者人次数", 1000, 5000, "人次"),
        ("医疗质量", "day_surgery_ratio", "日间手术占择期手术比例", 15.0, 25.0, "%"),
        ("医疗质量", "surgery_patient_ratio", "出院患者手术占比", 25.0, 40.0, "%"),
        ("医疗质量", "weichuang_ratio", "出院患者微创手术占比", 15.0, 25.0, "%"),
        ("医疗质量", "level4_ratio", "出院患者四级手术比例", 10.0, 20.0, "%"),
        ("医疗质量", "cmix", "病例组合指数(CMI)", 1.05, 1.35, "指数"),
        ("医疗质量", "complication_rate", "手术患者并发症发生率", 0.2, 0.8, "%"),
        ("医疗质量", "type1_incision_infection_rate", "I类切口手术部位感染率", 0.05, 0.3, "%"),
        ("医疗质量", "single_disease_qc_rate", "单病种质量控制合格率", 85.0, 98.0, "%"),
        ("医疗质量", "low_risk_mortality", "低风险组病例死亡率", 0.01, 0.05, "%"),
        ("医疗质量", "ddds", "抗菌药物使用强度(DDDs)", 30.0, 39.0, "DDDs"),
        ("医疗质量", "op_essential_drug_ratio", "门诊患者基本药物处方占比", 35.0, 50.0, "%"),
        ("医疗质量", "ip_essential_drug_ratio", "住院患者基本药物使用率", 65.0, 85.0, "%"),
        ("医疗质量", "blood_culture_rate", "抗菌药物治疗前血培养送检率", 40.0, 60.0, "%"),
        ("医疗质量", "emr_level", "电子病历应用功能水平分级", 4.0, 6.0, "级"),
        ("医疗质量", "lab_qc_rate", "室间质评项目合格率", 92.0, 99.0, "%"),
        ("医疗质量", "nursing_staff_ratio", "医护比", 1.1, 1.4, "比值"),
        ("医疗质量", "bed_nurse_ratio", "床护比", 0.45, 0.6, "比值"),
        ("医疗质量", "high_value_consumables_ratio", "重点监控高值耗材收入占比", 10.0, 25.0, "%"),
        ("医疗质量", "op_appointment_rate", "门诊患者预约诊疗率", 50.0, 80.0, "%"),
        ("医疗质量", "op_appointment_precision", "门诊预约后平均等待时间", 15.0, 35.0, "分钟"),
        ("医疗质量", "critical_rescue_success_rate", "急危重症抢救成功率", 90.0, 98.0, "%"),
        ("医疗质量", "clinical_pathway_rate", "临床路径管理比例", 30.0, 60.0, "%"),

        # ------------------------------------
        # 二、 运营效率 (19项)
        # ------------------------------------
        ("运营效率", "medical_service_income_ratio", "医疗服务收入占医疗收入比例", 28.0, 38.0, "%"),
        ("运营效率", "personnel_exp_ratio", "人员支出占业务支出比重", 35.0, 45.0, "%"),
        ("运营效率", "salary_income_ratio", "薪酬性收入占比", 30.0, 40.0, "%"),
        ("运营效率", "op_fee_growth", "门诊次均费用增幅", -3.0, 5.0, "%"),
        ("运营效率", "op_drug_fee_growth", "门诊次均药品费用增幅", -8.0, 2.0, "%"),
        ("运营效率", "ip_fee_growth", "住院次均费用增幅", -2.0, 4.0, "%"),
        ("运营效率", "ip_drug_fee_growth", "住院次均药品费用增幅", -10.0, 1.0, "%"),
        ("运营效率", "drug_income_ratio", "医疗收入中药品收入占比(药占比)", 20.0, 30.0, "%"),
        ("运营效率", "consumables_income_ratio", "耗材收入占比", 12.0, 18.0, "%"),
        ("运营效率", "test_income_ratio", "检查化验收入占比", 15.0, 25.0, "%"),
        ("运营效率", "asset_liability_ratio", "资产负债率", 35.0, 55.0, "%"),
        ("运营效率", "current_ratio", "流动比率", 1.2, 1.8, "比值"),
        ("运营效率", "quick_ratio", "速动比率", 0.9, 1.5, "比值"),
        ("运营效率", "inventory_turnover", "医疗库存物资周转率", 12.0, 24.0, "次"),
        ("运营效率", "bed_turnover_rate", "病床周转次数", 35.0, 45.0, "次"),
        ("运营效率", "bed_utilization_rate", "病床使用率", 88.0, 105.0, "%"),
        ("运营效率", "avg_length_of_stay", "平均住院日", 6.5, 8.5, "天"),
        ("运营效率", "fixed_asset_turnover", "固定资产总额周转率", 1.5, 3.0, "次"),
        ("运营效率", "energy_exp_ratio", "万元收入能耗支出", 120.0, 250.0, "元"),

        # ------------------------------------
        # 三、 持续发展 (10项)
        # ------------------------------------
        ("持续发展", "talent_training_ratio", "麻醉/儿科/重症/病理/中医医师占比", 4.0, 8.0, "%"),
        ("持续发展", "teacher_student_ratio", "医教比", 0.1, 0.25, "比值"),
        ("持续发展", "teaching_achievements", "医院承担教学任务情况得分", 85.0, 100.0, "分"),
        ("持续发展", "continuing_edu_pass_rate", "继续医学教育合格率", 95.0, 100.0, "%"),
        ("持续发展", "research_fund_per_100", "每百名卫技人员科研经费", 80.0, 250.0, "万元"),
        ("持续发展", "research_output_per_100", "每百名卫技人员科研成果转化金额", 5.0, 50.0, "万元"),
        ("持续发展", "paper_citation_impact", "高质量论文影响因子总量", 10.0, 50.0, "分"),
        ("持续发展", "talent_structure_ratio", "高级职称人员比例", 12.0, 25.0, "%"),
        ("持续发展", "trainee_pass_rate", "住院医师规范化培训结业通过率", 85.0, 98.0, "%"),
        ("持续发展", "credit_evaluation", "公共信用综合评价等级得分", 90.0, 100.0, "分"),

        # ------------------------------------
        # 四、 满意度评价 (3项)
        # ------------------------------------
        ("满意度评价", "op_satisfaction", "门诊患者满意度", 86.0, 96.0, "分"),
        ("满意度评价", "ip_satisfaction", "住院患者满意度", 89.0, 98.0, "分"),
        ("满意度评价", "staff_satisfaction", "医务人员满意度", 78.0, 92.0, "分"),
    ]

    mock_data = []
    # 模拟 2025年 1-12 月 及 2026年 1-4 月 的历史数据
    years_months = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 5)]
    
    for month_str in years_months:
        # 提取月份对应的数字，用于模拟季节性波动
        month_int = int(month_str.split('-')[1])
        
        for dim, code, name, min_val, max_val, unit in kpi_definitions:
            
            # 1. 加入季节性和趋势波动逻辑
            # 年底指标通常更好，年初稍差
            season_factor = 1.0 + (month_int - 6) * 0.005 
            
            val = random.uniform(min_val, max_val) * season_factor
            
            # 部分指标属于“越低越好” (负向指标)
            negative_indicators = [
                "complication_rate", "type1_incision_infection_rate", "low_risk_mortality", 
                "ddds", "op_fee_growth", "op_drug_fee_growth", "ip_fee_growth", "ip_drug_fee_growth",
                "drug_income_ratio", "asset_liability_ratio", "avg_length_of_stay", "energy_exp_ratio",
                "op_appointment_precision"
            ]
            
            # 2. 生成目标值 (模拟国家满分标杆值或均值)
            if code in negative_indicators:
                target = min_val * 1.1 # 负向指标，目标值设在低位
            elif unit in ["%", "分", "比值", "指数", "级"]:
                target = max_val * 0.95 # 正向指标，目标设在高位
            else:
                target = (min_val + max_val) / 2
                
            # 特殊修正：等级如果是分级，需要取整
            if unit == "级":
                val = round(val)
                target = round(target)
            else:
                val = round(val, 2)
                target = round(target, 2)
                
            mock_data.append((month_str, dim, code, name, val, target, unit))
            
    cursor.executemany("""
        INSERT INTO kpi_monthly_results 
        (record_month, dimension, metric_code, metric_name, metric_value, target_value, unit) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, mock_data)
    
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
        self.sqlite_conn = init_kpi_mock_db(settings.sqlite_db_path)
        
        # [核心重构点]：系统启动时，从同目录下的 metrics.json 加载指标字典
        self.metrics_registry = self._load_metrics_registry()

    def _load_metrics_registry(self) -> dict:
        """从外部 JSON 文件动态加载三级公立医院考核指标体系库"""
        metrics_file_path = os.path.join(os.path.dirname(__file__), 'metrics.json')
        try:
            with open(metrics_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 加载指标体系配置文件失败: {e}，将使用空指标库。")
            return {}

    def intent_router(self, user_query: str) -> str:
        """四分类路由：图谱知识、核心指标(MDL)、临时探索(SQL)、驾驶舱(Dashboard)"""
        prompt = f"""
        你是一个专业的三级公立医院考核指标问答系统的意图识别路由。
        请根据用户的问题，将其精准分类到以下四个类别之一。
        必须严格输出合法的 JSON 格式，例如：{{"intent": "core_kpi"}}。

        【类别定义与示例】：
        1. "graph_query": 查制度、逻辑、概念定义、计算公式等文本知识（知识图谱）
           - 例：“什么是多学科诊疗？”、“日间手术的定义是什么？”

        2. "core_kpi": 查明确的核心考核指标数值（标准语义层/MDL）
           - 例：“上个月微创手术占比是多少？”、“去年总收入情况？”、“门诊满意度是多少？”、“人员支出占比”

        3. "sql_query": 复杂的、临时的交叉数据探索，非核心考核指标（Text-to-SQL）
           - 例：“昨天做手术的患者里，年龄最大的是多少？”、“普外科主任上周做了几台手术？”

        4. "dashboard": 用户要求查看全院大屏、驾驶舱、全盘总览、考核总分等宏观全景。
           - 例：“打开院长驾驶舱”、“看看上个月的全院考核大屏”

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
            # 容错：如果大模型生成了预期外的词，默认切入动态 SQL 探索
            if intent not in ["graph_query", "core_kpi", "sql_query", "dashboard"]:
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

    def text_to_mdl(self, user_query: str) -> dict[str, Any]:
        """将自然语言转换为 MDL，动态提供可选指标列表"""
        
        # 将 metrics.json 中所有的指标代号和名称拼接成提示词
        metric_options = "\n".join([f'- "{code}": {info.get("name", "未知指标")}' for code, info in self.metrics_registry.items()])
        
        prompt = (
            '你是一个数据分析助手，请将用户的提问转化为JSON结构查询协议(MDL)。\n'
            '【当前系统已注册的标准核心指标列表】:\n'
            f'{metric_options}\n\n'
            '请根据用户的提问，在上述列表中选择最匹配的指标 code。\n'
            '输出严格的 JSON 格式:\n'
            '{\n'
            '  "metric_code": "选择最匹配的代号",\n'
            '  "time_period": "2026-03", // 提取年月，格式YYYY-MM，若无则为空字符串\n'
            '  "department": "骨科" // 提取科室，若无则为空字符串\n'
            '}\n'
            f'用户提问: {user_query}'
        )
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(response.choices[0].message.content.strip())
        except Exception:
            return {}

    def explain_and_draw(
        self, user_query: str, raw_data: Any, intent: str
    ) -> dict[str, Any]:
        """解释查询结果并按需生成 ECharts 图表配置"""
        prompt = f"""
        你是一个医院绩效汇报专家。用户提问: "{user_query}"。
        数据库查询出的原始上下文: {raw_data}。
        
        请严格按照以下 JSON 格式输出：
        {{
            "text": "用专业的人话向医院管理者解释数据结果（支持Markdown格式，可以加粗重点）。如果数据内容提示‘暂未接入’，请礼貌地告知用户。",
            "chart_option": {{}} // 如果是知识图谱查询、执行报错、或者数据不适合画图，请设为 null。如果是结构化的数值，请尝试生成合法的 ECharts option JSON 以进行可视化。
        }}
        """
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        try:
            result = json.loads(response.choices[0].message.content.strip())
        except Exception:
            result = {"text": "生成解释与图表失败，请稍后重试。", "chart_option": None}
        
        # 将引擎标识回传，供前端气泡底部展示“数据溯源标识”
        result["engine"] = intent
        return result

    def _run_graph_query(self, user_query: str) -> dict[str, Any]:
        """执行图谱查询分支"""
        cypher = self.text_to_cypher(user_query)
        try:
            with self.neo4j_driver.session() as session:
                data = [dict(record) for record in session.run(cypher)]
            return self.explain_and_draw(user_query, data, "graph_query")
        except Exception as e:
            return self.explain_and_draw(user_query, f"知识图谱查询失败: {e}", "graph_query")

    def _run_sql_query(self, user_query: str) -> dict[str, Any]:
        """执行 Ad-Hoc 探索查询分支 (Text-to-SQL)"""
        sql = self.text_to_sql(user_query)
        try:
            cursor = self.sqlite_conn.cursor()
            cursor.execute(sql)
            columns = [column[0] for column in cursor.description]
            data = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return self.explain_and_draw(user_query, data, "sql_query")
        except Exception as e:
            return self.explain_and_draw(user_query, f"动态SQL执行失败: {e}\nSQL为: {sql}", "sql_query")

    def _run_mdl_query(self, user_query: str) -> dict[str, Any]:
        """执行核心 KPI 查询分支 (基于 Metrics 注册表)"""
        mdl = self.text_to_mdl(user_query)
        metric_code = mdl.get("metric_code")
        time_period = mdl.get("time_period", "")
        department = mdl.get("department", "")

        # 1. 拦截：如果大模型提取的代号不在我们的 JSON 注册表中
        metric_info = self.metrics_registry.get(metric_code)
        if not metric_info:
             return self.explain_and_draw(user_query, "抱歉，无法在标准考核指标库中精准匹配您的提问，请尝试更换医学通用表述。", "core_kpi")

        # 2. 组装参数
        t_cond = f" AND record_month LIKE '{time_period}%'" if time_period else ""
        d_cond = f" AND department = '{department}'" if department else ""
        
        # 3. 提取安全 SQL 模板（如果 JSON 中没有配置 SQL，给一个兜底信息）
        sql_template = metric_info.get("sql", "SELECT 0 as result, '该核心指标配置缺失 SQL 逻辑' as remark")
        sql = sql_template.format(t=t_cond, d=d_cond)

        try:
            # 4. 执行绝对安全的预设 SQL
            cursor = self.sqlite_conn.cursor()
            cursor.execute(sql)
            columns = [column[0] for column in cursor.description]
            data = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # 5. 丰富上下文：把指标的名称、类别也带给大模型，让回答更显“专业”
            context_data = {
                "考核指标体系分类": f"{metric_info.get('category')} - {metric_info.get('subcategory')}",
                "标准指标名称": metric_info.get("name"),
                "识别到的过滤条件": mdl,
                "底层数据库计算结果": data
            }
            return self.explain_and_draw(user_query, context_data, "core_kpi")
            
        except Exception as e:
            return self.explain_and_draw(user_query, f"MDL 核心指标计算执行异常: {e}", "core_kpi")

    def _run_dashboard_query(self, user_query: str) -> dict[str, Any]:
        """执行院长驾驶舱查询：直接查出最近一个月的所有 56 项指标"""
        try:
            cursor = self.sqlite_conn.cursor()
            # 获取数据库中最新一个月的月份
            cursor.execute("SELECT MAX(record_month) FROM kpi_monthly_results")
            latest_month = cursor.fetchone()[0]

            cursor.execute("""
                SELECT dimension, metric_code, metric_name, metric_value, target_value, unit 
                FROM kpi_monthly_results 
                WHERE record_month = ?
            """, (latest_month,))
            rows = cursor.fetchall()

            # 初始化数据结构
            dashboard_data = {
                "医疗质量": [], "运营效率": [], "持续发展": [], "满意度评价": []
            }
            
            # 负向指标清单（越低越好）
            negative_codes = ["complication_rate", "type1_incision_infection_rate", "low_risk_mortality", "ddds", "op_fee_growth", "op_drug_fee_growth", "ip_fee_growth", "ip_drug_fee_growth", "drug_income_ratio", "asset_liability_ratio", "avg_length_of_stay", "energy_exp_ratio", "op_appointment_precision"]

            for dim, code, name, val, target, unit in rows:
                if dim not in dashboard_data: continue
                # 判定是否达标
                is_ok = (val <= target) if code in negative_codes else (val >= target)
                
                dashboard_data[dim].append({
                    "code": code,
                    "name": name,
                    "value": val,
                    "target": target,
                    "unit": unit,
                    "is_ok": is_ok,
                    "is_negative": code in negative_codes
                })

            return {
                "text": f"✅ 已为您生成 **{latest_month}** 全院三级公立医院绩效考核（国考）驾驶舱数据，请在下方交互面板中审阅：",
                "chart_option": None,
                "dashboard_data": dashboard_data,  # 传递给前端
                "engine": "dashboard"
            }
        except Exception as e:
            return {"text": f"生成驾驶舱失败: {e}", "chart_option": None, "engine": "dashboard"}

    def answer(self, user_query: str) -> dict[str, Any]:
        """系统入口总控"""
        intent = self.intent_router(user_query)
        if intent == "graph_query":
            return self._run_graph_query(user_query)
        elif intent == "core_kpi":
            return self._run_mdl_query(user_query)
        elif intent == "dashboard":
            return self._run_dashboard_query(user_query)  # [新增]
        else:
            return self._run_sql_query(user_query)

# 单例暴露
qa_service = HospitalQAService()