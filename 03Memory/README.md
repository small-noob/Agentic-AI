# 03Memory — Assignment

## 1. What this lesson is

Chapter 2 gave the agent tools: a registry, a path sandbox, `list_files /
read_file / write_file / calculate`. This chapter answers one question — **what
can tools not do?** — and then has you build the thing that can.

It comes in two independent halves:

| | What it is | What you do |
|---|---|---|
| **Part A** · `main.py` | A five-minute A/B demo: the same agent with and without memory | Run it, read the two traces |
| **Part B** · `pipeline.py` | The exercise: four TODOs, one long transcript | Implement `memory_starter.py`, one TODO at a time |

Part A uses chapter 2's toolset unchanged (`lesson2.py` imports the same
files — not copies). Nothing new is mounted: memory arrives as a `[memory]`
block in the context, not as a tool.

---

## 2. Part A — why an agent needs memory

A badge-audit assistant works across **two sessions**. Every session starts
with a fresh context; the only thing that can survive is what the memory
pipeline writes into the store.

**Session 1** states two facts, written to no file: the incident export is
**`incident_0812.txt`**, and the fine is **200 yuan** per violating record.

**Session 2** asks: how many confirmed violating records, and the total fine?
Return exactly `{"records":"...","total_fine":"..."}`. The correct answer is
`{"records": "7", "total_fine": "1400"}`, and its two halves deliberately
live in different places:

- `records` (7) exists only inside `incident_0812.txt` — only `read_file`
  reaches it.
- *Which* file that is, and the fine, were only ever **said** in session 1.
  The workspace holds three incident files (`0805`, `0812`, `0819`), so
  listing the directory does not disambiguate, and no file states the fine.

| Mode | What survives session 1 | Outcome |
|---|---|---|
| `tools` | Nothing | **FAIL** — guesses a file, invents a fine, or gives up |
| `memory` | Two records (~20 tokens) | **PASS** — read, calculate, finish in 3 steps |

Same tools, same loop, same model, same grader; the only line that differs
runs when a session ends. **Tools extend what an agent can DO; memory extends
what it can KEEP.** Part A is not graded beyond PASS/FAIL.

```bash
python main.py --mode compare      # both runs, one verdict table
python main.py --mode tools       # watch chapter 2's agent fail
python main.py --mode memory      # then: cat runs/memory.jsonl
```

(The workspace resets to its canonical three files at every session start —
a live model will jot what the user said into files if the disk lets it sit
there, and leftovers would quietly hand the tools baseline the answers.)

---

## 3. Part B — what you build

No agent, no ReAct loop. Two inputs and your four methods:

- **The seed store** — what "last month" left behind:
  `incident_file=incident_0812.txt`, `fine_per_violation=200`,
  `report_recipient=security-team`.
- **The transcript** (`sessions.TRANSCRIPT`) — one long handover
  conversation with everything planted:

| Planted in the transcript | Exercises |
|---|---|
| "logs land in `logs/access_2026-09.csv`", "audit runs on day 1" | TODO 1 extraction → TODO 3 **ADD** |
| "the fine is **250** now, not 200" | TODO 3 **UPDATE** (old row → superseded) |
| "**stop sending** the report to security-team" | TODO 3 **DELETE** (the revocation pass) |
| "the incident file is **still** incident_0812.txt" | TODO 3 **NOOP** |
| "keep the ops dashboard key ... ZAI_API_KEY=sk-..." said in the open | TODO 2 **secret** — extraction will surface it; the gate must stop it |
| a ~40-line config paste (with the same credential inside) | TODO 4 **L1 trim target** |
| "the audit covers the ServerRoom **and** the Lab" | TODO 2 compound-record check |
| the assistant's own wrong arithmetic ("ten records = 2,000 yuan") | TODO 1 must read **user turns only** |
| the transcript's sheer length vs a 600-token budget | TODO 4 **L2 compaction** |

The full specification of each TODO is in the docstrings of
`memory_starter.py` — that is the single source; this document does not
repeat it.

---

## 4. The workflow — one TODO at a time

Every TODO follows the same loop:

> **① read the docstring → ② implement → ③ run the step (real API) →
> ④ read the feedback and the file it saved → next TODO**

