"""Make chapter 2's modules importable from chapter 3.

02Tools/INSTRUCTOR_NOTES.md ends with a promise: "Later chapters import this
module directly and register their own tools." This file is how that import
works: it appends ``../../02Tools`` to ``sys.path`` (this file lives in
``03Memory/student/tools/``; 02Tools sits next to 03Memory in the repo root).

Appending - not prepending - matters. Both chapters define ``grader``,
``main``, ``tools`` and ``zhipu_client``; because chapter 3's own folders come
first on the path (see ``student/bootstrap.py``), those names keep resolving
here. Only the modules that exist solely in 02Tools resolve there:

    registry.py      the tool registry and call history
    sandbox.py       resolve_safe_path - the boundary every file tool crosses
    calculator.py    the safe calculator
    agent_tools.py   build_workspace_tools (list/read/write/calculate)
    agent.py         the Action / Action Input parser

Same files, no copies: a fix in chapter 2 is a fix here.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[3] / "02Tools"

if not TOOLS_DIR.is_dir():
    raise ImportError(
        "02Tools was not found next to 03Memory. Chapter 3 reuses chapter 2's "
        "registry, sandbox and calculator; keep the lesson folders side by side."
    )

if str(TOOLS_DIR) not in sys.path:
    sys.path.append(str(TOOLS_DIR))
