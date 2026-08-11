"""The agent's toolset: chapter 2's workspace tools, verbatim.

Nothing new is registered in this chapter. The registry, the path sandbox,
the calculator and the file tools are imported straight from 02Tools - the
same files students wrote descriptions for last week, not copies of them.

That is the point of Part A's comparison: the tools-only run and the memory
run hold EXACTLY the same registry. What differs between them is not what the
agent can do, but what it can remember - memory arrives as a [memory] block
in the context, not as a tool.
"""

from __future__ import annotations

from pathlib import Path

import lesson2  # noqa: F401  (appends 02Tools to sys.path; see lesson2.py)

from agent_tools import build_workspace_tools
from registry import ToolRegistry


def build_agent_registry(workspace_root: str | Path) -> ToolRegistry:
    """Chapter 2's registry: sandboxed list_files / read_file / write_file
    plus calculate. Both Part A modes get this registry and nothing else."""
    return build_workspace_tools(workspace_root)
