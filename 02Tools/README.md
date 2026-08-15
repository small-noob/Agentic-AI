# Tools, Skills, and the Sandbox — In-Class Exercise

In this exercise you give an agent the tools it needs to audit a month of door-access records, then watch what it still gets wrong and fix that with a written procedure. Lesson 1's agent had exactly one tool, a calculator, hard-coded into the loop. Here tools become a first-class thing: you write the text a model uses to choose between tools, you write a tool yourself, and you package a procedure as a reusable skill.

Complete the exercise in [`Tools_Lab_Learner.ipynb`](./Tools_Lab_Learner.ipynb). This learner notebook is entirely in English and does not contain the reference implementation.

## Learning goals

By the end of the exercise, you should be able to:

- turn a plain function into a tool a model can discover and call;
- explain why a tool's description, not its body, is its interface;
- distinguish a tool (one atomic operation) from a skill (a packaged procedure);
- explain why progressive disclosure makes a hundred skills affordable;
- explain why a path check must run after `Path.resolve()`, not before.

## The audit problem

A badge system has been running for a month and now has to be audited. Three files sit in `workspace/`:

| File | What it holds |
| ---- | ------------- |
| `policy.json` | allowed hours, per-door minimum clearance, the violation rules, the report-code formula |
| `employees.json` | badge_id → clearance level and status |
| `logs/access_2026-08.csv` | the raw swipe records: `timestamp, badge_id, door, result` |

The agent must report three values:

| Field | Meaning |
| ----- | ------- |
| `suspect` | the badge_id with the most policy violations |
| `violations` | the total number of violating records across all badges |
| `code` | the six-digit report code defined in `policy.json` |

**None of that data is in the prompt.** Lesson 1 made arithmetic the thing you could not fake; this exercise makes it file I/O. An agent with no working file tools cannot even name the badge.

The difficulty is not arithmetic either. It is the cross-file join: the log alone cannot tell you whether a record is a violation, because that depends on the roster and the policy at the same time. `policy.json` is the only authority on what counts as a violation — read it before you start. This README does not repeat its rules.

## What you need to complete

The notebook already provides the tool registry, the path sandbox, the calculator, the ReAct loop, the offline client and the grader. Your work is limited to three things.

### TODO 1 — the descriptions for `read_file` and `write_file`

Both functions are already written. You do not change a line of their code. What is missing is the only part the model ever sees: the tool description and the description of each parameter.

The model never receives a function body. It receives the catalogue that `registry.describe()` assembles out of those strings, and it picks a tool and its arguments from that alone. Say what the tool is for, what the path is relative to, an example value, and what the ceiling on `max_bytes` is.

### TODO 2 — a `list_files` tool

Write and register one tool yourself, so the model can discover the real filenames instead of guessing them:

```python
def list_files(path: str = ".") -> str
```

It must annotate its parameter, route `path` through `resolve_safe_path`, and raise `ToolError` rather than `SandboxError` when a path is rejected — the first becomes an Observation the model can correct, the second ends the run. Mark which entries are folders, and cap the number of entries.

### TODO 3 — a `SKILL.md` audit procedure

Write the procedure that turns a well-equipped but aimless agent into one that gets the answer right. The file has two parts: frontmatter (`name` and `description`) that sits in every system prompt and must stay under 400 characters, and a body that is loaded only when the model calls `load_skill`.

Write it from the failing trace you produced in section 3, one line for every mistake you saw. **Never hard-code the answer in the body.** A skill is a procedure, not a lookup table — swap in a different log file and yours must still work.

You do not need to write the path sandbox. It is provided, and section 0 shows what it defends against.

## Available actions

The model may use one action per turn:

```text
Action: list_files
Action Input: {"path": "."}

Action: read_file
Action Input: {"path": "policy.json"}

Action: calculate
Action Input: {"expression": "(11 * 9176 + 1005 * 31337) % 1000000"}

Action: load_skill
Action Input: {"name": "audit_access_log"}

Action: finish
Action Input: {"suspect":"Bxxxx","violations":0,"code":"xxxxxx"}
```

Lesson 1 parsed a single shape, `Calculate[expr]`. With several tools an action needs a name *and* structured arguments, which is why the format changes here.

The verifier in front of `finish` checks shape and process — that the files were read, that `calculate` produced the code, that the report was written. It never checks the answer against a stored key, because no real deployment has one.

## Requirements

- Python 3.9 or later
- VS Code with the Jupyter extension, Jupyter Notebook, or JupyterLab
- An internet connection and a Zhipu API key only if you want the live model run

