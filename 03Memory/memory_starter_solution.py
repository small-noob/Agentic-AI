"""STANDARD ANSWER - memory_starter.py with the four TODOs filled in.

How to use this file: attempt a TODO yourself FIRST. When you are stuck or
want to compare, read the matching prompt or method here - every added line
is tagged `# [solution]`, everything else (docstrings included) is identical
to your starter. Then close this file and write your own version; pasting it
wholesale teaches you nothing and shows immediately in the debrief.

    TODO 1  write_memory      transcript              -> candidate records     API
    TODO 2  validate_record   candidate record        -> allowed? why not?     no API
    TODO 3  reconcile         records + transcript    -> store changes         API
    TODO 4  build_context     store + history         -> budgeted messages     API

(This file is reference material only - nothing in the harness imports it.
`--implementation solution` runs `memory_agent.py`, the harness's internal
copy of the same pipeline.)
"""

from __future__ import annotations

import re

from react_loop import Assembled, ContextOverflow, extract_json_object
from tokens import count_messages, count_tokens

# --------------------------------------------------------------------------
# Provided constants. Tune them if you want - they are policy, not law.
# --------------------------------------------------------------------------

# A single message longer than this is a candidate for trimming at L1.
MAX_MESSAGE_TOKENS = 180

# How many recent turns stay verbatim when L2 compacts. The current turn must
# always survive: it is what the pipeline has to act on.
TAIL_KEEP = 4

# A starting point, not a complete list. Extend it in TODO 2.
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),          # OpenAI / Zhipu style
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),             # AWS access key id
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),             # [solution] GitHub token
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),    # [solution] Slack token
    re.compile(r"(?i)\b(password|passwd|secret|token|api_key)\s*[=:]\s*\S+"),  # [solution]
]

# Ways a model crams two facts into one record. Used by TODO 2.
COMPOUND_MARKERS = [" and ", " & ", "; ", "、", "\n"]

# --------------------------------------------------------------------------
# YOUR PROMPTS - this is where most of the real work of TODO 1 and TODO 3
# lives. Each TODO's docstring lists exactly what its prompt must say.
# --------------------------------------------------------------------------

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
"""  # [solution]

RECONCILE_PROMPT = """You judge how one candidate memory record relates to what is already stored.

Reply with JSON only: {"verdict": "ADD" | "UPDATE" | "DELETE" | "NOOP"}

- ADD: nothing is stored under this key or meaning yet.
- UPDATE: the stored value is outdated and the candidate replaces it.
- NOOP: the candidate says what is already stored.
- DELETE: the user explicitly revoked this fact this session.
Judge by meaning, not by string equality.
"""  # [solution]

REVOKE_PROMPT = """The user may have revoked some previously stored facts this session.

You are given the stored facts (one per line as "- key = value") and what the
user said. Reply with JSON only: {"revoked": ["key", ...]}

Rules:
- Only EXPLICIT revocations count: "stop doing X", "forget X", "X was retired",
  "we no longer use X".
- A changed value is an UPDATE, not a revocation - do not list it.
- When in doubt, return {"revoked": []}.
"""  # [solution]

# Provided - the compact() helper below uses it. Note how different its job
# is from TODO 1's: extraction keeps only durable facts as structured
# records, while this prompt writes prose and must preserve EVERY concrete
# value in the span. Same model, two uses.
COMPACT_PROMPT = """Summarise this slice of a conversation in at most 110 words.

