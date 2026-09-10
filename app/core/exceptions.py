"""自定义业务异常与全局异常处理器。

错误码对齐《前后端接口定义文档（V1.0）》3.1 通用规范。
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("insight.exceptions")


class BusinessException(Exception):
    """业务异常基类。"""

    code: int = 5000
    http_status: int = 500
    message: str = "服务器内部错误"

    def __init__(self, message: str | None = None) -> None:
        if message:
            self.message = message
        super().__init__(self.message)


class AuthError(BusinessException):
    """未认证（1001）。"""

    code = 1001
    http_status = 401
    message = "未认证或登录已过期"


class PermissionDeniedError(BusinessException):
    """无权限（1002）。"""

    code = 1002
    http_status = 403
    message = "无权限执行该操作"


class ParamError(BusinessException):
    """参数错误（1003）。"""

    code = 1003
    http_status = 400
    message = "参数错误"


class NotFoundError(BusinessException):
    """资源不存在（1004）。"""

    code = 1004
    http_status = 404
    message = "资源不存在"


class TaskAlreadyExistsError(BusinessException):
    """任务已存在（2001）。"""

    code = 2001
    http_status = 409
    message = "任务已存在"


class ConcurrencyLimitError(BusinessException):
    """并发限制（2002）。"""

    code = 2002
    http_status = 429
    message = "并发任务数已达上限"


class RateLimitError(BusinessException):
    """请求频率限制（2003）。"""

    code = 2003
    http_status = 429
    message = "请求过于频繁"


class ModelCallError(BusinessException):
    """模型调用失败（3001）。"""

    code = 3001
    http_status = 502
    message = "模型调用失败"


class FetchError(BusinessException):
    """数据抓取失败（3002）。"""

    code = 3002
    http_status = 502
    message = "数据抓取失败"


class EmailSendError(BusinessException):
    """邮件发送失败（4001）。"""

    code = 4001
    http_status = 502
    message = "邮件发送失败"


def _error_body(code: int, message: str) -> dict:
    return {"code": code, "message": message, "data": None}


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，保证所有错误均返回统一响应格式。"""

    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        return JSONResponse(
            status_code=exc.http_status, content=_error_body(exc.code, exc.message)
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content=_error_body(1003, f"参数校验失败: {exc.errors()[0].get('msg', '')}"
                                 if exc.errors() else "参数校验失败"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.status_code, str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # 保留服务端错误可见性：记录完整 traceback 供排查，但对外仅返回泛型消息
        logger.exception("Unhandled server error: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=_error_body(5000, "服务器内部错误"),
        )
