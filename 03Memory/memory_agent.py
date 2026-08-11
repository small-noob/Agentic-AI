"""Reference implementation - remove before distributing to students.

Two things live here:

* ``ToolsPolicy`` - Part A's baseline: when a session ends, keep nothing.
* ``MemoryPolicy`` - the reference memory pipeline. Part A uses its
  close_session (extract -> gate -> reconcile -> save); Part B's pipeline
  drives all four methods directly. ``memory_starter.py`` re-implements
  exactly these four methods as TODOs.
"""

from __future__ import annotations

import re

from react_loop import Assembled, ContextOverflow, extract_json_object
from tokens import count_messages, count_tokens

# A single message longer than this is a candidate for trimming at L1.
MAX_MESSAGE_TOKENS = 180

# How many recent turns stay verbatim when L2 compacts.
TAIL_KEEP = 4

SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),            # OpenAI / Zhipu style
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),               # AWS access key id
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),             # GitHub token
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),    # Slack token
    re.compile(r"(?i)\b(password|passwd|secret|token|api_key)\s*[=:]\s*\S+"),
]

COMPOUND_MARKERS = [" and ", " & ", "; ", "、", "\n"]

EXTRACT_PROMPT = """You extract durable facts from what a USER said in a work conversation.

Return JSON only, exactly this shape: {"facts": [{"key": "...", "value": "..."}]}

Rules:
- One fact per entry, never two. "X and Y" is two entries or none.
- Keys are SHORT generic snake_case names a later session could look up:
  "incident_file", "fine_per_violation", "log_file", "audit_day".
  Never prefix keys with a project or company name.
- Values are copied verbatim and kept atomic: a file name, a bare number, a
  date. No units, no trailing words ("250", not "250 yuan per record").
  Never compute, convert, or round.
- Keep only what stays true beyond this conversation: file locations,
  amounts, schedules, decisions, standing instructions.
- Drop greetings, acknowledgements, progress talk, and one-off requests.
- If a later statement corrects an earlier value, return only the corrected one.
- Never store a negation ("we stopped using X") as a fact - that is a
  revocation, not a fact. Return facts only.
"""

RECONCILE_PROMPT = """You judge how one candidate memory record relates to what is already stored.

Reply with JSON only: {"verdict": "ADD" | "UPDATE" | "DELETE" | "NOOP"}

- ADD: nothing is stored under this key or meaning yet.
- UPDATE: the stored value is outdated and the candidate replaces it.
- NOOP: the candidate says what is already stored.
- DELETE: the user explicitly revoked this fact this session.
Judge by meaning, not by string equality.
"""

REVOKE_PROMPT = """The user may have revoked some previously stored facts this session.

You are given the stored facts (one per line as "- key = value") and what the
user said. Reply with JSON only: {"revoked": ["key", ...]}

Rules:
- Only EXPLICIT revocations count: "stop doing X", "forget X", "X was retired",
  "we no longer use X".
- A changed value is an UPDATE, not a revocation - do not list it.
- When in doubt, return {"revoked": []}.
"""

COMPACT_PROMPT = """Summarise this slice of a conversation in at most 110 words.

Preserve every concrete value: file names, amounts, counts, dates, schedules,
and any instruction the user gave. Drop greetings, acknowledgements, and
restatements of intent. Write plain prose, no bullet points."""


def _user_text(conversation: list[dict], trim=None) -> str:
    """Flatten the USER turns only.

    The assistant's words are derived from what the user said - extract them
    and the pipeline feeds its own mistakes back into the store (a real run
    stored the agent's wrong arithmetic as if the user had said it). Tool
    Observations are skipped for the same reason.
    """
    parts = []
    for message in conversation:
        if message.get("role") != "user":
            continue
        content = str(message.get("content", ""))
        if content.startswith("Observation:"):
            continue
        if trim is not None:
            content = trim({"role": "user", "content": content})["content"]
        parts.append(content)
    return "\n\n".join(parts)


class ToolsPolicy:
    """Part A's baseline: chapter 2's agent, nothing kept between sessions."""

    name = "tools"

    def close_session(self, client, store, conversation, session_no) -> None:
        pass  # nothing survives - that is the point of this baseline


