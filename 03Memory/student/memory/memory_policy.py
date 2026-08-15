"""The memory pipeline you build. The four TODOs are ANSWERED IN THE NOTEBOOK.

This module holds only what is provided: the tuning constants, the compaction
prompt, and the helpers ``trim_oversized`` / ``compact`` / ``close_session``.
The four methods below deliberately raise NotImplementedError - each TODO cell
in ``Memory_Lab_Learner.ipynb`` defines the real method (and its prompt) and
binds it onto this class:

    TODO 1  write_memory      transcript              -> candidate records     API
    TODO 2  validate_record   candidate record        -> allowed? why not?     no API
    TODO 3  reconcile         records + transcript    -> store changes         API
    TODO 4  build_context     store + history         -> budgeted messages     API

Most of the real work of TODO 1 and TODO 3 is the PROMPTS you write in the
notebook - the method bodies are mostly plumbing. Two TODOs call the model and
two deliberately do not: extraction and reconciliation are language work, but
a gate whose verdict changes between runs is not a gate, and conflict
resolution you cannot test deterministically is a bug waiting to happen.
"""

from __future__ import annotations

import re

from tokens import count_tokens

# --------------------------------------------------------------------------
# Provided constants. Tune them if you want - they are policy, not law.
# --------------------------------------------------------------------------

# A single message longer than this is a candidate for trimming at L1.
MAX_MESSAGE_TOKENS = 180

# How many recent turns stay verbatim when L2 compacts. The current turn must
# always survive: it is what the pipeline has to act on.
TAIL_KEEP = 4

# A starting point, not a complete list. TODO 2 extends it in the notebook.
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),          # OpenAI / Zhipu style
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),             # AWS access key id
]

# Ways a model crams two facts into one record. Used by TODO 2.
COMPOUND_MARKERS = [" and ", " & ", "; ", "、", "\n"]

# Provided - the compact() helper below uses it. Note how different its job
# is from TODO 1's: extraction keeps only durable facts as structured
# records, while this prompt writes prose and must preserve EVERY concrete
# value in the span. Same model, two uses.
COMPACT_PROMPT = """Summarise this slice of a conversation in at most 110 words.

Preserve every concrete value: file names, amounts, counts, dates, schedules,
and any instruction the user gave. Drop greetings, acknowledgements, and
restatements of intent. Write plain prose, no bullet points."""


class MemoryPolicy:
    """Your memory pipeline. Part B drives these four methods directly."""

    name = "memory(yours)"

    def __init__(self, model: str = "", tail_keep: int = TAIL_KEEP) -> None:
        self.model = model
        self.tail_keep = tail_keep
        self.compactions = 0
        self.max_ladder_rung = 0

    def _kwargs(self) -> dict:
        """Pass this to client.chat(**self._kwargs()) so --model is respected."""
        return {"model": self.model} if self.model else {}

    # ====================================================================
    # TODO 1 - the write path. Answered in the notebook (Part B, TODO 1).
    # ====================================================================
    def write_memory(self, client, conversation: list[dict], session_no: int) -> list[dict]:
        """Turn one whole conversation into a list of candidate memory records."""
        raise NotImplementedError(
            "TODO 1: write_memory - answer in Memory_Lab_Learner.ipynb "
            "(the TODO 1 cell defines and binds it)")

    # ====================================================================
    # TODO 2 - the write gate. Answered in the notebook (Part B, TODO 2).
    # ====================================================================
    def validate_record(self, record: dict, store) -> tuple[bool, str]:
        """Decide whether one candidate record may enter the store."""
        raise NotImplementedError(
            "TODO 2: validate_record - answer in Memory_Lab_Learner.ipynb "
            "(the TODO 2 cell defines and binds it)")

    # ====================================================================
    # TODO 3 - update and forget. Answered in the notebook (Part B, TODO 3).
    # ====================================================================
    def reconcile(self, client, store, records: list[dict], conversation: list[dict],
                  session_no: int) -> None:
        """Apply the accepted records to the store: ADD / UPDATE / DELETE / NOOP."""
        raise NotImplementedError(
            "TODO 3: reconcile - answer in Memory_Lab_Learner.ipynb "
            "(the TODO 3 cell defines and binds it)")

    # ====================================================================
    # TODO 4 - working memory under a budget. Answered in the notebook.
    # ====================================================================
    def build_context(self, client, system: str, store, history: list[dict],
                      budget: int):
        """Assemble messages for one model call under ``budget`` tokens."""
        raise NotImplementedError(
            "TODO 4: build_context - answer in Memory_Lab_Learner.ipynb "
            "(the TODO 4 cell defines and binds it)")

    # ==================================================================
    # Provided. Not a TODO. Both TODO 1 (so the long paste cannot drown
    # the short facts) and TODO 4's L1 rung use this helper.
    # ==================================================================
    def trim_oversized(self, message: dict) -> dict:
        """Shorten one message; do not drop it.

        Returns ``message`` unchanged if it fits MAX_MESSAGE_TOKENS. Otherwise
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
    # when a session ends, and it is where 1 -> 2 -> 3 connect. Part A's
    # memory mode calls it; Part B's pipeline drives the four methods
    # directly, one step at a time.
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
