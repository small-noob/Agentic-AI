"""Zhipu AI HTTP client. Copied from 01Introduction with two additions.

1. ``chat`` returns a ``ChatResponse`` carrying the provider's reported ``usage``,
   because the harness audits its own token estimates against it.
2. Every call takes a ``purpose`` label ("agent" / "extract" / "reconcile" /
   "compact") so the trace can report what the API budget was actually spent on.

Standard library only.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-4-flash-250414"

PURPOSES = ("agent", "extract", "reconcile", "revoke", "compact")


@dataclass
class ChatResponse:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def __str__(self) -> str:
        return self.text


class ChatClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.2,
        max_tokens: int = 700,
        purpose: str = "agent",
    ) -> ChatResponse: ...


@dataclass
class CallLog:
    """Per-purpose API accounting, reported at the end of a run."""

    calls: Counter = field(default_factory=Counter)
    prompt_tokens: Counter = field(default_factory=Counter)

    def record(self, purpose: str, response: ChatResponse) -> None:
        self.calls[purpose] += 1
        self.prompt_tokens[purpose] += response.prompt_tokens or 0

    @property
    def total_calls(self) -> int:
        return sum(self.calls.values())

    @property
    def total_prompt_tokens(self) -> int:
        return sum(self.prompt_tokens.values())

    def summary(self) -> str:
        if not self.calls:
            return "no API calls"
        parts = [
            f"{purpose} x{self.calls[purpose]} ({self.prompt_tokens[purpose]:,}t)"
            for purpose in PURPOSES
            if self.calls[purpose]
        ]
        return (
            f"{self.total_calls} calls, {self.total_prompt_tokens:,} prompt tokens  ["
            + ", ".join(parts)
            + "]"
        )


@dataclass
class ZhipuClient:
    api_key: str
    endpoint: str = DEFAULT_ENDPOINT
    timeout: int = 60
    max_retries: int = 2
    log: CallLog = field(default_factory=CallLog)

    @classmethod
    def from_env(cls) -> "ZhipuClient":
        api_key = os.getenv("ZAI_API_KEY") or os.getenv("ZHIPU_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Missing API key. Set ZAI_API_KEY (or ZHIPU_API_KEY) in your "
                "shell before starting Jupyter; never hard-code a key in a "
                "cell or a file."
            )
        return cls(api_key=api_key, endpoint=os.getenv("ZAI_BASE_URL", DEFAULT_ENDPOINT))

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.2,
        max_tokens: int = 700,
        purpose: str = "agent",
    ) -> ChatResponse:
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
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False)
                usage = body.get("usage") or {}
                result = ChatResponse(
                    text=content,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                )
                self.log.record(purpose, result)
                return result
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:400]
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Zhipu API HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError,
                    http.client.HTTPException) as exc:
                # RemoteDisconnected ("remote end closed connection without
                # response") is an HTTPException, not a URLError - observed in
                # a real run killing session 2 mid-flight. Same retry policy.
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Zhipu API connection failed: {exc}") from exc

        raise RuntimeError("Zhipu API request failed after retries")
