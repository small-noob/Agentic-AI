# Instructor notes — not for distribution

Companion to *Memory and Context Management*. The student-facing story is in
`README.md` and the learner notebook; this file explains why the
lesson is shaped the way it is, what to protect when editing, and how to run
the classroom. `Memory_Lab_Teacher.ipynb` is the learner notebook with the
four TODO cells filled (every added line tagged `# [solution]`) and boxed
Teaching / Marking notes at each stop.

---

## 1. The shape: demo and exercise are separate on purpose

One lesson, two halves that share a world but not a dependency:

- **Part A** exists to make exactly one point — *tools extend what an agent
  can do, memory extends what it can keep* — in about 25 model calls. It is
  PASS/FAIL and students write nothing for it.
- **Part B** is where all four TODOs live, driven directly over one long
  transcript with no agent loop around them. Students answer in the
  notebook: each TODO cell binds one method onto `MemoryPolicy`, each step
  cell runs it live and prints ✓/✗ feedback that mirrors the grader.

Things this lesson deliberately does **not** contain, and why:

| Left out | Why |
|---|---|
| A full-history baseline ("just carry every transcript") | at classroom scale a competent compactor re-extracts the facts every turn and passes anyway — the honest lesson becomes unit economics, too subtle for a demo. It survives as a discussion question |
| A per-turn token budget in Part A | budget pressure is TODO 4's subject; in the demo it only adds noise |
| A `recall` tool | the digest is injected into context by the harness — retrieval-as-a-tool is a later chapter's topic |
| An offline/mock channel | every check students run is a live one; the only TODO that needs no API is the gate, and *why* is an exam point. The attack-set cell (pure code, deterministic) is the gate's always-available test |

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
  (`sessions.reset_workspace`, wired through `run_sessions`). Live models
  write what the user said into files when the disk lets them, and leftovers
  would quietly hand the tools baseline the answers. The system prompt also
  forbids it, but the reset is the real defence.

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
`report_recipient` deleted, the new log file + audit day added,
`incident_file` NOOPed, no `sk-` anywhere in the store.

## 4. The student loop, and why it is a loop

Every TODO is three cells in the learner notebook: **① background →
② answer the TODO cell (it binds the method) → ③ run the step cell (live)
and read the ✓/✗ feedback**. All green → next TODO; a red line names the
fix. Each step saves its output under `runs/`
(`0_initial_memory` → step files → `final_memory`) and later steps read the
earlier steps' files, so every stage is inspectable, diffable, and the chain
survives a kernel restart. The binding is per-kernel: after a restart the
TODO cells must be re-run — a `NotImplementedError` always names the cell
that was skipped.

## 5. Boundaries to keep teaching (the transferable content)

- **The gate never calls the model.** The model does not approve its own
  output; a nondeterministic gate cannot be reviewed. It is the only TODO
  testable without an API key — consequence, not coincidence — and the
  attack-set cell is that test: ten records, eight to reject, **two to
  admit**.
- **The gate never compares against state.** Duplicates are reconcile's
  NOOP, changed values its UPDATE. An early draft put dedup in the gate and
  reconcile's NOOP became dead code that never errored — misplaced
  responsibility produces exactly that. The two must-admit attack records
  pin this boundary.
- **Extraction reads user turns only.** The planted wrong arithmetic becomes
  a `ten_record_total`-style record if (and only if) assistant turns are
  included; the step-1 feedback calls it out by name. Self-poisoning is a
  real live failure, not a hypothetical.
- **Revocation needs its own pass** ("stop sending X" has no new value, so
  extraction never produces a candidate), and a changed value is an UPDATE,
  not a revocation — conflate them and the fine gets deleted instead of
  updated.

## 6. Grading decisions, and the live behaviour behind them