The notebook uses only the Python standard library. You do not need to install any other package. Environment setup instructions are in [`../01Introduction/preclass_setup/`](../01Introduction/preclass_setup/).

## Running the notebook

Open `Tools_Lab_Learner.ipynb` and select a Python kernel. Run the cells from top to bottom.

For the first run, use the offline client:

```python
USE_REAL_API = False
```

This mode does not call an API and produces a fixed trace, which is useful for checking your code. The whole exercise can be completed this way at no cost.

After the offline version passes, you may try the live model:

```python
USE_REAL_API = True
```

The default model is `glm-4-flash-250414`. Live model traces may differ from the offline trace.

## Setting the API key

### Get a Zhipu API key

1. Go to the [Zhipu AI Open Platform](https://bigmodel.cn/) and register or sign in with a phone number or email address.
2. Open the [**API Keys** page](https://bigmodel.cn/apikey/platform) from your account dashboard.
3. Select **New API Key** to create a key for your account.
4. Copy the key and store it safely. Do not post it in a chat, commit it to a repository, include it in a screenshot, or save it in the notebook you submit.

The recommended method is to start VS Code from a terminal where `ZAI_API_KEY` is set.

Linux or macOS:

```bash
export ZAI_API_KEY="your API key"
```

Windows PowerShell:

```powershell
$env:ZAI_API_KEY="your API key"
```

If VS Code is already open, close it before running these commands. It must be started from the same terminal to receive the environment variable.

If the environment variable is not set, the notebook uses `getpass()` to request the key temporarily. The input is hidden and is not printed in the notebook output.

Do not place an API key in:

- a normal Python string;
- a `%env` cell;
- an `os.environ[...]` assignment;
- the README or a screenshot;
- the notebook you submit.

Restart the kernel after the live test so that the key is removed from the current Python process.

## Suggested workflow

1. Set `USE_REAL_API = False`.
2. Run the setup and scaffolding cells.
3. Run section 0 and read all thirteen lines of the sandbox report.
4. Complete TODO 1, then read the tool catalogue the model receives.
5. Complete TODO 2, and confirm `list_files` appears in that catalogue.
6. Run section 3 and study the failing trace. Do not skip this — it is the material for TODO 3.
7. Complete TODO 3.
8. Run section 5 and check for `Score 20/20 — PASS`.
9. If time allows, switch to `USE_REAL_API = True` and compare the live trace.

## Completion check

Your offline run should show that:

- all 10 sandbox attacks are blocked and all 3 legitimate paths are served;
- the tool catalogue contains no `TODO` text;
- `list_files`, `read_file`, `write_file` and `calculate` all appear in the catalogue;
- the NoSkill run reaches a confident, wrong answer;
- the Skill run calls `load_skill` before anything else;
- the final grade is `Score 20/20 — PASS`.

The live model may read the files in a different order or take a different number of steps. It still needs to load the skill, read all three files, compute the code with `calculate`, write the report, and finish within the step limit.

## Grading

| Item | Points | How it is judged |
| ---- | -----: | ---------------- |
| Tools | 6 | descriptions written (2) + `list_files` registered and working (4) |
| Answer | 8 | `suspect` 3, `violations` 3, `code` 2 |
| Format | 2 | `Bxxxx` shape, integer, six digits |
| Process | 4 | all three data files read, `calculate` used, report written, `load_skill` called |

The process points are read off the tool-call history, so guessing the right answer earns nothing.

## Common problems

### `[TODO 2] list_files is not registered yet`

TODO 2 is still a stub. Until you register the tool, the agent's first action fails with `Unknown tool list_files` and the rest of the trace is noise.

### `TypeError: Tool list_files parameter path needs a supported type hint`

The registry builds the model-facing schema from your type hints. Annotate every parameter. Only `str`, `int`, `float` and `bool` are supported.

### The run ends with `max_steps`

Check whether one tool is failing on every call. Every Observation is printed, so start from the first `Tool error` and work forward.

### `finish` keeps getting rejected

Read the rejection message — it is specific. Before it can submit, the agent has to have read enough files, computed the code with `calculate`, written the report, and loaded the skill.

### The score stalls at 13/20 or 14/20

The agent is answering without reading `employees.json`. That is the failure this exercise is built around: your SKILL.md body has to say, explicitly, that the log cannot decide a violation on its own.

## Submitting

Save and hand in the notebook with all cells run from top to bottom. If you also ran the live model, keep that output too and say so — a live trace that differs from the offline one is interesting, not a problem. Check that no API key appears anywhere in the saved output.
