# Instructor notes — not for distribution

Companion to *Memory and Context Management*. The student-facing story is in
README.md; this file explains why the lesson is shaped the way it is, what to
protect when editing, and how to run the classroom.

---

## 1. The shape: demo and exercise are separate on purpose

One lesson, two halves that share a world but not a dependency:

- **Part A** (`main.py`) exists to make exactly one point — *tools extend
  what an agent can do, memory extends what it can keep* — in about 25 model
  calls. It is PASS/FAIL and students write nothing for it.
- **Part B** (`pipeline.py`) is where all four TODOs live, driven directly
  over one long transcript with no agent loop around them.

Things this lesson deliberately does **not** contain, and why:

| Left out | Why |
|---|---|
| A full-history baseline ("just carry every transcript") | at classroom scale a competent compactor re-extracts the facts on every turn and passes anyway — the honest live lesson becomes unit economics, too subtle for a demo. It survives as discussion question 4 |
| A per-turn token budget in Part A | budget pressure is TODO 4's subject; in the demo it only adds noise |
| A `recall` tool | the digest is injected into context by the harness — retrieval-as-a-tool is a later chapter's topic |
| Long multi-session scripts | the old design cost 100+ calls per run and the point drowned in the workload |

## 2. Part A — design invariants (protect these when editing)

The deliverable's two fields are split across the two places knowledge can
live: `records` exists only in `incident_0812.txt` (disk), the *choice* of
file and the fine exist only in session 1 (conversation).

- **Three incident files, and the right one is not the newest.** Live tools
  runs guess `0805` or `0819`; the decoys are what make `list_files`
  insufficient.
- **No file states the fine.** A live tools run once invented `5000` and
  submitted `3 × 5000 = 15000` — well-formed, confidently wrong. Project
  that trace; it is the lesson.
- **The workspace resets at every session start**
  (`sessions.reset_workspace`, wired through `run_sessions(on_session_start)`).
  Live models write what the user said into files when the disk lets them,
  and leftovers would hand the tools baseline the answers. The system prompt
  also forbids it, but the model ignores prompts often enough that the reset
  is the real defence. `test_demo.test_tools_run_fails` is the tripwire: if
  it ever passes, a conversational fact leaked onto disk.

## 3. Part B — the materials map

Seed store: `incident_file=incident_0812.txt`, `fine_per_violation=200`,
`report_recipient=security-team`. The transcript plants, in order: two new
facts (ADD), the fine change 200→250 (UPDATE), "stop sending to
security-team" (DELETE via the revocation pass), the unchanged incident file
(NOOP), a spoken credential plus the same credential inside a 40-line paste
(the gate's target and L1's trim target respectively), one compound fact,
one wrong assistant calculation (the self-poisoning trap), and a final
instruction that must survive TODO 4 verbatim.

The credential appears **twice on purpose**: buried in the paste, live
models usually skip it (config noise); spoken plainly with "hold on to it",
they extract it — which is what gives the gate something real to catch.

Reference end state: `fine_per_violation` 250 current / 200 superseded,
`report_recipient` deleted, `log_file` + `audit_day` added, `incident_file`
NOOPed, rejections non-empty, no `sk-` anywhere in the store.

## 4. The student loop, and why it is a loop

README prescribes the same cycle for every TODO: **read the docstring →
implement → test offline → run the step live → inspect the feedback and the
file it saved**. The machinery behind each stage:

- `check.py` renders the suite as two sections — YOUR TASK LIST (red = not
  done, not a bug) and GUARDRAILS (red = the harness broke). This stops
  students from reading the four NotImplementedError tracebacks as crashes.
  Fresh starter: 80 tests, 4 red, 10 waiting. Finished: all green.
- `pipeline.py --step n` runs one TODO, reads the earlier steps' files, and
  prints an instant ✓/✗ feedback block that mirrors the grader. The file
  lineage in `runs/` (`0_initial_memory` → step files → `final_memory`)
  means every stage's output is inspectable and diffable.
- The mock channel is deterministic and free; the live channel is the
  rehearsal with real drift. The mock's extractor misbehaves on purpose
  (credential, compound record, valueless record) so the gate is exercised
  offline no matter how clean a live extraction happens to be.

## 5. Boundaries to keep teaching (the transferable content)

- **The gate never calls the model.** The model does not approve its own
  output; a nondeterministic gate cannot be reviewed or unit-tested.
  `test_write_gate.py` is the only TODO with complete offline coverage —
  consequence, not coincidence.
