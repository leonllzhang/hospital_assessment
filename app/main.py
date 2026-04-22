from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.chat import router as chat_router
from app.core.config import FRONTEND_DIST_DIR, settings


app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.dev_frontend_origin, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix=settings.api_prefix)

assets_dir = FRONTEND_DIST_DIR / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def read_index():
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse(
        {
            "message": "前端已拆分为 Vue 3 项目。",
            "backend": "FastAPI 已启动",
            "next_steps": [
                "进入 frontend 目录安装依赖",
                "开发模式运行 Vite: npm run dev",
                "生产模式构建后，FastAPI 会自动托管 frontend/dist",
            ],
        }
    )


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    index_path = FRONTEND_DIST_DIR / "index.html"
    requested_path = FRONTEND_DIST_DIR / full_path
    if requested_path.exists() and requested_path.is_file():
        return FileResponse(requested_path)
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"message": f"未找到路径: /{full_path}"}, status_code=404)