| Decision | The live behaviour it answers |
|---|---|
| TODO 1 matched by key OR value | models rename keys (`audit_file` for `log_file`); key-locked grading grades the model's naming taste, not the student's extraction |
| TODO 3 values matched loosely ("250 yuan" counts as 250) | the same drift on the value side; the prompt asks for bare numbers, the grader stays tolerant |
| Gate judged against what was OFFERED | some live extractions are clean — an idle gate on a clean run is not a failure; a leak always is; the attack-set cell always offers the bad candidates |
| Code-side verdict guards (UPDATE→ADD / DELETE→NOOP when nothing is stored) | models return UPDATE for keys that hold nothing; the model names the relationship, the code keeps operations coherent with state |
| The verifier never checks answer values | its errors are fed back to the model as Observations — value checks would leak the answer |

Points: TODO 1 = 4 (one per expected fact) · TODO 2 = 6, all or nothing ·
TODO 3 = 6 (UPDATE trail 2, revocation 2, NOOP 1, ADD 1) · TODO 4 = 4
(fits 2, trim-before-compact 1, final instruction verbatim 1). Anything
short of 20/20 fails.

## 7. Where the answers live

The teacher notebook's filled TODO cells are the single source of the
standard answer — there is no separate solution file. The lesson does ship
`memory_agent.py` next to the notebooks, the harness-internal reference that
Part A's memory demo runs; it is unannotated and not shaped like the
notebook answers, and its docstring tells students the notebook is the
intended path. It cannot be removed: Part A imports it.

## 8. Suggested classroom plan (45–55 min)

| Time | What |
|---|---|
| 5 min | Part A: run tools then memory; read the tools failure out loud (wrong file, invented fine) |
| 3 min | The memory.jsonl cell — the store is a file you can read |
| 4 min | Part B framing: seed + transcript; the three-cell loop per TODO |
| 8 min | TODO 1: answer → step 1 → open `runs/1_todo1_candidates.json` |
| 6 min | TODO 2: the shortest TODO, the most transferable line — *which judgements may never be delegated to the model*. Attack set → step 2 → point at the rejected credential |
| 10 min | TODO 3: four verdicts + the separate revocation pass; step 3, project the `~ superseded` and `x deleted` rows |
| 10 min | TODO 4: the ladder; step 4, red ✗ rungs → green ✓ landing, then the report card |
| 4 min | The finish-line cells: full run, credential scan, submission checklist |

If time runs short, cut in this order: hand out TODO 4's ladder → hand out
the revocation pass → give half of TODO 1's prompt. **Do not cut TODO 2.**

## 9. Discussion questions (with the thread of an answer)

1. Which of Part A's failures is fixable with money — and what does the
   answer imply for system design? *(records: yes, better tools/retrieval;
   the spoken fine: no — no spend recovers what was never persisted)*
2. Why may the write gate never call the model? *(the model must not approve
   its own output; nondeterministic gates cannot be reviewed or tested)*
3. Extraction reads user turns only. What real failure does that prevent?
   *(self-poisoning — the assistant's wrong arithmetic entering the store)*
4. An agent that re-summarises its whole history every turn *can* pass this
   kind of task, spending more than half its tokens on compaction. In what
   sense is a good compactor "a memory system paid for by the turn"? When is
   that acceptable?
5. The verifier requires the total to be an actual calculator Observation
   but lets a *wrong* total through. Why is that boundary correct? *(its
   errors go back to the model; checking values would leak the answer)*

## 10. Expected states, for quick triage (live API)

| Situation | Expected |
|---|---|
| Learner notebook, TODO cells unanswered, a step cell run | `NotImplementedError` naming the TODO cell — not a crash |
| Teacher notebook, run top to bottom | Part A: tools FAIL, memory PASS; pipeline **PASS 20/20** (reference run: 22 calls, ~12k prompt tokens) |
| Attack-set cell | 10/10 verdicts, zero API calls |
| `grep "sk-" runs/final_memory.jsonl` | always empty; anything else is an automatic gate zero |
| Occasional 19/20 on revocation | live drift — run again before treating it as a defect |
| A step cell says `runs/<n>_... not found` | the earlier step was never run in this lineage |
