# Tools, Skills, and the Sandbox — Teacher notes

## The two files, and what differs between them

- [`Tools_Lab_Learner.ipynb`](./Tools_Lab_Learner.ipynb) — the student version. English, three TODOs, no reference implementation. This is what you hand out.
- [`Tools_Lab_Teacher.ipynb`](./Tools_Lab_Teacher.ipynb) — the same notebook with the three TODOs filled in and a quoted teaching note under each section heading. Running it top to bottom gives 10/10 attacks blocked and 20/20 PASS.
- `README.md` — the student handout: task, TODOs, environment, acceptance criteria.

The teacher notebook is **generated from the learner notebook by substitution**. Every cell is identical except the three TODO blocks, and the build refuses to run if a placeholder survives into the teacher copy. Do not hand-edit one and expect the other to follow; if you change the exercise, change the learner cells and regenerate.

Both notebooks default to `USE_REAL_API = False`.

## Reference answer

| Field | Value |
| ----- | ----- |
| `suspect` | `B1005` |
| `violations` | `11` |
| `code` | `594621` |

`code = (11 × 9176 + 1005 × 31337) mod 1000000 = 31594621 mod 1000000 = 594621`.

Per-badge violation counts: `B1005: 7`, `B1003: 2`, `B1006: 1`, `B1002: 1`.

## The three traps in the dataset

The data is 107 records and every trap produces a *different* wrong number, which is what makes the failing run worth studying:

1. **B1005's badge is `revoked`**, so all seven of its granted entries are violations — including the daytime lobby swipe on 2026-08-07. A student who filters only on "after hours" gets 6 and is one short.
2. **Four `denied` rows** look like the worst offences in the file and count for nothing. They are the control working correctly.
3. **A record breaking three rules is still one record.** Counting reasons instead of records inflates the total.

Together these mean the log alone cannot decide anything. An agent that reads only the CSV produces a confident, plausible, wrong answer — which is exactly the failure the skill exists to prevent. Do not let the class move past section 3 until someone says that out loud.

## How lesson 2 iterates on lesson 1

| | Lesson 1 | Lesson 2 |
| --- | --- | --- |
| The A/B being taught | no tools vs tools (Direct vs ReAct) | no procedure vs procedure (NoSkill vs Skill) |
| Tool count | 1, hard-coded into the loop | 4 + `load_skill`, mounted on a registry |
| Action format | `Calculate[expr]` | `Action: name` + `Action Input: {JSON}` |
| Where the data lives | in the prompt | on disk, reachable only through tools |
| The bottleneck | arithmetic | file I/O |
| What students write | the ReAct loop | tool descriptions, one tool, one SKILL.md |

The calculator is lesson 1's, unchanged. Point that out — it is the first concrete payoff of giving tools a stable interface instead of hard-coding one.

## Section 0 · the sandbox, and why it is no longer a TODO

This started life as an exercise, and it is worth knowing what students produced when it was. Almost every first attempt was:

```python
if ".." in user_path or user_path.startswith("/"):
    raise SandboxError(...)
```

That blocks 7 of the 10 attacks. The three it misses are the symlink cases, and they are the whole point: `escape_secrets` has no `..` and no leading `/`, so no check on the *text* of a path can see where it leads. The provided implementation calls `Path.resolve()` first — following symlinks, collapsing `..` — and only then tests containment.

Handing the answer over does not lose the lesson, as long as you make them **run** the cell and read all thirteen lines. Two questions that work well in the room:

- Which of the two failure modes — the leaky sandbox, or one that refuses everything — would survive code review? Which would survive production? The leaky one passes every happy-path test.
- Why are there three "must still be allowed" cases at all? Because a resolver that only ever raises blocks all ten attacks and is useless. A sandbox's job is to discriminate, not to refuse.

## Section 1 · descriptions

The bodies are given; students write only the descriptions. What to draw out: the model never sees a function body, only the catalogue `registry.describe()` builds from these strings. A description has to say **what the tool is for**, **what the path is relative to**, **an example**, and **the ceiling**.

Good classroom move: read two students' catalogues aloud and ask which one the class could act on without seeing the code.

## Section 2 · `list_files`

Three things to point at in the reference answer:

