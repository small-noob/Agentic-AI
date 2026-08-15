"""Put the lesson's source folders on sys.path. Import this first.

The student package groups its modules by function:

    models/   the API client and the token estimator
    tools/    chapter 2's toolset, imported - not copied (see tools/lesson2.py)
    tasks/    the session scripts, the workspace, and all ground truth
    memory/   the store and the memory policy - where your four TODOs land
    agent/    the ReAct loop, the pipeline, the grader, the trace display

Modules import each other by plain name (``from sessions import TRANSCRIPT``),
so every folder above goes onto sys.path here. 02Tools is APPENDED last (by
tools/lesson2.py), so chapter 3's same-named modules always win; the modules
that exist only in 02Tools - registry, sandbox, calculator, agent_tools, and
the ``agent`` Action parser - resolve there.
"""

from __future__ import annotations

import sys
from pathlib import Path

STUDENT_ROOT = Path(__file__).resolve().parent
SUBDIRS = ("models", "tools", "tasks", "memory", "agent")

for _name in reversed(SUBDIRS):
    _path = str(STUDENT_ROOT / _name)
    if _path not in sys.path:
        sys.path.insert(0, _path)

import lesson2  # noqa: E402,F401  (appends ../../02Tools to sys.path)
