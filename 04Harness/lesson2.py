"""Make chapter 2's modules importable from chapter 4. Import this first.

02Tools/INSTRUCTOR_NOTES.md ends with a promise: "Later chapters import this
module directly and register their own tools." Chapter 3 already takes it up in
its own ``lesson2.py``; this is the same file, doing the same job here. It
appends ``../02Tools`` to ``sys.path``.

Appending - not prepending - matters. Both chapters define ``grader``, ``main``,
``mock_client`` and ``task``; because 04Harness's own directory stays first on
the path, those names keep resolving here. Only the modules that exist solely in
02Tools resolve there:

    registry.py      the tool registry and call history
    sandbox.py       resolve_safe_path - the boundary every file tool crosses
    calculator.py    the safe calculator
    agent_tools.py   build_workspace_tools (list/read/write/calculate)
    agent.py         the Action / Action Input parser and the ReAct loop
    skill_loader.py  discover_skills and the skill tool
    zhipu_client.py  the API client and DEFAULT_MODEL
    redteam.py       the sandbox attack suite, rerun here as a regression gate

Same files, no copies: a fix in chapter 2 is a fix here. That is also why this
lesson adds no ninth module to the list - what chapter 4 contributes lives in
``roles.py``, ``actions.py``, ``events.py`` and ``verifiers.py``, and none of
those existed before.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent / "02Tools"

if not TOOLS_DIR.is_dir():
    raise ImportError(
        "02Tools was not found next to 04Harness. Chapter 4 reuses chapter 2's "
        "registry, sandbox, calculator, agent and skill loader; keep the lesson "
        "folders side by side."
    )

if str(TOOLS_DIR) not in sys.path:
    sys.path.append(str(TOOLS_DIR))