Preserve every concrete value: file names, amounts, counts, dates, schedules,
and any instruction the user gave. Drop greetings, acknowledgements, and
restatements of intent. Write plain prose, no bullet points."""


def _user_text(conversation: list[dict], trim=None) -> str:  # [solution]
    """Flatten the USER turns only - assistant turns and Observations are
    derived content; extracting them poisons the store with its own mistakes."""
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


class MemoryPolicy:
    """Your memory pipeline. Part B drives these four methods directly."""

    name = "memory(starter)"

    def __init__(self, model: str = "", tail_keep: int = TAIL_KEEP) -> None:
        self.model = model
        self.tail_keep = tail_keep
        self.compactions = 0
        self.max_ladder_rung = 0

    def _kwargs(self) -> dict:
        """Pass this to client.chat(**self._kwargs()) so --model is respected."""
        return {"model": self.model} if self.model else {}

    # ====================================================================
    # TODO 1 - the write path.
    # ====================================================================
    def write_memory(self, client, conversation: list[dict], session_no: int) -> list[dict]:
        """See memory_starter.py for the full specification."""
        # [solution] ------------------------------------------------------
        transcript = _user_text(conversation, trim=self.trim_oversized)
        facts = []
        for _attempt in range(2):  # one retry on an empty result
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
            if facts:
                break

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

    # ====================================================================
    # TODO 2 - the write gate.
    # ====================================================================
    def validate_record(self, record: dict, store) -> tuple[bool, str]:
        """See memory_starter.py for the full specification."""
        # [solution] ------------------------------------------------------
        if not isinstance(record, dict):
            return False, "not a record"

        # 1. SECRETS - first, because a leak can never be undone.
        blob = f'{record.get("key", "")} {record.get("value", "")}'
        for pattern in SECRET_PATTERNS:
            if pattern.search(blob):
                return False, "secret"

        # 2. SHAPE - key and value must be real, non-placeholder strings.
        key = record.get("key")
        value = record.get("value")
        if not isinstance(key, str) or not key.strip():
            return False, "missing key"
        if not isinstance(value, str) or not value.strip():
            return False, "missing value"
        if not any(ch.isalnum() for ch in value):
            return False, "placeholder value"

        # 3. ONE FACT PER RECORD.
        if any(marker in value for marker in COMPOUND_MARKERS):
            return False, "two facts in one record"

        # Deliberately NO comparison against store state: duplicates are
        # reconcile's NOOP, changed values its UPDATE.
        return True, "ok"

    # ====================================================================
    # TODO 3 - update and forget.
    # ====================================================================
    def reconcile(self, client, store, records: list[dict], conversation: list[dict],
                  session_no: int) -> None:
        """See memory_starter.py for the full specification."""
        # [solution] ------------------------------------------------------
        said = _user_text(conversation, trim=self.trim_oversized)

        # Part A - the model judges each candidate; this code performs the op.
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

            # Code-side guards: operations must stay coherent with state.
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
                # NOOP, or anything that is not one of the four words: not
                # writing is the safe default.
                store.noop(key)

        # Part B - revocations need their own pass.
        current = store.all()
        if current:
            listing = "\n".join(f'- {r["key"]} = {r["value"]}' for r in current)
            reply = client.chat(
                [
                    {"role": "system", "content": REVOKE_PROMPT},
                    {"role": "user",
                     "content": f"stored facts:\n{listing}\n\nwhat the user said:\n{said}"},
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

    # ====================================================================
    # TODO 4 - working memory under a budget.
    # ====================================================================
    def build_context(self, client, system: str, store, history: list[dict],
                      budget: int) -> Assembled:
        """See memory_starter.py for the full specification."""
        # [solution] ------------------------------------------------------
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

        # L1 - trim oversized messages; the message stays, just shorter.
        trimmed = [self.trim_oversized(m) for m in history]
        messages, new_used = assemble(trimmed)
        ladder.append(
            f"L1  trimmed oversized (-{used - new_used:,}t) "
            f"{new_used:,}t {'OK' if new_used <= budget else 'OVER'}"
        )
        rung(1)
        if new_used <= budget:
            return Assembled(messages, new_used, ladder)

        # L2 - compact all but the tail; L3 - all but the current turn.
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

    # ==================================================================
    # Provided. Not a TODO. Both TODO 1 (so the long paste cannot drown
    # the short facts) and TODO 4's L1 rung use this helper.
    # ==================================================================
    def trim_oversized(self, message: dict) -> dict:
        """Shorten one message; do not drop it.

        Returns `message` unchanged if it fits MAX_MESSAGE_TOKENS. Otherwise
        keeps the head and the tail (the head carries the framing, the tail
        often the conclusion) and leaves a visible marker, so anyone reading
        the trace can tell a trim happened.
        """
        content = str(message.get("content", ""))
        if count_tokens(content) <= MAX_MESSAGE_TOKENS:
            return message
        lines = content.splitlines()
        head, tail = lines[:10], lines[-3:]
        removed = max(0, len(lines) - len(head) - len(tail))
        shorter = "\n".join(head + [f"[... {removed} lines trimmed ...]"] + tail)
        return {**message, "content": shorter}

    # ==================================================================
    # Provided. Not a TODO. TODO 4's L2 and L3 rungs call this to squeeze
    # several turns into one short note - one API call per use, driven by
    # the provided COMPACT_PROMPT above.
    # ==================================================================
    def compact(self, client, messages: list[dict]) -> str:
        """Several turns in, one short prose note out. Lossy by design -
        which is exactly why your ladder tries the free, lossless trim first."""
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

    # ==================================================================
    # Provided. Not a TODO. This is the background write path: it runs once
    # when a session ends, and it is where 1 -> 2 -> 3 connect.
    # ==================================================================
    def close_session(self, client, store, conversation: list[dict], session_no: int) -> None:
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
