# 02Tools — Assignment

## 1. What you are building

You are giving an agent the tools it needs to **audit a month of door-access
records**.

In lesson 1 the agent had exactly one tool, a calculator, hard-coded into the
loop. This time is different: **none of the data the task needs is in the
prompt. It is all on disk.** The agent has to read files to get anywhere — so
you will build that ability, and make sure those tools cannot be turned around
and used to read things they should not.

### The task

The workspace holds three files:

```text
workspace/
├── policy.json                 access policy: allowed hours, per-door clearance, violation rules, report-code formula
├── employees.json              roster: badge_id → clearance level and status
└── logs/access_2026-08.csv     raw swipe records (timestamp, badge_id, door, result)
```

The agent has to report three values:

| Field | Meaning |
| --- | --- |
| `suspect` | the badge_id with the most policy violations |
| `violations` | the total number of violating records across all badges |
| `code` | the six-digit report code defined in `policy.json` |

**`policy.json` is the only authority on what counts as a violation and how the
code is computed.** This handout does not repeat those rules — go read that file
first.

### The four things you submit

| | What | Which file |
| --- | --- | --- |
| TODO 1 | Write the path sandbox `resolve_safe_path` | `starter_tools.py` |
| TODO 2 | Write the descriptions for the finished `read_file` / `write_file` | `starter_tools.py` |
| TODO 3 | Write a `list_files` tool yourself | `starter_tools.py` |
| TODO 4 | Write a `SKILL.md` audit procedure | `skills_starter/audit_access_log/SKILL.md` |

**Only those two files need to change.** Everything else is scaffolding.

---

## 2. Set up

Python 3.10 or newer. Standard library only — nothing to install.

```bash
cd 02Tools
python3 main.py --mode compare --offline
```

If you see `[NO SKILL] FAIL` and `[SKILL] PASS`, your environment is fine.
`--offline` uses a built-in fake model: no cost, no API key. **You can keep it on
for the entire assignment.**

Only configure a key when you want to call the real model (never put it in code
or a screenshot):

```bash
export ZAI_API_KEY="your API key"
export ZAI_MODEL="glm-4-flash-250414"
```

---

## 3. Before you write anything, watch it fail

```bash
python3 main.py --mode noskill --offline
```

Read the whole output. You will see the agent's `Thought` / `Action` /
`Observation` for every turn, and a 13/20 FAIL at the end.

**Study what it got wrong. That is the raw material for TODO 4.**

Then see what the reference implementation does:

```bash
python3 main.py --mode compare --offline
```

Same tools, 20/20 the second time. The only difference is that it loaded a
written-down procedure. Reproducing that difference is the point of this
assignment.

---

## 4. TODO 1 — the path sandbox

Open `starter_tools.py` and implement
`resolve_safe_path(root, user_path, must_exist=False)`.

Its job: turn an **untrusted** path into a real path inside the sandbox
directory, and raise `SandboxError` if that path would escape.

All three file tools go through it. It is the only door between the agent and
the rest of your disk.

### How to test it

```bash
python3 main.py --mode sandbox --implementation starter
```

Ten escape attempts get aimed at your function, and three legitimate requests
must still go through. The output looks like this:

```text
[blocked] parent_traversal   ...
[ESCAPED] symlink_to_file    escaped to /tmp/.../secrets.env    ← this line means you failed
--- these must still be allowed ---
[allowed] existing_file      ...
[REFUSED] workspace_root     ...                                ← so does this one
```

**To pass: all 10 `blocked`, all 3 `allowed`, score 6/6.**

### Two warnings

1. `if ".." in path` blocks 7 of the 10 — and scores **zero**. Ask yourself:
   can a path contain no `..` at all and still point outside the sandbox?
2. The opposite also scores **zero**: a function that only ever raises blocks
   all 10 attacks. That is what the 3 "must be allowed" checks are for. A
   sandbox's job is to **discriminate**, not to refuse.

The function's docstring has more detailed hints.

---

## 5. TODO 2 — write what the model reads

Still in `starter_tools.py`, look at `read_file` and `write_file` inside
`build_workspace_tools`.

**Both functions are already written. You do not change a line of code.** What
is missing is the only part the model ever sees — the tool and parameter
descriptions:

```python
@registry.tool(
    "TODO 2a: what does this tool do?",
    path="TODO 2b: what goes in path? relative to what? give an example",
    max_bytes="TODO 2c: what does max_bytes control, and what is the ceiling?",
)
def read_file(path: str, max_bytes: int = MAX_READ_BYTES) -> str:
    ...  # already written
```

The model never sees the function body. It sees a catalogue assembled from those
strings, and picks a tool and arguments from that alone. **The description is
the interface.** Replace every `TODO 2x`.

When you are done, print what the model actually gets and read it:

```bash
python3 -c "from starter_tools import build_workspace_tools; print(build_workspace_tools('workspace').describe())"
```

Read it as the model would: from this text alone, can you tell which tool fits
which job, what each argument takes, and in what form? A tool described as
"reads a file" is a tool the model will call with the wrong path.

---

## 6. TODO 3 — write a tool yourself

