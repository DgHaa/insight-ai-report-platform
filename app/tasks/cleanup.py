"""临时文件清理 Celery 任务（周期执行，清理过期导出文件）。"""
import logging
import os
import time
from pathlib import Path

from app.core.config import settings
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_SECONDS = 3600  # 默认清理 1 小时前的临时文件


@celery_app.task(name="app.tasks.cleanup.cleanup_temp_files")
def cleanup_temp_files(max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS) -> dict:
    """清理临时导出目录下过期的文件。

    注意：CELERY 任务在独立进程中执行，需确保 TEMP_DIR 为共享目录
    （Docker 部署时挂载共享 volume）。
    """
    temp_dir = Path(settings.TEMP_DIR)
    if not temp_dir.exists():
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("临时目录创建失败: %s（%s）", temp_dir, exc)
            return {"removed": 0, "error": str(exc)}
        return {"removed": 0}

    now = time.time()
    removed = 0
    freed_bytes = 0
    for path in temp_dir.iterdir():
        try:
            if path.is_file() and (now - path.stat().st_mtime) > max_age_seconds:
                freed_bytes += path.stat().st_size
                path.unlink()
                removed += 1
                logger.info("清理临时文件: %s", path)
        except OSError as exc:
            logger.warning("清理失败 %s: %s", path, exc)
    return {"removed": removed, "freed_bytes": freed_bytes, "max_age_seconds": max_age_seconds}


def write_temp_export(filename: str, content: bytes) -> str:
    """写入临时导出文件（供导出模块/邮件附件复用），返回完整路径。"""
    temp_dir = Path(settings.TEMP_DIR)
    temp_dir.mkdir(parents=True, exist_ok=True)
    safe_name = os.path.basename(filename)
    path = temp_dir / safe_name
    path.write_bytes(content)
    return str(path)