| | Implement | ③ Run & test — real API | ④ Look at |
|---|---|---|---|
| **TODO 1** | `write_memory` | `python pipeline.py --implementation starter --step 1` | `runs/1_todo1_candidates.json` + the feedback block |
| **TODO 2** | `validate_record` | `python pipeline.py --implementation starter --step 2` (this step itself makes no API call — the gate never talks to the model) | `runs/2_todo2_gate.json`: accepted vs rejected, with reasons |
| **TODO 3** | `reconcile` | `python pipeline.py --implementation starter --step 3` | `runs/3_todo3_operations.json` + `runs/final_memory.jsonl` |
| **TODO 4** | `build_context` — `trim_oversized` and `compact` are provided | `python pipeline.py --implementation starter --step 4` | the ladder (✗ over → ✓ landed) + **the 20-point report card** |

Each step ends with an instant ✓/✗ feedback block — that is your test: all
green means move on, a red line names exactly what to fix.

Each `--step n` reads the previous steps' files, so the chain survives across
separate runs. `--step 1` starts a fresh lineage:

```text
runs/0_initial_memory.jsonl    the seed store, before anything runs
runs/1_todo1_candidates.json   what extraction produced (rejects included)
runs/2_todo2_gate.json         what the gate accepted / rejected, and why
runs/3_todo3_operations.json   the verdicts and the store state after them
runs/final_memory.jsonl        the final store
```

Diff `0_initial_memory.jsonl` against `final_memory.jsonl`: that is the
conversation's entire effect on the store. Nothing is ever physically
removed — **update replaces the current value and keeps the audit trail;
revocation marks, it does not erase.**

### The finish line

```bash
python pipeline.py --implementation starter  # full run: PASS — 20/20
grep "sk-" runs/final_memory.jsonl           # must print nothing
```

**Submit:** your completed `memory_starter.py` and `runs/final_memory.jsonl`.

### Before you write anything

```bash
python check.py
```

Expected on the untouched starter: **four red TODOs, all guardrails green**
(10 ladder tests wait until TODO 4 exists). Red in YOUR TASK LIST means "not
done yet"; red in GUARDRAILS means the harness itself broke — usually an
accidental edit to a provided file.

### Stuck?

`memory_starter_solution.py` is the standard answer — the same file with the
four bodies filled in, every added line tagged `# [solution]`. Attempt the
TODO first; consult the matching method to compare; then close it and write
your own version. Nothing in the harness imports it — pasting it wholesale
earns the points and teaches you nothing, and it shows in the debrief.

---

## 5. How to do each TODO

### The toolbox — everything already written for you

| Call | What it does |
|---|---|
| `client.chat(messages, temperature=0.0, max_tokens=N, purpose="...", **self._kwargs())` | one model call; `str(reply)` is the text. `purpose` labels the call in the API report: use `"extract"` (TODO 1), `"reconcile"` and `"revoke"` (TODO 3) |
| `extract_json_object(text)` | pulls the first JSON object out of a messy reply (code fences, trailing prose) — never assume clean JSON |
| `store.get(key)` · `store.all()` · `store.keys()` | read the store; `get` returns the current record dict or `None` |
| `store.add(rec)` · `store.supersede(key, rec)` · `store.soft_delete(key, source=...)` · `store.noop(key)` | the four operations TODO 3 executes |
| `store.digest()` | the one-line `[memory] k=v \| ...` block TODO 4 puts into context |
| `self.trim_oversized(message)` — **provided** | shortens one over-long message, keeps head + tail + a visible marker |
| `self.compact(client, messages)` — **provided** | one API call: many turns in, one `[compacted N earlier turns] ...` note out |
| `count_tokens(text)` · `count_messages(messages)` | the budget arithmetic for TODO 4 |
| `Assembled(messages, tokens, ladder)` · `ContextOverflow(used, budget, why)` | TODO 4's return type, and its refusal when nothing fits |
| `MAX_MESSAGE_TOKENS` · `TAIL_KEEP` · `SECRET_PATTERNS` · `COMPOUND_MARKERS` | tuning knobs and the gate's starting lists |

### TODO 1 · `write_memory` — one prompt plus five lines of plumbing

**The prompt is the work.** Fill in `EXTRACT_PROMPT` (the placeholder at the
top of the file). It must demand, explicitly — a weak model does none of this
unprompted:

