# Memory Lab — student package

Everything happens in **`Memory_Lab_Learner.ipynb`**. Part A you run and
watch; Part B you answer four TODOs in the notebook's cells, one at a time,
and each step gives you instant ✓/✗ feedback from a live run.

## Setup

Python 3.10+. The only third-party dependency is optional
(`pip install -r requirements.txt` installs tiktoken for exact token counts;
without it a character-class estimator is used).

```bash
cd 03Memory/student
export ZAI_API_KEY="your key"        # macOS/Linux;  ZHIPU_API_KEY also works
$env:ZAI_API_KEY="your key"          # Windows PowerShell
jupyter lab                          # open Memory_Lab_Learner.ipynb
```

**Never put a real API key in a cell, a file, a screenshot, or a Git
repository.** The 6-point write-gate item in Part B is this exact rule,
applied to the agent. (The `sk-proj-...` string planted in the lesson
materials is a fake.)

Every model call is live — there is no offline mode. The one part of your
work that needs no API at all is the write gate (TODO 2), and *why that is*
is one of the lesson's exam points.

## What is in each folder

| Folder | Contents | Yours to edit? |
|---|---|---|
| `models/` | the Zhipu HTTP client, the token estimator | no |
| `tools/` | chapter 2's toolset, imported — not copied (`lesson2.py`) | no |
| `tasks/` | the session scripts, the briefing transcript, all ground truth, the `workspace/` | no |
| `memory/` | the store, the policy class your answers bind onto, the Part A reference | no — your answers live in the notebook |
| `agent/` | the ReAct loop, the step pipeline, the grader, the trace display | no |
| `runs/` | every run's output files — inspect and diff them freely | generated |

The notebook is the only place you write code. Each TODO cell defines one
method and binds it onto `MemoryPolicy`; the step cells drive exactly the
same pipeline as the command line:

```bash
python agent/main.py --mode compare              # Part A from a terminal
python agent/pipeline.py --implementation solution   # the reference pipeline
```

## The finish line

The notebook's final cells run the whole pipeline on a fresh lineage and
scan the store for leaked credentials. Target: **PASS — 20/20** and a clean
store (`grep "sk-" runs/final_memory.jsonl` prints nothing). Live models
drift — an occasional 19/20 on the revocation item is variance; run again.

**Submit:** the completed notebook (with outputs) and
`runs/final_memory.jsonl`.
