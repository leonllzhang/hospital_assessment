# app/services/report_generator.py
import sqlite3
import os
from typing import Dict, Any, List, Optional
from openai import OpenAI
from dotenv import load_dotenv
from markdown_it import MarkdownIt

load_dotenv()

# 初始化 Markdown → HTML 渲染器（GitHub Flavored Markdown）
_md = MarkdownIt("commonmark", {"linkify": False}).enable(["table", "strikethrough"])

# 负向指标（同 alert_engine.py，用于达标判定）
NEGATIVE_CODES = [
    "complication_rate", "type1_incision_infection", "low_risk_mortality",
    "antibiotic_ddds", "aux_drug_income_ratio", "op_antibiotic_ratio",
    "ip_antibiotic_ratio", "drug_income_ratio", "consumable_income_ratio",
    "op_fee_per_visit", "op_fee_growth", "ip_fee_per_discharge",
    "ip_fee_growth", "asset_liability_ratio", "avg_length_of_stay",
    "receivable_turnover", "energy_expense_ratio", "patient_complaint_rate"
]

class MonthlyReportGenerator:
    def __init__(self, db_path: str):
        self.db_path = db_path
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("未找到 DASHSCOPE_API_KEY，请检查 .env 文件是否配置正确。")
        # 同样调用我们配置好的模型（建议这里用长文本生成能力好的模型，如 qwen-max 或 gpt-4o）
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.model_name = "qwen-max"

    def _fetch_month_data(self, target_month: str) -> Dict[str, Any]:
        """从数据库提取全院指标，并进行初步的红黑榜计算"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT dimension, metric_code, metric_name, metric_value, target_value, unit
            FROM kpi_monthly_results
            WHERE record_month = ?
        """, (target_month,))

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return None

        # 整理数据
        total_metrics = len(rows)
        achieved_count = 0
        details = []

        # 使用负向指标清单进行准确的方向感知判定
        for dim, code, name, val, target, unit in rows:
            if code in NEGATIVE_CODES:
                is_achieved = val <= target  # 负向：越低越好
            else:
                is_achieved = val >= target  # 正向：越高越好

            if is_achieved:
                achieved_count += 1

            details.append({
                "维度": dim,
                "指标名称": name,
                "实际值": f"{val}{unit}",
                "目标值": f"{target}{unit}",
                "是否达标": "✅" if is_achieved else "❌"
            })

        return {
            "month": target_month,
            "total_metrics": total_metrics,
            "achieved_count": achieved_count,
            "achieved_rate": round(achieved_count / total_metrics * 100, 1) if total_metrics else 0,
            "details": details
        }

    def generate_markdown_report(self, target_month: str,
                                  alerts: Optional[List[Dict]] = None) -> str:
        """核心：将数据喂给大模型，生成麦肯锡风格的管理报告"""
        print(f"📊 正在抽取 {target_month} 的全院数据...")
        data_summary = self._fetch_month_data(target_month)
        
        if not data_summary:
            return "数据库中未找到该月份的数据，无法生成报告。"

        # 组装预警上下文
        alert_section = ""
        if alerts:
            red = [a for a in alerts if a["alert_level"] == "red"]
            yellow = [a for a in alerts if a["alert_level"] == "yellow"]
            if red or yellow:
                red_names = "、".join(a["metric_name"] for a in red[:5])
                yellow_names = "、".join(a["metric_name"] for a in yellow[:5])
                alert_section = f"""
### 异常预警概况：
- 红灯预警（严重偏离目标）：{len(red)} 项
  {'⚠️ ' + red_names if red_names else '无'}
- 黄灯预警（趋势偏离）：{len(yellow)} 项
  {'⚠️ ' + yellow_names if yellow_names else '无'}
"""

        print(f"🧠 正在请求大模型进行深度归因与报告撰写...")
        
        # 构建强大的 System Prompt 和数据上下文
        prompt = f"""
你现在是一家国内顶尖三级公立医院的首席运营官（COO）和绩效考核专家。
请根据以下我提供的【{target_month}】国考56项核心指标数据，生成一份极其专业、适合院长审阅的月度运营分析报告。

### 本月整体概况数据：
- 考核指标总数：{data_summary['total_metrics']} 项
- 达标指标数：{data_summary['achieved_count']} 项
- 整体达标率：{data_summary['achieved_rate']}%

### 各项指标明细数据：
{data_summary['details']}

{alert_section}
### 报告输出要求（必须使用 Markdown 格式排版）：
1. **执行摘要**：用2-3句话总结本月整体运营健康度。
2. **红黑榜洞察**：
   - 找出表现最亮眼（远超目标）的3个指标，给予肯定。
   - 找出问题最严重（远未达标，尤其是医疗质量和费用类）的3-5个指标，列为"黑榜"，并结合医疗行业常识，推测可能导致这些指标恶化的业务原因（如：收治了疑难重症、耗材管理不严等）。
3. **四大维度简评**：分别对【医疗质量】、【运营效率】、【持续发展】、【满意度评价】用一句话点评。
4. **管理层行动建议**：针对黑榜指标，给出下个月具体可执行的 3 条改进建议。

语气要求：严谨、客观、直击痛点，不要说废话。
"""
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": "你是一个只输出高质量 Markdown 格式报告的 AI 专家。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3 # 保持理性，减少发散
        )
        
        return response.choices[0].message.content

    def generate_html_report(self, target_month: str,
                             alerts: Optional[List[Dict]] = None) -> str:
        """生成完整 HTML 报告（带排版样式，可直接打印或浏览器打开）"""
        md_text = self.generate_markdown_report(target_month, alerts)
        body_html = _md.render(md_text)

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>医院运营分析报告 - {target_month}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", sans-serif;
    color: #1e293b; background: #f3f5f9; line-height: 1.8;
    padding: 40px 0;
  }}
  .report-container {{
    max-width: 900px; margin: 0 auto; background: #fff;
    border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    padding: 60px 70px;
  }}
  .report-header {{
    text-align: center; border-bottom: 3px solid #1e40af;
    padding-bottom: 30px; margin-bottom: 40px;
  }}
  .report-header h1 {{
    font-size: 28px; color: #1e3a5f; margin-bottom: 8px;
  }}
  .report-header .subtitle {{
    font-size: 15px; color: #64748b;
  }}
  .report-container h1 {{ font-size: 22px; color: #1e3a5f; margin: 32px 0 12px; }}
  .report-container h2 {{ font-size: 19px; color: #1e40af; margin: 28px 0 10px; border-left: 4px solid #3b82f6; padding-left: 12px; }}
  .report-container h3 {{ font-size: 16px; color: #334155; margin: 20px 0 8px; }}
  .report-container p  {{ margin: 8px 0; font-size: 15px; }}
  .report-container strong {{ color: #1e40af; }}
  .report-container ul, .report-container ol {{ margin: 10px 0 10px 24px; font-size: 15px; }}
  .report-container li {{ margin: 4px 0; }}
  .report-container table {{
    width: 100%; border-collapse: collapse; margin: 16px 0;
    font-size: 14px;
  }}
  .report-container th {{
    background: #1e40af; color: #fff; padding: 10px 12px; text-align: left;
  }}
  .report-container td {{
    padding: 8px 12px; border-bottom: 1px solid #e2e8f0;
  }}
  .report-container tr:nth-child(even) td {{ background: #f8fafc; }}
  .report-footer {{
    margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0;
    text-align: center; font-size: 13px; color: #94a3b8;
  }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .report-container {{ box-shadow: none; border-radius: 0; max-width: 100%; padding: 40px; }}
  }}
</style>
</head>
<body>
<div class="report-container">
<div class="report-header">
  <h1>三级公立医院绩效考核月度运营分析报告</h1>
  <p class="subtitle">报告期间：{target_month} ｜ 生成日期：{__import__("datetime").datetime.now().strftime("%Y-%m-%d")}</p>
</div>
{body_html}
<div class="report-footer">
  <p>本报告由 AI 智能分析引擎自动生成，数据来源为国考 56 项核心指标考核体系</p>
</div>
</div>
</body>
</html>"""


# 测试使用代码

# if __name__ == "__main__":
#     import os
    
#     # 1. 动态获取项目根目录 (即 E:\SourceCode\hospital_assessment)
#     base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    
#     # 2. 假设您的数据库存在 data 目录下
#     data_dir = os.path.join(base_dir, "")
#     db_path = os.path.join(data_dir, "hospital_data.db")
    
#     print(f"[SEARCH] 尝试寻找数据库路径: {db_path}")

#     # 3. 容错处理：如果之前没有 data 文件夹，自动建一个
#     if not os.path.exists(data_dir):
#         os.makedirs(data_dir)
#         print("📁 发现没有 data 文件夹，已自动为您创建。")
        
#     # 4. 检查文件是否真的存在
#     if not os.path.exists(db_path):
#         print("[WARN] 警告：找不到 hospital.db 文件！")
#         print("请确认您的 FastAPI 项目（web_app.py）是否启动过？因为数据库文件是在应用启动时由 init_mock_db() 生成的。")
#         print("请先运行一次 `python web_app.py` 生成数据库，然后再来执行此脚本。")
#     else:
#         generator = MonthlyReportGenerator(db_path)
#         # 给生成器提供我们造好的 2026年3月 的数据
#         markdown_report = generator.generate_markdown_report("2026-03")
        
#         print("\n================ 自动生成的 AI 报告如下 ================\n")
#         print(markdown_report)