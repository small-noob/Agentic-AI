"""Token accounting.

Two numbers matter here and they are not the same number.

* ``count_*`` is an ESTIMATE computed locally. The harness needs it *before* a
  request is sent, because a budget check that runs after the call is not a
  budget check - the request already went out.
* ``usage.prompt_tokens`` is the TRUTH the provider reports after the call.
  ``TokenDrift`` records the gap between the two so the estimate can be audited.

With ``tiktoken`` installed we use ``cl100k_base``. That is not GLM's tokenizer,
so it is still an estimate - just a much better one. Without tiktoken we fall
back to a character-class estimator: roughly one token per CJK character and
one per four ASCII characters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

try:  # pragma: no cover - depends on the environment
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover - fallback is the classroom default
    _ENCODING = None


_CJK = re.compile(r"[　-鿿豈-﫿＀-￯]")

# Every provider bills a per-message overhead for the role wrapper. Ignoring it
# makes a 20-message history look ~80 tokens cheaper than it really is.
PER_MESSAGE_OVERHEAD = 4


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _ENCODING is not None:
        return len(_ENCODING.encode(str(text), disallowed_special=()))
    text = str(text)
    cjk = len(_CJK.findall(text))
    return max(1, cjk + (len(text) - cjk) // 4)


def count_message(message: dict) -> int:
    return count_tokens(message.get("content", "")) + PER_MESSAGE_OVERHEAD


def count_messages(messages: list[dict]) -> int:
    return sum(count_message(m) for m in messages)


def estimator_name() -> str:
    return "tiktoken/cl100k_base" if _ENCODING is not None else "charclass-fallback"


@dataclass
class TokenDrift:
    """Compares local estimates against the provider's reported usage.

    A budget built on an estimator that runs 15% low is a budget that overflows
    in production. This table is what tells you which way yours leans.
    """

    samples: list[tuple[int, int]] = field(default_factory=list)

    def record(self, estimated: int, reported: int | None) -> None:
        if reported:
            self.samples.append((estimated, reported))

    @property
    def mean_relative_error(self) -> float:
        if not self.samples:
            return 0.0
        return sum(abs(e - r) / r for e, r in self.samples) / len(self.samples)

    def summary(self) -> str:
        if not self.samples:
            return f"estimator={estimator_name()} (no provider usage seen)"
        worst = max(self.samples, key=lambda s: abs(s[0] - s[1]))
        return (
            f"estimator={estimator_name()} n={len(self.samples)} "
            f"mean_rel_err={self.mean_relative_error:.1%} "
            f"worst=est {worst[0]} vs actual {worst[1]}"
        )
