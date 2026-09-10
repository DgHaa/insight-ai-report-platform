"""外部数据抓取服务：Requests（静态页）+ Playwright（JS 渲染）双引擎。

- 智能降级：优先轻量级 Requests，失败或内容为空时自动切换 Playwright；
- 支持配置：代理（HTTP/HTTPS/SOCKS5）、Cookie、自定义 Header、超时、重试次数；
- 支持从 user_data_source_credentials 表引用用户凭证；
- 内容截断：按用户配置的最大长度截断（2000/5000/10000）。
"""
import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.concurrency import TaskControl
from app.core.crypto import decrypt_value
from app.core.exceptions import FetchError
from app.core.ssrf import UnsafeURLError, validate_outbound_url

logger = logging.getLogger(__name__)

try:
    import requests  # noqa: F401
    REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    REQUESTS_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS_AVAILABLE = True
except ImportError:  # pragma: no cover
    BS_AVAILABLE = False

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class FetchConfig:
    """单次抓取配置。"""

    proxy: str | None = None          # http/https/socks5://...
    cookies: str | dict | None = None
    headers: dict | None = None
    timeout: float = field(default_factory=lambda: settings.FETCHER_DEFAULT_TIMEOUT)
    retries: int = field(default_factory=lambda: settings.FETCHER_DEFAULT_RETRIES)
    max_length: int = field(default_factory=lambda: settings.FETCHER_DEFAULT_MAX_LENGTH)
    use_playwright: bool | None = None  # None=智能降级

    @classmethod
    def from_module(cls, module: dict) -> "FetchConfig":
        """从报告模块配置（data_sources）构建抓取配置。"""
        ds = module.get("data_sources") or {}
        grab = ds.get("grab_config") or ds.get("fetch_config") or {}
        return cls(
            proxy=grab.get("proxy") or ds.get("proxy"),
            cookies=grab.get("cookies") or ds.get("cookies"),
            headers=grab.get("custom_headers") or grab.get("headers") or ds.get("custom_headers"),
            timeout=float(grab.get("timeout", settings.FETCHER_DEFAULT_TIMEOUT)),
            retries=int(grab.get("retries", settings.FETCHER_DEFAULT_RETRIES)),
            max_length=int(grab.get("max_length", settings.FETCHER_DEFAULT_MAX_LENGTH)),
            use_playwright=grab.get("use_playwright"),
        )


@dataclass
class FetchResult:
    """抓取结果。"""

    url: str
    text: str
    final_url: str
    status_code: int | None
    engine: str  # requests / playwright / simulate
    truncated: bool = False


async def load_credential_config(db, credential_id) -> FetchConfig | None:
    """从 user_data_source_credentials 表加载凭证配置（代理/Cookie/自定义Header）。

    注意：proxy/cookies 落库为密文（app.core.crypto），使用前必须解密，
    否则会把密文当作代理地址/Cookie 值发出请求。decrypt_value 对无
    ``fernet:`` 前缀的历史明文原样返回，兼容迁移前数据。
    """
    from app.models import UserDataSourceCredential

    cred = await db.get(UserDataSourceCredential, credential_id)
    if cred is None or not cred.is_active:
        return None
    return FetchConfig(
        proxy=decrypt_value(cred.proxy) or None,
        cookies=decrypt_value(cred.cookies) or None,
        headers=cred.custom_headers or None,
    )