- **The gate never compares against state.** Duplicates are reconcile's
  NOOP, changed values its UPDATE. An early draft put dedup in the gate and
  reconcile's NOOP became dead code that never errored — misplaced
  responsibility produces exactly that.
- **Extraction reads user turns only.** The planted wrong arithmetic becomes
  a `ten_record_total` record if (and only if) assistant turns are included;
  the checklist asserts its absence. Self-poisoning is a real live failure,
  not a hypothetical.
- **Revocation needs its own pass** ("stop sending X" has no new value, so
  extraction never produces a candidate), and a changed value is an UPDATE,
  not a revocation — conflate them and the fine gets deleted instead of
  updated. The mock's revoke handler matches only within a window around the
  revoking phrase for the same reason.

## 6. Grading decisions, and the live behaviour behind them

| Decision | The live behaviour it answers |
|---|---|
| TODO 1 matched by key OR value | models rename keys (`audit_file` for `log_file`); key-locked grading grades the model's naming taste, not the student's extraction |
| TODO 3 values matched loosely ("250 yuan" counts as 250) | the same drift on the value side; the prompt asks for bare numbers, the grader stays tolerant |
| Gate judged against what was OFFERED | some live extractions are clean — an idle gate on a clean run is not a failure; a leak always is; the mock always offers the three bad candidates |
| Code-side verdict guards (UPDATE→ADD / DELETE→NOOP when nothing is stored) | models return UPDATE for keys that hold nothing; the model names the relationship, the code keeps operations coherent with state |
| The verifier never checks answer values | its errors are fed back to the model as Observations — value checks would leak the answer; `test_never_checks_the_answer_value` pins the boundary |

## 7. Answer files

- **`memory_starter_solution.py`** — the student-facing standard answer: the
  starter with bodies filled in, every added line tagged `# [solution]`,
  docstrings identical. Nothing imports it; it exists to be read after an
  attempt. Verified: 20/20 through the mock pipeline.
- **`memory_agent.py`** — the harness's internal reference. It **cannot be
  removed**: `--implementation solution`, the guardrail tests and
  `test_write_gate`'s attack-set pattern import it.

## 8. Suggested classroom plan (45–55 min)

| Time | What |
|---|---|
| 5 min | Part A: `--mode compare`; read the tools failure out loud (wrong file, invented fine) |
| 3 min | `cat runs/memory.jsonl` — the store is a file you can read |
| 4 min | Part B framing: seed + transcript; the per-TODO loop; `check.py`'s two sections |
| 8 min | TODO 1: implement → `-k todo_1` → `--step 1` → open `1_todo1_candidates.json` |
| 6 min | TODO 2: the shortest TODO, the most transferable line — *which judgements may never be delegated to the model*. `--step 2`, open `2_todo2_gate.json`, point at the rejected credential |
| 10 min | TODO 3: four verdicts + the separate revocation pass; `--step 3`, project the `~ superseded` and `x deleted` rows |
| 10 min | TODO 4: the ladder; `--step 4`, red ✗ rungs → green ✓ landing, then the report card |
| 4 min | `grep "sk-" runs/final_memory.jsonl`; submission checklist |

If time runs short, cut in this order: provide TODO 4's compact prompt →
provide the revocation pass → give half of TODO 1's prompt. **Do not cut
TODO 2.**

## 9. Discussion questions

1. Which of Part A's failures is fixable with money — and what does the
   answer imply for system design?
2. Why may the write gate never call the model? Why does that make it the
   only fully unit-testable TODO?
3. Extraction reads user turns only. What real failure does that prevent?
4. An agent that re-summarises its whole history every turn *can* pass this
   kind of task, spending more than half its tokens on compaction. In what
   sense is a good compactor "a memory system paid for by the turn"? When is
   that acceptable?
5. The verifier requires the total to be an actual calculator Observation
   but lets a *wrong* total through. Why is that boundary correct?

## 10. Expected states, for quick triage

| Situation | Expected |
|---|---|
| Fresh starter, `python check.py` | 4 red TODOs, guardrails green, 10 waiting |
| Finished starter, `python check.py` | all green, 0 waiting |
| `pipeline.py --implementation starter` (finished) | PASS 20/20; occasional 19/20 on live revocation drift is discussion material, not a defect |
| Any guardrail red | the harness broke — check the last edit to a provided file |
| `grep "sk-" runs/final_memory.jsonl` | always empty; anything else is an automatic gate zero |
