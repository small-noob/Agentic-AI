"""Student starter. Complete TODO 1–3 here, then TODO 4 in skills_starter/.

Do not open sandbox.py or agent_tools.py until the debrief — they hold the
reference answers. Everything you need is described below.

Check your work as you go:

    python3 main.py --mode sandbox --implementation starter     # TODO 1
    python3 -m unittest discover -s tests -v                     # TODO 1-3
    python3 main.py --mode compare --implementation starter --offline
"""

from __future__ import annotations

from pathlib import Path

from calculator import normalize_expression, safe_calculate
from registry import ToolError, ToolRegistry

MAX_READ_BYTES = 20000
MAX_WRITE_BYTES = 20000
MAX_LISTED_ENTRIES = 100


class SandboxError(Exception):
    """Raised when a requested path would leave the sandbox root."""


def resolve_safe_path(root: str | Path, user_path: str, *, must_exist: bool = False) -> Path:
    """TODO 1 — turn an untrusted path into a real path inside ``root``, or refuse.

    Return the resolved ``Path`` when the request is legitimate, and raise
    ``SandboxError`` otherwise. Ten attacks in ``redteam.py`` will be aimed at
    this function; `python3 main.py --mode sandbox --implementation starter`
    shows which ones get through.

    Things worth thinking about before you write any code:

    - What should happen to a path that is already absolute?
    - ``"logs/../../secrets.env"`` contains no leading ``..`` — a check for the
      string ``".."`` at the start is not enough. What operation collapses a
      path down to what it really points at?
    - The workspace can contain a *symlink* aimed at a file outside the root. A
      check on the text of the path can never see that. Which pathlib method
      follows symlinks, and does your comparison happen before or after it?
    - Once you have both the resolved root and the resolved target, what is the
      precise test for "the target is inside the root"? Careful: the root itself
      is a legitimate target, and ``str.startswith`` says ``/tmp/workspace-evil``
      starts with ``/tmp/workspace``.
    - ``must_exist=True`` means a missing file should raise rather than return.

    Useful: ``Path.resolve()``, ``Path.is_absolute()``, ``Path.parents``.
    """

    raise NotImplementedError("TODO 1: implement resolve_safe_path in starter_tools.py")


def build_workspace_tools(root: str | Path, registry: ToolRegistry | None = None) -> ToolRegistry:
    """Register the workspace tools on the registry and return it.

    ``registry.tool(...)`` is a decorator. Its first argument describes the tool
    and its keyword arguments describe each parameter; together with your type
    hints they become the JSON schema the model reads when it decides what to
    call. ``calculate`` below is a complete worked example.
    """

    registry = registry if registry is not None else ToolRegistry()
    root = Path(root).resolve()

    # ---- worked example: written for you, nothing to do here ----------------
    @registry.tool(
        "Evaluate exact arithmetic. Supports + - * / % and pow(base, exponent, modulus).",
        expression="A numeric expression, e.g. '(11 * 9176 + 1005 * 31337) % 1000000'.",
    )
    def calculate(expression: str) -> str:
        normalized = normalize_expression(expression)
        try:
            value = safe_calculate(normalized)
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as exc:
            raise ToolError(exc) from exc
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value)

    # ---- TODO 2: these two work already — write what the model reads --------
    #
    # The bodies below are finished. What is missing is the only part the model
    # ever sees: the description of the tool and of each parameter. Replace
    # every "TODO 2" string.
    #
    # Write them for a reader who has never seen this workspace and must choose
    # a tool from the catalogue alone. Before moving on, run:
    #
    #     python3 -c "from starter_tools import build_workspace_tools; \
    #                 print(build_workspace_tools('workspace').describe())"
    #
    # and read the output as if you were the model. Can you tell which tool to
    # use for which job, what to pass, and in what form? A tool described as
    # "reads a file" is a tool the model will call with the wrong path.

    @registry.tool(
        "TODO 2a: what does this tool do?",
        path="TODO 2b: what goes in path? relative to what? give an example",
        max_bytes="TODO 2c: what does max_bytes control, and what is the ceiling?",
    )
    def read_file(path: str, max_bytes: int = MAX_READ_BYTES) -> str:
        try:
            target = resolve_safe_path(root, path, must_exist=True)
        except SandboxError as exc:
            raise ToolError(exc) from exc
        if target.is_dir():
            raise ToolError(f"'{path}' is a folder. Use list_files instead.")

        cap = max(1, min(int(max_bytes), MAX_READ_BYTES))
        data = target.read_bytes()[: cap + 1]
        text = data.decode("utf-8", errors="replace")
        if len(data) > cap:
            # Say so, or the model will treat a partial file as the whole file.
            text = text[:cap] + f"\n...[truncated at {cap} bytes; call read_file again with a larger max_bytes]"
        return text

    @registry.tool(
        "TODO 2d: what does this tool do?",
        path="TODO 2e: what goes in path? give an example",
        content="TODO 2f: what goes in content?",
    )
    def write_file(path: str, content: str) -> str:
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ToolError(f"Refusing to write more than {MAX_WRITE_BYTES} bytes")
        try:
            target = resolve_safe_path(root, path)
        except SandboxError as exc:
            raise ToolError(exc) from exc
        if target.is_dir():
            raise ToolError(f"'{path}' is an existing folder")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {target.relative_to(root).as_posix()}"

    # ---- TODO 3: now write one yourself ------------------------------------
    #
    # Add a `list_files` tool with this signature:
    #
    #     def list_files(path: str = ".") -> str
    #
    # It lists the files and folders inside a workspace folder, one entry per
    # line, so the model can discover the real filenames instead of guessing
    # them. Requirements:
    #
    #   - register it with @registry.tool(...), described as carefully as the
    #     two above;
    #   - annotate the parameter, or the registry will refuse to build a schema;
    #   - route `path` through resolve_safe_path — this is what TODO 1 was for;
    #   - raise ToolError (not SandboxError) when the path is rejected, so the
    #     message reaches the model as an Observation instead of killing the run;
    #   - marking which entries are folders saves the model a wasted call;
    #   - cap the output at MAX_LISTED_ENTRIES so one huge folder cannot flood
    #     the context.
    #
    # The two tools above show the shape. Copy their structure, not their text.

    return registry
