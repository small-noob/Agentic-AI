"""Make chapter 2's modules importable from chapter 4. Import this first.

Chapter 2 used to ship these as a module package next to this one, and both this
lesson and chapter 3 reached into ``../02Tools`` on ``sys.path`` to reuse them.
That stopped working when chapter 2 was restructured into notebooks only
(c154598, which called the breakage out and left it to be dealt with here).
Chapter 3 answered by absorbing what it needed; this is the same answer.

The eight modules now live in ``lesson2_modules/`` beside this file:

    registry.py      the tool registry and call history
    sandbox.py       resolve_safe_path - the boundary every file tool crosses
    calculator.py    the safe calculator
    agent_tools.py   build_workspace_tools (list/read/write/calculate)
    agent.py         the Action / Action Input parser and the ReAct loop
    skill_loader.py  discover_skills and the skill tool
    zhipu_client.py  the API client and DEFAULT_MODEL
    redteam.py       the sandbox attack suite, rerun here as a regression gate

They are chapter 2's files as of c154598^, with two deliberate changes: the red
team degrades gracefully where symlinks cannot be created (Windows without
Developer Mode), and DEFAULT_MODEL honours ``ZAI_MODEL``, which both READMEs
already tell students to set.

Appending - not prepending - still matters. Both chapters define ``grader``,
``main``, ``mock_client`` and ``task``; because 04Harness's own directory stays
first on the path, those names keep resolving here.
"""

from __future__ import annotations

import sys
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parent / "lesson2_modules"

if not MODULES_DIR.is_dir():
    raise ImportError(
        f"{MODULES_DIR} is missing. It holds chapter 2's registry, sandbox, "
        "calculator, agent and skill loader, which this lesson builds on."
    )

if str(MODULES_DIR) not in sys.path:
    sys.path.append(str(MODULES_DIR))
