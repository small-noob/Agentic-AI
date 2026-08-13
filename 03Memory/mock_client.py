"""Deterministic offline stand-in for GLM-4-Flash. Zero cost, no network.

Only the test suite uses it - main.py and pipeline.py always call the real
API. It plays five roles, dispatched on the ``purpose`` label:

* ``agent``     - a competent ReAct agent speaking chapter 2's protocol
* ``extract``   - a memory extractor (TODO 1's call)
* ``reconcile`` - an ADD/UPDATE/NOOP judge (TODO 3's call)
* ``revoke``    - the revocation pass (TODO 3's second call)
* ``compact``   - a summariser (TODO 4's call)

The mock is deliberately **honest**: for the agent role it answers only from
what is actually present in the context it was handed. If the incident file
name and the fine are not in a [memory] block, it does the honest thing - it
looks at the disk, finds three incident files and no fine, and says it cannot
answer. It does not quietly fix a broken TODO and it does not fabricate.

The extractor is deliberately **imperfect** in the same ways GLM-4-Flash is:
it transcribes the pasted credential, packs two facts into one record, and
returns a record with no value. TODO 2 exists to catch those, so the offline
path has to produce them. It also punishes a specific student mistake: feed it
ASSISTANT turns and it will happily extract the assistant's wrong arithmetic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from zhipu_client import CallLog, ChatResponse, DEFAULT_MODEL

SECRET_IN_PASTE = "sk-proj-3f9Qd7LmXb2vNp8KwRt5Yh1Zc4Ja6Ge0Su"


@dataclass
class MockClient:
    log: CallLog = field(default_factory=CallLog)

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.2,
        max_tokens: int = 700,
        purpose: str = "agent",
    ) -> ChatResponse:
        blob = "\n".join(str(m.get("content", "")) for m in messages)
        handler = {
            "extract": self._extract,
            "reconcile": self._reconcile,
            "revoke": self._revoke,
            "compact": self._compact,
        }.get(purpose, self._act)
        text = handler(messages, blob)
        response = ChatResponse(text=text, prompt_tokens=_estimate(blob), completion_tokens=60)
        self.log.record(purpose, response)
        return response

    # ------------------------------------------------------------------ agent
    def _act(self, messages: list[dict], blob: str) -> str:
        # Only assistant turns AFTER the current user request count as "what
        # this agent already did" - the system prompt shows example actions.
        this_turn = messages[_request_index(messages) + 1:]
        own_turns = "\n".join(
            str(m.get("content", "")) for m in this_turn if m.get("role") == "assistant"
        )
        returned = "\n".join(
            str(m.get("content", "")) for m in this_turn if m.get("role") == "user"
        )
        observations = re.findall(r"Observation:\s*(.+)", returned)
        request = _current_request(messages)

        is_deliverable = "total_fine" in request

        if not is_deliverable:
            return _step(
                "nothing to look up; I should acknowledge what was said.",
                "respond",
                {"message": _acknowledge(request)},
            )

        digest_file = _first(blob, [r"incident_file=([^\s|]+)"])
        digest_fine = _first(blob, [r"fine_per_violation=(\d+)"])
        did_list = "Action: list_files" in own_turns
        did_read = "Action: read_file" in own_turns
        did_calculate = "Action: calculate" in own_turns
        records = _first(returned, [r"confirmed violating records\s*:\s*(\d+)"])

        if digest_file and digest_fine:
            # The memory half is in context; the disk half needs read_file.
            if not did_read:
                return _step(
                    "memory names the incident file; the record count is on disk.",
                    "read_file",
                    {"path": digest_file},
                )
            if records and not did_calculate:
                return _step(
                    "total fine is the record count times the per-record fine.",
                    "calculate",
                    {"expression": f"{records} * {digest_fine}"},
                )
            if records and observations and observations[-1].strip().isdigit():
                return (
                    "Thought: both fields are backed by an Observation.\n"
                    "Action: finish\n"
                    "Action Input: " + json.dumps(
                        {"records": records, "total_fine": observations[-1].strip()}
                    )
                )

        # No memory: the honest path. Look at the disk, admit what is missing.
        if not did_list:
            return _step(
                "I do not know which file holds the incident; I should look.",
                "list_files",
                {"path": "."},
            )
        if not did_read:
            return _step(
                "three incident files; the newest seems the best guess.",
                "read_file",
                {"path": "incident_0819.txt"},
            )
        return _step(
            "nothing in my context says which incident the user means, and no "
            "file states the per-record fine, so I cannot compute this.",
            "respond",
            {"message": "I can see three incident files, but nothing available "
                        "this session says which one you mean or what the "
                        "per-record fine is."},
        )

    # ---------------------------------------------------------------- extract
    def _extract(self, messages: list[dict], blob: str) -> str:
        """Find the durable facts, and reproduce GLM-4-Flash's real mistakes."""
        payload = str(messages[-1].get("content", ""))
        source = _source_label(blob)
        facts: list[dict] = []

        def add(key: str, value: str) -> None:
            if not any(f.get("key") == key for f in facts):
                facts.append({"key": key, "value": value, "source": source})

        m = re.search(r"exported the confirmed violating records to `?(incident_0812\.txt)`?", payload)
        if m:
            add("incident_file", m.group(1))
        m = re.search(r"still `?(incident_0812\.txt)`?", payload)
        if m:
            add("incident_file", m.group(1))
        m = re.search(r"(\d+) yuan per\s+violating record", payload)
        if m:
            add("fine_per_violation", m.group(1))
        m = re.search(r"(logs/access_2026-09\.csv)", payload)
        if m:
            add("log_file", m.group(1))
        m = re.search(r"runs on day (\d+) of every month", payload)
        if m:
            add("audit_day", m.group(1))

        # Mistake 1: the model happily transcribes a credential it was shown.
        if SECRET_IN_PASTE in payload:
            facts.append({"key": "zai_api_key", "value": SECRET_IN_PASTE, "source": source})
        # Mistake 2: two facts crammed into one record.
        if re.search(r"covers the ServerRoom and the Lab", payload):
            facts.append({"key": "audit_scope",
                          "value": "the ServerRoom and the Lab", "source": source})
        # Mistake 3: a record with no value at all.
        facts.append({"key": "note", "source": source})

        # The poisoning trap: this only fires if ASSISTANT turns were included
        # in the extraction input - the wrong arithmetic is the assistant's.
        if re.search(r"ten-record incident would come to", payload):
            facts.append({"key": "ten_record_total", "value": "2000", "source": source})

        return json.dumps({"facts": facts}, ensure_ascii=False)

    # -------------------------------------------------------------- reconcile
    def _reconcile(self, messages: list[dict], blob: str) -> str:
        """Judge one candidate against what the store already holds."""
        key = _first(blob, [r"candidate key:\s*([^\s\n]+)"]) or ""
        value = _first(blob, [r"candidate value:\s*(.+)"])
        existing = _first(blob, [r"existing value:\s*(.+)"])

        if existing is None:
            verdict = "ADD"
        elif value is not None and existing.strip() == value.strip():
            verdict = "NOOP"
        else:
            verdict = "UPDATE"
        return json.dumps({"verdict": verdict, "key": key})

    # ----------------------------------------------------------------- revoke
    def _revoke(self, messages: list[dict], blob: str) -> str:
        """Which stored keys does this conversation revoke?

        Only text NEAR the revoking phrase counts - "the fine is 250 now ...
        stop sending to security-team" revokes the recipient, not the fine.
        """
        payload = str(messages[-1].get("content", ""))
        listed = re.findall(r"^\s*-\s*([^\s=]+)\s*=\s*(.+)$", payload, re.MULTILINE)
        phrase = re.search(
            r"stop sending|was retired|no longer|forget about|drop it",
            payload,
            re.IGNORECASE,
        )
        if not phrase or not listed:
            return json.dumps({"revoked": []})
        window = payload[max(0, phrase.start() - 60): phrase.start() + 90].lower()
        revoked = [
            key
            for key, value in listed
            if value.strip().lower() in window or key.strip().lower() in window
        ]
        return json.dumps({"revoked": revoked})

    # ---------------------------------------------------------------- compact
    def _compact(self, messages: list[dict], blob: str) -> str:
        """Lossy but not adversarial: keep the opening clause of each turn.

        This is what a small model does under a tight max_tokens - it keeps
        the beginnings of things. Concrete values that appear late inside a
        long message are the first casualty, which is why the tool-output trim
        (L1) has to happen before compaction (L2).
        """
        body = messages[-1].get("content", "")
        kept = []
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("SUMMAR"):
                continue
            kept.append(line[:80])
            if len(kept) >= 10:
                break
        return "Earlier in this conversation: " + " / ".join(kept)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _step(thought: str, action: str, arguments: dict) -> str:
    return (
        f"Thought: {thought}\n"
        f"Action: {action}\n"
        f"Action Input: {json.dumps(arguments, ensure_ascii=False)}"
    )


def _estimate(text: str) -> int:
    return max(1, len(text) // 4)


def _request_index(messages: list[dict]) -> int:
    """Index of the latest real user request (not an Observation)."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "user" and not str(
            message.get("content", "")
        ).startswith("Observation:"):
            return index
    return len(messages) - 1


def _current_request(messages: list[dict]) -> str:
    return str(messages[_request_index(messages)].get("content", ""))


def _first(blob: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, blob)
        if match:
            return next(g for g in match.groups() if g is not None)
    return None


def _source_label(blob: str) -> str:
    match = re.search(r"session[\s_]?(\d+)", blob, re.IGNORECASE)
    return f"session{match.group(1)}" if match else "session1"


def _acknowledge(request: str) -> str:
    head = " ".join(str(request).split())[:70]
    return f"Understood - noted: {head}..."
