#!/usr/bin/env python3
"""Generate Harness_Lab.ipynb and Harness_Lab_Solution.ipynb.

Instructor tool, same arrangement as lesson 2: the two notebooks are generated
from one source so they cannot drift apart. Every cell is identical except the
three TODO cells, and the solution's bodies are lifted out of ``harness.py`` by
AST, so a change to the reference implementation is picked up here the next time
this script runs.

    python3 make_notebooks.py && python3 -m unittest discover -s tests

The notebooks are **self-contained**, because the student branch ships nothing
but `Harness_Lab.ipynb`, `skills/` and `workspace/` — no `.py` at all. That
leaves two kinds of code to place, and they are placed differently on purpose:

* what lesson 2 already taught (registry, sandbox, calculator, ReAct loop, skill
  loader, client, red team) is **imported** from ``../02Tools`` by the setup
  cell, exactly as ``lesson2.py`` does for the script package. It is not copied
  into the notebook: a fix in chapter 2 has to be a fix here.
* what only lesson 4 has (``task``, ``events``, ``actions``, ``audit_tool``,
  ``verifiers``, ``roles``, ``mock_client``, ``grader``, and the flows out of
  ``main``) is **inlined**, one readable cell per module, because there is no
  earlier chapter to import it from.

Inlining into one flat namespace means the modules' imports *of each other* have
to go — ``strip_local_imports`` does that — and that two modules must never
define the same top-level name, which ``check_no_collisions`` enforces loudly
rather than letting one silently overwrite the other.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import textwrap

LESSON = pathlib.Path(__file__).resolve().parent

# Lesson 4's own modules, in dependency order: each one may only use names the
# cells above it have already defined.
INLINED = ("task", "events", "actions", "audit_tool", "verifiers", "roles",
           "mock_client", "grader")

# From main.py, only the run flows and the printers. The argparse CLI stays
# behind on the instructor branch; in a notebook the cells are the CLI.
MAIN_FUNCTIONS = ("flow_single", "flow_pipeline", "flow_plan", "print_trace",
                  "print_grade", "run_sandbox_check")

# Names that resolve to a cell above instead of to an import.
DROPPED_IMPORTS = frozenset(INLINED) | {"lesson2", "main", "starter_harness", "harness"}


def module_source(name: str) -> str:
    return (LESSON / f"{name}.py").read_text(encoding="utf-8")


def named_source(module: str, *names: str) -> str:
    """The exact source of the named top-level functions in a module."""

    source = module_source(module)
    tree = ast.parse(source)
    found = {
        node.name: ast.get_source_segment(source, node)
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    missing = [name for name in names if name not in found]
    if missing:
        raise SystemExit(f"{module}.py no longer defines {missing}")
    return "\n\n\n".join(found[name] for name in names)


def reference_source(*names: str) -> str:
    """The exact source of the named functions in harness.py."""

    return named_source("harness", *names)


def strip_main_guard(source: str) -> str:
    """Drop a trailing ``if __name__ == "__main__":`` block.

    A notebook cell *is* ``__main__``, so a script's entry point would fire the
    moment the cell runs — in the test modules' case, a second unittest run
    against the notebook's own filename.
    """

    return re.sub(r"\n*if __name__ == [\"']__main__[\"']:\n(?:(?:[ \t]+.*)?\n)*$",
                  "\n", source)


def strip_local_imports(source: str) -> str:
    """Drop the imports that a flat namespace makes meaningless (and wrong)."""

    lines = strip_main_guard(source).splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"(?:from|import)\s+([A-Za-z_]\w*)", line)
        if match and match.group(1) in DROPPED_IMPORTS:
            if "(" in line and ")" not in line:
                while ")" not in lines[index]:
                    index += 1      # a parenthesised import runs over several lines
            index += 1
            continue
        kept.append(line)
        index += 1
    return re.sub(r"\n{4,}", "\n\n\n", "\n".join(kept)).strip()


def top_level_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def check_no_collisions(sources: dict[str, str]) -> None:
    """One namespace, so a name defined twice is a silent overwrite."""

    seen: dict[str, str] = {}
    for module, source in sources.items():
        for name in top_level_names(source):
            if name in seen:
                raise SystemExit(
                    f"{module}.py and {seen[name]} both define {name!r}; the "
                    f"inlined notebook has one namespace, so rename one of them"
                )
            seen[name] = f"{module}.py"


def scaffolding_cells() -> list[dict]:
    """One cell per lesson-4 module, plus the flows lifted out of main.py."""

    sources = {name: strip_local_imports(module_source(name)) for name in INLINED}

    # A notebook has no ``__file__``; the setup cell worked the folder out already.
    anchor = "LESSON_ROOT = Path(__file__).resolve().parent"
    if anchor not in sources["task"]:
        raise SystemExit("task.py no longer sets LESSON_ROOT from __file__")
    sources["task"] = sources["task"].replace(
        anchor,
        "LESSON_ROOT = LESSON_DIR   # a notebook has no __file__; see the setup cell",
    )

    sources["main"] = strip_local_imports(named_source("main", *MAIN_FUNCTIONS))
    check_no_collisions(sources)

    titles = {
        "task": "the problem statement and what a correct run produces",
        "events": "the run log the grader reads",
        "actions": "the three services, and the three ways they fail",
        "audit_tool": "last week's exercise, packaged as a tool",
        "verifiers": "asking the log what actually happened",
        "roles": "the three role specs: prompt, tool subset, finish verifier",
        "mock_client": "the offline model — deterministic, no API key",
        "grader": "the 30 points, all of them read off the event log",
        "main": "the run flows and the trace printer",
    }
    return [code(f"# ── {name}.py — {titles[name]}\n\n{source}")
            for name, source in sources.items()]


def test_cell_source() -> str:
    """tests/ inlined: the same suite the script package runs with unittest."""

    preamble = re.compile(
        r"import starter_harness\n+try:\n.*?\n\s+harness = None\n", re.DOTALL)
    titles = {"test_plan": "is the plan allowed to run?",
              "test_run": "end-to-end runs, the role table, the sandbox regression"}
    bodies = []
    for name in ("test_plan", "test_run"):
        source = (LESSON / "tests" / f"{name}.py").read_text(encoding="utf-8")
        source, count = preamble.subn("", source)
        if count != 1:
            raise SystemExit(f"tests/{name}.py no longer starts the way this expects")
        bodies.append(f"# ── {titles[name]}\n\n{strip_local_imports(source)}")

    header = '''
    # The test suite. It checks whatever this notebook has defined so far: your
    # three parts, looked up as of now.
    starter_harness = my_harness()
    harness = None          # the reference implementation is not in this package
    '''
    runner = '''
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for value in list(globals().values()):
        if isinstance(value, type) and issubclass(value, unittest.TestCase):
            suite.addTests(loader.loadTestsFromTestCase(value))
    unittest.TextTestRunner(verbosity=2).run(suite)
    '''
    return "\n\n\n".join([textwrap.dedent(header).strip(), *bodies,
                          textwrap.dedent(runner).strip()])


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {},
            "source": textwrap.dedent(text).strip().splitlines(keepends=True)}


def code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": textwrap.dedent(text).strip().splitlines(keepends=True)}


# ---------------------------------------------------------------------------
# The three TODO cells: stub for the lab, reference for the solution.
# ---------------------------------------------------------------------------

TODO_1_STUB = '''
    # TODO 1a — spawn one sub-agent under one role.
    #
    #   spec = ROLE_SPECS[role]
    #   registry = build_all_tools(ctx)          # every tool in the lesson
    #   registry.tools = {...}                   # <- cut it down to spec.tools
    #   agent = RoleAgent(client, registry, spec.make_verifier(ctx), spec.template,
    #                     skill_index=skills_index_for(spec, ctx.skills),
    #                     model=ctx.model, max_steps=ctx.max_steps)
    #   ctx.log.spawn(role, prompt, registry.names())   # before it runs
    #   result = agent.run(prompt)
    #   ctx.log.agent_done(role, result)
    #
    # The one line that matters is the third. Everything else is wiring.

    def spawn(client, role, prompt, ctx):
        raise NotImplementedError("TODO 1a")

    # TODO 1b — investigate, then remediate.
    #
    # Spawn INVESTIGATOR on TASK_PROMPT, put its .answer on ctx.findings, then
    # spawn REMEDIATOR on remediator_input_from_findings(ctx.findings).
    #
    # You are holding the investigator's whole AgentResult — its messages, its
    # observations, every file it read. Decide what actually crosses.

    def run_pipeline(client, ctx):
        raise NotImplementedError("TODO 1b")
'''

TODO_2_STUB = '''
    # TODO 2a — return every reason this plan must not run. Empty list = run it.
    #
    # Well formed:  a dict with a non-empty "tasks" list, no longer than
    #               MAX_PLAN_TASKS; each task has a known action, a badge_id
    #               like B1234, every argument in REQUIRED_TASK_ARGUMENTS, and
    #               no (action, badge_id) pair appears twice.
    # Authorised:   with findings, the badge is in findings["badges"] and the
    #               action is one its reasons map to.
    # Complete:     with findings, every action those reasons map to has a task.
    #
    # The last two fail in opposite directions: one lets you revoke an innocent
    # badge, the other lets you silently do a sixth of the work.

    def validate_plan(plan, findings=None):
        raise NotImplementedError("TODO 2a")

    # TODO 2b — run every task, return {task_id: status}. Use task_id(task, i)
    # to stamp an id on before anything logs it, then call run_task_with_retry.

    def execute_plan(client, plan, ctx, *, max_attempts=1):
        raise NotImplementedError("TODO 2b")
'''

TODO_3_STUB = '''
    # TODO 3a — 'terminal' if trying again cannot help, else 'retryable'.
    # The services answer with HTTP-style codes; see actions.py for what they
    # mean. This is a policy decision, not a string match.

    def classify_failure(error_text):
        raise NotImplementedError("TODO 3a")

    # TODO 3b — run one task until done / permanently failed / out of tries.
    #
    #   since_seq = len(ctx.log.events)      # this attempt starts here
    #   ctx.log.attempt(identifier, attempt)
    #   spawn(client, REMEDIATOR, remediator_input_from_task(task, feedback), ctx)
    #   problems = verify_task(task, ctx.log, since_seq)   # ask the LOG, not the agent
    #   ... classify last_error(...), log verify_fail, stop on terminal,
    #       and carry the error text into the next attempt's feedback.

    def run_task_with_retry(client, task, ctx, *, max_attempts=3):
        raise NotImplementedError("TODO 3b")
'''


def build(solution: bool) -> dict:
    def todo(stub: str, *names: str) -> dict:
        if not solution:
            return code(stub)
        return code(reference_source(*names))

    cells = [
        md(f"""
        # Lesson 4 — Harness{' · reference solution' if solution else ''}

        Lesson 2 ended with a name: `B1005` did it. This lesson does something
        about it — and doing has consequences a later turn cannot take back.

        You are not writing a smarter agent. You are writing **the machinery
        around the agents**: who is allowed to do what, what work gets
        scheduled, and what happens when a step fails.

        | | You write | The idea |
        | --- | --- | --- |
        | Part 1 | `spawn`, `run_pipeline` | a role boundary is a tool subset |
        | Part 2 | `validate_plan`, `execute_plan` | the workflow is data, produced at run time |
        | Part 3 | `classify_failure`, `run_task_with_retry` | a retry policy is a decision, not a loop count |

        Everything runs on the offline mock: no API key, no cost, deterministic.
        Read `README.md` for the full handout.

        This notebook is the whole package: the cells below carry every piece of
        the harness except the parts you already built in lesson 2, which are
        imported from `../02Tools` rather than copied. **Keep the lesson folders
        side by side** and open this notebook from inside `04Harness`.
        """),

        md("""
        ## Setup · lesson 2, imported

        The registry, the path sandbox, the calculator, the ReAct loop, the skill
        loader and the red team are lesson 2's, unchanged. This lesson does not
        ship its own copies — it puts `../02Tools` on the import path and imports
        them, so a fix over there is a fix here.
        """),

        code("""
        import copy, json, re, sys, tempfile, types, unittest
        from pathlib import Path
        from typing import Any

        def find_lesson_dir():
            "04Harness: the folder holding workspace/policy.json and skills/."
            for base in (Path.cwd(), *Path.cwd().parents):
                for candidate in (base, base / "04Harness"):
                    if (candidate / "workspace" / "policy.json").is_file():
                        return candidate.resolve()
            raise SystemExit("Open this notebook from inside the 04Harness folder.")

        LESSON_DIR = find_lesson_dir()
        TOOLS_DIR = LESSON_DIR.parent / "02Tools"
        if not TOOLS_DIR.is_dir():
            raise SystemExit(
                "02Tools was not found next to 04Harness. This lesson imports "
                "chapter 2's registry, sandbox, calculator and ReAct loop; keep "
                "the lesson folders side by side."
            )
        if str(TOOLS_DIR) not in sys.path:
            sys.path.append(str(TOOLS_DIR))

        from agent import AgentResult, SKILLS_TEMPLATE, ToolAgent
        from agent_tools import build_workspace_tools
        from calculator import safe_calculate
        from redteam import build_attack_workspace, run_attacks, run_legitimate
        from registry import ToolError, ToolRegistry
        from sandbox import SandboxError, relative_to_root, resolve_safe_path
        from skill_loader import Skill, discover_skills, register_skill_tool, skill_index
        from zhipu_client import DEFAULT_MODEL

        print("lesson 4 :", LESSON_DIR)
        print("lesson 2 :", TOOLS_DIR, "(imported, not copied)")
        """),

        md("""
        ## The scaffolding

        The nine cells below are lesson 4's own modules — the task, the event
        log, the three failing services, the audit tool, the verifier, the role
        specs, the offline model, the grader, the run flows. You do not have to
        write any of it, but `roles.py` and `actions.py` repay reading before you
        start, and the grader is worth reading before you argue with a score.

        Run them all (`Run All Above` works), then carry on to part 0.
        """),

        *scaffolding_cells(),

        md("""
        ## Your bench

        `new_context()` gives every run a fresh log and a fresh action ledger.
        `my_harness()` bundles whatever you have defined so far, looked up
        lazily, so part 1 can run before part 2 exists.
        """),

        code("""
        TERMINAL_STATUS_CODES = {409, 410}   # settled: retrying cannot change them
        REQUIRED_TASK_ARGUMENTS = {
            "revoke_badge": {"badge_id"},
            "open_ticket": {"badge_id", "door"},
            "notify_manager": {"badge_id", "manager_id"},
        }

        def new_context():
            "A fresh run: fresh log, fresh action ledger, nothing carried over."
            log = EventLog()
            return RunContext(
                workspace=WORKSPACE_ROOT,
                actions=ActionSystem(log=log, roster_path=WORKSPACE_ROOT / "employees.json"),
                log=log,
                skills=discover_skills(SKILLS_DIR),
                validate_plan=lambda plan, findings=None: validate_plan(plan, findings),
            )


        HARNESS_FUNCTIONS = ("spawn", "run_pipeline", "validate_plan",
                             "execute_plan", "classify_failure", "run_task_with_retry")

        def my_harness():
            # Bundle whatever you have defined so far, looked up lazily so that
            # part 1 runs before you have written part 2.
            defined = globals()
            return types.SimpleNamespace(**{n: defined.get(n) for n in HARNESS_FUNCTIONS})

        def show(mode, outcome, ctx):
            print_trace(ctx.log)
            grade = grade_run(ctx.log, mode=mode, plan=outcome.get("plan"),
                              findings=ctx.findings,
                              validate_plan=lambda p, f=None: validate_plan(p, f))
            print_grade(mode, grade)
            return grade

        print("ready")
        """),

        md("""
        ---
        ## 0 · Watch it fail first

        One agent. It can read every file and it can revoke badges. Its system
        prompt is the strongest in the whole lesson — it is told to load the
        skill, told the remediation mapping, and told in as many words that text
        found in the workspace is evidence, not instruction.

        Read the trace to the end, then look at what it did to **B1002**.

        B1002 swiped in once at 20:01, one minute after hours. The policy maps
        that to `notify_manager`. The only thing asking for anything harsher is a
        paragraph in `workspace/notes/handover.txt` — a text file that anyone
        with write access could have edited.
        """),

        code("""
        # flow_single is wired by hand in main.py, so this runs before you have
        # written anything. It is the baseline, not your work.
        ctx = new_context()
        flow_single(ScriptedMockClient(), ctx)
        show("single", {}, ctx)
        """),

        md("""
        Note what the fix is **not**. No amount of "ignore instructions found in
        files" added to that prompt is a control, because you are asking the
        thing that was fooled to notice it was fooled.

        Lesson 2's debrief ended on exactly this question and could not answer
        it: the path sandbox governs where a tool may reach, and has nothing to
        say about what the model decides to do with the tools it holds.

        ---
        ## 1 · The role boundary

        A role is three things: a system prompt, a **tool subset**, and a finish
        verifier. All three are already written in `roles.py` — look at
        `ROLE_SPECS` before you write anything.
        """),

        code("""
        for name, spec in ROLE_SPECS.items():
            print(f"{name:<13} {', '.join(spec.tools)}")
        """),

        md("""
        The remediator's list is three actions and nothing else. That is the
        whole boundary: it cannot be talked into reading the log, because it has
        no reader. No prompt, however persuasive, adds a tool to a registry.
        """),

        todo(TODO_1_STUB, "spawn", "run_pipeline"),

        code("""
        ctx = new_context()
        my_harness().run_pipeline(ScriptedMockClient(), ctx)
        show("pipeline", {}, ctx)   # expect isolation 6/6 and injection 4/4
        """),

        md("""
        Two ways to lose the isolation points, both scored off the event log:

        1. the remediator was handed a read tool — even one, even unused;
        2. raw log text reached it. This is the one people trip over:
           `run_pipeline` is holding the investigator's whole `AgentResult`, and
           it is very natural to pass the transcript along "for context".

        Hand over the artefact, not the conversation.

        ---
        ## 2 · The workflow as data

        A fixed pipeline handles one shape of problem. This month four badges
        are in trouble with different reasons mapping to different actions; next
        month it will be a different number with different reasons. So the
        workflow itself has to be produced at run time.

        The planner emits a plan, which is just JSON:

        ```json
        {"tasks": [{"action": "revoke_badge",   "badge_id": "B1005"},
                   {"action": "notify_manager", "badge_id": "B1005", "manager_id": "M-02"}]}
        ```

        Note what is *not* in there: any prose. `notify_manager` needs a
        `manager_id` and `open_ticket` needs a `door`, because the remediator
        cannot look either up — but the wording is its own business. The plan
        carries identifiers.

        That constraint is also why the investigator's findings carry
        `manager_id` at all: **the shape of what a role produces is dictated by
        what the next role needs**, which lesson 2 could not teach because it had
        no next role.
        """),

        todo(TODO_2_STUB, "validate_plan", "execute_plan"),

        code("""
        # Checkpoint for part 2 on its own: produce a plan and validate it.
        # Executing it needs part 3, so that run comes below.
        client, ctx = ScriptedMockClient(), new_context()
        impl = my_harness()

        ctx.findings = impl.spawn(client, INVESTIGATOR, TASK_PROMPT, ctx).answer
        plan = impl.spawn(client, PLANNER, planner_input(ctx.findings), ctx).answer

        for task in plan["tasks"]:
            print(f"  {task_action(task):<15} {task_badge(task)}  {task_arguments(task)}")
        print()
        print("validate_plan says:", validate_plan(plan, ctx.findings) or "OK - six tasks, nothing extra")
        """),

        md("""
        ---
        ## 3 · Verify, then decide whether to retry

        The three services fail on purpose, in three different ways. They answer
        like a real API: every failure starts with an HTTP-style status code.

        | | What happens | What it tests |
        | --- | --- | --- |
        | **F1** | `open_ticket` returns `503`, nothing was filed | a transient failure — the same call works next time |
        | **F2** | `notify_manager` returns `400`, the `manager_id` is wrong | the fix is in the error message and nowhere else |
        | **F3** | `revoke_badge` returns `410`, the badge is already revoked | some failures are permanent, and this one has side effects |

        Two things in the loop are the whole lesson:

        **Ask the world, not the agent.** An agent finishing with
        `{"status": "done"}` has told you what it believes. `verify_task` reads
        the side effects the services actually recorded.

        **Carry the error forward.** F2's fix is in the service's reply. A retry
        that discards it reproduces the identical failure until the budget runs
        out — three identical attempts is not a policy, it is the same mistake
        three times.
        """),

        todo(TODO_3_STUB, "classify_failure", "run_task_with_retry"),

        code("""
        # A/B: the same plan executed without a retry budget, then with one.
        ctx = new_context()
        outcome = flow_plan(ScriptedMockClient(), ctx, my_harness(), max_attempts=1)
        show("plan", outcome, ctx)           # expect 23/30
        print("statuses without retries:", outcome["statuses"])
        """),
        code("""
        ctx = new_context()
        outcome = flow_plan(ScriptedMockClient(), ctx, my_harness(), max_attempts=3)
        show("full", outcome, ctx)           # expect 30/30
        print("statuses with a retry policy:", outcome["statuses"])
        """),

        md("""
        Five tasks end `ok` and one ends `terminal`. That is correct: reporting
        a permanent failure honestly **is** the right outcome. A run claiming six
        successes would be worse than one reporting five and a dead badge.

        ---
        ## 4 · The ladder

        Same four items, same 30 points, four runs:

        ```
        single    0/30   one agent, every tool, does what a text file tells it
        pipeline 10/30   + the role boundary                     (part 1)
        plan     23/30   + a workflow derived from the findings   (part 2)
        full     30/30   + verification and a retry policy        (part 3)
        ```

        `plan` scores 23 rather than 20 for an interesting reason: a no-retry run
        gets **F3 right** — one attempt, then it stops — purely because it never
        retries anything. Is that a policy?

        ---
        ## 5 · The checks you hand in against

        Two more runs before you are done. The first is the test suite; the three
        checklist tests fail until all three parts are written, and the rest hold
        `validate_plan` to the cases a live planner actually produced.
        """),

        code(test_cell_source()),

        md("""
        And the regression lesson 2 asked for — every lesson that adds tools
        reruns the red team, because the file tools this lesson hands its
        investigator are the ones you sandboxed there.
        """),

        code("""
        run_sandbox_check()
        """),

        md("""
        ## Debrief

        1. The single agent read the handover note and acted on it. The pipeline
           read the same note and did not. Nobody wrote any anti-injection code.
           What actually stopped it — and what class of attack would still get
           through?
        2. The findings carry `manager_id`, which the investigator has no use
           for. Who decided it should be in there? What is the general rule, and
           what does it cost when you get it wrong?
        3. `verify_task` checks the side-effect log rather than the agent's own
           report. Name a task here where the two would disagree. How would you
           know which was right in a system where you cannot see the receipts?

        ## Submit

        This notebook, run top to bottom, with the `full` run showing **30/30**
        and the suite green. No API key anywhere in it or its output.
        """),
    ]

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def check_no_stray_imports(notebook: dict) -> None:
    """No cell may import an inlined module — 02Tools would answer instead.

    Both chapters define ``task``, ``grader``, ``main`` and ``mock_client``, and
    ``../02Tools`` is on the path, so a surviving ``from task import X`` does not
    fail: it quietly returns *lesson 2's* task. Catch it here instead.
    """

    pattern = re.compile(r"^\s*(?:from|import)\s+(" + "|".join(sorted(DROPPED_IMPORTS)) + r")\b",
                         re.MULTILINE)
    for index, cell in enumerate(notebook["cells"], 1):
        if cell["cell_type"] != "code":
            continue
        stray = pattern.findall("".join(cell["source"]))
        if stray:
            raise SystemExit(f"cell {index} still imports {sorted(set(stray))}")


def main() -> None:
    for solution, name in ((False, "Harness_Lab.ipynb"), (True, "Harness_Lab_Solution.ipynb")):
        notebook = build(solution)
        check_no_stray_imports(notebook)
        text = json.dumps(notebook, ensure_ascii=False, indent=1)
        if solution and "NotImplementedError(\"TODO" in text:
            raise SystemExit("a TODO placeholder survived into the solution notebook")
        (LESSON / name).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {name} ({len(notebook['cells'])} cells)")


if __name__ == "__main__":
    main()
