"""DeepSeek API客户端封装"""

import json
import logging
import re
from typing import Any

import httpx
from openai import OpenAI
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.settings import settings

logger = logging.getLogger(__name__)


class DeepSeekClient:
    """DeepSeek API客户端

    封装API调用，支持：
    - JSON输出模式
    - 自动重试
    - 错误处理
    - 前缀缓���优化
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_retries: int | None = None,
        timeout: int | None = None,
    ):
        self.api_key = api_key or settings.deepseek_api_key
        self.base_url = base_url or settings.deepseek_base_url
        self.model = model or settings.deepseek_model
        self.max_retries = max_retries or settings.max_retries
        self.timeout = timeout or settings.request_timeout

        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=60.0),
        )

        # 失败兜底：主LLM失败时自动切换到fallback（通常是DeepSeek线上API）
        self.fallback_enabled = settings.llm_fallback_enabled
        self.fallback_api_key = settings.llm_fallback_api_key
        self.fallback_base_url = settings.llm_fallback_base_url
        self.fallback_model = settings.llm_fallback_model
        self.fallback_reasoner_model = settings.llm_fallback_reasoner_model
        self._fallback_client: OpenAI | None = None
        if self.fallback_enabled and self.fallback_api_key:
            self._fallback_client = OpenAI(
                api_key=self.fallback_api_key,
                base_url=self.fallback_base_url,
                timeout=httpx.Timeout(self.timeout, connect=60.0),
            )
        elif self.fallback_enabled:
            logger.warning("已启用fallback但未配置LLM_FALLBACK_API_KEY，fallback不可用")

        # 统计信息
        self.total_calls = 0
        self.total_tokens = 0
        self.cache_hits = 0
        self.fallback_calls = 0
        self.errors: dict[str, int] = {}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((httpx.TimeoutException, ConnectionError)),
    )
    def _call_api(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        json_mode: bool = True,
        use_reasoner: bool = False,
    ) -> str:
        """底层API调用"""
        return self._chat_with_client(
            client=self._client,
            model=self.deepseek_reasoner_model if use_reasoner else self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            is_fallback=False,
        )

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, ConnectionError)),
    )
    def _call_api_fallback(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        json_mode: bool = True,
        use_reasoner: bool = False,
    ) -> str:
        if self._fallback_client is None:
            raise RuntimeError("fallback client is not configured")

        return self._chat_with_client(
            client=self._fallback_client,
            model=self.fallback_reasoner_model if use_reasoner else self.fallback_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            is_fallback=True,
        )

    def _chat_with_client(
        self,
        *,
        client: OpenAI,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        is_fallback: bool,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            self.total_calls += 1
            if is_fallback:
                self.fallback_calls += 1

            response = client.chat.completions.create(**kwargs)

            if response.usage:
                self.total_tokens += response.usage.total_tokens
                if hasattr(response.usage, "prompt_cache_hit_tokens"):
                    self.cache_hits += response.usage.prompt_cache_hit_tokens

            content = response.choices[0].message.content
            if json_mode and not content:
                logger.warning("JSON模式返回空内容，准备重试")
                raise ValueError("Empty JSON response")
            return content or ""

        except Exception as e:
            error_code = getattr(e, "status_code", type(e).__name__)
            self.errors[str(error_code)] = self.errors.get(str(error_code), 0) + 1

            if hasattr(e, "status_code") and 400 <= e.status_code < 500:
                if e.status_code in (401, 402):
                    logger.error(f"API认证/余额错误: {e}")
                raise

            logger.error(f"{'fallback' if is_fallback else 'primary'} API调用失败: {e}")
            raise

    @property
    def deepseek_reasoner_model(self) -> str:
        return settings.deepseek_reasoner_model

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        json_mode: bool = False,
        use_reasoner: bool = False,
    ) -> str:
        """调用API

        Args:
            system_prompt: 系统提示（稳定前缀，利于缓存）
            user_prompt: 用户提示（可变部分）
            temperature: 温度参数
            max_tokens: 最大输出token
            json_mode: 是否使用JSON输出模式（prompt必须包含json关键词）
            use_reasoner: 是否使用reasoner模型

        Returns:
            API返回的文本内容
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            return self._call_api(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                use_reasoner=use_reasoner,
            )
        except Exception:
            if self._fallback_client is not None:
                logger.warning("主LLM调用失败，切换fallback模型重试")
                return self._call_api_fallback(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    use_reasoner=use_reasoner,
                )
            raise

    def call_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel] | None = None,
        *,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        use_reasoner: bool = False,
    ) -> dict[str, Any]:
        """调用API并解析JSON响应

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            response_model: 可选的Pydantic模型用于验证
            temperature: 温度参数
            max_tokens: 最大输出token
            use_reasoner: 是否使用reasoner模型

        Returns:
            解析后的JSON字典
        """
        parse_attempts = 3
        last_error: Exception | None = None
        last_content = ""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for attempt in range(1, parse_attempts + 1):
            try:
                content = self._call_api(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=True,
                    use_reasoner=use_reasoner,
                )
            except Exception as e:
                last_error = e
                if attempt < parse_attempts:
                    logger.warning(f"主LLM请求失败，重试中 ({attempt}/{parse_attempts})")
                continue

            last_content = content
            data = self._try_parse_json(content)
            if data is not None:
                validated = self._validate_json_data(data, response_model)
                if validated is not None:
                    return validated
                last_error = ValueError("JSON结构校验失败")
            else:
                last_error = ValueError("JSON解析失败")

            if attempt < parse_attempts:
                logger.warning(f"主LLM JSON解析/校验失败，重试中 ({attempt}/{parse_attempts})")

        if self._fallback_client is not None:
            logger.warning("主LLM多次失败，切换fallback模型")
            for attempt in range(1, parse_attempts + 1):
                try:
                    content = self._call_api_fallback(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=True,
                        use_reasoner=use_reasoner,
                    )
                except Exception as e:
                    last_error = e
                    if attempt < parse_attempts:
                        logger.warning(
                            f"fallback请求失败，重试中 ({attempt}/{parse_attempts})"
                        )
                    continue

                last_content = content
                data = self._try_parse_json(content)
                if data is not None:
                    validated = self._validate_json_data(data, response_model)
                    if validated is not None:
                        return validated
                    last_error = ValueError("fallback JSON结构校验失败")
                else:
                    last_error = ValueError("fallback JSON解析失败")

                if attempt < parse_attempts:
                    logger.warning(
                        f"fallback JSON解析/校验失败，重试中 ({attempt}/{parse_attempts})"
                    )

        logger.error(f"JSON解析失败: {last_error}\n原始内容: {last_content[:500]}")
        raise ValueError(f"JSON解析失败: {last_error}") from last_error

    def _validate_json_data(
        self,
        data: dict[str, Any],
        response_model: type[BaseModel] | None,
    ) -> dict[str, Any] | None:
        if response_model is None:
            return data
        try:
            validated = response_model.model_validate(data)
            return validated.model_dump()
        except ValidationError:
            return None

    def _try_parse_json(self, content: str) -> dict[str, Any] | None:
        """尝试解析JSON，支持对常见格式问题进行清洗"""
        candidates = [content, self._sanitize_json_text(content)]
        seen = set()

        for candidate in candidates:
            if not candidate:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
        return None

    def _sanitize_json_text(self, content: str) -> str:
        """清洗常见的非严格JSON输出"""
        text = content.strip()

        # 去除代码块包裹
        text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)

        # 截取首尾JSON对象
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

        # 去除尾随逗号
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return text.strip()

    def get_stats(self) -> dict[str, Any]:
        """获取调用统计"""
        return {
            "total_calls": self.total_calls,
            "fallback_calls": self.fallback_calls,
            "total_tokens": self.total_tokens,
            "cache_hits": self.cache_hits,
            "errors": self.errors,
        }


# 全局客户端实例
_client: DeepSeekClient | None = None


def get_client() -> DeepSeekClient:
    """获取全局客户端实例"""
    global _client
    if _client is None:
        _client = DeepSeekClient()
    return _client
