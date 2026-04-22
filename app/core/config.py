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
    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
    dashscope_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model_name = "qwen-plus"
    dev_frontend_origin = os.getenv("FRONTEND_DEV_ORIGIN", "http://127.0.0.1:5173")

    @property
    def missing_required_values(self) -> list[str]:
        missing: list[str] = []
        if not self.dashscope_api_key:
            missing.append("DASHSCOPE_API_KEY")
        if not self.neo4j_password:
            missing.append("NEO4J_PASSWORD")
        return missing


settings = Settings()
