# Direct vs. ReAct — In-Class Exercise

In this exercise, you will compare a one-shot model response with a small ReAct agent. Both approaches work on the same campus event planning problem. The Direct version answers once. The ReAct version can check a proposed plan, read the result, revise the plan, and calculate the final cost.

The exercise is in [`Introduction_ReAct.ipynb`](./Introduction_ReAct.ipynb).

## Learning goals

By the end of the exercise, you should be able to:

- follow a `Thought → Action → Observation` loop;
- explain why an Observation can change the agent's next Action;
- use a few-shot example to demonstrate an action protocol;
- use verifier feedback to write a Reflection;
- identify the role of the parser, tools, validator, and step limit in an agent harness.

## The planning problem

A school is arranging a workshop for 150 people. The plan must meet all of these requirements:

- wheelchair access is required;
- a projector is required;
- renting a projector costs 250;
- the workshop lasts two hours and must finish by 18:00;
- the presenter can start only at 14:00 or 16:00;
- the total cost cannot exceed 1,400.

The available venues are:

| Venue  | Capacity | Accessible | Built-in projector | Available start time |   Fee |
| ------ | -------: | :--------: | :----------------: | -------------------- | ----: |
| Hall A |      120 |    Yes    |        Yes        | 14:00, 16:00         |   900 |
| Hall B |      180 |    Yes    |         No         | 14:00                | 1,000 |
| Hall C |      160 |     No     |        Yes        | 16:00                |   800 |
| Hall D |      200 |    Yes    |        Yes        | 15:00                | 1,300 |

The initial plan is:

```json
{"venue": "Hall C", "start": "16:00", "rent_projector": false}
```

Your agent must check this plan, correct any violations, calculate the cost, and submit a verified result.

## What you need to complete

The notebook already provides the API client, action parser, tools, JSON handling, ReAct loop, and step limit. Your work is limited to three functions.

### `build_reasoning_prompt(constraints)`

Write the system prompt for the ReAct agent. It should make the model:

- check the complete initial plan first;
- use the latest Observation when choosing the next step;
- produce only one Action per turn;
- include `venue`, `start`, and `rent_projector` in every `VerifyPlan` call;
- call `Finish` only after the plan and cost have been verified.

### `build_few_shot_messages()`

Write a short example using a different, simpler room-selection problem. The example should demonstrate the full sequence:

```text
VerifyPlan → Observation → Reflection → VerifyPlan → Calculate → Finish
```

The example should show how the agent keeps valid parts of a plan and changes the part that failed.

### `build_reflection(feedback, previous_plan)`

Return a string beginning with `Reflection:`. It should:

- include the previous plan and the verifier feedback;
- state what can be kept;
- state what needs to change;
- avoid repeating a venue with a permanent problem such as insufficient capacity;
- remind the model to send a complete plan in its next `VerifyPlan` call.

You do not need to modify the tool implementations or the ReAct loop.

## Available actions

The model may use one action per turn:

```text
Action: VerifyPlan[{"venue":"Hall C","start":"16:00","rent_projector":false}]
Action: Calculate[1000+250]
Action: Finish[{"venue":"...","start":"...","rent_projector":true,"total_cost":...}]
```

`VerifyPlan` checks the constraints and reports any violations. `Calculate` evaluates the final cost. `Finish` submits the result after both the plan and cost have been checked.

## Requirements

- Python 3.9 or later
- VS Code with the Jupyter extension, Jupyter Notebook, or JupyterLab
- An internet connection and a Zhipu API key for the live model run

The notebook uses only the Python standard library. You do not need to install any other package.

## Running the notebook

Open `Introduction_ReAct.ipynb` and select a Python kernel. Run the cells from top to bottom.

For the first run, use the offline client:

```python
USE_REAL_API = False
```

This mode does not call an API and produces a fixed trace, which is useful for checking your code.

After the offline version passes, you may try the live model:

```python
USE_REAL_API = True
```

The default model is `glm-4-flash-250414`. Live model traces may differ from the offline trace.

## Setting the API key

The recommended method is to start VS Code from a terminal where `ZAI_API_KEY` is set.

Linux or macOS:

```bash
export ZAI_API_KEY="your API key"
```

Windows PowerShell:

```powershell
$env:ZAI_API_KEY="your API key"
```

If VS Code is already open, close it before running these commands. It must be started from the same terminal to receive the environment variable.

If the environment variable is not set, the notebook uses `getpass()` to request the key temporarily. The input is hidden and is not printed in the notebook output. If no input field appears in VS Code, use the environment variable method and restart the kernel.

Do not place an API key in:

- a normal Python string;
- a `%env` cell;
- an `os.environ[...]` assignment;
- the README or a screenshot;
- the notebook you submit.

Restart the kernel after the live test so that the key is removed from the current Python process.

Zhipu's API quick-start guide is available at [docs.bigmodel.cn](https://docs.bigmodel.cn/cn/guide/start/quick-start).

## Suggested workflow

1. Set `USE_REAL_API = False`.
2. Run the Direct section and inspect its one-shot answer.
3. Run the verifier and calculator checks.
4. Complete the three reasoning functions.
5. Run the ReAct loop.
6. Read each Action, Observation, and Reflection in the printed trace.
7. Check that the final result contains `pass=True`.
8. If time allows, switch to `USE_REAL_API = True` and compare the live trace.

## Completion check

Your offline run should show that:

- the Direct result does not pass the final check;
- the initial plan is sent to `VerifyPlan`;
- at least one invalid plan produces a Reflection;
- a revised plan passes `VerifyPlan`;
- the final cost comes from `Calculate`;
- `Finish` returns a complete JSON object;
- the final ReAct result shows `pass=True`.

The live model may try different venues or take a different number of steps. It still needs to respond to verifier feedback, verify the final plan, calculate the cost, and finish within the step limit.

## Common problems

### `complete_prompt_TODO`, `complete_few_shot_TODO`, or `complete_reflection_TODO`

One of the three functions is still empty or returns the wrong type. Check the function named in the message.

### The model leaves fields out of `VerifyPlan`

Make the system prompt, few-shot example, and Reflection state that every proposal must contain `venue`, `start`, and `rent_projector`.

### The run ends with `max_steps`

Check whether the model is repeating a venue that has already failed. Your Reflection should use the verifier feedback to prevent the same mistake from being proposed again.

### The JSON cannot be parsed

Use double quotes around JSON keys and strings. JSON Boolean values must be lowercase: `true` and `false`. Each model turn should contain only one Action.

### The live model takes a different path

This is expected. The live run does not need to match the offline trace step by step. Focus on whether the agent uses the feedback and reaches a valid result.

## Submission

Submit only the completed notebook:

```text
Introduction_ReAct.ipynb
```

Before submitting, check that:

- the notebook runs from top to bottom;
- the final ReAct result shows `pass=True`;
- all three reasoning functions are complete;
- no API key appears in the file or its outputs.
