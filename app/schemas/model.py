"""模型配置模块请求/响应模式。"""
from pydantic import BaseModel, Field


class ModelTestRequest(BaseModel):
    """POST /models/test 请求体。"""

    provider: str = Field(min_length=1, max_length=50)
    endpoint: str = Field(min_length=1)
    api_key: str | None = None
    model_name: str = Field(min_length=1, max_length=100)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=128000)


class ModelTestData(BaseModel):
    """模型连接测试响应数据。"""

    success: bool
    latency_ms: float
    message: str
