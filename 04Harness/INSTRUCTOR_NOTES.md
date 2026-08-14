# Instructor notes — the script package

> **The teaching notes moved.** Everything about why the lesson is shaped this
> way, the reference answers, the grading rationale, the classroom timing and the
> debrief answers now live in `04Harness/README_Teacher.md` **on `main`**, next
> to the two notebooks it describes. That is the file to read before teaching,
> and the file to edit when the lesson changes.
>
> This file keeps only what is true of *this branch* and of nothing else.

## Why this branch still exists

`main` ships the two notebooks and no `.py` at all. This branch keeps the script
package — `roles.py`, `actions.py`, `events.py`, `task.py`, `verifiers.py`,
`mock_client.py`, `grader.py`, `audit_tool.py`, `main.py`, `harness.py`,
`starter_harness.py` and `tests/` — for two reasons:

1. it is the **source** the notebooks are generated from, and
2. its CLI (`--mode single/pipeline/plan/full`, `--mode sandbox`, `--trace-out`)
   is the fastest way to demo the ladder in class without driving a notebook.

## Generating the notebooks

```bash
python3 make_notebooks.py                    # writes both notebooks here
python3 -m unittest discover -s tests        # 30 tests, exactly 3 failures
```

The 3 failures are the checklist tests, which are red against the untouched
starter by design.

Then carry both files to `main` — **never merge this branch**, which would drag
`harness.py` across:

```bash
git checkout main
git checkout lesson-04-harness-solution -- 04Harness/Harness_Lab_Learner.ipynb \
                                            04Harness/Harness_Lab_Teacher.ipynb
```

`make_notebooks.py` does more than swap three cells. It inlines lesson 4's own
modules one cell per module, strips the imports they make of each other (a
notebook has one namespace), refuses to emit a notebook where two modules define
the same top-level name or where a stray `from task import …` survived — that one
would silently resolve to *lesson 2's* `task.py`, which is also on the path — and
rewrites `task.py`'s `Path(__file__)` line, because a notebook has no `__file__`.
It also refuses to write a teacher notebook in which a `TODO` placeholder
survived. What it does **not** inline is anything from `02Tools`: the setup cell
puts `../02Tools` on `sys.path`, so the notebooks and this package reuse chapter 2
the same way.

Note that Python 3.10+ is required to *run* the generated notebooks — the teacher
cells carry `X | None` annotations that 3.9 evaluates eagerly. macOS's system
`python3` is 3.9.

## Both packages run standalone — checked, not assumed

- script package, untouched starter: 30 tests with exactly 3 failures,
  `--mode single --offline` gives a full trace and 0/30;
- `Harness_Lab_Learner.ipynb`, top to bottom: setup and the nine scaffolding
  cells run, the baseline scores 0/30, execution stops at TODO 1b;
- `Harness_Lab_Teacher.ipynb`, top to bottom: the ladder 0 → 10 → 23 → 30, the
  inlined suite green (30 tests), sandbox PASS.

Four things were needed to make that true, and they are worth knowing if you ever
restructure this:

- `--implementation` defaults to `starter`, and asking for `solution` without
  `harness.py` gives a plain message instead of an import traceback;
- `flow_single` in `main.py` is wired by hand rather than going through `spawn`,
  because the baseline run is what motivates part 1 and therefore has to work
  before part 1 exists;
- both test modules import `harness` inside a `try`, and grade only what is
  present. Here they check the student's work *and* the reference against the same
  cases; in the notebook the same suite runs against `my_harness()`;
- nothing in `harness.py` may import lazily inside a function body. The one that
  did (`from task import KNOWN_REASONS`) was hoisted: inlined into a cell, it
  would have reached across to `02Tools/task.py` and raised.

## Keeping the prose in step

`README.md` on this branch is the script-package handout (`python3 main.py --mode
full`); `README.md` on `main` is the notebook handout ("run the cells"). Same
lesson, two routes. Those two, plus `README_Teacher.md`, are maintained by hand —
everything else the student sees is generated.
