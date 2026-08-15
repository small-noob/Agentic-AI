"""The ReAct harness for Part A. Given to students - none of this is a TODO.

The action protocol is chapter 2's, and so is the code that speaks it: the
``Action:`` / ``Action Input:`` parser is imported from ``02Tools/agent.py``
and every tool call goes through ``02Tools/registry.py``.

Context assembly here is deliberately trivial - there is no budget and no
ladder in Part A (that is Part B's subject, TODO 4). Every turn the model
sees:

    system prompt
    [memory] block          <- only if the store holds anything
    the current session's conversation so far

The ONLY thing that differs between ``--mode tools`` and ``--mode memory`` is
what happens when a session ends: the tools policy keeps nothing, the memory
policy runs extract -> gate -> reconcile and saves the store. Same tools, same
loop, same model, same grader.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any

import lesson2  # noqa: F401  (appends 02Tools to sys.path; see lesson2.py)

import trace_display as ui  # rendering only; grading and parsing never touch it
from agent import parse_action  # 02Tools' Action / Action Input parser, unchanged
from registry import ToolRegistry
from tokens import TokenDrift, count_messages

# Per *user turn*, not per run. The deliverable turn needs read_file,
# calculate and finish, plus slack for a wrong guess and a format retry.
DEFAULT_MAX_STEPS = 6

FORMAT_ERROR_HINT = (
    'Format error: emit one "Action:" line naming a tool (or respond/finish) '
    'and one "Action Input:" line with a JSON object.'
)


# ---------------------------------------------------------------------------
# Parsing helper - shared with student code (TODO 1 and TODO 3 use it too)
# ---------------------------------------------------------------------------


def extract_json_object(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply, tolerantly.

    Weak models emit fenced blocks, trailing prose, and single-quoted dicts.
    Never assume a reply is clean JSON.
    """
    text = str(text)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    for candidate in re.findall(r"\{.{1,4000}\}", text, re.DOTALL):
        try:
            value = ast.literal_eval(candidate)
        except (SyntaxError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


# ---------------------------------------------------------------------------
# Shared types for TODO 4 (used by Part B's pipeline, not by this loop)
# ---------------------------------------------------------------------------


@dataclass
class Assembled:
    """What build_context returns: the messages, their cost, and the rungs."""

    messages: list[dict]
    tokens: int
    ladder: list[str] = field(default_factory=list)


class ContextOverflow(RuntimeError):
    """Raised when the assembled context cannot be brought under budget.

    The harness refuses to send the request. A budget that is merely reported
    is not a budget; this is what makes it real.
    """

    def __init__(self, used: int, budget: int, detail: str = "") -> None:
        super().__init__(
            f"assembled context is {used:,} tokens, budget is {budget:,}"
            + (f" ({detail})" if detail else "")
        )
        self.used = used
        self.budget = budget


# ---------------------------------------------------------------------------
# Trace records
# ---------------------------------------------------------------------------


@dataclass
class TurnRecord:
    session: int
    turn: int
    step: int
    context_tokens: int
    model_text: str
    action: dict | None  # {"name": ..., "arguments": {...}} once parsed
    observation: str | None


@dataclass
class RunResult:
    answer: dict | None = None
    stopped_reason: str = ""
    turns: list[TurnRecord] = field(default_factory=list)
    drift: TokenDrift = field(default_factory=TokenDrift)


def _assemble(system: str, store: Any, history: list[dict]) -> list[dict]:
    """system + [memory] digest (when non-empty) + the session so far."""
    messages = [{"role": "system", "content": system}]
    digest = store.digest()
    if digest:
        messages.append({"role": "system", "content": digest})
    messages.extend(history)
    return messages


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def run_sessions(
    client: Any,
    policy: Any,
    store: Any,
    sessions: dict[int, list[dict]],
    system_prompt: str,
    registry: ToolRegistry,
    verifier=None,
    model: str = "",
    only_session: int | None = None,
    verbose: bool = True,
    max_steps: int = DEFAULT_MAX_STEPS,
    answer_keys: set[str] | None = None,
    on_session_start=None,
) -> RunResult:
    """Run the scripted sessions in order and return the trace.

    Only the *user* turns are scripted. The agent produces its own assistant
    turns, so the conversation the memory pipeline extracts from is the one
    that really happened. ``registry`` carries the auditable tool-call history
    the verifier and grader read - same object, same audit, as chapter 2.

    ``on_session_start`` is called with the session number before each session
    begins; main.py passes the workspace reset through it.
    """
    result = RunResult()
    kwargs = {"model": model} if model else {}

    ordered = sorted(sessions) if only_session is None else [only_session]

    # finish is only accepted on the last user turn of the last session being
    # run - the turn that asks for the deliverable. Without this guard a
    # chatty model can "finish" during session 1's goodbye and silently skip
    # the rest (a real GLM-4-Flash failure, not a hypothetical).
    final_session = ordered[-1]
    final_turn = max(
        (e["turn"] for e in sessions[final_session] if e["role"] == "user"),
        default=None,
    )
    finish_not_yet = (
        "finish is not accepted yet: the user has not asked for the final "
        "deliverable in this turn. End the turn with respond instead."
    )

    for session_no in ordered:
        if on_session_start is not None:
            on_session_start(session_no)
        history: list[dict] = []
        if verbose:
            ui.session_banner(session_no, policy.name, 0)

        for entry in sessions[session_no]:
            if entry["role"] != "user":
                continue  # assistant turns are generated, not replayed
            history.append({"role": "user", "content": entry["content"]})
            if verbose:
                ui.user_card(session_no, entry["turn"], entry["content"])

            for step in range(1, max_steps + 1):
                messages = _assemble(system_prompt, store, history)
                context_tokens = count_messages(messages)
                if verbose:
                    ui.ladder([f"context {context_tokens:,}t"])

                reply = client.chat(messages, purpose="agent", **kwargs)
                result.drift.record(context_tokens, reply.prompt_tokens)
                text = str(reply)
                history.append({"role": "assistant", "content": text})

                def record(action: dict | None, observation: str | None) -> None:
                    result.turns.append(
                        TurnRecord(session_no, entry["turn"], step, context_tokens,
                                   text, action, observation)
                    )

                def observe(observation: str, tail: str, kind: str = "tool") -> None:
                    history.append({"role": "user", "content": f"Observation: {observation}\n{tail}"})
                    if verbose:
                        ui.observation(observation, kind)

                parsed = parse_action(text, registry)

                if parsed is None:
                    # A model that emits the final JSON without wrapping it in
                    # a finish action still deserves to be graded on it.
                    candidate = extract_json_object(text)
                    if (answer_keys and candidate is not None
                            and answer_keys <= set(candidate)
                            and session_no == final_session
                            and entry["turn"] == final_turn):
                        parsed = _FinishShim(candidate)

                if verbose:
                    # A parse-error string carries no action; show the raw reply.
                    ui.model_card(step, text, None if isinstance(parsed, str) else parsed)

                if parsed is None:
                    record(None, FORMAT_ERROR_HINT)
                    observe(FORMAT_ERROR_HINT, "Continue with one Thought and one Action.",
                            kind="format")
                    continue

                if isinstance(parsed, str):  # parse error with a specific message
                    record(None, parsed)
                    observe(parsed, "Continue with one Thought and one Action.", kind="format")
                    continue

                action_view = {"name": parsed.name, "arguments": parsed.arguments}

                if parsed.name == "respond":
                    if session_no == final_session and entry["turn"] == final_turn:
                        # The mirror of the finish guard: on the deliverable
                        # turn, respond is not an exit.
                        redirect = (
                            "The user asked for the final deliverable this turn. "
                            "Do the work with your tools - list_files if you are "
                            "unsure of a name, read what you need, calculate what "
                            "you must - then submit with finish."
                        )
                        record(action_view, redirect)
                        observe(redirect, "Continue with exactly one Action.", kind="guard")
                        continue
                    record(action_view, None)
                    if verbose:
                        ui.turn_end()
                    break  # the turn is answered; move to the next user turn

                if parsed.name == "finish":
                    if not (session_no == final_session and entry["turn"] == final_turn):
                        record(action_view, finish_not_yet)
                        observe(finish_not_yet, "Continue with exactly one Action.", kind="guard")
                        continue
                    answer = parsed.arguments
                    errors = verifier(answer, registry) if verifier else []
                    if errors:
                        observation = "finish blocked by verifier: " + "; ".join(
                            dict.fromkeys(errors)
                        )
                        record(action_view, observation)
                        observe(observation, "Correct it, then continue with exactly one Action.",
                                kind="verifier")
                        continue
                    result.answer = answer
                    result.stopped_reason = "finish_action"
                    record(action_view, None)
                    if verbose:
                        ui.finish_ok()
                    policy.close_session(client, store, history, session_no)
                    return result

                observation = registry.call(parsed.name, parsed.arguments)
                record(action_view, observation)
                observe(observation, "Continue with one concise Thought and exactly one Action.")
            else:
                if verbose:
                    ui.warn(f"step budget {max_steps} reached for this turn")

        # End of session: the write path. This line IS the A/B comparison -
        # the tools policy does nothing here, the memory policy extracts.
        policy.close_session(client, store, history, session_no)
        if verbose:
            print()
            print(store.report(session_no))

    result.stopped_reason = result.stopped_reason or "sessions_exhausted"
    return result


class _FinishShim:
    """Wraps a bare answer JSON so it flows through the finish branch."""

    name = "finish"

    def __init__(self, arguments: dict) -> None:
        self.arguments = arguments