- JSON only, in the exact shape `{"facts": [{"key": "...", "value": "..."}]}`
- one fact per entry, never two
- short generic snake_case keys — give an example (`fine_per_violation`) and
  an anti-example (`badge_system_fine_amount`)
- bare verbatim values: no units, no computing, no rounding
- durable facts only; if a later statement corrects a value, return only the
  corrected one; never store a negation ("stop sending X" is a revocation)

Then the body:

1. Flatten USER turns only: skip `role != "user"` and any content starting
   with `"Observation:"`; pass each message through `self.trim_oversized()`;
   join with blank lines.
2. One call: `client.chat([{"role": "system", "content": EXTRACT_PROMPT},
   {"role": "user", "content": transcript}], temperature=0.0,
   max_tokens=600, purpose="extract", **self._kwargs())`.
3. `facts = (extract_json_object(str(reply)) or {}).get("facts", [])` — an
   empty result deserves one retry.
4. For each fact dict, stamp `source=f"session{session_no}"` and
   `session=session_no`; return the list.

### TODO 2 · `validate_record` — three ifs; no prompt, no API call

1. **Extend `SECRET_PATTERNS` first**: GitHub `ghp_...`, Slack
   `xox[baprs]-...`, and the generic `password= / token= / api_key=` shapes.
   The attack set tests exactly these.
2. Secrets: scan key and value **together**
   (`f"{record.get('key','')} {record.get('value','')}"`) against every
   pattern → `(False, "secret")`.
3. Shape: is it a dict; is `key` a non-empty string; is `value` a non-empty
   string containing at least one letter or digit →
   `(False, "missing key" / "missing value" / "placeholder value")`.
4. Compound: any `COMPOUND_MARKERS` marker inside the value →
   `(False, "two facts in one record")`.
5. Otherwise `(True, "ok")`. **Never compare against what the store holds** —
   that is TODO 3's job, and the tests fail a gate that does.

### TODO 3 · `reconcile` — two prompts, one loop, one extra pass

**Prompts first.** `RECONCILE_PROMPT`: define the four verdicts
(ADD / UPDATE / DELETE / NOOP), demand JSON only in a shape you specify
(e.g. `{"verdict": "..."}`), and say *judge by meaning, not string equality*.
`REVOKE_PROMPT`: explicit revocations only; a changed value is an UPDATE, not
a revocation; when in doubt return `{"revoked": []}`.

Part A — for each accepted record:

1. `existing = store.get(record["key"])`
2. Build the user message as plain lines: `candidate key: ...`,
   `candidate value: ...`, then `existing value: ...` **only if `existing` is
   not None**, then `what the user said this session:` plus the flattened
   user text.
3. `client.chat(..., temperature=0.0, max_tokens=120, purpose="reconcile",
   **self._kwargs())`, parse, `verdict = str(data.get("verdict", "")).upper()`.
4. Guard before executing: UPDATE when nothing is stored → treat as ADD;
   DELETE when nothing is stored → NOOP; anything unrecognised → NOOP
   (not writing is the safe default).
5. Execute it yourself: ADD → `store.add` · UPDATE → `store.supersede` ·
   DELETE → `store.soft_delete` · NOOP → `store.noop`.

Part B — once per conversation: list the current facts as `- key = value`
lines, append the user text, call with `purpose="revoke"`, and
`store.soft_delete(key, source=f"session{session_no}")` each returned key.

### TODO 4 · `build_context` — the ladder (trim and compact are handed to you)

1. Write a tiny `assemble(msgs)` helper: a system message holding `system`,
   plus a second system message holding `store.digest()` when it is
   non-empty, plus `msgs`; measure with `count_messages()`.
2. **L0**: assemble `history` as-is; append a ladder line like
   `f"L0 raw assembly {used:,}t OK"`; if it fits the budget, return
   `Assembled(messages, used, ladder)`.
3. **L1**: `trimmed = [self.trim_oversized(m) for m in history]`;
   reassemble; the ladder line must contain the word **trim** (the grader
   checks that trim was attempted before compact).
