"""服务部AI洞察平台 - FastAPI 应用入口。

启动方式：
    uvicorn app.main:app --host 0.0.0.0 --port 8000

API 文档：
    http://localhost:8000/docs     （Swagger UI）
    http://localhost:8000/redoc    （ReDoc）
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

啊from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import models  # noqa: F401  确保所有 ORM 模型注册到 Base.metadata
from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.session import close_engine, warm_up_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动预热连接池，退出释放连接。"""
    # 安全自检：使用占位 SECRET_KEY 会允许任意身份令牌伪造，生产必须替换
    if settings.SECRET_KEY == "insight-secret-key-change-me-in-production":
        logging.getLogger("app").warning(
            "安全告警：SECRET_KEY 仍为占位默认值，JWT 可被任意伪造！"
            " 请在环境变量 / .env 中设置强随机密钥后再部署到生产环境。"
        )
    await warm_up_pool()
    # 启动对账：复位因服务重启/任务异常而卡在 generating 的孤儿报告
    try:
        from app.services.generation import generation_manager

        fixed = await generation_manager.reconcile_orphans()
        if fixed:
            logging.getLogger("app").warning(
                "启动对账：复位 %d 份卡在 generating 的孤儿报告", fixed
            )
    except Exception:  # noqa: BLE001
        logging.getLogger("app").exception("启动对账失败（不影响服务启动）")
    # 启动对账：复位因进程重启而卡在 sending 的邮件任务
    try:
        from app.services.email import reconcile_stuck_email_tasks

        stuck = await reconcile_stuck_email_tasks()
        if stuck:
            logging.getLogger("app").warning(
                "启动对账：复位 %d 个卡在 sending 的邮件任务", stuck
            )
    except Exception:  # noqa: BLE001
        logging.getLogger("app").exception("邮件任务启动对账失败（不影响服务启动）")
    # 启动进程内定时邮件调度器（Celery beat 场景可同时运行，抢占互斥）
    try:
        from app.services.email import start_email_scheduler

        start_email_scheduler()
    except Exception:  # noqa: BLE001
        logging.getLogger("app").exception("启动邮件调度器失败（不影响服务启动）")
    yield
    try:
        from app.services.email import stop_email_scheduler

        await stop_email_scheduler()
    except Exception:  # noqa: BLE001
        pass
    await close_engine()


def _cors_origins() -> list[str]:
    raw = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    return raw or ["*"]


_cors = _cors_origins()
# 通配符 "*" 与 allow_credentials=True 在浏览器中互不兼容且存在安全隐患，
# 因此通配时强制关闭凭证；指定具体域名时才允许携带凭证。
_allow_credentials = _cors != ["*"]

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="服务部AI洞察平台后端 API（FastAPI + SQLAlchemy async + asyncpg）",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
)

# 注册全局异常处理器（统一响应格式）
register_exception_handlers(app)

# CORS：私有化部署，允许前端跨域直连（生产请通过 CORS_ORIGINS 收紧为前端域名白名单）
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册全部业务路由（Base URL: /api/v1）
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["系统"], summary="健康检查")
async def health_check() -> dict:
    return {"status": "ok", "service": settings.PROJECT_NAME}

# gzip 压缩响应（>=1KB 的静态资源/接口响应自动压缩，显著降低内网传输耗时）
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ==================== 生产静态托管：后端直接提供前端构建产物 ====================
# 将 frontend/dist 挂载到 FastAPI，内网访问 http://<本机IP>:8000 即打开平台，
# /api 与 WebSocket 同源直连（无需 3000 端口代理层），并启用 gzip 压缩。
DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if DIST_DIR.is_dir() and (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # 后端相关路径不兜底（保持原有 404 行为）
        if full_path.startswith(
            ("api/", "docs", "redoc", "openapi.json", "health")
        ):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        target = DIST_DIR / full_path
        if target.is_file():
            return FileResponse(target)
        # SPA 前端路由回退到 index.html
        return FileResponse(DIST_DIR / "index.html")
else:
    logging.getLogger(__name__).warning(
        "frontend/dist 不存在，未启用前端静态托管（仅提供 API）"
    )
