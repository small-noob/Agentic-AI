"""The long-term memory store. Given to students - not one of the TODOs.

A JSONL file on disk, one record per line. Disk matters: the three sessions are
three independent agent runs with fresh contexts, so a store that lived only in
a Python list would make "cross-session" a fiction. Because it is a file, you
can also inspect it between sessions:

    python agent/main.py --mode memory --session 1
    cat runs/memory.jsonl
    python agent/main.py --mode memory --session 2

A record:

    {"key": "test_files", "value": "8", "source": "session1:turn5",
     "session": 1, "status": "current"}

``status`` is one of ``current`` / ``superseded`` / ``deleted``. Nothing is ever
physically removed - Part 4's Update replaces the *current value* and keeps the
audit trail, so you can still see what the agent used to believe and when that
changed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import lesson2  # noqa: F401  (appends 02Tools to sys.path; see lesson2.py)

from sandbox import resolve_safe_path

CURRENT = "current"
SUPERSEDED = "superseded"
DELETED = "deleted"


@dataclass
class MemoryStore:
    """Rooted like a chapter-2 workspace: ``relpath`` is resolved against
    ``root`` through the same ``resolve_safe_path`` every file tool uses.

    The lesson taught last week was "every file tool goes through the sandbox
    door". A memory store is a file the *harness* writes rather than the agent,
    but the rule does not care who is holding the pen - so the store walks
    through the same door. You do not have to write this; you do have to know
    it is there.
    """

    root: Path | None = None
    relpath: str = "memory.jsonl"
    records: list[dict] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    operations: list[dict] = field(default_factory=list)

    # -- persistence ------------------------------------------------------
    def target(self) -> Path | None:
        """Where this store lives on disk, sandbox-checked. None = in-memory."""
        if self.root is None:
            return None
        return resolve_safe_path(self.root, self.relpath)

    @classmethod
    def load(cls, root: str | Path | None, relpath: str = "memory.jsonl") -> "MemoryStore":
        store = cls(root=Path(root) if root is not None else None, relpath=relpath)
        target = store.target()
        if target is not None and target.exists():
            for line in target.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    store.records.append(json.loads(line))
        return store

    def save(self) -> None:
        target = self.target()
        if target is None:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(json.dumps(r, ensure_ascii=False) for r in self.records)
        target.write_text(body + ("\n" if body else ""), encoding="utf-8")

    def reset(self) -> None:
        self.records.clear()
        self.rejections.clear()
        self.operations.clear()
        target = self.target()
        if target is not None and target.exists():
            target.unlink()

    # -- reads ------------------------------------------------------------
    def all(self, status: str = CURRENT) -> list[dict]:
        if status == "*":
            return list(self.records)
        return [r for r in self.records if r.get("status") == status]

    def get(self, key: str, status: str = CURRENT) -> dict | None:
        for record in reversed(self.records):
            if record.get("key") == key and record.get("status") == status:
                return record
        return None

    def has(self, key: str, value: str) -> bool:
        return any(
            r.get("key") == key
            and r.get("value") == value
            and r.get("status") == CURRENT
            for r in self.records
        )

    def keys(self, status: str = CURRENT) -> list[str]:
        return [r["key"] for r in self.all(status)]

    # -- writes -----------------------------------------------------------
    def add(self, record: dict) -> dict:
        stored = {
            "key": record["key"],
            "value": record["value"],
            "source": record.get("source", "unknown"),
            "session": record.get("session", 0),
            "status": CURRENT,
        }
        self.records.append(stored)
        self.operations.append({"op": "ADD", "key": stored["key"], "value": stored["value"]})
        return stored

    def supersede(self, key: str, record: dict) -> dict:
        old = self.get(key)
        if old is not None:
            old["status"] = SUPERSEDED
            old["superseded_by"] = record.get("source", "unknown")
        stored = self.add(record)
        self.operations[-1] = {
            "op": "UPDATE",
            "key": key,
            "old": old["value"] if old else None,
            "value": stored["value"],
            "at": stored["source"],
        }
        return stored

    def soft_delete(self, key: str, source: str = "unknown") -> bool:
        record = self.get(key)
        if record is None:
            return False
        record["status"] = DELETED
        record["revoked_by"] = source
        self.operations.append({"op": "DELETE", "key": key, "at": source})
        return True

    def noop(self, key: str) -> None:
        self.operations.append({"op": "NOOP", "key": key})

    def log_rejection(self, record: object, reason: str) -> None:
        self.rejections.append({"record": record, "reason": reason})

    # -- context ----------------------------------------------------------
    def digest(self) -> str:
        """The memory block that goes into the model's context.

        This string is what TODO 4 pays for out of its token budget. Keeping it
        short is the whole reason extraction is worth doing.
        """
        current = self.all(CURRENT)
        if not current:
            return ""
        body = " | ".join(f'{r["key"]}={r["value"]}' for r in current)
        return f"[memory] {body}"

    # -- reporting --------------------------------------------------------
    def report(self, session_no: int) -> str:
        lines = [f"[memory] after session {session_no}"]
        for record in self.records:
            flag = {CURRENT: " ", SUPERSEDED: "~", DELETED: "x"}.get(record["status"], "?")
            lines.append(
                f"  {flag} {record['key']:<18} {record['value']:<28} "
                f"{record['status']:<11} {record['source']}"
            )
        if self.rejections:
            lines.append(f"  rejected {len(self.rejections)} candidate(s):")
            for item in self.rejections:
                shown = json.dumps(item["record"], ensure_ascii=False)
                if len(shown) > 66:
                    shown = shown[:63] + "..."
                lines.append(f"    - {shown}  reason={item['reason']}")
        return "\n".join(lines)

    def leaked_secrets(self, patterns: list[str]) -> list[str]:
        """Every forbidden fragment that made it into the store. Should be empty."""
        blob = json.dumps(self.records, ensure_ascii=False)
        return [p for p in patterns if p in blob]

