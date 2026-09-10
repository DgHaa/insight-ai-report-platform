"""出站 URL 安全校验（SSRF 防护）。

防止任意登录用户通过「模型 endpoint」或「报告数据源抓取 URL」让服务器
访问内网/云元数据等受限地址。

策略：
- 仅允许 http / https 协议；
- 拒绝 IP 字面量落在私有/回环/链路本地/保留/组播网段；
- 对域名做 DNS 解析，解析结果若落在上述受限网段同样拒绝
  （可拦截「域名指向内网 IP」的常见 SSRF 手法）。

注意：本函数会发起一次 DNS 解析（阻塞），异步调用方请用
``asyncio.to_thread(validate_outbound_url, url)`` 包裹，避免阻塞事件循环。
"""
import ipaddress
import socket

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(Exception):
    """目标 URL 被判定为不安全（SSRF 风险）。"""


def _ip_is_restricted(ip: str) -> bool:
    """判断 IP 是否属于受限网段（私有/回环/链路本地/保留/组播）。"""
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    )


def _resolve_host(host: str) -> list[str]:
    """解析域名到 IP 列表（仅用于校验，失败返回空列表）。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, OSError):
        return []
    ips: set[str] = set()
    for info in infos:
        ip = info[4][0]
        ips.add(ip.split("%")[0])
    return list(ips)


def validate_outbound_url(url: str) -> str:
    """校验出站 URL 是否安全。安全则返回原 URL，否则抛 UnsafeURLError。"""
    if not url or not isinstance(url, str):
        raise UnsafeURLError("URL 不能为空")
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"不允许的协议: {parsed.scheme or '(无)'}（仅支持 http/https）")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL 缺少主机名")

    # IP 字面量直接判定
    if _ip_is_restricted(host):
        raise UnsafeURLError("目标地址为受限内网/回环地址，已被拒绝")

    # 域名解析后再判定一次（拦截指向内网 IP 的域名）
    for ip in _resolve_host(host):
        if _ip_is_restricted(ip):
            raise UnsafeURLError("目标域名解析后为受限内网地址，已被拒绝")

    return url