4. **L2 then L3**: for `keep` in `(self.tail_keep, 1)`: split
   `trimmed[:-keep]` and `trimmed[-keep:]`, call
   `note = self.compact(client, head)`, and rebuild the context as one
   system message holding `note` plus the tail verbatim; ladder line
   contains **compact**.
5. Still over → `raise ContextOverflow(used, budget, "...")`. Track
   `self.max_ladder_rung` as you climb.

---

## 6. Grading

**Part A** is PASS/FAIL (both fields right, the total actually computed with
`calculate`, the right file actually read — the verifier checks the agent's
own tool history, never the answer).

**Part B** is 20 points, split by TODO. Anything short of full marks fails:

| TODO | Points | Judged by |
|---|---|---|
| 1 extraction | 4 | each expected fact surfaced (matched by key *or* value — the model's naming taste is not your grade) |
| **2 write gate** | **6 · all or nothing** | no secret in the store, and everything rejectable that was offered got rejected — chapter 2's sandbox item reborn; one leak and it is 0 |
| 3 reconcile | 6 | UPDATE with audit trail 2 · revocation applied 2 · NOOP occurred 1 · ADD occurred 1 |
| 4 ladder | 4 | fits the budget 2 · L1 before L2 1 · the final instruction survives verbatim 1 |

Two TODOs call the model and two deliberately do not. **"Why may TODO 2
never call the model" is an exam point**: a gate whose verdict can differ
between runs is not a gate, and cannot be unit-tested.

---

## 7. Project layout

```text
03Memory/
├── lesson2.py                 # puts ../02Tools on sys.path — the reuse manifest
├── sessions.py                # both parts' scripts, the workspace, all ground truth
├── main.py                    # PART A: tools / memory / compare
├── pipeline.py                # PART B: the four steps, files + feedback per step
├── check.py                   # the readable test report (wraps unittest)
├── memory_starter.py          # YOUR file — four TODOs (docstrings are the spec)
├── memory_starter_solution.py # the standard answer — consult, don't paste
├── memory_agent.py            # harness-internal reference (drives --implementation solution)
├── memory_store.py            # the store (provided); persists through 02Tools' sandbox
├── react_loop.py              # Part A's loop; Assembled/ContextOverflow for TODO 4
├── tools.py                   # chapter 2's registry, verbatim — nothing new mounted
├── grader.py                  # demo PASS/FAIL + the 20-point pipeline card
├── mock_client.py             # deterministic stand-in; used by the test suite only
├── trace_display.py           # terminal rendering (display only, not a TODO)
├── tokens.py / zhipu_client.py
├── workspace/                 # canonical: three incident files, reset every session
├── runs/                      # Part A's memory.jsonl; Part B's 0_initial → final lineage
├── tests/                     # red-until-done checklist + the guardrails
└── Memory_Lab.ipynb           # the in-class notebook (mirrors main.py + pipeline.py)
```

## 8. Setup

Python 3.10+. The only third-party dependency is optional (`pip install -r
requirements.txt` for tiktoken; without it a character-class estimator is
used).

```bash
cd 03Memory
export ZAI_API_KEY="your API key"        # main.py / pipeline.py runs are live
export ZAI_MODEL="glm-4-flash-250414"    # the free model
```

**Never put a real API key in code, this README, screenshots, notebook
outputs, or a Git repository.** The 6-point gate item is this rule, applied
to the agent. (The `sk-proj-...` string that appears in the lesson materials
is a planted fake.)

The zero-cost channel is the test suite: `python check.py` (or raw
`python -m unittest discover -s tests -v`) runs everything on a
deterministic mock — honest (broken TODOs fail offline too) and imperfect on
purpose (its extractor transcribes the credential, packs two facts into one
record, and emits a record with no value: the three candidates your gate
must catch).

## 9. Reference results (live GLM-4-Flash, free tier)

| Run | Result | Cost |
|---|---|---|
| Part A `tools` | FAIL — wrong file, invented fine | ~10 calls |
| Part A `memory` | PASS — `{"records":"7","total_fine":"1400"}` | ~15 calls, ~7k tokens |
| Part B pipeline (reference) | **PASS 20/20**, credential extracted then rejected by the gate, store clean | ~10 calls, ~5k tokens |

Live models drift (key names, units, an occasional 19/20 on revocation);
grading matches by subject, and the deterministic mock channel is the
authoritative red/green.
