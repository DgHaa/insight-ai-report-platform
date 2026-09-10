"""模型调用服务：多 Provider 适配 + Token 统计 + 延迟测量。

支持的 Provider（设计文档 1.3.4《模型接入模块》）：
- ascend   ：华为云 MaaS API / MindIE 推理引擎（OpenAI 兼容格式）
- openai   ：标准 OpenAI API
- anthropic：Claude Messages API
- custom   ：兼容 OpenAI 格式的自定义 API

成本日志：调用成功后由上层通过 cost_logger 记录（unit_price 由用户自填）。
"""
import asyncio
import logging
import random
import time
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.exceptions import ModelCallError
from app.core.ssrf import UnsafeURLError, validate_outbound_url

logger = logging.getLogger(__name__)

PROVIDERS = ["ascend", "openai", "anthropic", "custom"]

# 共享 system 设定：角色 + 语言 + 输出规范。所有调用复用，便于厂商 prompt caching。
_SYSTEM_PROMPT = (
    "你是一名严谨的中文行业研究分析师，擅长为企业管理层撰写洞察报告。"
    "要求：1) 始终使用简体中文；2) 使用 Markdown 组织内容；"
    "3) 结论须有依据，避免无来源的主观断言；"
    "4) 除非明确要求，不要输出“好的，以下是…”之类的客套开场白，直接给出分析内容。"
)


class ModelOutputTruncatedError(ModelCallError):
    """输出被 max_tokens 截断（推理模型预算不足、最终内容为空）。

    此类错误重试必再次失败（相同 prompt + 相同过小 max_tokens），调用方不应重试。
    """


