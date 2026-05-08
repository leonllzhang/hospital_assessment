"""
红绿灯异动预警引擎 (AlertEngine)
四层架构：
  1. 规则定义层 — alert_rules 表 + 自动规则生成
  2. 数据巡检层 — patrol() 对比实际值与阈值
  3. AI归因层   — run_ai_attribution() LLM诊断根因
  4. 精准触达层 — get_escalation_message() 分级上报话术
"""
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from openai import OpenAI
from app.core.config import settings


# 负向指标（越低越好），与 hospital_qa.py 保持一致
NEGATIVE_CODES = [
    "complication_rate", "type1_incision_infection", "low_risk_mortality",
    "antibiotic_ddds", "aux_drug_income_ratio", "op_antibiotic_ratio",
    "ip_antibiotic_ratio", "drug_income_ratio", "consumable_income_ratio",
    "op_fee_per_visit", "op_fee_growth", "ip_fee_per_discharge",
    "ip_fee_growth", "asset_liability_ratio", "avg_length_of_stay",
    "receivable_turnover", "energy_expense_ratio", "patient_complaint_rate"
]


class AlertEngine:
    """
    红绿灯预警引擎

    使用方式:
        engine = AlertEngine(sqlite_conn)
        engine.patrol("2026-03")          # 巡检某月
        alerts = engine.get_active_alerts()  # 获取预警
    """

    def __init__(self, sqlite_conn: sqlite3.Connection,
                 action_server=None):
        self.conn = sqlite_conn
        self.action_server = action_server  # 可选，用于 AI 归因时查手术流水

        # LLM 客户端（AI 归因时使用）
        self.llm_client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )
        self.llm_model = settings.model_name  # qwen-plus

    # ==========================================================
    # 1. 规则定义层 — 建表 & 种子数据
    # ==========================================================

    @staticmethod
    def create_tables(cursor: sqlite3.Cursor) -> None:
        """创建预警规则表和预警日志表"""
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS alert_rules (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_code   TEXT    NOT NULL UNIQUE,
                metric_name   TEXT    NOT NULL,
                dimension     TEXT    NOT NULL,
                unit          TEXT    DEFAULT '',
                is_negative   INTEGER DEFAULT 0,
                yellow_pct    REAL    DEFAULT 10.0,
                red_pct       REAL    DEFAULT 25.0,
                is_active     INTEGER DEFAULT 1,
                created_at    TEXT    DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS alert_logs (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                record_month          TEXT    NOT NULL,
                metric_code           TEXT    NOT NULL,
                metric_name           TEXT    NOT NULL,
                dimension             TEXT    NOT NULL,
                metric_value          REAL    NOT NULL,
                target_value          REAL    NOT NULL,
                deviation_pct         REAL    NOT NULL,
                alert_level           TEXT    NOT NULL,
                is_negative           INTEGER DEFAULT 0,
                escalation_target     TEXT    DEFAULT 'dept_head',
                root_cause            TEXT    DEFAULT '',
                action_recommendation TEXT    DEFAULT '',
                is_read               INTEGER DEFAULT 0,
                created_at            TEXT    DEFAULT (datetime('now','localtime')),
                UNIQUE(record_month, metric_code)
            );
        """)

    @staticmethod
    def seed_rules(cursor: sqlite3.Cursor,
                   kpi_defs: list,
                   negative_codes: list) -> None:
        """为全部指标生成默认预警规则（幂等）"""
        for dim, code, name, *_rest, unit in kpi_defs:
            is_neg = 1 if code in negative_codes else 0
            cursor.execute("""
                INSERT OR IGNORE INTO alert_rules
                    (metric_code, metric_name, dimension, unit, is_negative,
                     yellow_pct, red_pct)
                VALUES (?, ?, ?, ?, ?, 10.0, 25.0)
            """, (code, name, dim, unit, is_neg))

    # ==========================================================
    # 2. 数据巡检层 — 核心 patrol
    # ==========================================================

    def patrol(self, month: str) -> List[Dict[str, Any]]:
        """
        巡检指定月份：读取 kpi_monthly_results，与阈值对比，写入 alert_logs。
        返回：触发了预警（黄灯 + 红灯）的列表。
        """
        cursor = self.conn.cursor()

        # 读取该月所有 KPI 数据
        cursor.execute("""
            SELECT metric_code, metric_name, dimension, metric_value,
                   target_value, unit
            FROM kpi_monthly_results
            WHERE record_month = ?
        """, (month,))
        rows = cursor.fetchall()

        triggered = []

        for code, name, dim, val, target, unit in rows:
            # 查询该指标的预警规则
            cursor.execute("""
                SELECT is_negative, yellow_pct, red_pct
                FROM alert_rules WHERE metric_code = ?
            """, (code,))
            rule = cursor.fetchone()
            if not rule:
                continue  # 没有规则，跳过

            is_neg, yellow_pct, red_pct = rule

            # 计算偏离度
            # 正向指标：实际低于目标 → 偏离
            # 负向指标：实际高于目标 → 偏离
            if is_neg:
                # 负向：实际值越低越好，偏离当 实际值 > 目标值
                if val > target:
                    deviation = round((val - target) / target * 100, 1)
                else:
                    deviation = 0.0
            else:
                # 正向：实际值越高越好，偏离当 实际值 < 目标值
                if val < target:
                    deviation = round((target - val) / target * 100, 1)
                else:
                    deviation = 0.0

            # 映射等级
            if deviation >= red_pct:
                alert_level = "red"
            elif deviation >= yellow_pct:
                alert_level = "yellow"
            else:
                alert_level = "green"

            # 分级上报目标
            if alert_level == "red":
                # 检查上月是否也是红灯（持续红灯 → 院长级）
                prev = self._prev_month(month)
                cursor.execute("""
                    SELECT alert_level FROM alert_logs
                    WHERE metric_code = ? AND record_month = ?
                """, (code, prev))
                prev_row = cursor.fetchone()
                if prev_row and prev_row[0] == "red":
                    escalation = "dean"
                else:
                    escalation = "medical_office+dept_head"
            elif alert_level == "yellow":
                escalation = "dept_head"
            else:
                escalation = ""

            # UPSERT 写入日志
            cursor.execute("""
                INSERT OR REPLACE INTO alert_logs
                    (record_month, metric_code, metric_name, dimension,
                     metric_value, target_value, deviation_pct, alert_level,
                     is_negative, escalation_target)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (month, code, name, dim, val, target, deviation,
                  alert_level, is_neg, escalation))

            if alert_level in ("yellow", "red"):
                triggered.append({
                    "id": cursor.lastrowid,
                    "metric_code": code,
                    "metric_name": name,
                    "dimension": dim,
                    "alert_level": alert_level,
                    "metric_value": val,
                    "target_value": target,
                    "deviation_pct": deviation,
                    "unit": unit,
                    "is_negative": is_neg,
                    "escalation_target": escalation,
                })

        self.conn.commit()
        return triggered

    def patrol_latest(self) -> List[Dict[str, Any]]:
        """巡检最新月份"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(record_month) FROM kpi_monthly_results")
        month = cursor.fetchone()[0]
        return self.patrol(month) if month else []

    # ==========================================================
    # 查询方法
    # ==========================================================

    def get_active_alerts(self, month: str = "",
                          level: str = "") -> List[Dict[str, Any]]:
        """查询预警日志"""
        cursor = self.conn.cursor()
        conditions = []
        params = []
        if month:
            conditions.append("record_month = ?")
            params.append(month)
        if level:
            conditions.append("alert_level = ?")
            params.append(level)
        where = " AND ".join(conditions) if conditions else "1=1"

        cursor.execute(f"""
            SELECT id, record_month, metric_code, metric_name, dimension,
                   metric_value, target_value, deviation_pct, alert_level,
                   is_negative, escalation_target, root_cause,
                   action_recommendation, is_read
            FROM alert_logs
            WHERE {where} AND alert_level IN ('yellow','red')
            ORDER BY alert_level DESC, deviation_pct DESC
        """, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_alert_summary(self, month: str = "") -> Dict[str, Any]:
        """按维度和等级统计预警数量"""
        cursor = self.conn.cursor()
        if not month:
            cursor.execute("SELECT MAX(record_month) FROM kpi_monthly_results")
            month = cursor.fetchone()[0]
            if not month:
                return {"total": 0, "red": 0, "yellow": 0,
                        "by_dimension": {}, "month": ""}

        cursor.execute("""
            SELECT dimension, alert_level, COUNT(*) as cnt
            FROM alert_logs
            WHERE record_month = ? AND alert_level IN ('yellow','red')
            GROUP BY dimension, alert_level
        """, (month,))
        rows = cursor.fetchall()

        by_dim: Dict[str, Any] = {}
        red = yellow = total = 0
        for dim, level, cnt in rows:
            if dim not in by_dim:
                by_dim[dim] = {"red": 0, "yellow": 0}
            by_dim[dim][level] = cnt
            if level == "red":
                red += cnt
            else:
                yellow += cnt
            total += cnt

        return {
            "month": month,
            "total": total,
            "red": red,
            "yellow": yellow,
            "by_dimension": by_dim,
        }

    def get_alerts_for_metric(self, metric_code: str,
                              month: str = "") -> List[Dict[str, Any]]:
        """查询某个指标的预警（用于 Agent 主动警告）"""
        cursor = self.conn.cursor()
        if not month:
            cursor.execute("SELECT MAX(record_month) FROM kpi_monthly_results")
            month = cursor.fetchone()[0]

        cursor.execute("""
            SELECT id, alert_level, deviation_pct, metric_value,
                   target_value, escalation_target
            FROM alert_logs
            WHERE metric_code = ? AND record_month = ?
              AND alert_level IN ('yellow','red')
        """, (metric_code, month))
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def mark_read(self, alert_id: int) -> None:
        """标记已读"""
        self.conn.execute(
            "UPDATE alert_logs SET is_read = 1 WHERE id = ?",
            (alert_id,)
        )
        self.conn.commit()

    # ==========================================================
    # 3. AI 归因层
    # ==========================================================

    def run_ai_attribution(self, alert_id: int) -> Dict[str, str]:
        """
        对某条预警进行深度归因分析：
        1. LLM 生成诊断 SQL → 查手术流水
        2. LLM 基于数据给出根因 + 行动建议
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT record_month, metric_code, metric_name, dimension,
                   metric_value, target_value, deviation_pct, alert_level,
                   is_negative
            FROM alert_logs WHERE id = ?
        """, (alert_id,))
        row = cursor.fetchone()
        if not row:
            return {"root_cause": "未找到对应预警记录",
                    "action_recommendation": ""}

        month, code, name, dim, val, target, dev, level, is_neg = row

        direction = "越低越好（负向指标）" if is_neg else "越高越好（正向指标）"

        # --- 第1步：LLM 生成诊断 SQL ---
        sql_prompt = f"""
