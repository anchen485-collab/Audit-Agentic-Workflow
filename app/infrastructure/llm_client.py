import json
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.domain.errors import LLMOutputError


class LLMClient(Protocol):
    """LLM 客户端协议，方便 mock 客户端和真实客户端切换。"""

    def complete_json(self, prompt: str) -> dict[str, Any]:
        """根据 prompt 返回结构化 JSON。"""


class MockLLMClient:
    """测试和本地开发使用的 mock LLM 客户端。"""

    def __init__(self, response: dict[str, Any] | None = None):
        self.response = response or {
            "action": "needs_human_review",
            "confidence": 50,
            "risk_score": 60,
            "reason": "mock LLM 默认转人工复核。",
            "suggestion": "请人工确认。",
            "needs_review": True,
        }

    def complete_json(self, prompt: str) -> dict[str, Any]:
        """返回预设 JSON，避免单元测试访问真实网络。"""
        return self.response


class OpenAICompatibleLLMClient:
    """OpenAI-compatible chat completions 客户端。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 30,
        http_post: Callable[..., httpx.Response] = httpx.post,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.http_post = http_post

    def complete_json(self, prompt: str) -> dict[str, Any]:
        """调用模型并把响应内容解析为 JSON。"""
        raw_text = self.complete_text(prompt)

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as error:
            raise LLMOutputError(f"LLM 输出不是合法 JSON：{raw_text}") from error

        if not isinstance(data, dict):
            raise LLMOutputError("LLM 输出 JSON 顶层必须是对象。")

        return data

    def complete_text(self, prompt: str) -> str:
        """调用 OpenAI-compatible chat completions 接口。"""
        response = self.http_post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是企业录入审批助手，只能输出合法 JSON，不要输出 Markdown。",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "temperature": 0,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]
