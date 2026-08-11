"""Everything the lesson runs against: scripts, workspace, ground truth.

The lesson has two independent halves:

PART A - "why memory" (a demo, not an exercise)
    Two tiny sessions in the badge-audit world of chapter 2. Session 1 states
    two facts that exist in NO file; session 2 asks a question that needs both
    of them plus one number that exists ONLY on disk. Tools alone fail, tools
    plus memory pass. That is the whole demo.

PART B - the four TODOs (an exercise, not a demo)
    One long briefing transcript plus a seed memory store left over from "last
    month". Students run their pipeline over it: extract (TODO 1), gate
    (TODO 2), reconcile (TODO 3), and assemble a budgeted context (TODO 4).
    No agent, no ReAct loop - pipeline in, store state out.
"""

from __future__ import annotations

from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = LESSON_ROOT / "workspace"

# ---------------------------------------------------------------------------
# The workspace - Part A's on-disk half
# ---------------------------------------------------------------------------
# Three incident exports. Which one matters was said in conversation only;
# the record count lives in the file only. The two decoys are why a
# tools-only agent cannot just list_files and guess: 0819 is newer, 0805 is
# older, and nothing on disk says which incident the user meant.

_INCIDENT = """incident report {date}
door                        : D3 (ServerRoom)
type                        : tailgating
confirmed violating records : {count}
badge                       : {badge}
status                      : closed
"""

CANONICAL_WORKSPACE = {
    "incident_0805.txt": _INCIDENT.format(date="2026-08-05", count=3, badge="B1002"),
    "incident_0812.txt": _INCIDENT.format(date="2026-08-12", count=7, badge="B1005"),
    "incident_0819.txt": _INCIDENT.format(date="2026-08-19", count=5, badge="B1006"),
}


def reset_workspace() -> None:
    """Restore the workspace to exactly CANONICAL_WORKSPACE.

    Called before every session. A live model will jot what the user said
    into files if the disk lets it sit there (observed in a real run), and
    leftovers would hand the tools-only baseline the conversational facts.
    "Nothing survives between sessions except the memory store" is enforced,
    not hoped for.
    """
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    for path in sorted(WORKSPACE_ROOT.rglob("*"), reverse=True):
        rel = path.relative_to(WORKSPACE_ROOT).as_posix()
        if path.is_file() and rel not in CANONICAL_WORKSPACE:
            path.unlink()
        elif path.is_dir():
            try:
                path.rmdir()  # only succeeds once emptied
            except OSError:
                pass
    for rel, content in CANONICAL_WORKSPACE.items():
        target = WORKSPACE_ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            target.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# PART A - session 1: two facts, stated plainly, written nowhere
# ---------------------------------------------------------------------------

SESSION_1 = [
    {
        "turn": 1,
        "role": "user",
        "content": (
            "Morning. Last Tuesday we had a tailgating incident at the ServerRoom. "
            "I exported the confirmed violating records to `incident_0812.txt` in "
            "your workspace - remember which file that is, we'll need it later."
        ),
    },
    {
        "turn": 2,
        "role": "assistant",
        "content": (
            "Noted - the incident file is incident_0812.txt. I'll use that one "
            "when you come back to it."
        ),
    },
    {
        "turn": 3,
        "role": "user",
        "content": (
            "One more thing: the admin office fixed the fine at 200 yuan per "
            "violating record. That's all for today."
        ),
    },
    {
        "turn": 4,
        "role": "assistant",
        "content": "Got it - 200 yuan per violating record. See you.",
    },
]

# ---------------------------------------------------------------------------
# PART A - session 2: one question that needs both halves
# ---------------------------------------------------------------------------

FINAL_REQUEST = (
    "Back. Give me the numbers for that incident: how many confirmed violating "
    "records, and the total fine (record count times the per-record fine). "
    "Return exactly this JSON and nothing else:\n"
    '{"records":"...","total_fine":"..."}'
)

SESSION_2 = [
    {"turn": 1, "role": "user", "content": FINAL_REQUEST},
]

SESSIONS = {1: SESSION_1, 2: SESSION_2}

# records lives only in incident_0812.txt; total_fine = 7 x 200, where 200 was
# only ever said in session 1. Tools can answer one half, memory the other.
EXPECTED_ANSWER = {"records": "7", "total_fine": "1400"}
REQUIRED_CALCULATOR_RESULTS = {"1400"}
REQUIRED_READS = {"incident_0812.txt"}

# What session 1 should leave in the store (the demo pipeline's output).
EXPECTED_DEMO_MEMORY = {
    "incident_file": "incident_0812.txt",
    "fine_per_violation": "200",
}

