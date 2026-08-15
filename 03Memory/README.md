# 03Memory — Memory and Context Management

Chapter 2 gave the agent tools: a registry, a path sandbox, `list_files /
read_file / write_file / calculate`. This chapter answers one question —
**what can tools not do?** — and then has you build the thing that can.

**Tools extend what an agent can DO; memory extends what it can KEEP.**

The lesson is one Jupyter notebook in two halves:

| | What it is | What you do |
|---|---|---|
| **Part A** | A five-minute A/B demo: the same agent with and without memory | Run the cells, read the two traces |
| **Part B** | The exercise: four TODOs (extract → gate → reconcile → budgeted context) driven over one long transcript | Answer each TODO in the notebook, run its step live, move on when it is green |

## Layout

```text
03Memory/
├── student/     the student package — hand out this folder
│   ├── Memory_Lab_Learner.ipynb     the lab: all four TODOs are answered here
│   ├── models/  tools/  tasks/  memory/  agent/    the scaffolding, by function
│   └── README.md                    setup, workflow, what to submit
└── teacher/     instructors only — do not distribute
    ├── Memory_Lab_Teacher.ipynb     answers filled + teaching / marking notes
    └── README_Teacher.md            design invariants, grading, classroom plan
```

## Quick start (students)

```bash
cd 03Memory/student
export ZAI_API_KEY="your key"        # or ZHIPU_API_KEY; never put it in a cell
jupyter lab                          # open Memory_Lab_Learner.ipynb
```

Every model call is live (free GLM-4-Flash tier) — see `student/README.md`
for details. Instructors start at `teacher/README_Teacher.md`.
