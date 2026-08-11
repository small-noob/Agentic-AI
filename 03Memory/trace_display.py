"""Terminal rendering for the run trace. Display only - not a TODO.

Nothing in this module affects parsing, grading, or what the model sees.
react_loop.py calls into it when verbose; every function just prints.

Colors auto-disable when stdout is not a terminal (piping to a file or tee)
or when NO_COLOR is set; FORCE_COLOR=1 forces them back on.

Roles:   🙋 USER=cyan  💭 thought=gray  🔧 tool=magenta  💬 reply=green  🏁 finish=bold
Results: 📎 observation=dim  ❌ tool error=red  ⚠️ format=yellow  🛑 guard/verifier=red
"""

from __future__ import annotations

import json
import os
import re
import sys
import textwrap


def _color_enabled() -> bool:
    if os.getenv("FORCE_COLOR"):
        return True
    if os.getenv("NO_COLOR"):
        return False
    return sys.stdout.isatty()


_ON = _color_enabled()


def _c(code: str) -> str:
    return f"\033[{code}m" if _ON else ""


RESET, BOLD, DIM = _c("0"), _c("1"), _c("2")
CYAN, MAGENTA, RED, GREEN, YELLOW, GRAY = (
    _c("36"), _c("35"), _c("31"), _c("32"), _c("33"), _c("90"),
)

WIDTH = 72


def _clip(text: str, limit: int = 300) -> str:
    text = " ".join(str(text).split())
    return text[:limit] + " ..." if len(text) > limit else text


def _rows(text: str, limit: int = 300, width: int = WIDTH - 4) -> list[str]:
    return textwrap.wrap(_clip(text, limit), width) or [""]


def _block(icon: str, color: str, text: str, limit: int = 220) -> None:
    """One icon-labelled entry inside a card; continuation lines align."""
    rows = _rows(text, limit)
    print(f"│ {color}{icon} {rows[0]}{RESET}")
    for row in rows[1:]:
        print(f"│ {color}   {row}{RESET}")


# ---------------------------------------------------------------- cards

def session_banner(session_no: int, policy_name: str, budget: int = 0) -> None:
    bar = "═" * WIDTH
    tail = f" · budget {budget:,}t" if budget > 0 else ""
    print(f"\n{BOLD}{bar}\n SESSION {session_no} · policy={policy_name}{tail}\n{bar}{RESET}")


def user_card(session_no: int, turn_no: int, content: str) -> None:
    print(f"\n{CYAN}{BOLD}🙋 USER (S{session_no}·T{turn_no}){RESET}")
    for row in _rows(content):
        print(f"{CYAN}│{RESET} {row}")


def ladder(lines) -> None:
    """Context-assembly rungs. Compaction is a teaching moment - highlight it."""
    for line in lines:
        text = " ".join(str(line).split())
        if "compact" in text:
            print(f"  {YELLOW}🗜 {text}{RESET}")
        else:
            print(f"  {DIM}⚙ {text}{RESET}")


def model_card(step: int, raw_text: str, parsed) -> None:
    """One ReAct step: the thought, then whatever action was parsed.

    ``parsed`` is the action object (has .name / .arguments), or None when
    the reply failed to parse - then the raw text is shown and the following
    observation line explains the format error.
    """
    print(f"{BOLD}🤖 MODEL · step {step}{RESET}")

    thought = re.search(r"Thought:\s*(.+?)(?=\s*Action\s*:|\Z)", str(raw_text), re.S)
    if thought and thought.group(1).strip():
        _block("💭", GRAY, thought.group(1))

    name = getattr(parsed, "name", None)
    if name == "respond":
        args = parsed.arguments
        message = args.get("message", args) if isinstance(args, dict) else args
        _block("💬", GREEN, f"「{_clip(message, 200)}」")
    elif name == "finish":
        _block("🏁", BOLD, "finish ▸ " + json.dumps(parsed.arguments, ensure_ascii=False), limit=300)
    elif name:
        args = json.dumps(parsed.arguments, ensure_ascii=False)
        _block("🔧", MAGENTA, f"{name} ▸ {_clip(args, 180)}")
    else:
        _block("❓", YELLOW, _clip(raw_text, 220))


# ---------------------------------------------------------- observations