@dataclass
class ModelCallResult:
    """一次模型调用的结果。"""

    text: str
    provider: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    usage: dict | None = None


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数（模型未返回 usage 时的兜底）：约 4 字符/token。"""
    return max(1, len(text) // 4 + 1)


def _is_reasoning_model(model_name: str | None) -> bool:
    """根据名称关键字判断是否为推理模型（思考会占用输出预算）。"""
    hints = getattr(settings, "REASONING_MODEL_HINTS", None) or []
    name = (model_name or "").lower()
    return any(h and h.lower() in name for h in hints)


async def _post_json(url: str, payload: dict, headers: dict, timeout: float | None) -> dict:
    """POST JSON 并返回响应 dict。"""
    try:
        async with httpx.AsyncClient(
            timeout=timeout or settings.MODEL_CALL_TIMEOUT
        ) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise ModelCallError(f"模型调用超时: {type(exc).__name__}") from exc
    except httpx.HTTPError as exc:
        raise ModelCallError(f"模型调用网络错误: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        hint = ""
        if resp.status_code == 404 and not (
            "/chat/completions" in url or "/messages" in url
        ):
            hint = "（404 常见原因：endpoint 缺少 API 路径，如 /chat/completions）"
        # 注意：不回显上游响应体（避免 SSRF 场景下泄露内网返回内容）
        raise ModelCallError(
            f"模型接口返回状态码 {resp.status_code} (POST {url}){hint}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise ModelCallError("模型响应不是合法 JSON") from exc


class _BaseAdapter:
    """Provider 适配器基类：统一调用并返回 (text, usage)。"""

    provider: str = "custom"

    async def call(
        self,
        *,
        endpoint: str,
        api_key: str | None,
        model_name: str,
        prompt: str,
        temperature: float | None,
        max_tokens: int | None,
        timeout: float | None,
    ) -> tuple[str, dict | None]:
        raise NotImplementedError


class _OpenAICompatibleAdapter(_BaseAdapter):
    """OpenAI / 昇腾 MaaS / MindIE / 自定义（OpenAI 兼容格式）。"""

    provider = "openai"

    async def call(
        self, *, endpoint, api_key, model_name, prompt, temperature, max_tokens, timeout, system=None
    ) -> tuple[str, dict | None]:
        system_text = _SYSTEM_PROMPT
        if system:
            system_text = system_text + "\n" + system
        messages = [{"role": "system", "content": system_text}]
        if settings.MODEL_PROMPT_CACHING:
            # 仅对已知支持 cache_control 的厂商生效（如 DeepSeek/Anthropic 风格）。
            # 开启后 system 前缀被缓存，跨模块/多次调用可命中，省 token 且加速。
            messages[0]["cache_control"] = {"type": "ephemeral"}
        messages.append({"role": "user", "content": prompt})
        payload: dict = {
            "model": model_name,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        data = await _post_json(endpoint, payload, headers, timeout)
        try:
            choice = data["choices"][0]
            message = choice["message"]
            text = message.get("content") or ""
        except (KeyError, IndexError, TypeError):
            raise ModelCallError("模型响应格式不符合 OpenAI 规范")
        if not text.strip() and choice.get("finish_reason") == "length":
            # 推理模型（如 deepseek reasoner 系）会先输出 reasoning_content，
            # 当 max_tokens 过小时推理过程即耗尽输出长度，最终答案为空字符串。
            # 这是不可重试错误：相同 prompt + 相同过小 max_tokens 必再次失败。
            raise ModelOutputTruncatedError(
                "模型输出被 max_tokens 上限截断（finish_reason=length），最终内容为空。"
                "请调大模块配置中的 max_tokens 参数后重试。"
            )
        return text, data.get("usage")


class _AnthropicAdapter(_BaseAdapter):
    """Anthropic Claude Messages API。"""

    provider = "anthropic"

    async def call(
        self, *, endpoint, api_key, model_name, prompt, temperature, max_tokens, timeout, system=None
    ) -> tuple[str, dict | None]:
        url = endpoint or "https://api.anthropic.com/v1/messages"
        system_text = _SYSTEM_PROMPT
        if system:
            system_text = system_text + "\n" + system
        payload: dict = {
            "model": model_name,
            "max_tokens": max_tokens or 1024,
            "system": system_text,
            "messages": [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            payload["temperature"] = temperature

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key or "",
            "anthropic-version": "2023-06-01",
        }
        data = await _post_json(url, payload, headers, timeout)
        try:
            text = "".join(
                block.get("text", "")
                for block in data.get("content", [])
                if block.get("type") == "text"
            )
        except Exception as exc:  # noqa: BLE001
            raise ModelCallError("Anthropic 响应格式解析失败") from exc
        return text, data.get("usage")


# 昇腾 MaaS / MindIE 与 OpenAI 兼容格式一致
ADAPTERS: dict[str, type[_BaseAdapter]] = {
    "openai": _OpenAICompatibleAdapter,
    "custom": _OpenAICompatibleAdapter,
    "ascend": _OpenAICompatibleAdapter,
    "anthropic": _AnthropicAdapter,
}


class ModelClient:
    """统一模型调用客户端。"""

    async def call(
        self,
        *,
        provider: str,
        endpoint: str,
        api_key: str | None,
        model_name: str,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        system: str | None = None,
    ) -> ModelCallResult:
        adapter_cls = ADAPTERS.get((provider or "custom").lower())
        if adapter_cls is None:
            raise ModelCallError(f"不支持的模型提供商: {provider}")

        # SSRF 防护：拒绝指向内网/回环/云元数据等受限地址的 endpoint
        try:
            if endpoint:
                await asyncio.to_thread(validate_outbound_url, endpoint)
        except UnsafeURLError as exc:
            raise ModelCallError(f"模型 endpoint 不安全，已被拒绝: {exc}") from exc

        # 安全上限：按模型类别裁剪/抬升 max_tokens。
        # - 非推理模型：超过较紧上限则裁剪，防空耗 token；
        # - 推理模型：思考过程占用输出预算，若请求值过小会被耗尽导致答案为空，
        #   因此抬升到安全下限（与历史 32000/16000 实践一致）。
        reasoning = _is_reasoning_model(model_name)
        if reasoning:
            floor = int(settings.MODEL_REASONING_MIN_TOKENS or 16000)
            if max_tokens is None or max_tokens < floor:
                logger.info(
                    "推理模型 max_tokens %s 过小，已抬升到安全下限 %s 防空耗截断",
                    max_tokens, floor,
                )
                max_tokens = floor
        else:
            cap = int(settings.MODEL_MAX_TOKENS_CAP or 0)
            if cap and max_tokens and max_tokens > cap:
                logger.info("max_tokens %s 超过安全上限 %s，已裁剪", max_tokens, cap)
                max_tokens = cap

        start = time.monotonic()
        text, usage = await adapter_cls().call(
            endpoint=endpoint,
            api_key=api_key,
            model_name=model_name,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            system=system,
        )
        latency_ms = round((time.monotonic() - start) * 1000, 1)

        usage = usage or {}
        prompt_tokens = int(usage.get("prompt_tokens") or _estimate_tokens(prompt))
        completion_tokens = int(usage.get("completion_tokens") or _estimate_tokens(text))
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))

        return ModelCallResult(
            text=text,
            provider=provider,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            usage=usage,
        )

    async def test_connection(
        self,
        *,
        provider: str = "custom",
        endpoint: str,
        api_key: str | None,
        model_name: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> tuple[bool, float, str]:
        """轻量连接测试，返回 (是否成功, 延迟ms, 消息)。

        模拟模式（GENERATION_SIMULATE=True，演示/验收环境）：不发起真实网络请求，
        直接返回模拟成功——演示环境配置的 endpoint 均为示例地址（example.com），
        真实请求必然失败，模拟返回便于演示“测试连接”流程。
        生产环境（GENERATION_SIMULATE=False）：发起真实请求校验连接。
        """
        if settings.GENERATION_SIMULATE:
            latency_ms = round(random.uniform(50, 300), 1)
            return True, latency_ms, "连接成功（模拟模式，未发起真实请求）"

        start = time.monotonic()
        try:
            result = await self.call(
                provider=provider,
                endpoint=endpoint,
                api_key=api_key,
                model_name=model_name,
                prompt="ping",
                temperature=temperature,
                max_tokens=max_tokens or 5,
                timeout=timeout or settings.MODEL_TEST_TIMEOUT,
            )
            return True, result.latency_ms, "连接成功"
        except ModelCallError as exc:
            return False, round((time.monotonic() - start) * 1000, 1), str(exc)
        except Exception as exc:  # noqa: BLE001
            return False, 0.0, f"未知错误: {exc}"


# ==================== 兼容旧接口 ====================
_model_client = ModelClient()


async def call_model(
    *,
    endpoint: str,
    api_key: str | None,
    model_name: str,
    prompt: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """兼容旧调用：按 custom（OpenAI 兼容格式）调用，仅返回文本。"""
    result = await _model_client.call(
        provider="custom",
        endpoint=endpoint,
        api_key=api_key,
        model_name=model_name,
        prompt=prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return result.text


async def test_model_connection(
    *,
    endpoint: str,
    api_key: str | None,
    model_name: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[bool, float, str]:
    """兼容旧调用：按 custom 提供商测试连接。"""
    return await _model_client.test_connection(
        provider="custom",
        endpoint=endpoint,
        api_key=api_key,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )
