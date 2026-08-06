"""Student starter: implement the ReAct loop without looking at react_agent.py.

Instructors can distribute this file together with tools.py, task.py, grader.py,
and zhipu_client.py while withholding react_agent.py until the debrief.
"""

from __future__ import annotations

from tools import ToolEnvironment
from zhipu_client import ChatClient, DEFAULT_MODEL


class StarterReactAgent:
    def __init__(
        self,
        client: ChatClient,
        tools: ToolEnvironment,
        model: str = DEFAULT_MODEL,
        max_steps: int = 6,
    ) -> None:
        self.client = client
        self.tools = tools
        self.model = model
        self.max_steps = max_steps

    def run(self, task_prompt: str):
        # TODO 1: create messages with a system prompt that defines the two
        # ReAct actions: Calculate and Finish.

        # TODO 2: loop for at most self.max_steps. In each iteration:
        #   a. call self.client.chat(...)
        #   b. parse exactly one Action line
        #   c. execute Calculate through self.tools
        #   d. append the returned Observation to messages

        # TODO 3: stop only on a valid Finish JSON or the step budget. Return
        # enough trace data for the grader to inspect the tools used.
        raise NotImplementedError("Complete the three TODO blocks in react_starter.py")
