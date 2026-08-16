# 03Memory — Memory and Context Management

Chapter 2 gave the agent tools: a registry, a path sandbox, `list_files /
read_file / write_file / calculate`. This chapter answers one question —
**what can tools not do?** — and then has you build the thing that can.

**Tools extend what an agent can DO; memory extends what it can KEEP.**

The whole lab is one notebook, **`Memory_Lab_Learner.ipynb`**, in two halves:

| | What it is | What you do |
|---|---|---|
| **Part A** | A five-minute A/B demo: the same agent with and without memory | Run the cells, read the two traces, end on the comparison card |
| **Part B** | The exercise: four TODOs (extract → gate → reconcile → budgeted context) driven over one long transcript | Answer each TODO **in the notebook**, run its step live, move on when it is green |

## Files

```text
Memory_Lab_Learner.ipynb   the lab — background, Part A, and your four TODOs
Memory_Lab_Teacher.ipynb   instructors only: answers filled + teaching notes
README_Teacher.md          instructors only: design notes, grading, classroom plan
memory_lab.py              all the machinery, sectioned and readable — not a TODO
memory_agent.py            Part A's internal reference pipeline — do NOT open
                           before the debrief; Part B asks you to build exactly this
workspace/                 three incident files (reset to canonical every session)
runs/                      created at runtime — every step's output, inspectable
```

The notebook teaches; `memory_lab.py` holds the gears — the API client, the
store, the ReAct loop, the grader, the step pipeline, and chapter 2's
sandboxed toolset (embedded verbatim since lesson 2 became notebook-only).
The chapter is fully self-contained; open `memory_lab.py` when a TODO's spec
names something.

## Setup

Python 3.10+, once per environment:

```bash
cd 03Memory
pip install -r requirements.txt     # jupyterlab + tiktoken
jupyter lab                         # open Memory_Lab_Learner.ipynb
```

(Opening the notebook in VS Code instead? You only need
`pip install ipykernel`, then pick your environment as the kernel.)

The setup cell asks for your API key in a **hidden prompt** — paste it there
and it stays in the kernel's memory only. (Setting `ZAI_API_KEY` /
`ZHIPU_API_KEY` in your shell before starting Jupyter also works and skips
the prompt.)

**Never put a real API key in a cell, a file, a screenshot, or a Git
repository.** The 6-point write-gate item in Part B is this exact rule,
applied to the agent. (The `sk-proj-...` string planted in the lesson
materials is a fake.)

Every model call is live (free GLM-4-Flash) — there is no offline mode. The
one part of your work that needs no API at all is the write gate (TODO 2),
and *why that is* is one of the lesson's exam points.

## The finish line

The notebook's final cells run the whole pipeline on a fresh lineage and
scan the store for leaked credentials. Target: **PASS — 20/20** and a clean
store (`grep "sk-" runs/final_memory.jsonl` prints nothing). Live models
drift — an occasional 19/20 on the revocation item is variance; run again.

**Submit:** the completed notebook (with outputs) and
`runs/final_memory.jsonl`.