你是一个医院数据分析师。系统监测到一条异常预警：
- 指标: {name} ({code})
- 所属维度: {dim}
- 当前值: {val}，目标值: {target}
- 偏离度: {dev}%，等级: {'红灯(严重)' if level == 'red' else '黄灯'}
- 指标方向: {direction}

请生成一条 SQLite SQL 查询语句，用于从手术记录表 `surgery_records` 中
探查可能导致该指标异常的原因。

可用字段：record_month, department, doctor_name, is_weichuang, surgery_level, fee
月份：{month}

请只输出 SQL 本身，不要带任何解释或标记。
"""
        try:
            sql_resp = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": sql_prompt}],
                temperature=0.1,
            )
            diag_sql = sql_resp.choices[0].message.content.strip()
            # 去除可能的 markdown 代码块标记
            diag_sql = diag_sql.replace("```sql", "").replace("```", "").strip()
        except Exception as e:
            diag_sql = f"-- LLM 生成 SQL 失败: {e}"

        # --- 第2步：执行 SQL ---
        query_result = ""
        if self.action_server and diag_sql and not diag_sql.startswith("--"):
            try:
                result = self.action_server.execute_ad_hoc_sql(diag_sql)
                if result.get("status") == "success":
                    query_result = json.dumps(
                        result["data"][:20], ensure_ascii=False, indent=2
                    )
                else:
                    query_result = f"查询未返回数据: {result.get('message', '')}"
            except Exception as e:
                query_result = f"查询执行异常: {e}"
        else:
            query_result = "（无可用流水数据）"

        # --- 第3步：LLM 综合分析 ---
        analysis_prompt = f"""
