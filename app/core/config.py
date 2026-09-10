from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ---- 基础 ----
    PROJECT_NAME: str = "服务部AI洞察平台"
    API_V1_PREFIX: str = "/api/v1"

    # ---- 安全 / 部署 ----
    # 前端域名白名单（逗号分隔）。生产务必收紧为具体域名，不要用 "*"。
    CORS_ORIGINS: str = "*"
    # 是否暴露 /docs /redoc /openapi.json（含完整端点面）。生产建议设为 False。
    ENABLE_DOCS: bool = True

    # ---- 数据库 ----
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/insight_ai"
    DB_ECHO: bool = False
    DB_POOL_MIN_SIZE: int = 5
    DB_POOL_MAX_SIZE: int = 40
    DB_POOL_TIMEOUT: int = 30

    # ---- JWT ----
    SECRET_KEY: str = "insight-secret-key-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 24 小时

    # ---- 内部邮箱域名（发送邮件时无需白名单校验） ----
    INTERNAL_EMAIL_DOMAINS: list[str] = ["insight.local"]

    # ---- 报告生成任务 ----
    MAX_CONCURRENT_TASKS: int = 5      # 全局最大并发生成任务数（asyncio.Semaphore）
    GENERATION_TIMEOUT_SECONDS: int = 1800  # 30 分钟硬止损
    GENERATION_SIMULATE: bool = True   # 模拟生成（True 时不调用真实模型 API）
    GENERATION_STEP_DELAY: float = 0.5  # 模拟执行时每步延迟（秒）
    # 单份报告内模块的并发数（模块之间无数据依赖，可并行提速；设为 1 恢复严格串行）
    GENERATION_MODULE_CONCURRENCY: int = 3
    # 单模块 max_tokens 安全上限（非推理模型）：超过则裁剪，防止空耗 token。
    MODEL_MAX_TOKENS_CAP: int = 8000
    # 推理模型（思考过程会占用输出预算）使用更高的上限，避免被全局 cap 截断导致内容为空。
    MODEL_REASONING_MAX_TOKENS_CAP: int = 64000
    # 推理模型的安全 max_tokens 下限：若请求值过小，思考过程会耗尽预算、最终答案为空。
    # 任何推理模型调用都会被抬升到此值，避免偶发截断（与历史 32000/16000 实践一致）。
    MODEL_REASONING_MIN_TOKENS: int = 16000
    # 用于识别推理模型的名称关键字（小写子串匹配）。
    REASONING_MODEL_HINTS: list[str] = [
        "deepseek-reasoner", "deepseek-v4-flash", "deepseek-r1",
        "o1", "o3", "o4", "claude-3-7-sonnet-thinking", "thinking",
    ]
    # 全部模块跑完后，是否再调用一次模型生成跨模块「执行摘要」
    GENERATION_ENABLE_SUMMARY: bool = True
    # 执行摘要的安全 max_tokens 下限（非推理模型）。摘要 prompt 比单模块更长，
    # 若沿用模块的较小 max_tokens，推理模型会被思考过程耗尽导致答案为空。
    EXEC_SUMMARY_MAX_TOKENS: int = 4000
    # 参考资料总字符预算（多 URL 累加后按此上限等比裁剪，避免超出模型上下文）
    PROMPT_MAX_CHARS: int = 20000
    # 参考资料相关性筛选：仅保留含关键词的段落，显著降低喂给模型的 token（①）
    GENERATION_REF_RELEVANCE_FILTER: bool = True
    # 大纲先行（⑥）：生成模块前用一次轻量调用规划各模块角度，减少重复与遗漏
    GENERATION_ENABLE_OUTLINE: bool = True
    # 启用模型厂商的 prompt caching（如支持 cache_control 的 provider）。
    # 默认关闭，避免不兼容的 provider 报错；开启后 system 消息（角色+框架+schema）会被缓存。
    MODEL_PROMPT_CACHING: bool = False
    # 模型调用失败重试次数（指数退避），0 表示不重试
    MODEL_CALL_RETRIES: int = 2

    # ---- 模型调用 ----
    MODEL_CALL_TIMEOUT: int = 60       # 模型 API 调用超时（秒）
    MODEL_TEST_TIMEOUT: int = 15       # 连接测试超时（秒）

    # ---- 抓取缓存 ----
    FETCH_CACHE_TTL: int = 300         # 同一 URL+配置的抓取结果缓存秒数（0 表示关闭）

    # ---- 定时报告调度 ----
    REPORT_SCHEDULER_ENABLED: bool = True  # 是否扫描并派发到期的报告调度

    # ---- 邮件 ----
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = True
    SMTP_SENDER: str = ""
    EMAIL_SIMULATE: bool = True        # 模拟发送（True 时不真正调用 SMTP）

    # ---- Redis / 并发 / Celery ----
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ---- 外部数据抓取 ----
    FETCHER_DEFAULT_TIMEOUT: float = 10.0   # 单 URL 抓取超时（秒）
    FETCHER_DEFAULT_RETRIES: int = 2        # 失败重试次数（0~3）
    FETCHER_DEFAULT_MAX_LENGTH: int = 5000  # 正文截断长度（2000/5000/10000）
    FETCHER_ENABLE_PLAYWRIGHT: bool = True  # 是否启用 Playwright 降级引擎

    # ---- 临时文件 ----
    TEMP_DIR: str = "./temp"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