AGENT_SYSTEM_TEMPLATE = """
You are an audit assistant working across separate sessions. You do not
remember anything by yourself: what you know from earlier sessions arrives in
a [memory] block in your context, and nothing else survives between sessions.
Files live in your workspace - read them with your tools.

Available tools:
{tools}

Respond with exactly one Thought and one Action per turn:

Thought: one short sentence about the next step
Action: tool_name
Action Input: {{"argument": "value"}}

Action Input must be a single JSON object on one line. After each Action the
runtime replies with an Observation. Use the observed values verbatim.

Two more actions end the current turn instead of calling a tool:

Action: respond
Action Input: {{"message": "your short reply to the user"}}

Action: finish
Action Input: {{"records":"...","total_fine":"..."}}

Use respond when the user is briefing you - acknowledge briefly. Use finish
only for the final deliverable, with exactly the JSON shape the user asked for.

Rules:
- One Action per turn. Never invent an Observation.
- Never do arithmetic in your head. Use calculate and read the Observation.
- Never state a value you have not seen in the context, a file, or an Observation.
- Paths are relative to the workspace root. The sandbox rejects anything outside it.
- Never copy what the user said into workspace files. The workspace is shared
  reference material, not your notebook.
- finish is accepted only when the user asks for the final deliverable. Until
  then, end your turn with respond.
""".strip()


# ---------------------------------------------------------------------------
# PART B - the seed store: what "last month" left behind
# ---------------------------------------------------------------------------

SEED_MEMORY = [
    {"key": "incident_file", "value": "incident_0812.txt", "source": "seed", "session": 0},
    {"key": "fine_per_violation", "value": "200", "source": "seed", "session": 0},
    {"key": "report_recipient", "value": "security-team", "source": "seed", "session": 0},
]

# ---------------------------------------------------------------------------
# PART B - the briefing transcript: one long conversation, four TODOs of bait
# ---------------------------------------------------------------------------
# What is planted where:
#   ADD     "logs/access_2026-09.csv"  and  "audit runs on day 1"
#   UPDATE  fine 200 -> 250
#   DELETE  "stop sending the report to security-team"
#   NOOP    "the incident file is still incident_0812.txt"
#   TODO 2  the pasted exporter config contains a credential; one sentence
#           packs two facts; (the mock also emits a record with no value)
#   TODO 1  the assistant's own turn contains a wrong derived number - user
#           turns only, or the pipeline poisons itself
#   TODO 4  the paste is the L1 trim target; the whole transcript is the L2 one

EXPORTER_ENV_PASTE = """BADGE_EXPORT_SOURCE=door-controller-3
BADGE_EXPORT_FORMAT=csv
BADGE_EXPORT_SCHEDULE=0 2 * * *
BADGE_EXPORT_TIMEZONE=Asia/Singapore
BADGE_EXPORT_RETRIES=3
BADGE_EXPORT_BACKOFF=1.5
ZAI_API_KEY=sk-proj-3f9Qd7LmXb2vNp8KwRt5Yh1Zc4Ja6Ge0Su
EXPORT_BUCKET=s3://badge-exports/monthly
EXPORT_RETENTION_DAYS=90
EXPORT_COMPRESSION=gzip
CHECKSUM_ALGO=sha256
CONTROLLER_HOST=door-ctl.internal
CONTROLLER_PORT=8443
CONTROLLER_TLS=required
CONTROLLER_TIMEOUT=30
ROSTER_SYNC=hourly
ROSTER_SOURCE=hr-system
CLOCK_SOURCE=ntp.internal
CLOCK_MAX_DRIFT_MS=500
LOG_LEVEL=INFO
LOG_FORMAT=json
ALERT_CHANNEL=#facilities
ALERT_ON_FAILURE=true
DEAD_LETTER_DIR=/var/spool/badge-dlq
MAX_BATCH_ROWS=5000
HEALTHCHECK_PATH=/healthz
HEALTHCHECK_INTERVAL=60
DASHBOARD_URL=https://ops.internal/badges
METRICS_PORT=9102
TRACE_SAMPLE_RATE=0.05
PROXY=off
IPV6=off
LOCALE=C.UTF-8
NICE_LEVEL=10
UMASK=0027
TMPDIR=/var/tmp/badge-export
KEEP_PARTIALS=false
VERIFY_ROW_COUNT=true
FAIL_FAST=false
NOTIFY_ON_EMPTY=true"""

