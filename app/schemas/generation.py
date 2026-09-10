"""报告生成模块请求/响应模式。"""
import uuid

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    """POST /reports/{id}/generate 请求体。"""

    force: bool = False  # true=强制重新生成（忽略“配置未变则覆盖”的规则）
    style_id: uuid.UUID | None = None  # 指定本次生成使用的风格（为空沿用报告当前风格）


class GenerateData(BaseModel):
    """触发生成响应数据。"""

    task_id: uuid.UUID
    status: str


class ProgressEvent(BaseModel):
    """生成进度事件（WebSocket 推送）。"""

    phase: str  # init / fetching / generating / storing / complete / failed / terminated
    progress: int
    message: str
    version: int | None = None
