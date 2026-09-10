"""敏感字段脱敏工具（统一全站掩码规则）。"""
from app.core.crypto import decrypt_value

# 读取时不应回显的敏感请求头（大小写不敏感匹配）
SENSITIVE_HEADER_KEYS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
    "x-auth-token",
}


def mask_secret(value: str | None, head: int = 2, tail: int = 4, mask: str = "****") -> str | None:
    """脱敏字符串：保留首尾若干字符，中间用掩码替换。

    示例：mask_secret("token-abcdef1234") -> "to****1234"
    """
    if not value:
        return value
    if len(value) <= head + tail:
        return mask
    return value[:head] + mask + value[-tail:]


def mask_custom_headers(headers: dict | None) -> dict | None:
    """返回脱敏后的自定义请求头：敏感头的 value 替换为 <redacted>，其余原样。"""
    if not headers:
        return headers
    return {
        k: ("<redacted>" if str(k).lower() in SENSITIVE_HEADER_KEYS else v)
        for k, v in headers.items()
    }


def safe_decrypt(value: str | None) -> str | None:
    """解密后用统一掩码脱敏（用于列表/详情展示场景）。"""
    return mask_secret(decrypt_value(value))
