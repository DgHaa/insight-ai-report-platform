"""模型配置模块：POST /models/test、GET /models/providers。"""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.exceptions import ModelCallError, RateLimitError
from app.core.ratelimit import RateLimited, check_rate_limit
from app.core.response import ApiResponse, success
from app.models import User
from app.schemas.model import ModelTestRequest, ModelTestData
from app.services.model_client import PROVIDERS, ModelClient

router = APIRouter(prefix="/models", tags=["模型配置"])


@router.post("/test", response_model=ApiResponse, summary="测试模型连接")
async def test_model(
    body: ModelTestRequest,
    user: User = Depends(get_current_user),
) -> ApiResponse:
    # 速率限制：该接口会向用户指定地址发起请求，需抑制被用作内网探测放大器
    try:
        check_rate_limit(f"model-test:{user.id}", limit=20, window=60)
    except RateLimited as exc:
        raise RateLimitError(str(exc)) from exc

    ok, latency, message = await ModelClient().test_connection(
        provider=body.provider,
        endpoint=body.endpoint,
        api_key=body.api_key,
        model_name=body.model_name,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
    )
    if not ok:
        raise ModelCallError(message)
    return success(data=ModelTestData(success=True, latency_ms=latency, message=message))


@router.get("/providers", response_model=ApiResponse, summary="支持的模型提供商")
async def get_providers(
    user: User = Depends(get_current_user),
) -> ApiResponse:
    return success(data={"providers": PROVIDERS})
