"""Minimal Zhipu AI HTTP client using only the Python standard library."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


DEFAULT_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = os.getenv("ZAI_MODEL", "glm-4-flash-250414")


class ChatClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 900,
    ) -> str: ...


@dataclass
class ZhipuClient:
    api_key: str
    endpoint: str = DEFAULT_ENDPOINT
    timeout: int = 60
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "ZhipuClient":
        api_key = os.getenv("ZAI_API_KEY") or os.getenv("ZHIPU_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Missing API key. Set ZAI_API_KEY in your shell; do not hard-code it."
            )
        return cls(
            api_key=api_key,
            endpoint=os.getenv("ZAI_BASE_URL", DEFAULT_ENDPOINT),
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.2,
        max_tokens: int = 900,
    ) -> str:
        payload = json.dumps(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                if isinstance(content, str):
                    return content
                return json.dumps(content, ensure_ascii=False)
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")[:500]
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Zhipu API HTTP {exc.code}: {error_body}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Zhipu API connection failed: {exc}") from exc

        raise RuntimeError("Zhipu API request failed after retries")