def _extract_text(html: str) -> str:
    """HTML → 纯文本（去除 script/style 及导航/页脚等样板噪声）。

    噪声元素会稀释有效信息并浪费 token，因此一并剥离。
    """
    if BS_AVAILABLE:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(
            [
                "script", "style", "noscript", "iframe", "template",
                "nav", "footer", "aside", "header", "form", "button", "svg",
            ]
        ):
            tag.decompose()
        text = soup.get_text("\n")
    else:  # 兜底：简易标签剥离
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ==================== 抓取结果缓存 ====================
# 同一 URL + 抓取配置在 TTL 内直接复用结果，避免跨模块/重复生成时的重复抓取。
# 进程内实现；多 worker 部署时各自持有独立缓存（语义仍正确，仅命中率下降）。
_FETCH_CACHE: dict[tuple, tuple[float, "FetchResult"]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = 500


def _cache_key(url: str, cfg: "FetchConfig") -> tuple:
    headers = cfg.headers or {}
    return (
        url,
        cfg.proxy,
        str(cfg.cookies),
        cfg.timeout,
        cfg.retries,
        cfg.max_length,
        cfg.use_playwright,
        tuple(sorted(headers.items())),
    )


def _cache_get(key: tuple) -> "FetchResult | None":
    ttl = getattr(settings, "FETCH_CACHE_TTL", 0)
    if ttl <= 0:
        return None
    now = time.monotonic()
    with _CACHE_LOCK:
        item = _FETCH_CACHE.get(key)
        if item is None:
            return None
        if now - item[0] > ttl:
            _FETCH_CACHE.pop(key, None)
            return None
        return item[1]


def _cache_put(key: tuple, result: "FetchResult") -> None:
    ttl = getattr(settings, "FETCH_CACHE_TTL", 0)
    if ttl <= 0:
        return
    now = time.monotonic()
    with _CACHE_LOCK:
        if len(_FETCH_CACHE) >= _CACHE_MAX_ENTRIES:
            expired = [
                k for k, (t, _) in _FETCH_CACHE.items() if now - t > ttl
            ]
            for k in expired:
                _FETCH_CACHE.pop(k, None)
            # 仍超容量则丢弃最早写入的
            while len(_FETCH_CACHE) >= _CACHE_MAX_ENTRIES:
                _FETCH_CACHE.pop(next(iter(_FETCH_CACHE)))
        _FETCH_CACHE[key] = (now, result)


def _truncate(text: str, max_length: int) -> tuple[str, bool]:
    """按最大长度截断内容。"""
    if max_length <= 0 or len(text) <= max_length:
        return text, False
    return text[:max_length] + "...（内容已截断）", True


def _build_proxies(proxy: str | None) -> dict | None:
    """构建 requests 代理字典（SOCKS5 需安装 requests[socks]）。"""
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _playwright_proxy(proxy: str | None) -> dict | None:
    if not proxy:
        return None
    return {"server": proxy}


def _requests_get(url: str, proxies, cookies, headers: dict, timeout: float):
    """同步 GET（在 asyncio.to_thread 中执行）。"""
    import requests

    resp = requests.get(
        url,
        proxies=proxies,
        cookies=cookies,
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp


class Fetcher:
    """双引擎抓取服务。

    策略：优先 Requests（轻量、快速）；失败/内容为空时自动降级到 Playwright
    无头浏览器（处理 JS 渲染与反爬页面）。
    """

    def __init__(
        self,
        *,
        enable_playwright: bool | None = None,
    ) -> None:
        self._enable_playwright = (
            settings.FETCHER_ENABLE_PLAYWRIGHT
            if enable_playwright is None
            else enable_playwright
        )

    # ---------------- 公共入口 ----------------

    async def fetch_url(
        self,
        url: str,
        config: FetchConfig | None = None,
        control: TaskControl | None = None,
    ) -> FetchResult:
        """抓取单个 URL（Requests → Playwright 智能降级）。"""
        cfg = config or FetchConfig()
        if control is not None:
            control.check()

        # SSRF 防护：拒绝指向内网/回环/云元数据等受限地址的数据源 URL
        try:
            await asyncio.to_thread(validate_outbound_url, url)
        except UnsafeURLError as exc:
            raise FetchError(f"抓取地址不安全，已被拒绝: {exc}") from exc

        # TTL 缓存：同一 URL+配置短时间内的重复抓取直接复用
        key = _cache_key(url, cfg)
        cached = _cache_get(key)
        if cached is not None:
            logger.info("抓取命中缓存（TTL=%ss）: %s", settings.FETCH_CACHE_TTL, url)
            return cached

        # 1) Requests 引擎
        if not cfg.use_playwright:
            try:
                result = await self._fetch_requests(url, cfg, control)
                if result.text.strip():
                    _cache_put(key, result)
                    return result
                logger.info("Requests 抓取内容为空，降级到 Playwright: %s", url)
            except FetchError:
                if cfg.use_playwright is False or not self._enable_playwright:
                    raise
                logger.info("Requests 抓取失败，降级到 Playwright: %s", url)

        # 2) Playwright 引擎（JS 渲染）
        result = await self._fetch_playwright(url, cfg, control)
        if result.text.strip():
            _cache_put(key, result)
        return result

    # ---------------- Requests 引擎 ----------------

    async def _fetch_requests(
        self, url: str, cfg: FetchConfig, control: TaskControl | None
    ) -> FetchResult:
        if not REQUESTS_AVAILABLE:
            raise FetchError("requests 库未安装")

        proxies = _build_proxies(cfg.proxy)
        cookies = cfg.cookies
        headers = dict(cfg.headers or {})
        headers.setdefault("User-Agent", _DEFAULT_UA)

        last_exc: Exception | None = None
        for attempt in range(1, cfg.retries + 2):
            if control is not None:
                control.check()
            try:
                resp = await asyncio.to_thread(
                    _requests_get, url, proxies, cookies, headers, cfg.timeout
                )
                text = _extract_text(resp.text)
                text, truncated = _truncate(text, cfg.max_length)
                return FetchResult(
                    url=url,
                    text=text,
                    final_url=resp.url or url,
                    status_code=resp.status_code,
                    engine="requests",
                    truncated=truncated,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt <= cfg.retries:
                    await asyncio.sleep(0.5 * attempt)
        raise FetchError(f"Requests 抓取失败: {url}（{last_exc}）")

    # ---------------- Playwright 引擎 ----------------

    async def _fetch_playwright(
        self, url: str, cfg: FetchConfig, control: TaskControl | None
    ) -> FetchResult:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise FetchError(
                "Playwright 未安装，无法进行 JS 渲染抓取（pip install playwright && playwright install chromium）"
            )

        last_exc: Exception | None = None
        for attempt in range(1, cfg.retries + 2):
            if control is not None:
                control.check()
            html = ""
            try:
                async with async_playwright() as p:
                    launch_kwargs: dict = {"headless": True}
                    proxy = _playwright_proxy(cfg.proxy)
                    if proxy:
                        launch_kwargs["proxy"] = proxy
                    browser = await p.chromium.launch(**launch_kwargs)
                    try:
                        context = await browser.new_context(
                            user_agent=_DEFAULT_UA,
                            extra_http_headers=cfg.headers or None,
                        )
                        if isinstance(cfg.cookies, dict) and cfg.cookies:
                            await context.add_cookies(
                                [
                                    {"name": k, "value": v, "url": url}
                                    for k, v in cfg.cookies.items()
                                ]
                            )
                        page = await context.new_page()
                        await page.goto(
                            url,
                            timeout=int(cfg.timeout * 1000),
                            wait_until="domcontentloaded",
                        )
                        if control is not None:
                            control.check()
                        html = await page.content()
                        await context.close()
                    finally:
                        await browser.close()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt <= cfg.retries:
                    await asyncio.sleep(0.5 * attempt)
                continue

            text = _extract_text(html)
            text, truncated = _truncate(text, cfg.max_length)
            if text.strip():
                return FetchResult(
                    url=url,
                    text=text,
                    final_url=url,
                    status_code=None,
                    engine="playwright",
                    truncated=truncated,
                )

        raise FetchError(f"Playwright 抓取失败: {url}（{last_exc}）")