_KINDS = {
    # kind        icon   color         label
    "tool":       ("📎", "",           ""),
    "tool_error": ("❌", "",           ""),
    "format":     ("⚠️", "",           "FORMAT ERROR"),
    "guard":      ("🛑", "",           "GUARD"),
    "verifier":   ("🛑", "",           "VERIFIER"),
}


def observation(text: str, kind: str = "tool") -> None:
    if kind == "tool" and str(text).lstrip().startswith("Tool error"):
        kind = "tool_error"
    icon, _, label = _KINDS.get(kind, _KINDS["tool"])
    color = {
        "tool": DIM,
        "tool_error": RED,
        "format": YELLOW,
        "guard": RED + BOLD,
        "verifier": RED,
    }.get(kind, DIM)
    body = (f"{label} ▸ " if label else "") + _clip(text, 260)
    rows = _rows(body, 300)
    print(f"└ {color}{icon} {rows[0]}{RESET}")
    for row in rows[1:]:
        print(f"     {color}{row}{RESET}")


def turn_end() -> None:
    print(f"{DIM}└ ◀ turn ended (respond){RESET}")


def finish_ok() -> None:
    print(f"{GREEN}{BOLD}└ ✅ finish accepted — verifier passed{RESET}")


def warn(text: str) -> None:
    print(f"  {YELLOW}⚠️ {text}{RESET}")


def overflow(text: str) -> None:
    print(f"  {RED}{BOLD}🛑 CONTEXT OVERFLOW ▸ {text}{RESET}")


# ------------------------------------------------------------- main.py

def run_banner(label: str, budget: int = 0) -> None:
    bar = "#" * WIDTH
    tail = f"   (budget {budget:,}t)" if budget > 0 else ""
    print(f"\n{BOLD}{bar}\n#  {label}{tail}\n{bar}{RESET}")


def verdict(passed: bool, score: int, total: int) -> str:
    color, word = (GREEN, "PASS") if passed else (RED, "FAIL")
    return f"{color}{BOLD}{word}{RESET} — {score}/{total}"


def _stat(icon: str, label: str, value: str, color: str = "") -> None:
    rows = _rows(value, limit=500, width=WIDTH - 18)
    print(f" {icon} {label:<12}{color}{rows[0]}{RESET}")
    for row in rows[1:]:
        print(f"     {'':<12}{color}{row}{RESET}")


def summary_card(*, label: str, budget: int, passed: bool, score: int, total: int,
                 feedback: list, answer, stopped: str, peak: int,
                 compactions: int, rung: int, mem: tuple,
                 api: str = "", drift: str = "",
                 overflow_msg=None, partial_note=None) -> None:
    """The end-of-run report card. Verdict and diagnosis first, stats after."""
    bar = "─" * WIDTH
    print(f"\n{bar}")
    if partial_note is not None:
        print(f" {BOLD}🏆 {label}{RESET}   {YELLOW}{BOLD}NOT GRADED{RESET}")
        print(bar)
        for row in _rows(partial_note, 300, WIDTH - 5):
            print(f" {YELLOW}{row}{RESET}")
    else:
        print(f" {BOLD}🏆 {label}{RESET}   {verdict(passed, score, total)}")
        print(bar)
        mark, colr = ("✓", GREEN) if passed else ("✗", RED)
        for item in feedback:
            rows = _rows(item, 300, WIDTH - 5)
            print(f" {colr}{mark} {rows[0]}{RESET}")
            for row in rows[1:]:
                print(f" {colr}  {row}{RESET}")
    print()

    _stat("📝", "answer", json.dumps(answer, ensure_ascii=False),
          RED + BOLD if answer is None else (GREEN if passed else ""))
    _stat("⏹", "stopped", stopped)
    if budget > 0:
        pct = peak * 100 // budget
        _stat("📐", "context", f"peak {peak:,} / {budget:,}t  ({pct}% of budget)",
              YELLOW if pct >= 95 else "")
    else:
        _stat("📐", "context", f"peak {peak:,}t")
    if compactions or rung:
        _stat("🗜", "compactions", f"{compactions} · highest rung L{rung}", YELLOW)
    cur, sup, dele = mem
    _stat("🧠", "memory", f"{cur} current · {sup} superseded · {dele} deleted",
          DIM if (cur + sup + dele) == 0 else "")
    if api:
        _stat("🌐", "api", api)
    if drift:
        _stat("📏", "estimate", drift, DIM)
    if overflow_msg:
        _stat("🛑", "overflow", overflow_msg, RED + BOLD)