At the end of the same function, add a `list_files` tool:

```python
def list_files(path: str = ".") -> str
```

It lists the files and folders in a workspace directory, one per line, so the
model can **discover** the real filenames instead of guessing them.
Requirements:

- register it with `@registry.tool(...)`, described as carefully as the two
  above;
- **annotate the parameter** — without a type hint the registry refuses to build
  a schema and raises `TypeError`;
- **route `path` through `resolve_safe_path`** — this is what TODO 1 was for;
- raise **`ToolError`**, not `SandboxError`, when a path is rejected, so the
  message reaches the model as an Observation it can correct instead of killing
  the run;
- marking which entries are folders saves the model a wasted call;
- cap the number of entries with `MAX_LISTED_ENTRIES` so one huge folder cannot
  flood the context.

The two finished tools above show the shape. Copy the structure, not the text.

### Testing TODO 2 and 3

```bash
python3 -m unittest discover -s tests -v
```

The suite is your checklist: anything unfinished tells you exactly what is
missing (for example `TODO 2: these tools still have placeholder
descriptions`). **It starts red. All green means done.** Once you finish, it
runs the same cases against your implementation and the reference one.

---

## 7. TODO 4 — write the SKILL.md

Open `skills_starter/audit_access_log/SKILL.md`.

**A tool is one thing the agent can do. A skill is the procedure for using
those tools.** Your tools work now, but section 3 showed you what still happens:
the agent skips a file, miscounts, and computes the wrong code. This step writes
down how the task should be done and hands it over.

The file has two parts:

- **Frontmatter** (between the `---` lines): `name` and `description`. This part
  goes into **every** system prompt, so it has to be short (under 400
  characters) and has to say both what the skill does *and* when to use it.
- **Body**: loaded only after the model judges the skill relevant and calls
  `load_skill`. Spend length here — which files must be read, what exactly
  counts as a violation, whether the thing being counted is records or reasons,
  how the report code is computed.

That asymmetry is the whole point: a hundred skills cost a hundred catalogue
lines up front, and the bodies are paid for only on demand.

### How to write it

Go back to the `--mode noskill` output from section 3 and write one line in the
body for **every mistake it made**. What did it skip? What did it miscount? Why
did it miscount?

**One hard rule: never hard-code the answer in the body.** A skill is a
procedure, not a lookup table — swap in a different log file and your SKILL.md
must still work. A line like `the suspect is B1005` fails the assignment.

### How to test it

```bash
python3 main.py --mode skill --implementation starter --skills-dir skills_starter --offline
```

Note `--skills-dir skills_starter`: without it you are running the reference
answer, not yours.

---

## 8. When everything is done

Run these three in order. All three must pass:

```bash
python3 main.py --mode sandbox --implementation starter                                # expect 6/6
python3 -m unittest discover -s tests -v                                               # expect all green
python3 main.py --mode compare --implementation starter --skills-dir skills_starter    # expect 20/20
```

The last one is the graded run. To see how the real model behaves, drop
`--offline` and save the trace:

```bash
python3 main.py --mode compare --implementation starter --skills-dir skills_starter \
  --trace-out runs/my_run.json
```

The trace holds the full model output, actions, observations, tool-call history
and grades. It never contains your API key.

### Submit

- `starter_tools.py`
- `skills_starter/audit_access_log/SKILL.md`
- `runs/my_run.json` (if you ran the real model)

---

## 9. Grading (20 points)

| Item | Points | How it is judged |
| --- | --- | --- |
| Answer | 8 | `suspect` 3, `violations` 3, `code` 2 |
| Format | 2 | `Bxxxx` shape, integer, six digits |
| Process | 4 | all three data files read, `calculate` used, report written, `load_skill` called |
| Sandbox | 6 | all 10 attacks blocked and all 3 real paths served — **one leak and it is 0** |

**Anything short of full marks on any item fails the assignment.**

The process points are read off the tool-call history, so guessing the right
answer earns nothing. The sandbox item is all-or-nothing: a single escape means
the agent can reach `secrets.env` outside `workspace/`.

---

## 10. If you get stuck

**Three attacks keep getting through the sandbox**
The three with `symlink` in the name. Think about it: a symlink's *text* looks
completely ordinary, but the place it points to is outside the sandbox. Is your
check running on the path string, or on where that path really leads?
`Path.resolve()` is worth a look in the docs.

**`TypeError` when a tool is registered**
A parameter is missing its type hint, or uses an unsupported type. Only `str`,
`int`, `float` and `bool` are supported.

**The agent's `finish` keeps getting rejected**
Read the rejection — it is specific. Before submitting, the agent has to have
read enough files, computed the code with `calculate`, and written the report.
That is deliberate: it is not allowed to guess.

**The agent runs out of steps**
`--max-steps` defaults to 12. First check whether some tool is failing on every
call — every Observation is printed, so start from the first `Tool error`.

**You want to see the reference implementation**
`sandbox.py`, `agent_tools.py` and `skills/audit_access_log/SKILL.md` are the
answers to three of the TODOs, and `Tools_Lab_Solution.ipynb` is the solved
notebook. Do not open them before you have written your own.