class MemoryPolicy:
    """The reference memory pipeline."""

    name = "memory"

    def __init__(self, model: str = "", tail_keep: int = TAIL_KEEP) -> None:
        self.model = model
        self.tail_keep = tail_keep
        self.compactions = 0
        self.max_ladder_rung = 0

    def _kwargs(self) -> dict:
        return {"model": self.model} if self.model else {}

    # ------------------------------------------------------------ TODO 1
    def write_memory(self, client, conversation: list[dict], session_no: int) -> list[dict]:
        transcript = _user_text(conversation, trim=self.trim_oversized)
        reply = client.chat(
            [
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": transcript},
            ],
            temperature=0.0,
            max_tokens=600,
            purpose="extract",
            **self._kwargs(),
        )
        data = extract_json_object(str(reply)) or {}
        facts = data.get("facts", [])
        if not facts:  # one retry on an empty result (observed live)
            reply = client.chat(
                [
                    {"role": "system", "content": EXTRACT_PROMPT},
                    {"role": "user", "content": transcript},
                ],
                temperature=0.0,
                max_tokens=600,
                purpose="extract",
                **self._kwargs(),
            )
            data = extract_json_object(str(reply)) or {}
            facts = data.get("facts", [])

        records = []
        for fact in facts:
            if not isinstance(fact, dict):
                records.append({"raw": fact, "source": f"session{session_no}",
                                "session": session_no})
                continue
            record = dict(fact)
            record["source"] = f"session{session_no}"
            record["session"] = session_no
            records.append(record)
        return records

    # ------------------------------------------------------------ TODO 2
    def validate_record(self, record: dict, store) -> tuple[bool, str]:
        # No API call, on purpose: a gate whose verdict can differ between
        # runs is not a gate. And no comparisons against store state - that
        # is reconcile's subject (its NOOP and UPDATE verdicts).
        if not isinstance(record, dict):
            return False, "not a record"

        blob = f'{record.get("key", "")} {record.get("value", "")}'
        for pattern in SECRET_PATTERNS:
            if pattern.search(blob):
                return False, "secret"

        key = record.get("key")
        value = record.get("value")
        if not isinstance(key, str) or not key.strip():
            return False, "missing key"
        if not isinstance(value, str) or not value.strip():
            return False, "missing value"
        if not any(ch.isalnum() for ch in value):
            return False, "placeholder value"

        if any(marker in value for marker in COMPOUND_MARKERS):
            return False, "two facts in one record"

        return True, "ok"

    # ------------------------------------------------------------ TODO 3
    def reconcile(self, client, store, records: list[dict], conversation: list[dict],
                  session_no: int) -> None:
        said = _user_text(conversation, trim=self.trim_oversized)

        # Part A - judge each candidate; the model names the relationship,
        # this code performs the operation.
        for record in records:
            key = record.get("key", "")
            existing = store.get(key)
            lines = [
                f"candidate key: {key}",
                f"candidate value: {record.get('value', '')}",
            ]
            if existing is not None:
                lines.append(f"existing value: {existing['value']}")
            lines.append("what the user said this session:")
            lines.append(said)

            reply = client.chat(
                [
                    {"role": "system", "content": RECONCILE_PROMPT},
                    {"role": "user", "content": "\n".join(lines)},
                ],
                temperature=0.0,
                max_tokens=120,
                purpose="reconcile",
                **self._kwargs(),
            )
            data = extract_json_object(str(reply)) or {}
            verdict = str(data.get("verdict", "")).strip().upper()

            # Code-side guards: the model names the relationship, but the
            # operation must stay coherent with actual state. UPDATE of a key
            # that holds nothing is an ADD; DELETE of nothing is a no-op.
            if verdict == "UPDATE" and existing is None:
                verdict = "ADD"
            if verdict == "DELETE" and existing is None:
                verdict = "NOOP"

            if verdict == "ADD":
                store.add(record)
            elif verdict == "UPDATE":
                store.supersede(key, record)
            elif verdict == "DELETE":
                store.soft_delete(key, source=record.get("source", "unknown"))
            else:
                # NOOP, or anything that is not one of the four words. Not
                # writing is the safe default: a wrong write corrupts state,
                # a skipped write only loses one fact.
                store.noop(key)

        # Part B - revocations need their own pass: "stop sending X" names a
        # key without a new value, so extraction never produces a candidate.
        self._apply_revocations(client, store, said, session_no)

    def _apply_revocations(self, client, store, said: str, session_no: int) -> None:
        current = store.all()
        if not current:
            return
        listing = "\n".join(f'- {r["key"]} = {r["value"]}' for r in current)
        reply = client.chat(
            [
                {"role": "system", "content": REVOKE_PROMPT},
                {"role": "user", "content": f"stored facts:\n{listing}\n\nwhat the user said:\n{said}"},
            ],
            temperature=0.0,
            max_tokens=120,
            purpose="revoke",
            **self._kwargs(),
        )
        data = extract_json_object(str(reply)) or {}
        for key in data.get("revoked", []) or []:
            if isinstance(key, str):
                store.soft_delete(key.strip(), source=f"session{session_no}")

    # ------------------------------------------------------------ TODO 4
    def build_context(self, client, system: str, store, history: list[dict],
                      budget: int) -> Assembled:
        ladder: list[str] = []

        def assemble(msgs: list[dict]) -> tuple[list[dict], int]:
            base = [{"role": "system", "content": system}]
            digest = store.digest()
            if digest:
                base.append({"role": "system", "content": digest})
            base.extend(msgs)
            return base, count_messages(base)

        def rung(n: int) -> None:
            self.max_ladder_rung = max(self.max_ladder_rung, n)

        # L0 - assemble everything.
        messages, used = assemble(list(history))
        ladder.append(f"L0  raw assembly {used:,}t {'OK' if used <= budget else 'OVER'}")
        rung(0)
        if used <= budget:
            return Assembled(messages, used, ladder)

        # L1 - trim oversized messages; the message stays, it just gets shorter.
        trimmed = [self.trim_oversized(m) for m in history]
        messages, new_used = assemble(trimmed)
        ladder.append(
            f"L1  trimmed oversized (-{used - new_used:,}t) "
            f"{new_used:,}t {'OK' if new_used <= budget else 'OVER'}"
        )
        rung(1)
        if new_used <= budget:
            return Assembled(messages, new_used, ladder)

        # L2 - compact everything except the last tail_keep turns.
        for keep, level in ((self.tail_keep, 2), (1, 3)):
            head, tail = trimmed[:-keep] or [], trimmed[-keep:]
            if not head:
                continue
            note = self.compact(client, head)
            compacted = [{"role": "system", "content": note}] + tail
            messages, used_now = assemble(compacted)
            ladder.append(
                f"L{level}  compact 0..N-{keep} ({len(head)} turns -> "
                f"{count_tokens(note):,}t) {used_now:,}t "
                f"{'OK' if used_now <= budget else 'OVER'}"
            )
            rung(level)
            if used_now <= budget:
                return Assembled(messages, used_now, ladder)

        raise ContextOverflow(used, budget, "even L3 cannot fit this turn")

    def trim_oversized(self, message: dict) -> dict:
        content = str(message.get("content", ""))
        if count_tokens(content) <= MAX_MESSAGE_TOKENS:
            return message
        lines = content.splitlines()
        head, tail = lines[:10], lines[-3:]
        removed = max(0, len(lines) - len(head) - len(tail))
        shorter = "\n".join(head + [f"[... {removed} lines trimmed ...]"] + tail)
        return {**message, "content": shorter}

    def compact(self, client, messages: list[dict]) -> str:
        self.compactions += 1
        body = "\n\n".join(f'[{m["role"]}] {m["content"]}' for m in messages)
        reply = client.chat(
            [
                {"role": "system", "content": COMPACT_PROMPT},
                {"role": "user", "content": body},
            ],
            temperature=0.0,
            max_tokens=280,
            purpose="compact",
            **self._kwargs(),
        )
        return f"[compacted {len(messages)} earlier turns] {reply}"

    # ---------------------------------------------------------- provided
    def close_session(self, client, store, conversation: list[dict], session_no: int) -> None:
        """The write path: extract -> gate -> reconcile -> save."""
        candidates = self.write_memory(client, conversation, session_no)

        accepted = []
        for record in candidates:
            ok, reason = self.validate_record(record, store)
            if ok:
                accepted.append(record)
            else:
                store.log_rejection(record, reason)

        self.reconcile(client, store, accepted, conversation, session_no)
        store.save()