你是一位资深医院管理专家。系统监测到一条考核指标预警，请进行归因分析并给出行动建议。

## 预警信息
- 指标: {name} ({code})
- 维度: {dim}
- 当前值: {val}，目标值: {target}
- 偏离度: {dev}%
- 预警等级: {level}
- 指标方向: {direction}

## 底层数据探查结果
```
{query_result}
```

请返回 JSON 格式（不要带 markdown 标记）:
{{
    "root_cause": "用 2-3 句话分析可能导致该指标异常的根因",
    "action_recommendation": "给出 2-3 条具体可执行的管理改进建议，使用 Markdown 格式"
}}
"""
        try:
            analysis_resp = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": analysis_prompt}],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            result_text = analysis_resp.choices[0].message.content.strip()
            result = json.loads(result_text)
            root_cause = result.get("root_cause", "AI 分析暂时无法确定根因。")
            action_rec = result.get("action_recommendation", "建议人工复核数据。")
        except Exception as e:
            root_cause = f"AI 归因分析调用失败: {e}"
            action_rec = "请联系技术人员检查大模型服务状态。"

        # 回写数据库
        cursor.execute("""
            UPDATE alert_logs
            SET root_cause = ?, action_recommendation = ?
            WHERE id = ?
        """, (root_cause, action_rec, alert_id))
        self.conn.commit()

        return {"root_cause": root_cause, "action_recommendation": action_rec}

    # ==========================================================
    # 4. 精准触达层 — 分级上报话术
    # ==========================================================

    def get_escalation_message(self, alert: Dict[str, Any]) -> Dict[str, str]:
        """
        根据预警级别生成分级上报消息
        返回: { target, title, message }
        """
        name = alert["metric_name"]
        level = alert["alert_level"]
        val = alert["metric_value"]
        target = alert["target_value"]
        dev = alert["deviation_pct"]
        escalation = alert.get("escalation_target", "dept_head")

        if level == "red" and escalation == "dean":
            target_role = "院长"
            title = f"🚨 【院长红线预警】{name} 严重偏离目标"
            message = (
                f"【🚨 院长红线预警】全院{name}（当前值{val}）"
                f"已严重偏离目标值({target})，偏离度达{dev}%。"
                f"该指标已持续多月处于红灯状态，建议立即召开专题会议研究对策。"
            )
        elif level == "red":
            target_role = "医务处/质控科 + 科室主任"
            title = f"🔴 【红灯预警】{name} 需立即关注"
            message = (
                f"【🔴 红灯预警】{name}（当前值{val}）"
                f"已超过预警红线（目标值{target}），偏离度{dev}%。"
                f"建议立即核查该指标涉及的业务流程，排查是否存在操作不规范或流程缺陷。"
            )
        else:  # yellow
            target_role = "科室主任"
            title = f"🟡 【黄灯提示】{name} 出现下滑趋势"
            message = (
                f"【🟡 黄灯提示】{name}（当前值{val}）"
                f"低于考核目标（{target}），偏离度{dev}%。"
                f"请关注该指标的日常运行情况，防止趋势进一步恶化。"
            )

        return {
            "target": target_role,
            "title": title,
            "message": message,
        }

    # ==========================================================
    # 内部工具
    # ==========================================================

    @staticmethod
    def _prev_month(month: str) -> str:
        """计算上个月，如 '2026-03' → '2026-02'"""
        dt = datetime.strptime(month, "%Y-%m")
        prev = dt - timedelta(days=28)  # 回退约一个月
        return prev.strftime("%Y-%m")