- `path` goes through `resolve_safe_path` — that is what the sandbox is for;
- a rejected path raises **`ToolError`**, not `SandboxError`. The first becomes an Observation the model can correct; the second ends the run. This distinction is worth a minute of its own;
- the entry count is capped, or one large folder floods the context window.

Marking directories is not decoration either. Without it the model calls `read_file` on `logs` and burns a turn on the error.

## Section 4 · tool vs skill

One sentence each:

- A **tool** is one thing the runtime can do. It costs a schema in the system prompt and returns an Observation.
- A **skill** is a procedure for using tools. It costs one catalogue line and returns instructions.

The payoff is measurable and the notebook prints it: the reference skill's catalogue line is about 160 characters against a 2,400-character body, so a hundred skills cost roughly 16,000 characters resident instead of 250,000. Ask what happens at a thousand skills, and where the failure mode moves to — the description, not the body.

The hard rule in the handout is that the body must not contain the answer. Check for this when marking: `B1005`, `11` and `594621` appear nowhere in the reference SKILL.md, and a submission that hard-codes any of them has written a lookup table, not a procedure.

## Grading — 20 points

| Item | Points | Judged by |
| ---- | -----: | --------- |
| Tools | 6 | descriptions written (2) + `list_files` registered and working (4) |
| Answer | 8 | `suspect` 3, `violations` 3, `code` 2 |
| Format | 2 | shape of each field |
| Process | 4 | all three files read, `calculate` used, report written, `load_skill` called |

Process points come off the tool-call history, so a student who hard-codes the three values into `finish` still fails: the history will not show `employees.json` being read or `load_skill` being called.

`EXPECTED` is visible in the grading cell and students can read it. That is a deliberate trade — local self-grading is worth more than hiding three numbers, and knowing them is not enough to pass. The one thing it costs is section 3: a student who has read `EXPECTED` already knows the true count is 11. If a cohort starts skipping that observation step, regenerate the dataset and hand out a notebook whose `EXPECTED` matches the new data.

### A deliberate difference from lesson 1

Lesson 1's `Finish` verifier compared against the stored answer and rejected wrong ones. That is a classroom shortcut, and it quietly hands the model the answer: keep guessing, the verifier says when you are right.

This lesson's verifier checks **shape and process only** and never looks at the expected values — the constraint every real deployment lives under. Students routinely assume a verifier can validate correctness, so this is worth ten minutes.

## Debrief answers

**1. Where should a piece of knowledge live?** System prompt: always present, always paid for, crowds everything else out as the number of tasks grows. Tool description: also paid for on every call, and the right home for anything about that one tool's interface. Skill: one catalogue line resident, body on demand — the right home for multi-step procedure. The test is whether the knowledge is about a *tool* or about a *job*.

**2. Why can't a verifier check correctness?** Because a verifier holding the answer is just an oracle — the model can guess until it is told it is right. Production has no answer key. What a real verifier can check is what a correct *process* must look like: which files were read, which tool produced the number.

**3. Does the sandbox stop prompt injection?** No, and this is the most valuable of the three. The sandbox constrains what the **runtime will do**, not what the **model will decide to do**. An injected agent will happily call `read_file('../secrets.env')`; the sandbox stops the read, not the decision. Students who conflate the two build agents that treat a persuasive document as authority.

## Suggested classroom timing (50–60 minutes)

- 5 min — recap lesson 1's single hard-coded tool; show what `registry.describe()` prints.
- 8 min — section 0. Run it, then walk the three symlink attacks.
- 5 min — TODO 1. Most of the work is writing prose, not code.
- 10 min — TODO 2.
- 8 min — section 3. Run it, then have the class list what went wrong before you say anything.
- 10 min — TODO 3, written directly from that list.
- 5 min — section 5, compare the two runs.
- 5–10 min — debrief.

If time is short, hand out TODO 1 completed and keep 2 and 3; the skill is the part students most often want to take home and finish.

## Regenerating the dataset

The workspace is generated deterministically. To reuse the assignment next term with a fresh answer key, change the seed and the suspect's event list, then update `EXPECTED` in the grading cell of both notebooks and the reference numbers in this file.

Keep the `denied` decoys and the daytime revoked swipe — they are what separate a careful reading of the policy from a plausible guess.
