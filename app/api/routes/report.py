# app/api/routes/report.py
from fastapi import APIRouter
from pathlib import Path
from app.services.report_generator import MonthlyReportGenerator
from app.services.hospital_qa import action_server
from pydantic import BaseModel
import asyncio

router = APIRouter()

# 【终极防错版路径计算】
# 当前文件是: hospital_assessment/app/api/routes/report.py
# .parents[0] -> routes/
# .parents[1] -> api/
# .parents[2] -> app/
# .parents[3] -> hospital_assessment/ (项目根目录)
base_dir = Path(__file__).resolve().parents[3]

# 拼接并转换为字符串形式
db_path = str(base_dir / "hospital_data.db")

print(f"🗄️ 报告生成器已锁定数据库路径: {db_path}")

# 实例化报告生成器
report_generator = MonthlyReportGenerator(db_path)

@router.get("/generate")
async def generate_monthly_report(month: str, format: str = "markdown"):
    """前端调用此接口，获取指定月份的 AI 分析报告。
       format 参数可选 "markdown" 或 "html"，默认 "markdown"。"""
    print(f"📡 收到前端生成报告请求，月份: {month}, 格式: {format}")
    try:
        try:
            alerts = action_server.alert_engine.get_active_alerts(month)
        except Exception:
            alerts = None

        markdown_text = report_generator.generate_markdown_report(month, alerts)

        result = {
            "status": "success",
            "month": month,
            "report_content": markdown_text,
        }

        if format == "html":
            result["html_content"] = report_generator.generate_html_report(month, alerts)

        return result
    except Exception as e:
        print(f"❌ 报告生成失败: {str(e)}")
        return {"status": "error", "message": str(e)}
    

# 定义前端传过来的数据格式
class PushRequest(BaseModel):
    month: str
    report_content: str
    target_user: str = "院长"

@router.post("/push")
async def push_report_to_mobile(req: PushRequest):
    """模拟推送到企业微信/钉钉的接口"""
    print(f"📲 [Push API] 准备将 {req.month} 的报告推送到【{req.target_user}】的手机端...")
    
    try:
        # 模拟网络请求延迟
        await asyncio.sleep(1.5)
        
        # 在真实的商业项目中，这里会替换为类似下面的代码：
        # requests.post("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx", json={
        #     "msgtype": "markdown",
        #     "markdown": {"content": req.report_content}
        # })
        
        print(f"✅ 推送成功！内容长度: {len(req.report_content)} 字符")
        return {
            "status": "success",
            "message": f"已成功通过企业微信推送到【{req.target_user}】的手机！"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}