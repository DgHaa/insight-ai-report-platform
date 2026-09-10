"""轻量级静态加密工具（at-rest 凭据加密）。

基于 SECRET_KEY 派生 Fernet 密钥，对落库的敏感字段（第三方数据源 proxy/cookies、
SMTP 口令、模型 API Key 等）做对称加密，避免明文入库。

约定：密文统一以 ``fernet:`` 前缀存储，便于与历史明文数据区分：
- 写入：encrypt_value(明文) -> "fernet:<token>"
- 读取：decrypt_value("fernet:<token>") -> 明文
- 读取历史明文（无前缀）：原样返回，兼容迁移前数据

注意：密钥由 SECRET_KEY 派生，因此 SECRET_KEY 变更后旧密文将无法解密，
需重新录入凭据。生产务必使用强随机且稳定的 SECRET_KEY。
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet

from app.core.config import settings

logger = logging.getLogger(__name__)

_PREFIX = "fernet:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_value(plaintext: str | None) -> str | None:
    """加密明文；None 透传；空字符串也会加密存储。"""
    if plaintext is None:
        return None
    token = _fernet().encrypt(plaintext.encode("utf-8"))
    return _PREFIX + token.decode("ascii")


def decrypt_value(ciphertext: str | None) -> str | None:
    """解密密文；无前缀视为历史明文直接返回；解密失败记录告警并返回空串。"""
    if ciphertext is None:
        return None
    if not ciphertext.startswith(_PREFIX):
        # 兼容迁移前的明文数据
        return ciphertext
    try:
        token = ciphertext[len(_PREFIX):].encode("ascii")
        return _fernet().decrypt(token).decode("utf-8")
    except Exception:  # noqa: BLE001
        logger.warning("凭据解密失败（可能 SECRET_KEY 已变更），返回空值")
        return ""