TRANSCRIPT = [
    {
        "turn": 1,
        "role": "user",
        "content": (
            "Morning. I'm handing the monthly access audit over to you today - "
            "let me walk you through what changed since last month."
        ),
    },
    {
        "turn": 2,
        "role": "assistant",
        "content": "Ready when you are. I'll keep track as we go.",
    },
    {
        "turn": 3,
        "role": "user",
        "content": (
            "September's raw logs land in `logs/access_2026-09.csv`. That is the "
            "file the audit runs on from now on."
        ),
    },
    {
        "turn": 4,
        "role": "assistant",
        "content": "Noted - the audit reads logs/access_2026-09.csv.",
    },
    {
        "turn": 5,
        "role": "user",
        "content": (
            "The audit itself runs on day 1 of every month, before the management "
            "call. Don't let it slip."
        ),
    },
    {
        "turn": 6,
        "role": "assistant",
        "content": "Understood - audit on day 1, ahead of the call.",
    },
    {
        "turn": 7,
        "role": "user",
        "content": (
            "Finance bumped the fine: it is 250 yuan per violating record now, "
            "not 200. Use the new number for anything you compute."
        ),
    },
    {
        "turn": 8,
        "role": "assistant",
        "content": (
            "Got it - 250 per record. So a ten-record incident would come to "
            "2,000 yuan."  # wrong on purpose: 10 x 250 = 2,500. Extract user
            # turns only, or this mistake ends up in the store.
        ),
    },
    {
        "turn": 9,
        "role": "user",
        "content": (
            "Stop sending the monthly report to security-team - that mailing "
            "list was retired last week. Just drop it."
        ),
    },
    {
        "turn": 10,
        "role": "assistant",
        "content": "Will do - no more copies to security-team.",
    },
    {
        "turn": 11,
        "role": "user",
        "content": (
            "The August incident file is still `incident_0812.txt`, unchanged - "
            "same file as before."
        ),
    },
    {
        "turn": 12,
        "role": "assistant",
        "content": "Right, incident_0812.txt, same as last month.",
    },
    {
        "turn": 13,
        "role": "user",
        "content": (
            "Here's the config block the badge exporter runs with - sanity-check "
            "it when you get a chance:\n\n" + EXPORTER_ENV_PASTE
        ),
    },
    {
        "turn": 14,
        "role": "assistant",
        "content": (
            "Read through it. One flag: the block contains a live-looking "
            "credential - I won't carry that forward anywhere."
        ),
    },
    {
        "turn": 15,
        "role": "user",
        "content": "Good catch, I'll rotate it. Also: the audit covers the ServerRoom and the Lab.",
    },
    {
        "turn": 16,
        "role": "assistant",
        "content": "Noted, both doors are in scope.",
    },
    {
        "turn": 17,
        "role": "user",
        "content": (
            "Oh, and keep the ops dashboard key so you can pull the monthly "
            "numbers - the key is ZAI_API_KEY=sk-proj-3f9Qd7LmXb2vNp8KwRt5Yh1Zc4Ja6Ge0Su. "
            "You'll need it on every run, so hold on to it."
        ),
    },
    {
        "turn": 18,
        "role": "assistant",
        "content": (
            "I'll use it when I pull the numbers, but I won't write that key "
            "into memory or any file."
        ),
    },
    {
        "turn": 19,
        "role": "user",
        "content": (
            "That's everything. First run is next Monday - don't start anything "
            "before then."
        ),
    },
    {
        "turn": 20,
        "role": "assistant",
        "content": "Understood. I have what I need for the handover.",
    },
]

TRANSCRIPT_SESSION_NO = 1  # the seed records are session 0

# What the store must look like after the pipeline has run over TRANSCRIPT.
EXPECTED_PIPELINE_MEMORY = {
    "current": {
        "incident_file": "incident_0812.txt",
        "fine_per_violation": "250",
        "log_file": "logs/access_2026-09.csv",
        "audit_day": "1",
    },
    "superseded": {"fine_per_violation": "200"},
    "revoked_subjects": ["security-team"],
}

# The four facts TODO 1 must surface (values checked loosely by the grader).
EXPECTED_EXTRACTED = {
    "log_file": "logs/access_2026-09.csv",
    "audit_day": "1",
    "fine_per_violation": "250",
    "incident_file": "incident_0812.txt",
}

# Anything matching these must never appear anywhere in the store.
FORBIDDEN_IN_MEMORY = ["sk-proj-", "sk-", "ghp_", "AKIA"]

# TODO 4's demo: assemble this system prompt + the transcript under the budget.
PIPELINE_SYSTEM = (
    "You are the audit assistant. Use the [memory] block and the conversation "
    "to answer the manager's questions."
)
PIPELINE_BUDGET = 600
