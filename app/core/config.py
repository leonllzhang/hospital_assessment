import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"

load_dotenv(BASE_DIR / ".env")


class Settings:
    app_name = "三级公立医院考核问答系统"
    api_prefix = "/api"
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD")

    # LLM 提供商 (qwen / deepseek)
    llm_provider = os.getenv("LLM_PROVIDER", "qwen").lower()
    # API Keys
    _dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
    _deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    # 可选覆盖
    _custom_base_url = os.getenv("LLM_BASE_URL") or ""
    _custom_model_name = os.getenv("LLM_MODEL_NAME") or ""

    dev_frontend_origin = os.getenv("FRONTEND_DEV_ORIGIN", "http://127.0.0.1:5173")
    # SQLite 数据库文件存储路径，默认存储在项目根目录下
    sqlite_db_path = str(BASE_DIR / "hospital_data.db")

    # ---- 根据 LLM_PROVIDER 动态计算 ----

    @property
    def dashscope_api_key(self) -> str | None:
        """当前启用的 API Key（兼容旧属性名）"""
        if self.llm_provider == "deepseek":
            return self._deepseek_api_key
        return self._dashscope_api_key

    @property
    def dashscope_base_url(self) -> str:
        """当前启用的 API Base URL（兼容旧属性名）"""
        if self._custom_base_url:
            return self._custom_base_url
        if self.llm_provider == "deepseek":
            return "https://api.deepseek.com"
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @property
    def model_name(self) -> str:
        """当前启用的模型名称"""
        if self._custom_model_name:
            return self._custom_model_name
        if self.llm_provider == "deepseek":
            return "deepseek-chat"
        return "qwen-plus"

    @property
    def missing_required_values(self) -> list[str]:
        missing: list[str] = []
        if not self.dashscope_api_key:
            if self.llm_provider == "deepseek":
                missing.append("DEEPSEEK_API_KEY（当前 LLM_PROVIDER=deepseek）")
            else:
                missing.append("DASHSCOPE_API_KEY")
        if not self.neo4j_password:
            missing.append("NEO4J_PASSWORD")
        return missing


settings = Settings()
